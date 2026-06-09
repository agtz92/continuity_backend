# Activity log — backend reference

Append-only feed of everything the user does. Drives the **Log** tab in
the UI and the **Analytics** panel. Lives in a single table
(`core_activity`) discriminated by `kind`.

This doc is for backend engineers touching the feed, the dashboard, or
the analytics surface. The UI side (`LogView.tsx`) consumes the same
data — there's no parallel storage on the frontend.

---

## Why a single table

There used to be two:

- `core_update`: user-authored notes (editable) **plus** a special
  `"Completed: X"` row that `toggle_task` wrote on task completion.
- `core_activitylog` (slice 1, May 2026): auto-only events for
  create/delete/status/due-date changes. Never editable.

Two tables meant duplicated reads in `compute_analytics`, a UI log that
hid achievements behind the user's writing habits, and two sets of
mutations to maintain. Migration `0009_activity_unify` collapses both
into `core_activity` keyed by `kind`. The slice-2 plan in
`~/.claude/plans/cuando-cree-elimine-temporal-lobster.md` has the full
context.

---

## Data model

[backend/core/models.py](core/models.py) — `Activity` extends
`TimestampedModel` (UUID id, user_id indexed, auto `created`).

```python
class ActivityKind(TextChoices):
    NOTE                     = "note"
    PROJECT_CREATED          = "project_created"
    PROJECT_DELETED          = "project_deleted"
    PROJECT_STATUS_CHANGED   = "project_status_changed"
    PROJECT_DUE_DATE_CHANGED = "project_due_date_changed"
    TASK_CREATED             = "task_created"
    TASK_COMPLETED           = "task_completed"
    TASK_DELETED             = "task_deleted"
    TASK_DUE_DATE_CHANGED    = "task_due_date_changed"
    IDEA_CREATED             = "idea_created"
    IDEA_DELETED             = "idea_deleted"
    IDEA_PROMOTED            = "idea_promoted"

class Activity(TimestampedModel):
    kind              = CharField(choices=ActivityKind.choices, db_index=True)
    entity_id         = UUIDField(null=True)         # no FK — survives deletion
    entity_title      = CharField(max_length=500)    # denormalized
    project_id        = UUIDField(null=True)         # denormalized for fast filter
    target_project_id = UUIDField(null=True)         # only set for idea_promoted
    note              = TextField(default="")        # only set for kind=NOTE
    previous_value    = TextField(default="")        # ISO datetime or status
    new_value         = TextField(default="")
```

**Indexes** (per-user is the only useful access pattern):

```sql
(user_id, -created)
(user_id, kind)
(user_id, project_id)
```

### Field semantics by kind

| Kind | `entity_id` | `entity_title` | `project_id` | `previous_value` | `new_value` | `note` |
|---|---|---|---|---|---|---|
| `note` | NULL | "" | the project | "" | "" | user's text |
| `project_created` | project.id | project.name | project.id | "" | "" | "" |
| `project_deleted` | project.id | project.name (snapshot) | project.id | "" | "" | "" |
| `project_status_changed` | project.id | project.name | project.id | old status | new status | "" |
| `project_due_date_changed` | project.id | project.name | project.id | iso(old) or "" | iso(new) or "" | "" |
| `task_created` | task.id | task.title | task.project_id | "" | "" | "" |
| `task_completed` | task.id | task.title | task.project_id | "" | "" | "" |
| `task_deleted` | task.id | task.title (snapshot) | task.project_id | "" | "" | "" |
| `task_due_date_changed` | task.id | task.title | task.project_id | iso(old) or "" | iso(new) or "" | "" |
| `idea_created` | idea.id | idea.title | NULL | "" | "" | "" |
| `idea_deleted` | idea.id | idea.title (snapshot) | NULL | "" | "" | "" |
| `idea_promoted` | idea.id | idea.title (snapshot) | new project.id | "" | "" | "" |

`idea_promoted` also sets `target_project_id` to the new project — the
idea is gone, the project is the surviving entity. We deliberately
**don't** emit `idea_deleted` + `project_created` for promotion; it's
one logical event.

### Denormalization rationale

- `entity_id` has **no FK** because a row must survive the deletion of
  whatever it references. Without that, `kind=project_deleted` rows would
  cascade away the moment Django's ORM tore down the project.
- `entity_title` is snapshotted for the same reason. Without it, the
  Log view shows "Deleted (untitled)" after deletion.
- `project_id` is denormalized (not a FK either) so we can filter the
  feed by project cheaply without joins — the analytics panel does
  this constantly.

### What the model does **not** capture

