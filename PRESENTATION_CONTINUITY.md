# Continuity (`continuu.it`)
### The project manager that makes you *finish* — built for people who start more than they finish

> **Payments, pricing and subscriptions — source of truth:**
> [Integración de pagos web y móvil](docs/integracion-pagos-web-y-movil.md) and
> [pagos-unificados/PLAN.md](docs/pagos-unificados/PLAN.md). Anything this
> document says about prices or billing is a summary; where they differ, those win.

> **How to read this document.** It is written in layers. Sections 1 and 2 give a
> business reader the whole value of the product in about two minutes. Each section
> after that adds depth, ending in a clearly separated **Technical Annex** for anyone
> who wants the engineering detail. You can stop at any layer and still have a
> complete and accurate picture for your level.
>
> *Prepared from a direct reading of the source code on 14 September 2026. Every
> figure below was taken from the code or from project documentation. Anything not
> verifiable in the source is explicitly flagged as **to confirm** rather than asserted.*

---

## 1. Executive summary

**Continuity is a personal productivity workspace with one strong opinion: every project you start must reach a decision.**

Most productivity tools are excellent at helping you *add* things — more tasks, more notes, more lists. They are silent about the real problem of ambitious people: a growing **graveyard of half-finished projects** that quietly drains time, momentum, and confidence. Continuity is built around closing that loop. A project here is never allowed to simply drift. It must end up **Finished, Launched, Paused on purpose, or deliberately Killed** — never abandoned.

| | |
|---|---|
| **What it is** | A workspace for projects, tasks, ideas, routines and notes — on the web and on mobile — with a built-in AI assistant called **Loop**. |
| **The problem it solves** | The hidden cost of unfinished work: stalled side-projects, forgotten commitments, and the slow erosion of trust in your own ideas. |
| **Who it's for** | Founders, freelancers and side-project builders — in the product's own words, *"people who start more than they finish."* |
| **Why it's different** | **Forced closure.** A project that goes quiet is automatically flagged and the user is asked to decide its fate. Killed projects go to a **Graveyard** that keeps the reason, and the AI eventually tells you *why you keep abandoning things*. |
| **How you reach it** | A web app, a mobile app (iOS, in TestFlight) and — unusually — **from inside Claude itself**, through a secure standards-based connector. |
| **Business model** | Freemium: a free tier plus two paid tiers, **Pro ($8.99/mo)** and **Studio ($14.99/mo)**, both with a 14-day trial. Sold through three channels (web, App Store, Google Play) at identical USD prices. |
| **Stage** | A live, running product in **private beta** (50 spots, lifetime free access for testers). |

**The one-line pitch:** *Continuity turns "I'll get to it later" into a decision.*

### Why an executive should care

- It is not a prototype. Roughly **122,000 lines of application code** across three codebases, **545 automated backend tests**, deployed infrastructure, a payment system wired to three stores, a working AI assistant, and an admin back-office.
- The differentiation is **structural, not cosmetic**. The "forced closure" idea is encoded in the data model and in scheduled background jobs, not in marketing copy — a competitor cannot add it as a feature flag.
- There is a **distribution channel most products don't have**: users can operate Continuity from inside Claude, and in that mode the AI cost is billed to the user's own Claude subscription rather than to Continuity.

---

## 2. What you can do with Continuity

Everything below is a **capability that exists in the product today**. These are things a user can actually do, described as benefits rather than mechanics.

### Manage projects that can't quietly die
- Capture a project with its purpose, **the *why*, and the next concrete step** — three fields that force you to be honest about whether it should exist.
- Move it through an explicit lifecycle: **Idea → Active → Stalled → Paused → Launched → Killed → Archived.**
- When a project goes quiet for **14 days**, the system marks it **Stalled** and confronts you with a simple choice: keep it, pause it, or kill it.
- **See time as a material.** Every project carries a "cooling" reading — *warm* (touched in the last 7 days), *cooling* (8–21), *cold* (22+) — so a neglected project literally looks neglected. At 45 days the product asks whether it is still alive.
- **Close with intention.** Pausing captures the context, the next action and the blocker. Killing captures the reason, the learnings, and whether you'd restart. A closed project becomes a record, not a regret.
- **Revive** a paused or killed project later, with its closure notes waiting for you.
- **See what's actually stuck.** "Blocked" isn't a status you set — it's derived: a project is blocked when one of its open tasks is waiting on something unresolved.

### Break work down and actually do it
- Create **tasks** with due dates, due times, estimated effort in hours, and an optional link to a project.
- Record **blockers** ("this is waiting on X") so nothing stalls silently.
- A focused **Today** view: what's due, what's overdue, which routines are pending, and what you already finished today — and you can **customize which sections appear and in what order**.
- **Today's Focus** mixes tasks, stalled projects and next steps into one short list of what actually deserves attention.

### Capture without friction
- **Quick capture (⌘K)**: type one line — *"Call the supplier tomorrow #Website !high"* — and the product parses it into a real task with a project, a date and a priority. Tokens that don't resolve stay in the title rather than being silently dropped, and nothing is lost if you're offline: drafts and failed writes are queued and retried.
- On paid plans, **⌘↵ interprets the line with AI** — and deliberately does *not* write anything: it rewrites your line showing what it understood, so you can confirm.

