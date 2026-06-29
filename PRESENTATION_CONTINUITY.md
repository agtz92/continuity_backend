# Continuity (`continuu.it`)
### The project manager that makes you *finish* — built for people who start more than they finish

> **How to read this document.** It is organized in layers. The first two sections give
> a business reader the full value of the product in about two minutes. Each section
> after that adds depth, ending with a clearly separated **Technical Annex** for anyone
> who wants the engineering detail. You can stop reading at any layer and still have a
> complete, accurate picture for your level.

---

## 1. Executive summary

**Continuity is a personal productivity workspace with one strong opinion: every project you start must reach a decision.**

Most productivity tools are great at helping you *add* things — more tasks, more notes, more lists. They are silent about the real problem of ambitious people: a growing **graveyard of half-finished projects** that quietly drains time, momentum, and confidence. Continuity is the first tool built around closing that loop. A project in Continuity is never allowed to simply *drift*. It must end up **Finished, Launched, Paused on purpose, or deliberately Killed** — never abandoned.

| | |
|---|---|
| **What it is** | A workspace to manage projects, tasks, ideas, routines and notes — on web and mobile — with a built-in AI assistant. |
| **The problem it solves** | The hidden cost of unfinished work: stalled side-projects, forgotten commitments, and the slow erosion of trust in your own ideas. |
| **Who it's for** | Founders, freelancers, and side-project builders — people who "start more than they finish." |
| **Why it's different** | It introduces *forced closure*: a project that goes quiet is surfaced and you are asked to decide its fate. It even keeps a "graveyard" and uses AI to show you *why* you keep abandoning things. |
| **How you reach it** | A web app, a mobile app (iOS, in TestFlight), and — uniquely — directly from inside Claude (Anthropic's AI assistant) through a secure connector. |
| **Business model** | Freemium. A free tier, plus two paid tiers (**Pro** and **Studio**) that raise limits and unlock the more powerful AI features. Currently in **private beta** (50 spots). |

**The one-line pitch:** *Continuity turns "I'll get to it later" into a decision.*

---

## 2. What you can do with Continuity

Everything below is a **capability the product has today**. Think of these as the things a user can actually do, described as benefits rather than mechanics.

### Manage projects that can't quietly die
- Capture a project with its purpose, the *why*, and the **next concrete step**.
- Move it through a clear lifecycle: **Idea → Active → Stalled → Paused → Launched → Killed → Archived.**
- When a project goes quiet, the system flags it as **Stalled** and asks you to decide: *ship it, kill it, or get help.*
- **Close with intention.** Pausing captures context and the next action; killing captures the reason and the lessons learned — so a closed project is a record, not a regret.
- **Revive** a paused or killed project later — and the AI reads your old closure notes to brief you on where you left off.

### Break work down and actually do it
- Create **tasks** with due dates, due times, estimated effort (hours), and links to a project.
- Mark **blockers** ("this task is waiting on X") so nothing silently stalls.
- See a focused **"Today"** view: what's due, what's overdue, what routines are pending, and what you've already finished today.

### Capture ideas without cluttering your projects
- Jot down **ideas** instantly, with no project required.
- **Promote** a promising idea into a full project in one step.
- Stale ideas (sitting untouched for weeks) are surfaced so you can promote or let them go.

### Build consistency with routines
- Define recurring **routines** (daily, weekly, monthly, or custom).
- Tick them off as you go and track your cadence over time.

### Keep your thinking in one place
- **Quick Notes** — a Notion-style notebook with collapsible, reorderable sections, categories, and pinning.
- **Project notes** — notes attached directly to a specific project.

### See your real productivity, honestly
- An **Analytics** dashboard with multiple panels: completion cadence, project status breakdown, backlog trend, most-active weekdays, top projects by effort, the **idea → project → task funnel**, sleeping projects, and your AI usage.

### Plan visually
- A **Calendar** with Day / Week / Month views that lays out your projects and routines, showing how much is on your plate on any given day.
- **Subscribe to it anywhere.** Export your tasks and routines as a private, read-only calendar feed (`.ics`) you can subscribe to from **iOS Calendar, Google Calendar, or Outlook** — a deliberate one-way feed (no fragile two-way sync, no third-party credentials stored).

### Get help from an AI that knows your work
- **Loop**, the built-in assistant, can answer questions about your projects and — on paid plans — create and update tasks for you through conversation.
- Use it directly from inside **Claude** (Anthropic's assistant) via a secure connector, so you can manage Continuity without leaving your AI chat.

### Stay reminded
- Connect notification channels (Telegram today; more planned) to get nudges about what's pending.

> **The central objects you work with:** *Projects* (the heart of it), *Tasks*, *Ideas*,
> *Routines*, and *Notes* — all tied together by an *Activity log* that quietly records
> what you accomplish, and a *Graveyard* that remembers what you let go.

---

## 3. Who uses it, and what they can do

Continuity is primarily a **single-user product** — it's *your* workspace, not a team collaboration tool. But there are a few distinct types of actor that interact with the system.

| Actor | Who they are | What they can do |
|---|---|---|
| **The individual user** | A founder, freelancer, or builder managing their own work. | Everything in Section 2: create and close projects, manage tasks/ideas/routines/notes, view analytics and calendar, chat with the AI, and configure their account, theme, and notifications. |
| **The AI assistant (Loop)** | Continuity's built-in assistant, acting on the user's behalf. | Reads the user's data to answer questions; on paid plans, creates and updates tasks and projects through conversation. Always scoped to that one user's data. |
| **An external AI client (Claude)** | The user's own Claude app, connected through a secure link. | The same read/write capabilities as Loop, but accessed from inside Claude. The user grants access explicitly and can revoke it at any time. |
| **The administrator / operator** | The Continuity team running the service. | A separate admin area to manage the beta waitlist, users, billing, announcements, the marketing/help content, support inbox, and system health. *(Internal-facing; not part of the customer product.)* |

> There is **no multi-user collaboration** today — no shared projects, no team
> workspaces, no comment threads between users. Each account is private to its owner.
> This is a deliberate focus, not a gap to apologize for: the product is about *your*
> relationship with *your* unfinished work.

---

## 4. What makes Continuity distinctive

This section explains the handful of things that genuinely set Continuity apart. For each, we say **why it matters to the business first**, then offer the technical "why" for readers who want it.

### 4.1 Forced closure — the product's core idea

**Why it matters.** Every other tool lets work pile up silently. Continuity's entire reason to exist is that it *refuses to let a project quietly rot.* After a stretch of inactivity, a project is automatically marked **Stalled** and the user is confronted with a simple, humane choice: finish it, kill it, or ask for help. This is the feature the whole brand is built on ("Finish what you start"), and it's the reason a user would choose Continuity over a generic to-do app.

**The detail.** A project's life is modeled as an explicit state machine — `idea → active → stalled → paused → launched → killed → archived`. A scheduled background job sweeps active projects and transitions ones that have gone quiet to `stalled`. Crucially, this automatic transition is treated as a *non-event* for activity tracking, so the system doesn't fool itself into thinking the user was active.

### 4.2 The Graveyard and AI "autopsy"

**Why it matters.** Killing a project is reframed from a failure into a *learning moment*. Killed projects don't vanish — they go to a **Graveyard**, each carrying the reason it died and what was learned. Once a user has killed a few projects, the AI looks across all of them and surfaces the **pattern**: *why* this person keeps abandoning work. That insight is something no checklist app can offer, and it's a strong reason to stay.

**The detail.** Killing a project captures structured closure notes (reason, learnings, whether you'd restart). A best-effort AI reflection is generated per kill. Once there are three or more killed projects, a second AI pass computes a cross-project insight, cached as a single record and refreshable on demand.

### 4.3 One AI, three front doors — including *inside Claude*

**Why it matters.** Continuity's assistant ("Loop") doesn't just live in the app. The same intelligence is available on the website, in the mobile app, **and from directly inside Claude** through an industry-standard connector. A power user can manage their projects by simply talking to the AI assistant they already use every day. And there's a clever commercial angle: when used through that connector, **the AI usage is billed to the user's own Claude account, not to Continuity** — so this distribution channel costs Continuity almost nothing to run.

**The detail.** The web assistant, the mobile assistant, and the external connector all call the *same* underlying tool layer. The external connector is implemented as an MCP (Model Context Protocol) server — the open standard Anthropic uses for tool integrations — secured with a full OAuth 2.1 login flow, with the connection auditable and revocable. The server is built, deployed, and tested today; its public settings toggle is held behind a "Coming soon" label pending launch (see Section 5).

### 4.4 Privacy by design in analytics

**Why it matters.** Continuity measures engagement to run the business, but it does so **without storing the content of what you do**. For a product that holds your most personal ambitions, "we count that you were active, we don't read what you wrote" is a meaningful trust signal.

**The detail.** Interaction metrics are recorded as daily counts per user and per channel (web / mobile / connector). No message content or payload is persisted in these metrics, and a recording failure never breaks the user's actual request.

### 4.5 A marketing site engineered to be fast

**Why it matters.** First impressions convert. The public site was deliberately rebuilt to load fast even on a phone on a weak connection — because a slow landing page costs sign-ups.

**The detail.** The marketing pages are served as pre-built static pages (cached at the edge), with the heavy application code, AI client, and animation libraries kept out of the public bundle. The result was a roughly 44% reduction in initial page weight and image payloads shrunk from megabytes to tens of kilobytes.

### 4.6 Fair, transparent limits per plan

**Why it matters.** The free-to-paid model is enforced cleanly and predictably, so users always know what they get, and upgrades feel fair rather than punitive.

**The detail.** Every limit (number of projects, tasks, ideas, routines, notes, plus AI message and token allowances) is defined in one place per plan and enforced consistently — whether the user creates something by hand or asks the AI to do it. See the Annex for the exact numbers.

---

## 5. Where each capability stands today

Continuity is a real, running product, not a prototype — but like any active product, some pieces are fully shipped and others are in flight. This table is an honest snapshot.

| Capability | Web | Mobile | Notes |
|---|---|---|---|
| Projects, tasks, ideas, routines | ✅ Shipped | ✅ Shipped | Full lifecycle including stalled/paused/killed. |
| Today view & Activity log | ✅ Shipped | ✅ Shipped | |
| Quick Notes (Notion-style) | ✅ Shipped | ✅ Shipped | |
| Calendar (Day/Week/Month) | ✅ Shipped | ✅ Shipped | Drag-to-reschedule is a planned enhancement. |
| Calendar export (`.ics` feed) | ✅ Shipped | ✅ Shipped | Account-level: private read-only subscription URL. Direct Google/iCloud two-way sync is **deliberately not built** (OAuth-verification & credential-storage cost). |
| Analytics dashboard | ✅ Shipped | ✅ Shipped | |
| Loop AI assistant | ✅ Shipped | ✅ Shipped | Read on free tier; write on paid tiers. |
| Graveyard + AI autopsy | ✅ In product | ✅ In product | Core models and logic are in the codebase. |
| Beta program + lifecycle | ✅ In product | — | 50-spot cohort with lifetime deal. Inactivity is tracked in rolling tiers (ghost / brief / established) and unused spots are auto-reclaimed via a bilingual email sequence — always with a prior warning, and `dry_run` by default. |
| Claude connector (MCP) | 🟡 Built, not switched on | — | Backend is complete and live (the `/mcp/` endpoint and full OAuth 2.1 login are deployed and tested). The customer-facing settings screen still presents it as "Coming soon" — it's awaiting the launch toggle in the UI, not more engineering. |
| Account self-deletion | ✅ Shipped | ✅ Shipped | Full backend + a two-step confirmation in the mobile app. Satisfies the App Store requirement. |
| Push notifications (mobile) | — | 🟡 Backend live, client gated | The *reverse* of a typical gap: the **server** is built and wired (Expo provider, `ExpoPushToken` table, `register_push_token` mutation, dispatched from the hourly cron). The **mobile client** still gates token registration behind a `PUSH_BACKEND_READY=false` flag, so end-to-end push activates the moment that flag flips. |
| WhatsApp notifications | 🟡 Planned | 🟡 Planned | Telegram is live today. |

> **A note on documentation vs. reality.** Some internal design documents in the project
> still describe certain features (e.g. project closure, the beta lifecycle) as
> "designed, not yet built." The actual source code is *ahead* of those documents — the
> corresponding data models and logic are already present. Where they disagree, this
> presentation follows the **code**, which is the source of truth.

---

# Technical Annex
*Clearly separated from the business sections above. Everything below is for a technically inclined reader.*

## A. Technology stack

| Layer | Technology |
|---|---|
| **Backend** | Python, **Django 5.1**, **Strawberry GraphQL**. Runs on Render. |
| **Database** | **PostgreSQL**, hosted on Supabase. |
| **Authentication** | Supabase Auth (JWT bearer tokens); the backend verifies the token and derives the user identity. |
| **Web frontend** | **Next.js 15** (App Router), **React 19**, **Apollo Client** (GraphQL), **Tailwind CSS**, **next-intl** (English/Spanish). Hosted on Vercel. |
| **Mobile** | **Expo SDK 54 / React Native**, **NativeWind** (Tailwind for RN), Apollo Client, built/distributed via **EAS**; first build in TestFlight (bundle `it.continuu.app`). |
| **AI** | Anthropic Claude — a fast model for normal chat and a stronger "deep" model (Sonnet) for harder requests, gated by plan. |
| **Payments** | **Stripe** (subscriptions for Pro/Studio). |
| **Transactional email** | **Resend** (bilingual welcome + lifecycle emails). |
| **Notifications** | Telegram today; WhatsApp planned. |

> **Definitions for non-specialists.** *GraphQL* — a query language that lets the apps ask
> the server for exactly the data they need in one request. *JWT* — a signed digital token
> that proves who you are without re-entering your password. *MCP (Model Context Protocol)* —
> an open standard, created by Anthropic, that lets AI assistants safely use external tools.

## B. Architecture overview

```
                         ┌──────────────────────────┐
        Web (Next.js) ───┤                          │
                         │                          │
     Mobile (Expo/RN) ───┤   GraphQL API (Django +  │──── PostgreSQL (Supabase)
                         │      Strawberry)         │
   Claude  ── MCP/OAuth ─┤                          │──── Stripe / Resend / Telegram
   (external AI client)  │   shared assistant tools │
                         └──────────────────────────┘
```

- All three clients (web, mobile, external Claude) speak to **one GraphQL API**.
- A small **public, unauthenticated GraphQL endpoint** serves only *published* marketing/help
  content to the static website, kept separate from the authenticated app API.
- The in-app assistant and the external connector share the **same tool implementations**
  (`core/assistant/tools/`), so behavior and permissions stay consistent across surfaces.

## C. Core data model (entities)

Confirmed in `backend/core/models.py`:

| Entity | Purpose |
|---|---|
| **Project** | The central object. 7-state lifecycle (`idea/active/stalled/paused/launched/killed/archived`), priority, optional category, due date, and structured closure notes. |
| **Task** | A unit of work; optional project link, due date/time, estimated hours, done flag. |
| **TaskBlocker** | Records that a task is blocked by something. |
| **Idea** | Lightweight capture; can be promoted to a Project. |
| **Routine** / **RoutineOccurrence** | Recurring habit + its individual occurrences. |
| **ProjectNote** | A note attached to a specific project. |
| **QuickNote** / **NoteSection** | Notion-style notebook note with ordered, collapsible sections. |
| **Category** | User-defined tag shared across projects and notes. |
| **Activity** | Append-only log of meaningful events (the basis of the Log and analytics). |
| **GraveyardInsight** | Cached cross-project AI reflection on killed projects. |
| **StalledSweepState** | Bookkeeping for the background "stall" sweep. |
| **AccountProfile** | Per-user plan, billing/Stripe linkage, beta-cohort status, and quota/cache versioning. |
| **InteractionDay** / **UsageDay** | Privacy-preserving daily counters (engagement and AI usage). |
| **OAuthClient / AuthorizationCode / RefreshToken / ConnectionEvent** | Backing tables for the secure MCP connector. |

## D. Plans and limits (exact figures from code)

**Entity limits** (`core/quotas.py`) — `∞` = unlimited:

| Limit | Free | Pro | Studio |
|---|---|---|---|
| Projects (excl. killed/archived) | 3 | 25 | ∞ |
| Tasks per project | 20 | 200 | ∞ |
| Open tasks (total) | 50 | ∞ | ∞ |
| Routines | 2 | 20 | ∞ |
| Ideas | 30 | 500 | ∞ |
| Categories | 3 | 15 | ∞ |
| Quick Notes | 50 | 1,000 | ∞ |
| Notes per project | 3 | ∞ | ∞ |
| Sections per note | 20 | ∞ | ∞ |

**AI assistant quotas** (`core/assistant/quotas.py`):

| AI limit | Free | Pro | Studio |
|---|---|---|---|
| Messages per day | 15 | 200 | 600 |
| Tokens per month | 100K | 3M | 15M |
| "Deep" (Sonnet) messages per day | 0 (off) | 5 | 25 |

> A design nuance worth noting: if a user drops from a paid plan to Free while *over* the
> limit, creation is blocked across the app until they clean up below the cap — preventing
> "free behavior on paid leftovers." Billing-exemption is intentionally **decoupled** from
> the plan (a beta member, friend, or investor can be exempt from charges while still on a
> given feature tier).

## E. Security & privacy posture

- **Authentication** on every authenticated request via Supabase JWT; the user identity is
  derived server-side, not trusted from the client.
- The **admin** surface is gated behind an explicit `is_admin` flag and **every admin action
  is audit-logged**.
- The **external connector** uses an OAuth authorization flow; connections are recorded as
  events (authorized / refreshed / revoked) and can be revoked by the user or an admin.
- The connector is **rate-limited per plan** (Free 30 / Pro 120 / Studio 300 requests per minute)
  to protect the API surface, with a tool **policy layer** that scopes which tools each plan may
  call — preventing plan-escalation or admin-tool access from the connector.
- **Analytics store counts, not content** — no message bodies or payloads are persisted in
  the interaction metrics, and metric-recording failures never break the underlying request.
- The **bug-report** channel is intentionally one-way (user → admin inbox), with no
  user-facing reply path and a soft per-user rate limit.

## F. Notable engineering decisions

- **Static-first marketing site.** Public pages are pre-rendered and edge-cached, with locale
  driven by the URL (not cookies) so the pages can stay fully static. Heavy libraries (Apollo,
  Supabase client, animation) are excluded from the public bundle. Net effect: ~44% smaller
  first-load JavaScript (233 kB → 130 kB) and images shrunk from ~3.3 MB to ~120 KB.
- **Idempotent, config-driven operations.** Background jobs (welcome emails, inactivity
  reclaim, stall sweeps) are idempotent and tunable through a runtime config table without a
  redeploy; emails default to a `dry_run` mode for safe rollout.
- **Shared tool layer for all AI surfaces** keeps the in-app assistant and the external
  connector behaviorally identical and gated by the same plan checks.
- **Active modularization effort.** The team tracks oversized "god-files" in
  `AUDITORIA_CODIGO.md` and is decomposing them; this is internal code-health work, not
  user-facing.

## G. Internationalization

- Full **English / Spanish** support across web and mobile, via `next-intl` (web) and
  `i18next-ICU` (mobile). Marketing locale is encoded in the URL (`/` for English, `/es` for
  Spanish) to keep pages statically cacheable.

## H. Testing & deployment

- **Backend:** pytest + pytest-django (SQLite in-memory, Supabase JWT stubbed). Deployed on
  Render (`render.yaml`, `Procfile`, `build.sh`) with scheduled cron jobs for lifecycle tasks.
- **Web:** Vitest + Testing Library with a mocked GraphQL client; deployed on Vercel.
- **Mobile:** built and distributed through EAS; first build is in Apple TestFlight.

## I. Open items / to confirm

- **Exact subscription prices** (the dollar amounts for Pro and Studio) live in Stripe and were
  not read from the codebase — confirm separately before quoting them.
- **Mobile push notifications** are backend-complete (Expo provider, token table, registration
  mutation, hourly-cron dispatch); what's pending is the mobile client flipping
  `PUSH_BACKEND_READY` to register tokens. Calendar and account self-deletion are already shipped
  on mobile. *(Note: an older doc described this as "server not enabled" — that's stale; the gap is
  on the client side.)*
- **Connector launch.** The MCP connector backend is fully built, deployed, and tested (live
  `/mcp/` endpoint with OAuth 2.1). What remains is flipping the user-facing settings screen
  from "Coming soon" to live — a launch decision, not outstanding engineering.
- The working directory is **not a git repository**, so this presentation reflects the current
  state of files rather than version history.

---

*Prepared from a direct review of the Continuity codebase (backend, web frontend, mobile app,
and project documentation). Figures and capabilities are taken from the source; anything not
verifiable in the code is explicitly flagged as "to confirm" rather than asserted.*