- The actor (always the row's `user_id`; we don't track who-on-behalf-of-whom).
- Project notes (`ProjectNote`) — those are a separate first-class
  feature in `core_projectnote`. Adding a note used to write a stub
  Update row; we dropped that in slice 2 to reduce feed noise. The
  frontend still surfaces newly-created `ProjectNote` rows in the
  "Done today" section alongside `kind=NOTE` activities (see
  [Frontend integration](#frontend-integration) below) — but they do
  **not** appear in the main LogView feed.
- Profile/category mutations.
- Notification deliveries (those live in `core_notification`).

---

## Service layer

[backend/core/services/activities.py](core/services/activities.py) is
the only module that should write to `core_activity` directly. Every
domain service calls into it.

### Internal helper

```python
def log_event(
    user_id, *,
    kind,                # ActivityKind value
    entity_id=None,
    entity_title="",
    project_id=None,
    target_project_id=None,
    previous_value="",
    new_value="",
    note="",
) -> Activity:
```

Always called **right next to** `bump_context_version(user_id)` in the
service that performs the mutation. Same single-point-of-entry pattern
the rest of the codebase uses — no Django signals, no decorators.

`iso(dt)` is a tiny helper that returns `""` for `None` so date-change
rows don't store the literal string `"None"`.

### Public note operations

User-authored notes are the only `kind` the frontend can create,
update, or delete. They go through:

```python
add_note(user_id, *, project_id, note)         -> Activity (kind=NOTE)
update_note(user_id, activity_id, *, note)     -> Activity
delete_note(user_id, activity_id)              -> None
list_activity(user_id, *,
              project_id=None,
              kinds=None,
              limit=100,
              since=None, until=None)          -> list[Activity]
```

`update_note` / `delete_note` look up the row with
`kind=NOTE` filtered — any attempt to mutate a non-NOTE row raises
`NotFoundError` so the editability rule is enforced server-side, not just
hidden in the UI.

`add_note` also bumps the parent project's `last_activity` (notes count
as activity for the "sleeping project" heuristic).

### Where each event is emitted

| Service function | Emits |
|---|---|
| `projects.create_project` | `project_created` |
| `projects.update_project` | `project_status_changed` and/or `project_due_date_changed` — only when the value actually differs from the row before save |
| `projects.delete_project` | `project_deleted` (fetch-then-delete to snapshot the name) |
| `tasks.create_task` | `task_created` |
| `tasks.update_task` | `task_due_date_changed` only — the `done` flag changing inside `update_task` is NOT logged (toggle is a separate code path) |
| `tasks.toggle_task` | `task_completed` when flipping to done. Un-completing logs nothing — it's an undo, not an achievement |
| `tasks.delete_task` | `task_deleted` |
| `ideas.create_idea` | `idea_created` |
| `ideas.delete_idea` | `idea_deleted` |
| `ideas.promote_idea` | `idea_promoted` (single event, see above) |

`projects.update_project` and `tasks.update_task` capture the **old**
value before mutating the model, then compare after `.save()`. No log
row is written when the value didn't actually change — this matters
because the frontend echoes every field on every save, so a no-op edit
to status would otherwise spam the log.

### Cycle break: `_common.py`

`services/projects.py` needs `log_event` and `services/activities.py`
needs an ownership check that lives naturally in `projects`. To avoid a
circular import:

- `services/_common.py` exports `NotFoundError`.
- `projects.py` re-exports it for backward compatibility with existing
  `from .services.projects import NotFoundError` callers.
- `activities.py` imports `NotFoundError` from `_common` and does its
  own inline `Project.objects.filter(...).exists()` check instead of
  calling `assert_owned`.

---

## GraphQL surface

[backend/core/schema.py](core/schema.py).

### Type

```graphql
type Activity {
  id: ID!
  kind: String!
  entityId: ID
  entityTitle: String!
  projectId: ID
  targetProjectId: ID
  note: String!
  previousValue: String!
  newValue: String!
  created: DateTime!
}
```

### Queries

```graphql
type Query {
  dashboard: Dashboard!     # includes `activities: [Activity!]!`
  activity(
    limit: Int = 100,
    since: DateTime,
    until: DateTime,
    projectId: ID,
    kinds: [String!],
  ): [Activity!]!
}
```

`Dashboard.activities` returns **all** the user's activity rows.
That's fine for now — the per-user feed is small enough that pagination
isn't needed. The standalone `activity(...)` query is the one to use
for the eventual stats panel and for project-specific drill-downs.

`limit` is capped server-side to 500 (`activities_svc.list_activity`).

### Mutations

```graphql
type Mutation {
  addNote(projectId: ID!, note: String!): Activity!
  updateNote(id: ID!, note: String!): Activity!
  deleteNote(id: ID!): Boolean!
}
```

No mutation to write non-NOTE rows directly — those only come from
domain mutations (`createProject`, `toggleTask`, etc.). This is the
mechanism that keeps the feed honest: the server is the source of truth
for what happened.

---

## Analytics integration

[backend/core/analytics.py](core/analytics.py) used to fold `Update`
rows together with `Task.completed_at` to compute "activity events".
Now it reads directly from `Activity`:

| Stat | How it's computed |
|---|---|
| `cadence.active_days_in_range` | Distinct dates over the windowed queryset |
| `cadence.total_activity_events` | `Activity.count()` in window — every kind counts |
| `activity_series[*].updates` | Daily count of `kind=note` |
| `activity_series[*].completed_tasks` | Daily count of `kind=task_completed` |
| `activity_series[*].total_events` | Daily count of all kinds |
| `weekday_heatmap` | All kinds, grouped by ISO weekday of `Activity.created` |
| `top_projects` | `Activity.values("project_id").annotate(Count)` over window; delta against equivalent prior window |
| `category_breakdown` | Joined manually via `project_to_category` map (Activity has no FK to Project) |
| `idea_funnel` | Still reads `Idea.created` + `Project.promoted_from_idea_at` — pre-migration ideas don't have IDEA_CREATED rows, so preserving the historical signal matters here |
| `backlog`, `sleeping_projects`, `stale_ideas`, `effort` | Untouched — they read Tasks/Projects/Ideas directly |

The `ActivityPoint` GraphQL shape (`updates`, `completedTasks`,
`totalEvents`) is preserved so the existing `ActivityChart` keeps
rendering — what changed is the semantics of `updates` (now = notes
only) and `totalEvents` (now = everything).

---

## Editability rules

Enforced at the **service** layer:

- `kind=NOTE` rows can be edited or deleted by their owner via
  `update_note` / `delete_note`.
- Every other kind is immutable through the public API. There's no
  `updateActivity` mutation. Deletion is also not allowed.

This is intentional. Audit-log rows are evidence of what happened; the
user editing or deleting them silently would defeat the point.

If you ever need to retroactively edit (e.g. fix a wrong
`entity_title`), do it via a one-off Django management command, not
the GraphQL surface.

---

## Migration history

| Migration | What it did |
|---|---|
| `0008_project_due_date_activitylog` | Added `due_date` to `Project` and created the original `core_activitylog` table (now removed). Kept here because production already applied it. |
| `0009_activity_unify` | Manual migration. Creates `core_activity`, backfills it from `core_update` (rows starting with `"Completed: "` → `kind=task_completed` with `entity_id` resolved by title-within-project; rest → `kind=note`), preserves the original `created` timestamps, then drops `core_update` and `core_activitylog`. |

### Backfill heuristic, in detail

```python
if note_text.startswith("Completed: "):
    task_title = note_text[len("Completed: "):]
    task = Task.objects.filter(
        user_id=u.user_id,
        project_id=u.project_id,
        title=task_title,
    ).first()
    Activity(kind="task_completed",
             entity_id=task.id if task else None,
             entity_title=task_title,
             project_id=u.project_id, ...)
else:
    Activity(kind="note",
             note=note_text,
             project_id=u.project_id, ...)
```

Edge cases the heuristic handles gracefully:

- Task was renamed or deleted after completion → `entity_id` is NULL
  but `entity_title` still shows what was completed.
- User wrote a real note that happens to start with "Completed: " → 
  it gets misclassified as `task_completed`. Rare and recoverable.

### Reverse migration

`reverse_noop` — re-creates `core_update` and `core_activitylog`
empty. Good enough for dev rollback; not a faithful round-trip.

---

## Adding a new activity kind

1. Add the value to `ActivityKind` in `core/models.py`.
2. (Optional but recommended) make a migration that updates the
   `choices=` enum on the column — `migrations.AlterField` on the
   `kind` field. Django will pick it up automatically with `makemigrations`.
3. Find the service mutation that should emit it. Call
   `log_event(user_id, kind=ActivityKind.YOUR_NEW_KIND, ...)` next to
   the existing `bump_context_version(user_id)` line.
4. If `update_X` should detect a diff (like status_changed does):
   capture the old value before mutating, compare after `.save()`,
   only log when it actually changed.
5. Add a render branch in
   `frontend/src/components/views/LogView.tsx`:
   - `describe()` for the human-readable string
   - `iconFor()` for the icon
   - if it's an achievement, add it to `ACHIEVEMENT_KINDS`; if it's a
     change, to `CHANGE_KINDS`; if it's a deletion, to `DELETED_KINDS`.
6. Decide whether analytics should special-case it. The default is
   "counts toward `totalEvents` only" — that's free, no code needed.
   Only special-case if you want it to show up in `activitySeries`
   alongside `updates`/`completedTasks`.
7. Write a test in `core/tests/test_activity.py` asserting the row is
   written with the expected fields.

---

## Performance notes

- The dashboard query loads **all** the user's activity rows. At ~10
  rows/day that's ~3650/year, which is fine for the size of the user
  base. If/when this gets uncomfortable, switch the LogView to consume
  the lazy `activity(...)` query with a cursor.
- `log_event` is a single `INSERT` with no joins. The bump it adds to
  each mutation is one extra round-trip — comparable in cost to
  `bump_context_version`, which we've already accepted.
- The migration backfill iterates rows in Python (`.iterator()`) and
  resolves task titles one at a time. With 40 rows on the production
  user this took milliseconds; if a user ever has 50k Updates the
  migration would want a bulk strategy. Not a current concern.

---

## Frontend integration

The frontend reads `Activity` rows from `Dashboard.activities` and
exposes them in two places.

### `LogView.tsx` — the dedicated feed

Renders every kind with per-type icons and lets the user filter by
chip group (`All`, `Achievements`, `Notes`, `Changes`, `Deleted`). Only
`kind=NOTE` rows are editable / deletable from this UI — the backend
enforces the rule, the UI just hides the affordance for everything else.

### `TodayView.tsx` — the "Done today" rail

This section deliberately mixes three sources to give the user a
sense of accomplishment for *anything* they did today:

| Source | What shows up | DoneItem.kind | Badge text |
|---|---|---|---|
| `Task` with `completedAt` today | Task completions | `task` | **TAREA** / **TASK** |
| `Activity` with `kind=NOTE` created today | Timeline log entries (from "Log Update" button) | `log` (`source: "activity"`) | **NUEVO LOG** / **NEW LOG** |
| `ProjectNote` created today | Rich project notes from the Notes section | `log` (`source: "projectNote"`) | **NOTA NUEVA** / **NEW NOTE** |

The two note-shaped sources share the same visual treatment
(`TrendingUp` icon, `accent-2` color, single chip filter labeled **#
entradas** / **# entries**) but their per-item badge differs to
reflect the user's mental model: a "log" is a quick timeline entry, a
"note" is a richer document attached to the project.

The merge happens in `frontend/src/hooks/useTodayFocus.ts`. The
`DoneItem.log` variant carries a normalized `{ id, projectId, text }`
plus a `source` field for telemetry / future per-type styling — the
backend doesn't see the union, it just serves the raw `Activity` rows
and `ProjectNote` rows separately through `Dashboard`.

Other `Activity` kinds (`project_created`, `task_completed`,
`idea_promoted`, etc.) are **not** surfaced in "Done today" — they
have their own home in `LogView` and the analytics chart. Adding them
there would over-celebrate trivial actions like renaming a project.

---

## Tradeoffs we live with

1. **Best-effort logging.** `log_event` is a synchronous insert in the
   same transaction as the parent mutation, but there's no
   `transaction.atomic()` wrapping the two — if the log insert raises,
   the mutation has already committed. Acceptable because the failure
   modes (DB down, schema mismatch) would also fail the parent
   mutation, and we'd rather lose a log row than block the user.
2. **No actor/source.** Every row's actor is implicitly the
   row's `user_id`. We don't track "this was triggered by the assistant
   running a tool" vs "this was a direct UI action". If that becomes
   useful, add a `source` column rather than overloading `kind`.
3. **idea_promoted is one event, not three.** Analytics code that
   wants "projects created including promoted ones" has to look at
   both `project_created` and `idea_promoted`. Documented above.
4. **History begins at slice-2 deploy.** Migration 0009 backfilled
   what was in `core_update` but couldn't reconstruct project/idea
   creates, deletes, status changes, etc. from before that table
   existed. Pre-migration projects show up in the dashboard with no
   `project_created` row. Live with it.
5. **One table, two personalities.** Editable NOTE rows live next to
   immutable system events. We mitigate by enforcing the
   editability rule in the service (not just the UI) and by never
   exposing a `updateActivity` GraphQL mutation. If this ever feels
   unsafe, splitting back into two tables is a one-migration job.