### Capture ideas without cluttering your projects
- Jot down **ideas** instantly, with no project required.
- **Promote** a promising idea into a full project in one step.
- Ideas left untouched for weeks are surfaced so you can promote them or let them go.

### Build consistency with routines
- Define recurring **routines** — daily, weekly, monthly or custom intervals — with optional times and effort estimates.
- Tick them off as they come due and track your cadence over time.

### Keep your thinking in one place
- **Quick Notes** — a Notion-style notebook: notes made of collapsible sections you can drag to reorder, categorize, pin, or attach to a project.
- **Project notes** — an update log attached to a single project.

### See your real productivity, honestly
- An **Analytics** dashboard: completion cadence, activity over time, project status breakdown, category breakdown, backlog health (overdue / due soon / quick wins), most-active weekdays, top projects by effort, the **idea → project → task funnel**, sleeping projects, stalled projects, stale ideas, and your Loop usage.

### Plan visually, and take the plan with you
- A **Calendar** with Day / Week / Month views showing tasks and routines, and how loaded any given day is.
- **Subscribe to it anywhere.** A private, read-only calendar feed (`.ics`) you can subscribe to from iOS Calendar, Google Calendar or Outlook — one URL, every platform, no passwords handed over.
- **Or write directly into your calendar.** Connect Google Calendar and your tasks and routines are pushed as real events (routines as a single recurring event, not one event per day). An iCloud path exists via CalDAV for users who want native writes on Apple. *(See §5 for its deployment caveat.)*
- **Import from Google Tasks** — a one-shot import that routes each Google list into a Continuity project, with de-duplication so re-running it doesn't double your work.

### Get help from an AI that knows your work
- **Loop**, the built-in assistant, answers questions about your projects and — on the top tier — **creates and reorganizes your work through conversation**, with 44 dedicated capabilities covering every object in the product.
- Use it **from inside Claude** through a secure connector, so you can manage Continuity without leaving the AI chat you already use.

### Stay reminded, on your own terms
- **Telegram** digests — a weekly review, a daily "what's pending", and an end-of-day warning that only fires if something is still open.
- **Mobile push notifications**, and bilingual transactional **email**.
- All of it scheduled in *your* timezone, at *your* chosen hour, and switchable per type.

### Own your data
- **Export and re-import** your entire workspace as a file.
- **Delete your account** — permanently, from inside the app, in two confirmations.

> **The central objects you work with:** *Projects* (the heart of it), *Tasks*, *Ideas*,
> *Routines*, *Notes* and *Categories* — tied together by an *Activity log* that quietly
> records what you accomplish, and a *Graveyard* that remembers what you let go.

### The objects, in one table

| Object | What it is | Why it exists |
|---|---|---|
| **Project** | A body of work with a name, a *why*, a next step, a status, a priority and optional closure notes. | The unit the whole product defends: it must reach a decision. |
| **Task** | A unit of work, optionally inside a project, with a due date/time and estimated hours. | What you actually do today. |
| **Blocker** | A note that a task is waiting on something. | Makes "stuck" visible instead of silent — and rolls up to the project. |
| **Idea** | A one-line capture with no commitment. | Lets you record an impulse without opening a project you'll abandon. |
| **Routine** | A recurring commitment with its own occurrences. | Consistency, separate from one-off work. |
| **Quick Note** | A notebook note with collapsible, reorderable sections. | Thinking that doesn't fit in a task. |
| **Category** | A user-defined label shared across projects and notes. | Grouping without a rigid hierarchy. |
| **Activity** | An append-only log of meaningful events. | Feeds the diary, the analytics and the "is this user alive?" logic. |
| **Graveyard insight** | A cached AI reflection across killed projects. | Turns a pile of failures into a pattern you can act on. |

---

## 3. Who uses it, and what each can do

Continuity is deliberately a **single-user product** — it is *your* workspace, not a team tool. But several distinct actors interact with the system.

| Actor | Who they are | What they can do |
|---|---|---|
| **The individual user** | A founder, freelancer or builder managing their own work. | Everything in §2: create and close projects, manage tasks, ideas, routines and notes, see analytics and the calendar, talk to Loop, connect integrations, and configure their account, theme, avatar, language and notifications. |
| **The visitor** | Anyone on the public website. | Read the landing page, the blog, the help centre and the legal pages — in English or Spanish — without an account. |
| **Loop, the built-in assistant** | Continuity's own AI, acting on the user's behalf. | Reads that one user's data to answer questions; on the top tier, creates and updates their work through conversation. Never crosses between users, and is bound by exactly the same limits as the human. |
| **An external AI client (Claude)** | The user's own Claude app, connected through a secure link the user authorizes. | Reads their Continuity data from inside Claude; on the top tier, writes too. The user grants access explicitly and can revoke it at any time. |
| **The administrator / operator** | The Continuity team running the service. | A separate back-office at `admon.continuu.it`: manage users and plans, the beta cohort, billing and revenue, announcements, the marketing and help content, the bug-report inbox, background jobs, platform stats and an audit log. *(Internal; not part of the customer product.)* |

