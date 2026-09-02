"""Read-only PREVIEW of the inactivity follow-up audience — sends NOTHING.

Lists every user (beta AND non-beta) with no significant interaction in the
last N days (default 15), so we can see exactly who a "14-day inactive" email
would reach before committing to a real send. It measures inactivity with the
SAME `significant_events_q()` the cron uses, so this preview and the live
lifecycle agree on "days inactive".

Important context this surfaces:
- The real inactivity sequence (`run_beta_lifecycle`) only touches the beta
  cohort and is tiered; for a beta user this prints the exact email the cron
  WOULD send (the furthest-due step). day-14 lands on `inactivity_3` (ghost,
  a warn) or `reengage_2` (brief/established, a nudge).
- Non-beta users have NO inactivity email template/flow today, so they show as
  "(sin plantilla)". Emailing them needs a new template + flow first.

This command writes no rows and sends no email. Run it on Render (where the
Supabase service-role key resolves addresses):

    python manage.py preview_inactive_followup            # 15 days
    python manage.py preview_inactive_followup --days 14 --limit 50
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Optional

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.services import beta_lifecycle


def _parse_ts(val) -> Optional[dt.datetime]:
    if not val:
        return None
    parsed = parse_datetime(str(val))
    if parsed is not None and timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, dt.timezone.utc)
    return parsed


class Command(BaseCommand):
    help = "Preview (no sends) the users inactive >= N days for an inactivity follow-up."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=15, help="Inactivity threshold (default 15).")
        parser.add_argument("--limit", type=int, default=0, help="Cap printed rows (0 = all).")

    def handle(self, *args, **options):
        from core.admin_api.supabase_admin import SupabaseAdminError, fetch_all_users
        from core.assistant.models import AccountProfile
        from core.models import Activity
        from core.notifications.models import NotificationSettings

        threshold = options["days"]
        limit = options["limit"]
        now = timezone.now()
        cfg = beta_lifecycle._load_config()
        floor = cfg.get("lifecycle_start_at")

        # Universe of users. Supabase auth is the source of truth for "all
        # users"; fall back to profiles + activity if the admin key is absent
        # (e.g. local dev), so the command still runs and reports what it can.
        supa: dict[uuid.UUID, object] = {}
        try:
            supa = {u.id: u for u in fetch_all_users()}
        except SupabaseAdminError:
            self.stdout.write("(Supabase unavailable — emails will be blank; using profiles+activity.)")

        profiles = {p.user_id: p for p in AccountProfile.objects.all()}
        if supa:
            user_ids = set(supa) | set(profiles)
        else:
            act_ids = set(Activity.objects.values_list("user_id", flat=True).distinct())
            user_ids = set(profiles) | act_ids

        last_sig = beta_lifecycle_last_sig(list(user_ids))
        locales = dict(
            NotificationSettings.objects.filter(user_id__in=user_ids).values_list("user_id", "locale")
        )

        rows = []
        for uid in user_ids:
            profile = profiles.get(uid)
            s_user = supa.get(uid)
            is_beta = bool(profile and profile.beta_cohort)

            if is_beta:
                # Authoritative: exactly what the cron measures/would send.
                tier, anchor, days_inactive, _ = beta_lifecycle.classify(
                    uid, profile.beta_enrolled_at, now, cfg
                )
                would = _due_email(tier, days_inactive, cfg)
            else:
                anchor = last_sig.get(uid)
                if anchor is None and s_user is not None:
                    anchor = _parse_ts(getattr(s_user, "created_at", None))
                if anchor is None and profile is not None:
                    anchor = profile.created
                if floor is not None and (anchor is None or anchor < floor):
                    anchor = floor
                days_inactive = (now - anchor).days if anchor else None
                tier = "non-beta"
                would = "(sin plantilla)"

            if days_inactive is None or days_inactive < threshold:
                continue

            rows.append(
                {
                    "email": getattr(s_user, "email", "") or "",
                    "user_id": str(uid),
                    "days": days_inactive,
                    "cohort": "beta" if is_beta else "no-beta",
                    "tier": tier,
                    "would_send": would,
                    "locale": locales.get(uid, "en"),
                }
            )

        rows.sort(key=lambda r: r["days"], reverse=True)

        total = len(rows)
        n_beta = sum(1 for r in rows if r["cohort"] == "beta")
        self.stdout.write("")
        self.stdout.write("=== PREVIEW (dry-run, NO emails sent) ===")
        self.stdout.write(
            f"Inactive >= {threshold} days: {total} users "
            f"({n_beta} beta, {total - n_beta} no-beta). Now={now.isoformat()}"
        )
        shown = rows[:limit] if limit else rows
        self.stdout.write("")
        self.stdout.write(f"{'days':>4}  {'cohort':<7} {'tier':<12} {'would_send':<16} {'loc':<3} email")
        for r in shown:
            self.stdout.write(
                f"{r['days']:>4}  {r['cohort']:<7} {r['tier']:<12} "
                f"{r['would_send']:<16} {r['locale']:<3} {r['email'] or r['user_id']}"
            )
        if limit and total > limit:
            self.stdout.write(f"... {total - limit} more (raise --limit to see all).")
        self.stdout.write("")
        self.stdout.write("Nothing was sent. To actually email the beta cohort, use run_beta_lifecycle.")


def beta_lifecycle_last_sig(user_ids: list[uuid.UUID]) -> dict[uuid.UUID, dt.datetime]:
    """Last significant Activity per user (same filter the cron uses)."""
    from django.db.models import Max

    from core.models import Activity

    rows = (
        Activity.objects.filter(user_id__in=user_ids)
        .filter(beta_lifecycle.significant_events_q())
        .values("user_id")
        .annotate(last=Max("created"))
    )
    return {r["user_id"]: r["last"] for r in rows}


def _due_email(tier: str, days_inactive: Optional[int], cfg: dict) -> str:
    """The email id the cron would send now for a beta user — the furthest-due
    step at/below days_inactive (idempotent behaviour of process_profile)."""
    if days_inactive is None:
        return "—"
    steps = beta_lifecycle.steps_for(tier, cfg)
    due = [s for s in steps if days_inactive >= s.day]
    return due[-1].email_id if due else "(not due yet)"
