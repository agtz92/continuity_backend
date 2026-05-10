# AI Assistant

Chat-with-Claude inside Continuity. Read-only today (Phase 1), mutation
support coming next (Phase 2).

- Backend: Django app at `core.assistant`, mounted at `/api/assistant/`.
- Frontend: slide-out drawer triggered from a sparkle icon in the TopNav,
  rendered from `frontend/src/components/assistant/`.
- Model: Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) only, for now.
  Sonnet 4.6 "deep mode" lands in Phase 3.
- Auth: same Supabase JWT pipeline as `/graphql/` (extracted into
  `core.auth.authenticate_request`). Every tool runs server-side and
  filters by `user_id` — the model can never see another user's data.

---

## Setup

### 1. Get an Anthropic API key

1. Go to https://console.anthropic.com → **API Keys** → **Create key**.
2. Copy it. You'll never see it again.

The key sits **only** on the backend. The browser never gets it.

### 2. Backend `.env`

Add to `backend/.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

That's the only required env var. Optional knobs (defaults shown):

```
ASSISTANT_MODEL_FAST=claude-haiku-4-5-20251001
ASSISTANT_MAX_TOKENS_OUT=1024
ASSISTANT_MAX_TOOL_ITERATIONS=6
ASSISTANT_MAX_INPUT_TOKENS=8000
ASSISTANT_MAX_HISTORY_MESSAGES=12
ASSISTANT_MAX_INPUT_CHARS=4000
ASSISTANT_RATE_LIMIT_USER=30/m
ASSISTANT_RATE_LIMIT_BURST=5/10s
ASSISTANT_RATE_LIMIT_IP=60/m
```

### 3. Install + migrate

```bash
cd backend
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # picks up anthropic==0.40.0
python manage.py migrate           # creates assistant_* tables
python manage.py runserver
```

Tables created: `assistant_accountprofile`, `assistant_conversation`,
`assistant_message`, `assistant_usageday`.

### 4. Promote yourself to admin (optional, for dev)

The default plan is `free` (20 messages/day, 200K tokens/month). For
development, flip yourself to `admin` (no limits):

1. Find your Supabase user UUID:
   - Supabase dashboard → **Authentication** → **Users** → click your row
     → copy the `User UID`. (It's a UUID v4.)
2. Run:
   ```bash
   python manage.py set_plan <your-uuid> admin
   ```

Use `pro` instead of `admin` to test the paid-tier quotas (300 msg/day +
5M tokens/month).

### 5. Frontend

No new env vars or dependencies. The frontend derives the assistant base
URL from your existing `NEXT_PUBLIC_GRAPHQL_URL`:

```bash
cd frontend
npm run dev
```

Sign in, look for the **Ask Claude** sparkle button in the top-right of
the dashboard nav.

### 6. Production (Render + Vercel)

- **Render**: add `ANTHROPIC_API_KEY` in the dashboard under your service's
  **Environment** tab. The next deploy will run `migrate` automatically
  via `build.sh`. SSE streaming works on Render's free tier in our
  testing.
- **Vercel**: nothing new — the frontend talks to the same backend
  hostname it always did.

### 7. Smoke test

```bash
# 1. From a logged-in browser session, open DevTools → Network → grab
#    a Bearer token from any GraphQL request's Authorization header.
TOKEN=eyJhbGc...

# 2. Hit /usage/
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/assistant/usage/

# 3. Send a chat (SSE stream)
curl -N -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"content":"What did I work on last week?"}' \
     http://localhost:8000/api/assistant/chat/