> **There is no multi-user collaboration today** — no shared projects, no team workspaces,
> no comments between users. Each account is private to its owner. This is a deliberate
> product decision, not an oversight: the product is about *your* relationship with
> *your* unfinished work. A B2B "Teams" layer has been designed on paper but **no code
> for it exists yet** (see §5).

### What each plan unlocks, in plain terms

| | **Free** | **Pro** — $8.99/mo | **Studio** — $14.99/mo |
|---|---|---|---|
| The workspace | A real, non-expiring workspace: 3 projects, 50 open tasks, 2 routines, 30 ideas | Room to run a portfolio: 25 projects, 20 routines, 500 ideas, 1,000 notes | Unlimited |
| **Loop** | Not included — the app shows what Loop *would* do with your data | **Query mode**: a catalogue of ready-made questions about your own work | **Conversation mode**: Loop creates, edits and reorganizes your work |
| Claude connector | **Included, read-only** | Included, read-only | Included, **with write access** |
| Integrations | Calendar feed, Telegram, email | + Google Tasks and Google Calendar sync, daily digest | Everything |
| AI quick capture | — | — | Included |

> **A notable commercial choice:** the *free* tier gets the Claude connector. That is not
> an accident. Reading your own data through your own Claude subscription costs Continuity
> almost nothing — so the cheapest tier gets the feature that costs the least to serve,
> and Continuity's own AI spend is concentrated in the tier that pays for it.
> *(Annual billing: Pro $89.99/yr, Studio $149.99/yr — a 17% saving. 14-day trial on both.)*

---

## 4. What makes Continuity distinctive

This section covers the handful of things that genuinely set the product apart. For each: **why it matters commercially first**, then the technical detail for readers who want it.

### 4.1 Forced closure — the core idea

**Why it matters.** Every other tool lets work pile up in silence. Continuity's reason to exist is that it *refuses to let a project quietly rot*. After a stretch of inactivity a project is automatically marked **Stalled** and the user is confronted with a humane choice: keep it, pause it, or kill it. This is the feature the whole brand rests on ("Finish what you start"), and it is the reason someone would choose this over a generic to-do app.

**The detail.** A project's life is an explicit seven-state machine (`idea → active → stalled → paused → launched → killed → archived`). An hourly scheduled job sweeps active projects and moves ones untouched for 14 days to `stalled`. Two details show the care taken: only `active` projects auto-stall (an idea is allowed to sit), and the automatic transition is **excluded from the engagement signals** used elsewhere — the system refuses to let its own robot reset the user's activity clock. There is also an avalanche guard so that turning the feature on doesn't stall a hundred projects at once.

### 4.2 Time as a visible material

**Why it matters.** Most tools show you a list where a project touched this morning looks identical to one abandoned in March. Continuity makes neglect *visible* — a cold project looks cold — so the confrontation happens before the product has to nag.

**The detail.** Two derived values ship with every project: `days_since_touch` and a `cooling` band (warm 0–7, cooling 8–21, cold 22+). Crucially these are computed **server-side in exactly one place**, because the alternative — each client computing its own — produces the failure where the web says "11 days" and the phone says "cold" about the same project. "Blocked" is derived the same way, from whether any open task has an unresolved blocker, rather than being added as an eighth project status.

### 4.3 The Graveyard and the AI autopsy

**Why it matters.** Killing a project is reframed from failure into *learning*. Killed projects don't vanish — they go to a **Graveyard**, each carrying why it died and what was learned. Once you've killed a few, the AI looks across all of them and names **the pattern**: why *this person* keeps abandoning work. No checklist app can offer that, and it is a strong reason to stay.

**The detail.** Killing a project captures structured closure notes and triggers a one-time AI reflection. Once three or more projects are dead, a second pass computes a cross-project insight, cached as a single record and invalidated when a project is revived. Both passes are **compute-on-write and strictly best-effort**: reading the graveyard never calls the model, and any failure — no API key, an API error, a plan that doesn't include it — is swallowed so that *the kill itself always succeeds*. The product never blocks a user's decision on an AI call.

### 4.4 One assistant, three front doors — including *inside Claude*

**Why it matters.** Loop isn't only in the app. The same intelligence is on the web, in the mobile app, **and inside Claude** through an industry-standard connector — so a power user can manage their projects by talking to the assistant they already use daily. And there's a commercial edge: used through the connector, **the AI usage is billed to the user's own Claude subscription, not to Continuity**. That distribution channel costs almost nothing to run, which is exactly why even the free tier gets it.

**The detail.** The web assistant, the mobile assistant and the external connector all call the *same* 44-tool layer, so behaviour cannot drift between surfaces. The connector is an **MCP (Model Context Protocol) server** — the open standard Anthropic uses for tool integrations — fronted by a self-hosted **OAuth 2.1** authorization server with PKCE, dynamically registered clients, hashed authorization codes and refresh tokens, per-plan rate limiting, and an event log of every authorize / refresh / revoke so a connection can be audited and cut off.

