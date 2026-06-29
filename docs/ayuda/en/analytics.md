# Analytics

The **Analytics** tab is your control panel: it turns your activity —updates, completed tasks, logged hours, ideas— into charts and panels that tell you *how* you're doing, not just what's left. It's a **read-only** view: you don't edit anything here, but you do pick the **date range** that feeds every panel.

---

## 1. General anatomy

[image: analytics-01-overview.png]

Top to bottom, Analytics is built like this:

1. **Title + range selector** — at the top. The range (7d/30d/90d/1y/All) feeds **every** panel at once.
2. **Cadence & activity** — your recent pulse: how many days you were active and the daily curve.
3. **Project panels** — most active, backlog, status/category, effort, sleeping.
4. **Idea panels** — the idea funnel and stale ideas.

> **Note:** on **mobile** you'll see a strip of **chips** (Activity · Cadence · Status · …) and **one panel** at a time: tap a chip to switch panel. On **desktop** they're all stacked. While it recomputes after you change the range, **“refreshing…”** appears next to the title.

---

## 2. Date range & Cadence

[image: analytics-02-range.png]

The range selector is the only thing you "edit" here. Below it, **Cadence** gives you your pulse: **Active days** (how many days in the range had at least one update or completed task) and **Events** (the total of those interactions).

**How to use it**
- Together they're your "pulse": many events but few active days = you work in bursts.
- The values recompute based on the chosen range.

**How to edit it**
- Tap **7d / 30d / 90d / 1y / All** to change the range.
- It's the **only** editable thing in the view; it **recomputes every panel** at once.
- The default on entry is **30 days**.

---

## 3. Daily activity

[image: analytics-03-activity.png]

Two lines, day by day: the **green** one is updates (log entries) and the **blue** one is completed tasks. The X axis is labelled every few days.

**How to use it**
- Look for the **trend**, not single days: are you climbing, dropping, or holding pace?
- Hover a point to see that day's detail in a tooltip.
- Blue spikes without green = you closed tasks but didn't log progress (or vice versa).

**How to edit it**
- Read-only. Change what you see by adjusting the **date range** (section 2).
- With long ranges (1y / All) the curve smooths out and labels space apart.

---

## 4. Most active

[image: analytics-04-topprojects.png]

Top 5 projects by interactions (updates + completed tasks) in the range. The big number is interactions; the arrow is the change vs the previous period (**▲ up**, **▼ down**, – flat).

**How to use it**
- Confirms **where your energy actually went** in the range.
- The arrow compares against the previous period of the same length: spot projects cooling off (▼).
- Under each name you see the project's status (active, stalled, launched…).

**How to edit it**
- Read-only. If there was no activity in the range, you'll see **“No activity in this range.”**

---

## 5. By weekday

[image: analytics-05-heatmap.png]

A heatmap from Monday to Sunday. More **intense** = more interactions that day; the number inside each cell is the count.

**How to use it**
- Reveals your **weekly pattern**: which days you perform best and when you dip.
- Handy for planning: schedule hard work on your strong days.

**How to edit it**
- Read-only. It accumulates across the whole chosen range.

---

## 6. Backlog

[image: analytics-06-backlog.png]

Health of your open work. The subtitle is your total open tasks; each tile highlights an actionable group.

**How to use it**
- **Overdue** and **Due soon (7d)** = what to handle now so it doesn't pile up.
- **Quick wins** = projects with ≤2 open tasks (close them fast).
- **Almost there** = projects ≥80% complete, one push from done.

**How to edit it**
- Read-only; to move the numbers, go to **Tasks** or **Projects** and advance open work.

---

## 7. By status and category

[image: analytics-07-breakdown.png]

How your projects split. On the left, bars by **status** (each color = a lifecycle stage); on the right, your **categories** with project count and interactions. The subtitle counts the total projects.

**How to use it**
- Check the **balance**: too many "Stalled" or "Idea" versus "Active" is a signal.
- The category side shows where your projects and activity concentrate.

**How to edit it**
- Read-only. Category colors are the ones you set when creating them.
- With no categories you'll see **“No categories.”**; with no projects, **“No data.”**

---

## 8. Effort & Idea funnel

[image: analytics-08-effort.png]

**Effort** splits your logged hours per project. The big number is total hours; **Coverage** warns how many tasks carry hours (otherwise the total underestimates).

[image: analytics-09-effort.png]

**Idea funnel** shows **Created** → **Promoted** → conversion **Rate** to project.

**How to use it**
- Effort: discover what you actually spend time on.
- Low coverage = log hours on more tasks so the total is reliable.
- Funnel: a very low rate suggests you hoard ideas without deciding.

**How to edit it**
- Read-only. Hours come from the **hours logged on your tasks**.
- No hours in range: **“No tasks with logged hours in this range.”**

---

## 9. Sleeping · Stale ideas

[image: analytics-10-sleeping.png]

**Sleeping** lists projects with no recent activity (≥7 days). The badge groups severity (**7-14d** → **15-30d** → **30+d**) and on the right are the exact days idle.

[image: analytics-11-sleeping.png]

**Stale ideas** are ideas sitting 30+ days without being promoted to a project; on the right, their age.

**How to use it**
- It's your **rescue** list: reactivate a project or drop an idea to free up space.
- "Sleeping" complements the **Today** alert, but here you see the full list.
- To act, open the project or idea from their respective tabs.

**How to edit it**
- Read-only. If all is on track: **“Nothing sleeping. Good pace.”** and **“No stale ideas.”**

> **Note:** every panel is **read-only**: Analytics doesn't change your data, it *reflects* it. The only lever is the **date range** up top. If a panel comes up empty, it's almost always a lack of data in that range — widen it or log more activity.