```

Expected SSE frames in order: `meta` → optionally `tool_use_start` +
`tool_result` → `text_delta`* → `usage` → `done`. After the second
identical question, `usage.cache_read_input_tokens` should be ~80%+ of
total input tokens (system prompt + tool defs + skinny-context all hit
the cache).

---

## What's in Phase 1 (shipped)

| Tool | Description |
|---|---|
| `get_dashboard_summary` | Counts of active/sleeping/launched/archived projects, open/overdue/due-soon tasks, ideas. |
| `list_projects(status?, priority?, category?, limit≤50)` | Sorted by recent activity. |
| `get_project_detail(id)` | Project + 10 most-recent tasks, 5 updates, note titles. |
| `list_tasks(project_id?, done?, due_within_days?, limit≤50)` | |
| `list_ideas(limit≤30)` | |
| `list_categories()` | |
| `get_analytics(view, range)` | Cadence, top projects, backlog health, sleeping, stale ideas, idea funnel, effort, weekday heatmap. |
| `search(query, kind?, limit≤20)` | Substring search across projects/tasks/ideas/notes. |

Token-frugality measures already in place:

- System prompt + tool defs cached together; skinny-context cached
  separately and busted via `AccountProfile.context_version` (bumped
  inside `core/services/_cache.py:bump_context_version` whenever a
  service mutates user data).
- Skinny-context block (top 20 projects, status counts) answers ~70% of
  questions without a tool round-trip.
- Tool results capped at ~2KB / 50 rows / 280-char text fields.
- `max_tokens=1024` per turn, max 6 tool iterations per request, max 12
  history messages per request.
- Per-user rate limits: `5/10s` burst, `30/m` sustained.
- Daily message + monthly token quotas enforced before each call.
- Streaming with cancel — the frontend's `Stop` button calls
  `/cancel/`, which sets a cache flag the streaming loop checks every
  iteration.

---

## Phase 2 — Mutations (next)

Adds write tools so the assistant can actually act on the user's data.
Every mutation handler still goes through `core/services/*` (single
source of truth) and bumps `context_version` (cache invalidation).

### 2.1 New tools

#### Additive (run inline, no confirmation)

These create new rows. The user can always undo by deleting, so the
trade-off favors fewer clicks.

| Tool | Args | Notes |
|---|---|---|
| `create_task` | `title`, `project_id?`, `due_date?`, `effort_hours?` | |
| `bulk_create_tasks` | `project_id?`, `tasks: [{title, due_date?, effort_hours?}]` | Hard cap 25 items per call. Each title ≤ 200 chars. |
| `add_update` | `project_id`, `note` | Activity log entry. |
| `create_idea` | `title`, `description?`, `why?` | |
| `create_project_note` | `project_id`, `title?`, `body` | |
| `create_category` | `name`, `color?` | Idempotent — `get_or_create` semantics. |

#### Modifying (require confirmation)

These change existing rows or status. The user must approve each one.

| Tool | Args | Notes |
|---|---|---|
| `update_task` | `id`, fields… | Re-titles, re-parents, sets due/effort. |
| `toggle_task` | `id` | Flips `done`; auto-creates an Update on completion. |
| `update_project_status` | `id`, `status` | `active`/`stalled`/`paused`/`launched`/`archived`. |
| `update_project_priority` | `id`, `priority` | |
| `promote_idea` | `id` | Idea → Project. |
| `create_project` | `name`, fields… | New project ≠ trivial — confirm. |

#### Destructive (require confirmation)

| Tool | Args | Notes |
|---|---|---|
| `delete_task` | `id` | |
| `delete_idea` | `id` | |
| `delete_update` | `id` | |
| `delete_project_note` | `id` | |
| `delete_project` | `id` | Cascades to tasks + updates + notes. Extra-prominent confirm UI. |
| `delete_category` | `id` | |

### 2.2 Confirmation flow

Anthropic tool-use is request/response — the model can't pause and ask
for permission mid-tool. We fake it server-side:

1. Model calls e.g. `update_task(id=…, done=true)`.
2. Server's tool dispatcher sees the tool's `requires_confirmation=True`
   flag. Instead of executing, it:
   - Persists a `PendingToolCall` row keyed by `tool_use_id`,
     `conversation_id`, `tool_name`, `args`, `expires_at` (5 min).
   - Returns a synthetic `tool_result` to the model:
     `{"status": "awaiting_user_confirmation", "tool_use_id": "..."}`.
   - Emits a `tool_pending_confirmation` SSE frame to the frontend with
     a human-readable preview (e.g. "Mark 'Wire up Stripe webhook' as
     done?").
3. Model sees the synthetic result, says "I've proposed X — let me know
   if you want me to apply it" and emits `end_turn`.
4. Frontend renders a `ToolConfirmation` card with **Apply** / **Cancel**.
5. On **Apply**: frontend POSTs `/api/assistant/chat/` with body
   `{conversation_id, content: "", confirm_tool_call: {tool_use_id, approved: true}}`.
6. Backend looks up `PendingToolCall`, runs the real handler, bumps
   `context_version`, appends a real `tool_result` block to the
   conversation history, and either ends the turn (no follow-up needed)
   or kicks the model for one more round (e.g. "Done. Anything else?").
7. On **Cancel** (or 5-min timeout): pending row deleted, model gets
   `{"status": "user_declined"}` and acknowledges.

The `PendingToolCall` model + cleanup cron is the only new persistence.

### 2.3 Bulk operations

`bulk_create_tasks` is the killer feature for the user's "bulk task
creation" use case. Cap at 25 items per call (not configurable —
beyond that, the model should ask a follow-up).

For pasting a long markdown / plaintext list:

- Frontend pre-flight: regex-detect lines starting with `- `, `* `, `1. `,
  or naked one-per-line strings. If detected, show a "Bulk-create N
  tasks?" preview before sending — model not invoked.
- Submit lands at deterministic endpoint `POST /api/assistant/quick/bulk_tasks/`:
  `{project_id, items: ["title1", "title2", ...]}` → calls
  `tasks_svc.bulk_create_tasks` directly. Costs zero LLM tokens.

This is the cheapest possible path. The chat-driven `bulk_create_tasks`
tool stays as a fallback for natural-language requests.

### 2.4 Files to add / modify

**Backend:**
- `backend/core/services/tasks.py` — add `bulk_create_tasks(user_id, *, project_id, items)`. Wraps in `transaction.atomic`, caps at 25, max 200 chars each.
- `backend/core/assistant/tools/write.py` — new module, `@tool`-registered handlers for the table above.
- `backend/core/assistant/models.py` — add `PendingToolCall(id, conversation_fk, tool_use_id UNIQUE, tool_name, args JSONB, created, expires_at)`.
- `backend/core/assistant/migrations/0002_pending_tool_call.py` — schema migration.
- `backend/core/assistant/views.py` — extend `ChatView.post` to handle `confirm_tool_call`. Extend tool dispatcher to short-circuit on `requires_confirmation` and emit the SSE frame.
- `backend/core/assistant/quick.py` + url — new `/quick/bulk_tasks/` endpoint.
- `backend/core/assistant/tools/__init__.py` — load `write` module on import (alongside `read`).
- `backend/core/assistant/management/commands/cleanup_pending_tools.py` — runs hourly, deletes expired `PendingToolCall`s.
- Tests: `test_tools_write.py`, `test_confirmation_flow.py`, `test_quick_bulk.py`.

**Frontend:**
- `frontend/src/components/assistant/ToolConfirmation.tsx` — preview card with Apply / Cancel, generates a one-line summary per tool name (e.g. "Create 3 tasks in *Telegram bot*", "Delete idea *Voice memo capture*").
- `frontend/src/components/assistant/AssistantPanel.tsx` — listen for `tool_pending_confirmation` SSE frames; render the card sticky at the bottom of the message list.
- `frontend/src/components/assistant/BulkTasksPreview.tsx` — paste-detection modal; calls `quickBulkTasks(...)`.
- `frontend/src/lib/assistantApi.ts` — add `quickBulkTasks(projectId, items)` and `confirmToolCall(conversationId, toolUseId, approved)`.
- `frontend/src/hooks/useAssistant.ts` — handle `tool_pending_confirmation` events, expose `confirmTool(toolUseId, approved)`.
- i18n: add `assistant.confirm.*` keys to both locale files.

### 2.5 New tests

- `test_tools_write.py` — every write tool: user-scoping, idempotency, bulk cap, transaction rollback on partial failure.
- `test_confirmation_flow.py` — destructive tool emits `tool_pending_confirmation` and does NOT mutate; subsequent confirm `approved=true` does mutate; `approved=false` doesn't; expired `PendingToolCall` returns 404.
- `test_quick_bulk.py` — `/quick/bulk_tasks/` honors user-scoping, caps to 25 items, returns the created task IDs.
- `test_context_version_bumps.py` — every mutation tool bumps `AccountProfile.context_version` exactly once.

### 2.6 Risks / open questions

1. **Model retrying after denial.** If the user clicks Cancel, the model
   may try the same tool again on its next turn. Mitigation: return a
   strongly-worded "user declined this action" tool_result that the
   system prompt explicitly tells the model to respect. Cap at 2 retries
   on the same `tool_use_id` before refusing server-side.
2. **Mass-action footguns.** If the model writes "delete all stalled
   projects", the loop could spam delete tool calls. Mitigation:
   `delete_*` tools have a stricter rate limit (`3/m` per user) and the
   confirmation card refuses to bundle deletes — one card per delete.
3. **Bulk creation under the assistant's own context_version pump.**
   Each `create_task` bumps `context_version`, busting the cache; doing
   25 in a row would invalidate the skinny-context 25 times. Mitigation:
   `bulk_create_tasks` bumps `context_version` exactly once after the
   transaction commits, not per row.
4. **Stale `PendingToolCall`s.** A user who walks away mid-confirm
   leaves rows. Mitigation: 5-minute `expires_at` + hourly cleanup
   command (which can run alongside `send_weekly_digest` once the
   cron is wired on Render).

---

## Phase 3 — Plugins + deep mode (after Phase 2)

- Tools: `start_plugin_setup`, `request_telegram_link`,
  `update_notification_settings`, `disconnect_channel`,
  `enable_weekly_digest`. The assistant walks the user through the
  Telegram link flow using the existing `requestChannelLink` mutation
  under the hood.
- Replace `<ComingSoon />` at
  `frontend/src/app/settings/plugins/page.tsx` with a real plugin
  catalog UI.
- Sonnet 4.6 deep-mode toggle (gated to `pro` plan).
- Rolling-summary summarizer — when conversation passes 14 messages,
  Haiku rewrites the older ones into a 6-bullet "what's been done /
  pending / open questions" string stored on
  `Conversation.summary`. Cuts long-conversation cost ~5×.

## Phase 4 — Stripe paywall

- Stripe Checkout from `/settings/billing`'s "Upgrade" button.
- Webhook flips `AccountProfile.plan` and sets `plan_renews_at`.
- Telegram weekly-cost summary for `is_admin` users.

---

## Operations

### Where data lives

| Table | What |
|---|---|
| `assistant_accountprofile` | Per-user plan + cache version. One row per user. |
| `assistant_conversation` | Chat threads. |
| `assistant_message` | Individual turns. `content` is the raw Anthropic content-block array. |
| `assistant_usageday` | Daily usage counters. Append-only. |

### How to bump someone's plan

```bash
python manage.py set_plan <uuid> pro       # 300 msg/day, 5M tokens/month
python manage.py set_plan <uuid> admin     # uncapped
python manage.py set_plan <uuid> free      # demote
```

### How to look at someone's usage

```bash
python manage.py shell -c "from core.assistant.quotas import get_usage; \
  import uuid; print(get_usage(uuid.UUID('<uuid>')))"
```

Or query `UsageDay` in `/admin/`.

### Tuning quotas

`core/assistant/quotas.py:PLAN_QUOTAS` is a plain dict. Edit and
restart — no migration needed. (Eventually move to env vars.)

### Killing a runaway conversation

The streaming loop checks a per-conversation cache flag:

```bash
python manage.py shell -c "from django.core.cache import cache; \
  cache.set('assistant:cancel:<conv-uuid>', 1, 60)"
```

That stops the stream within a chunk or two.

---

## Tests

```bash
python manage.py test core.assistant      # 31 tests, ~80s
# or
pytest core/assistant/tests
```

Coverage:
- `test_quotas.py` — cap enforcement, recording, lazy profile creation.
- `test_skinny_context.py` — XML-wrapping, locale/timezone, user-scoping, escaping.
- `test_cache_layout.py` — cache_control on system blocks, version bump invalidates skinny-context.
- `test_tools_read.py` — every read tool: user-scoping, filters, limits, error wrapping.
- `test_view.py` — JWT required, SSE frame format, tool execution, oversized input rejection, quota enforcement.