The two channels are **priced by separate policies on purpose**, and the code says so in as many words: the connector spends the user's money, the assistant spends Continuity's. Re-tiering one therefore cannot silently move the other.

### 4.5 Three assistants behind one switch

**Why it matters.** "AI features" usually means one expensive thing that either works or is locked behind a paywall. Continuity ships **three genuinely different assistants** so that every tier gets an honest answer, and so the AI bill tracks revenue instead of usage.

| Tier | What the user gets | What it costs to serve |
|---|---|---|
| **Free** | A panel showing what Loop *would* do with their data, and a way to upgrade | **Zero** — no model call is possible |
| **Pro** | A catalogue of ready-made questions, answered instantly from their real data | **Zero** — answers are computed on Continuity's own servers |
| **Studio** | The real conversational assistant that can create and reorganize work | Metered AI spend |

**The detail.** The rule lives in a single function. Before it existed, the answer to "what can this plan do with Loop?" was spelled out in six places that didn't talk to each other. Now the server publishes the mode to the clients, so neither the web nor the mobile app infers capability from the plan name. The middle tier is the interesting one: it is a *deterministic* catalogue rendered server-side in the user's language, which never reaches an AI model — so it can't be rate-limited, can't hallucinate, and can't cost anything. Its labels come from the server too, which means adding a new canned question needs **no app release**.

There is also a "deep" model tier (a stronger Claude model for harder requests) with **no user-facing switch at all**, and the reasoning is stated explicitly in the code: a button that is sometimes honoured and sometimes silently ignored — which is what it became once a quota ran out — is worse than no button. The server decides, based on an admin flag and a daily cap.

### 4.6 Payments where price parity is structural

**Why it matters.** Continuity sells the same subscription on the web, the App Store and Google Play. The obvious risk in that setup is prices drifting apart, or two stores both believing they own a customer's plan. Both failures are designed out rather than watched for.

**The detail.** There is **one set of amounts** shared by all three channels, so charging differently per channel would take a deliberate edit to one file. And every channel funnels into a **single write point** for "which plan does this user have and who sold it." That layer guarantees three things: a stale event from one channel can never overwrite another channel's live entitlement; conflicts resolve deterministically (the longest-running entitlement wins, and the loser is written to the audit log so it can be refunded) rather than by arrival order; and billing exemptions are honoured in exactly one place. Store notifications are de-duplicated by the store's own event id and kept in full, so that "I paid on my iPhone and the app says Free" is answerable.

One small decision shows the level of care: each product identifier is stored as a *list*, because the payment provider's products are immutable and every price change mints a new id. With a single id, existing subscribers' renewals would arrive unrecognized and those people would silently lose their plan at renewal — *precisely the customers who had been paying longest*.

### 4.7 Privacy by design in the metrics

**Why it matters.** Continuity measures engagement to run the business, but it does so **without storing what you do**. For a product holding your most personal ambitions, "we count that you were active, we never read what you wrote" is a real trust signal — and one fewer thing to disclose in a security review.

**The detail.** Interaction metrics are daily counters per user and per channel (web / mobile / connector). No message content, query text, IP or user-agent is persisted in them, and a failure to record a metric never breaks the user's actual request. The AI usage meter works the same way: counts and token totals, not conversations.

### 4.8 A marketing site engineered to convert

**Why it matters.** First impressions convert. The public site was rebuilt to load fast on a phone on a weak connection, because a slow landing page costs sign-ups directly.

**The detail.** The public pages are pre-built and cached at the edge, while the logged-in application stays dynamic. The enabling decision is unglamorous and absolute: **the root layout must never read cookies**, because doing so turns the entire application dynamic and kills the pre-rendering. Language therefore lives in the URL (`/` for English, `/es` for Spanish) instead of a cookie, and the heavy libraries — the data client, the auth SDK, the animation library — are kept out of the public bundle entirely. The reported result was roughly **44% less first-load JavaScript** (233 kB → 130 kB) and images cut from ~3.3 MB to ~120 KB.

### 4.9 A design system with only three voices

**Why it matters.** A product about focus cannot itself be visually noisy. The current redesign reduces the entire interface to three meanings, which is what lets a stalled project *feel* different from a healthy one without a legend.

**The detail.** Colour is allowed to say exactly three things — `signal` (it hurts: overdue, blocked, error), `accent` (it wants attention today) and `closed` (done, launched). **There is no fourth colour**; everything else is said with ink weight or rule strength. A recurring time or an effort estimate is *metadata*, not a signal — "a 2h doesn't hurt." Colour values live in one generated token file, mirrored to the mobile app with an automated parity check that fails the moment a single hex diverges between platforms.

### 4.10 Fair, transparent limits

**Why it matters.** The freemium model is enforced predictably, so users always know what they get and an upgrade feels fair rather than punitive.

**The detail.** Every limit — projects, tasks, ideas, routines, notes, plus AI allowances — is defined once per plan and enforced at the service layer, which means **the limit applies identically whether the user creates something by hand or asks Loop to create it.** There is no path around it. Exact figures are in the Annex.

---

## 5. Where each capability stands today

Continuity is a real, running product, not a prototype — but like any active product some pieces are fully shipped and others are in flight. An honest snapshot.

| Capability | Web | Mobile | Notes |
|---|:--:|:--:|---|
| Projects, tasks, ideas, routines, categories | ✅ | ✅ | Full lifecycle including stalled / paused / killed / revive. |
| Today view, Today's Focus, customizable layout | ✅ | ✅ | |
| Activity log | ✅ | ✅ | |
| Quick Notes (Notion-style) | ✅ | ✅ | |
| Quick capture (⌘K) with parser | ✅ | ✅ | Parser duplicated verbatim across platforms; **tests exist only on web**. |
| Calendar (Day / Week / Month) | ✅ | ✅ | |
| Calendar `.ics` subscription feed | ✅ | ✅ | Private read-only URL; works on iOS, Google and Outlook. |
| Google Calendar push + Google Tasks import | ✅ | ✅ | One-way (Continuity → Google), re-syncs patch instead of duplicating. |
| iCloud CalDAV write | 🟡 | 🟡 | Code is written and wired, **but the `caldav` library is not in `requirements.txt`**, so it reports itself unavailable in the deployed environment. Installing it is the remaining step. |
| Analytics dashboard | ✅ | ✅ | |
| Loop assistant (3 tiers) | ✅ | ✅ | |
| Graveyard + AI autopsy | ✅ | ✅ | Best-effort by design; never blocks the kill. |
| Claude connector (MCP + OAuth 2.1) | ✅ | — | Live endpoint, consent screen and a real settings page. Connections are listed and revocable. |
| Payments — three channels | ✅ | ✅ | Web paywall and native paywall both built on RevenueCat; store product ids and keys are configuration, not code. |
| Telegram digests (weekly, daily, end-of-day) | ✅ | ✅ | Runs from an hourly cron, scheduled in the user's own timezone. |
| Mobile push notifications | — | ✅ | **Enabled** (11 Sep 2026). Kept behind an environment variable rather than a hard-coded `true`, so it can be switched off without a 20-minute rebuild. |
| Bilingual lifecycle email (Resend) | ✅ | ✅ | Ships with `dry_run` **on by default** — sends are logged for admin preview instead of delivered. |
| Beta programme + lifecycle | ✅ | — | 50 spots, enrollment open. Inactivity tracked in rolling tiers; unused spots auto-reclaimed, always after a warning. |
| Account self-deletion | ✅ | ✅ | Hard delete of data plus the auth account. Satisfies Apple's requirement. |
| Backup export / import | ✅ | ✅ | |
| Admin back-office | ✅ | — | Deliberately excluded from mobile. |
| Marketing site + blog + help centre + CMS | ✅ | — | Bilingual, statically served, edited from the admin panel. |
| Visual redesign | 🟡 | 🟡 | **Waves 0 and 1 complete, wave 2 partial.** The interface is mid-transition by design; both platforms already carry the new primitives and token system. |
| Sleeping-project alerts | 🔲 | 🔲 | Designed; the notification command does not exist yet. |
| WhatsApp notifications | 🔲 | 🔲 | Fully specified in `docs/whatsapp-integration.md`; **no code**. Telegram is the live channel. |
| Teams / B2B collaboration | 🔲 | 🔲 | Product decisions closed on paper (`docs/teams/PLAN.md`); **no model, no code**. |
| Mobile home-screen widget | 🔲 | 🔲 | Planned in `docs/plan-widget-movil.md`; **no code**. |

**Legend:** ✅ shipped · 🟡 partial or blocked on a non-engineering step · 🔲 documented but not built · — not applicable

> **A note on documentation versus reality.** Several internal design documents in this
> project describe features as "designed, not yet built" when the code is in fact **ahead**
> of them, and at least one payments document contradicts itself in its own header because
> the migration it describes has since been implemented. Where documentation and code
> disagree, this presentation follows **the code**.

---

# Technical Annex
*Clearly separated from the business sections above. Everything below is for a technically inclined reader.*

## A. Technology stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.12, **Django 5.1.4**, **Strawberry GraphQL 0.253.1**, psycopg 3, gunicorn (gthread workers, so the assistant's streaming responses flush as they arrive), WhiteNoise, django-ratelimit. Deployed on **Render**. |
| **Database** | **PostgreSQL**, hosted on **Supabase**. Row-Level Security is enabled, but the real defence is the ORM's per-user filter at the service layer. |
| **Authentication** | **Supabase Auth**. The client holds a signed token (JWT); the backend verifies it and derives the user identity server-side. Django has no `User` model of its own. |
| **Web frontend** | **Next.js 15.0.7** (App Router), **React 19**, **Apollo Client 3**, **Tailwind CSS 3.4**, **next-intl** (EN/ES), Tiptap 3 (the admin CMS editor), Recharts, dnd-kit, framer-motion, driver.js. Package manager **pnpm**. Hosted on **Vercel**. |
| **Mobile** | **Expo SDK 54 / React Native 0.81.5**, expo-router 6, **NativeWind 4.2** (Tailwind for React Native), Apollo Client 4, i18next + ICU. Package manager **npm**. Built and distributed via **EAS**; in Apple TestFlight, bundle `it.continuu.app`. |
| **AI** | **Anthropic Claude** — a fast model for normal chat, and a stronger "deep" model gated by an admin switch plus a per-plan daily cap. |
| **Payments** | **RevenueCat** across all three channels (Web Billing, App Store, Google Play). Stripe is no longer an issuer — it remains only the card processor underneath Web Billing. |
| **Transactional email** | **Resend** (bilingual welcome and lifecycle emails). |
| **Notifications** | **Telegram** (direct HTTP, no SDK) and **Expo Push**. WhatsApp is specified but not built. |

> **Definitions for non-specialists.** *GraphQL* — a query language that lets an app ask the
> server for exactly the data it needs in one request, instead of stitching together several.
> *JWT* — a signed digital token that proves who you are without re-sending your password.
> *MCP (Model Context Protocol)* — an open standard, created by Anthropic, that lets AI
> assistants safely use external tools. *OAuth 2.1* — the "Sign in with…" handshake that lets
> one app act on your behalf in another without ever seeing your password. *ISR / static
> rendering* — building pages ahead of time so a visitor gets a file instead of waiting for
> a computation. *Cron* — a scheduled job that runs on a timer.

## B. Repository layout — read this before anything else

The project is **not a monorepo**, despite what some internal documents assume. It is **three sibling folders, each with its own git repository**; the top-level folder is not version-controlled at all.

| Folder | Contents | Scale |
|---|---|---|
| `backend/` | Django + Strawberry GraphQL API | ~37,700 lines of Python (excluding migrations), 36 core migrations, **545 test functions in 50 files** |
| `frontend/` | Next.js web app, marketing site and admin panel | ~55,500 lines of TypeScript/TSX, 28 test files |
| `continuity-mobile/` | Expo / React Native app (separate public repo) | ~28,700 lines of TypeScript/TSX, **no automated tests** |

Two consequences that matter operationally:

1. **There is no shared package layer, and there cannot be one without first building monorepo infrastructure.** Cross-platform logic (the quick-capture parser, the design tokens, the bug-report topic list) is therefore **duplicated deliberately and kept in sync by convention** — with an automated parity check for the design tokens, and a documented "if you edit one, copy the other" rule for the rest.
2. **The backend deploys from a different GitHub repository** (`agtz92/continuity_backend`), not from this working folder.

## C. Architecture overview

```
                            ┌────────────────────────────────┐
     Web (Next.js/Vercel) ──┤                                │
                            │      Django + Strawberry       │
     Mobile (Expo / RN)   ──┤            on Render           ├── PostgreSQL (Supabase)
                            │                                │
     Claude ── MCP/OAuth ───┤   one shared assistant-tool    ├── Anthropic · RevenueCat
     (external AI client)   │            layer               │   Resend · Telegram · Expo
                            └────────────────────────────────┘
                                          ▲
     Marketing site (static) ──── public, unauthenticated GraphQL ─┘
```

**Public surface of the backend:**

| Endpoint | Purpose |
|---|---|
| `/graphql/` | The single authenticated API for both apps. |
| `/public-graphql/` | Published marketing and help content only. **No authentication**, deliberately separate from the app API, so the static site can be built without credentials. |
| `/mcp/` | The Claude connector (JSON-RPC), accepted with and without a trailing slash because MCP clients don't follow redirects on POST. |
| `/.well-known/oauth-*`, `/oauth/{register,authorize,token}` | The self-hosted OAuth 2.1 authorization server for the connector. |
| `/api/assistant/{chat,actions,usage,parse-capture,conversations,cancel}/` | The assistant surface. `chat` streams; `actions` is the deterministic catalogue. |
| `/api/billing/{store-webhook,revenuecat}/` | Payment notifications from all three channels. |
| `/api/telegram/webhook/<secret>/` | Inbound Telegram binding. |
| `/api/calendar/feed/<token>.ics` | The private calendar subscription feed. |
| `/api/google/oauth/callback` | Shared callback for Google Tasks and Google Calendar. |

**Scheduled work** runs as a single hourly Render cron chaining: lifecycle welcome emails → weekly digest → daily digest → due reminders → announcement push → OAuth token cleanup → stalled-project sweep → beta lifecycle. Each command gates itself on the user's local hour, so one hourly job covers every timezone. The beta lifecycle runs inside this chain — hour-gated to 15:00 UTC — explicitly to avoid paying for a second cron service.

## D. Core data model

Confirmed in `backend/core/models.py` and the app-level model files:

| Entity | Purpose |
|---|---|
| **Project** | The central object. Seven-state lifecycle, priority, optional category and due date, manual ordering, plus structured closure notes for both pause and kill, and a one-time AI reflection on death. |
| **Task** | Optional project link, due date/time, estimated hours, done flag, a "parked" due date for deferrals, and a client token so a retried write never creates a duplicate. |
| **TaskBlocker** | What a task is waiting on. Rolls up to derive a project's "blocked" state. |
| **Idea** | Lightweight capture; promotable to a Project (the promotion timestamp is kept for the funnel analytics). |
| **Routine** / **RoutineOccurrence** | A recurring commitment and its individual instances. |
| **ProjectNote** | An update attached to one project. |
| **QuickNote** / **NoteSection** | Notebook note with ordered, collapsible sections. Deleting a category or project **does not** delete the note. |
| **Category** | User-defined label, unique per user, shared across projects and notes. |
| **Activity** | Append-only log of meaningful events — the basis of the diary, the analytics, and the engagement signals. |
| **GraveyardInsight** | Cached cross-project AI reflection on killed projects. |
| **StalledSweepState** | Bookkeeping so the stall sweep can't avalanche. |
| **AccountProfile** | Per-user plan, billing channel and subscription ids, admin flag, billing exemption, beta cohort state, and a cache version counter. *(Despite the name, not an auth user — Supabase owns those.)* |
| **AppConfig** | Global typed key/value runtime configuration — the beta knobs, the deep-model switch, the email `dry_run` master switch. Changing behaviour does not require a redeploy. |
| **UserPreferences** | Today-view layout, stored as JSON so new sections need no migration. |
| **OnboardingProgress** | Five-step onboarding plus tour state. |
| **InteractionDay** / **UsageDay** | Privacy-preserving daily counters (engagement and AI usage). |
| **GoogleOAuthCredential** / **ICloudCalendarCredential** | Integration credentials, encrypted at rest (Fernet). |
| **OAuthClient / AuthorizationCode / RefreshToken / ConnectionEvent** | The connector's OAuth tables. Codes and refresh tokens are stored **hashed**; access tokens are stateless and short-lived. |
| **NotificationSettings / NotificationLink / Notification / ExpoPushToken / EmailSend** | Channel preferences, linked channels, the send outbox, device tokens, and email idempotency. |
| **StoreWebhookEvent** | Every payment notification, keyed by the store's own event id — de-duplication and reconciliation in one table. |
| **BlogPost / Page / HelpCategory / HelpResource / MediaAsset** | The CMS behind the public site. |
| **Announcement**, **BugReport**, **AdminAuditLog** | In-app announcements, the one-way support inbox, and a record of every admin action. |

## E. Plans and limits (exact figures from the code)

**Entity limits** (`core/quotas.py`) — `∞` means unlimited. `admin` matches `studio`.

| Limit | Free | Pro | Studio |
|---|--:|--:|--:|
| Projects (excluding killed/archived) | 3 | 25 | ∞ |
| Tasks per project | 20 | 200 | ∞ |
| Open tasks (total) | 50 | ∞ | ∞ |
| Routines | 2 | 20 | ∞ |
| Ideas | 30 | 500 | ∞ |
| Categories | 3 | 15 | ∞ |
| Quick Notes | 50 | 1,000 | ∞ |
| Notes per project | 3 | ∞ | ∞ |
| Sections per note | 20 | ∞ | ∞ |

**Assistant limits** (`core/assistant/{tiers,quotas}.py`):

| | Free | Pro | Studio | Admin |
|---|:--:|:--:|:--:|:--:|
| Assistant mode | `none` | `canned` | `llm` | `llm` |
| Reaches the AI model? | No | **No** | Yes | Yes |
| Messages per day | — | — | 600 | ∞ |
| Monthly token ceiling | — | — | **None, deliberately** | — |
| "Deep" model messages/day | 0 | 0 | 25 | 100 |
| Connector (MCP) rate limit | 30/min | 120/min | 300/min | 600/min |
| Connector capability | Read + set priority | Read + set priority | Full read/write | Full read/write |

Two design nuances worth reading twice:

- **Studio has no monthly token ceiling on purpose.** The code states why: the old one cut people off mid-month with no warning and no way to see it coming. The daily message count is the honest, legible limit, and the deep-model cap bounds the expensive half.
- **A paid plan must never be able to do less than a cheaper one.** That is why Pro keeps `set_project_priority` on the connector even though it is a mutating tool — the free tier already had it.
- **Billing exemption is decoupled from the plan.** A beta member, friend, investor or partner can be exempt from charges while sitting on any feature tier, with an optional expiry.

**Other limits:** GraphQL is rate-limited at 120 requests/min per user and 300/min per IP. The bug-report channel allows 10 submissions per user per hour.

## F. Security and privacy posture

- **Authentication** on every authenticated request via the Supabase token; the identity is derived server-side and never trusted from the client. Every service-layer query filters by that user id.
- **Row-Level Security is enabled** on the database, but the documentation is candid that the ORM filter is the real defence — RLS is depth, not the primary control.
- **The admin surface** is gated behind an explicit `is_admin` flag, and **every admin action is written to an audit log** with actor, action, target and payload.
- **The connector** uses a full OAuth 2.1 flow with PKCE and public clients only (no shared secret to leak). Authorization codes and refresh tokens are **stored hashed**, so a database leak cannot replay them; access tokens are stateless and short-lived, and revocation works through the refresh token. Every authorize / refresh / revoke is recorded as an event the user or an admin can see and act on.
- **The connector's permission policy is enforced twice** — once when advertising which tools exist, and again before executing one. The second check is the real guarantee: a tool the model was never shown is still rejected. The plan and the user id always come from the server, never from the model's arguments.
- **Integration credentials are encrypted at rest** (Fernet) — Google refresh tokens and the iCloud app-specific password alike.
- **Metrics store counts, not content.** No message bodies, query text, IPs or user agents in the interaction metrics; a metric failure never breaks the request it was measuring.
- **The bug-report channel is intentionally one-way** (user → admin inbox) with no reply path — stated in the code as a design invariant, not an unfinished feature.
- **Outbound email defaults to `dry_run`**, so a misconfigured lifecycle job logs instead of mailing real users.
- **Account deletion is a hard delete** of application data in a single transaction, followed by deletion of the auth account.

## G. Notable engineering decisions

Beyond the product-level items in §4, these decisions are visible in the code and worth knowing:

- **Streaming writes are persisted as they happen, not at the end of the turn.** The reasoning is recorded in the codebase: the assistant's tools have already written to the database by the time a stream is cut, so persisting the conversation at the end left users with a real project and eight real tasks and a chat that never mentioned creating them. A cut stream now loses at most the tail.
- **Running out of tool budget is not an error.** The assistant spends one more call *without tools* so the model can close the turn by saying what it managed to do. A user is never left with half-finished writes and no explanation.
- **Config-driven, idempotent background jobs.** Welcome emails, inactivity reclaim and stall sweeps are all idempotent and tunable through a runtime configuration table without a redeploy.
- **A deliberate rejection of two-way calendar sync.** The read-only `.ics` feed is one implementation that covers iOS, Google and Outlook without storing anyone's credentials. The heavier credential-storing paths exist for users who want native writes, and the code says plainly that most users are better served by the feed.
- **List queries defer large content columns.** The public content API explicitly avoids loading article bodies in list views, and counts published items with a single aggregate query rather than one per category — both guarded with comments explaining the N+1 they prevent.
- **An active, measured modularization effort.** Oversized files are tracked in `AUDITORIA_CODIGO.md` across three audit passes, with before/after line counts. Every file originally marked urgent has been resolved; the report is candid about two regressions the refactor itself introduced.

## H. Internationalization

Full **English / Spanish** support across web, mobile, notifications and lifecycle email. On the web, the marketing locale is encoded in the **URL** (`/` English, `/es` Spanish, with `/resources` ↔ `/recursos`) specifically so those pages can stay statically cacheable; the logged-in app resolves locale from a cookie. Canonical and `hreflang` metadata is declared per language pair. The help centre exists in both languages. The admin panel is intentionally Spanish-only and not internationalized.

## I. Testing and deployment

- **Backend:** pytest + pytest-django — **545 test functions across 50 files**. The suite is fully isolated from the developer's environment: an in-memory SQLite database, a stubbed auth secret, and no outbound HTTP. Deployed on Render via `render.yaml` / `build.sh` / `Procfile`, with the scheduled cron described in §C.
- **Web:** Vitest + Testing Library, 28 test files, with a mocked GraphQL client. Deployed on Vercel; the marketing/app static-vs-dynamic split is verifiable from the build output.
- **Mobile:** verified by `expo export` followed by `tsc --noEmit`, in that order — because the export step is what regenerates the typed routes. Distributed via EAS to TestFlight. **There is no automated test suite.**

## J. Open items and things to confirm

1. **A contradiction in the beta offer.** The landing page promises *"Lifetime free access to Pro tier"*, but the backend enrolls beta members in **Studio** (deliberately — the conversational assistant lives there). The product is more generous than the copy. **To confirm:** which is intended, and update the other.
2. **iCloud CalDAV is code-complete but not deployable as configured** — the `caldav` library is absent from `requirements.txt`, so the feature reports itself unavailable. This is a one-line fix plus a verification pass, not outstanding engineering.
3. **A `basic` plan appears in the connector's permission policy but does not exist** in the plan enum. Harmless today (it is a read-only entry), but it is either dead code or an unshipped tier.
4. **The payments documentation contradicts itself in its own header.** The migration it describes as pending has been implemented on all three channels; closing phase D means rewriting sections 2–9 of that document. Until then, the code is the only reliable source.
5. **The visual redesign is mid-flight** (waves 0–1 done, wave 2 partial). Screens will not all look alike until it lands.
6. **Cross-platform duplicated logic is a standing risk.** The quick-capture parser is a verbatim copy between web and mobile, and **its tests exist only on the web side**. A divergence would make the same typed sentence create different things on the two platforms.
7. **The mobile app has no automated tests** — the largest coverage gap in the project.
8. **Local prices outside USD are not equalized.** Parity is guaranteed in dollars; Apple and Google apply their own conversion matrices, so a euro or peso price will differ between channels unless set by hand on both sides. Documented as a known, accepted limitation.
9. **Not decided, per the payments plan:** whether the mobile paywall should sell to someone who already has a web entitlement, and whether assisted migration between channels is ever built.
10. **The working directory is not a git repository** and the three sub-projects version independently, so this presentation reflects the state of the files on disk rather than release history.

---

*Prepared from a direct review of the Continuity codebase — backend, web frontend, mobile
app, and project documentation — on 14 September 2026. Figures and capabilities are taken
from the source; anything not verifiable in the code is flagged above as "to confirm"
rather than asserted.*
