"""Admin GraphQL — área de billing: MRR/ARR/churn y lista de suscriptores.

Extraído de schema.py (split de AdminQuery por área, ver AUDITORIA_CODIGO.md).
Se re-fusiona en `AdminQuery` vía merge_types en schema.py.
"""

from __future__ import annotations

import logging
from typing import Optional

import strawberry
from strawberry.types import Info

from core.assistant.models import AccountProfile, Plan

from .permissions import _admin_user_id
from .supabase_admin import SupabaseAdminError, get_users_map
from .types import *  # noqa: F401,F403

logger = logging.getLogger(__name__)


@strawberry.type
class AdminBillingQuery:
    @strawberry.field(name="adminBillingOverview")
    def admin_billing_overview(self, info: Info) -> AdminBillingOverview:
        """Resumen de ingresos recurrentes y churn próxima.

        Calcula MRR/ARR y el desglose por (plan, periodo) sumando el equivalente
        mensual de cada suscripción de pago activa (excluye exentos y sin
        ``stripe_subscription_id``). El ``price_id`` se colapsa en periodo vía
        ``period_for_price`` para que la UI vea una matriz limpia de 4 filas. Los
        emails de la churn próxima se traen en bloque (best-effort) y quedan ""
        si Supabase falla, para no tumbar el panel.

        Args:
            info: Contexto GraphQL; debe ser admin.

        Returns:
            ``AdminBillingOverview`` con MRR/ARR, conteos y churn próxima.

        Raises:
            GraphQLError: si el solicitante no es admin (vía ``_admin_user_id``).
        """
        _admin_user_id(info)

        from django.conf import settings as dj_settings

        from core.billing.plans import (
            amount_cents_for_price,
            is_stripe_test_mode,
            monthly_cents_for_price,
            period_for_price,
        )

        paid_plans = [Plan.PRO.value, Plan.STUDIO.value]
        paying_qs = AccountProfile.objects.filter(
            plan__in=paid_plans,
            is_billing_exempt=False,
        ).exclude(stripe_subscription_id="")

        # Aggregate breakdown by (plan, price_id) — we collapse price_id into
        # period via period_for_price() so the UI sees a clean 4-row matrix.
        bucket: dict[tuple[str, str], dict] = {}
        mrr_cents = 0
        paying_count = 0
        for plan, price_id in paying_qs.values_list("plan", "stripe_price_id"):
            period = period_for_price(price_id) or "unknown"
            monthly = monthly_cents_for_price(price_id)
            key = (plan, period)
            slot = bucket.setdefault(
                key,
                {"count": 0, "monthly_each": monthly, "total": 0},
            )
            slot["count"] += 1
            slot["total"] += monthly
            # Keep the "each" value stable even if some rows have monthly=0
            # (unconfigured amount) — prefer the first non-zero we see.
            if slot["monthly_each"] == 0 and monthly > 0:
                slot["monthly_each"] = monthly
            mrr_cents += monthly
            paying_count += 1

        breakdown = [
            PlanPeriodBreakdown(
                plan=plan,
                period=period,
                count=slot["count"],
                monthly_cents_each=slot["monthly_each"],
                total_monthly_cents=slot["total"],
            )
            for (plan, period), slot in sorted(bucket.items())
        ]

        billing_exempt_count = AccountProfile.objects.filter(
            is_billing_exempt=True,
        ).exclude(plan=Plan.FREE.value).count()

        pending_cancel_qs = paying_qs.filter(cancel_at_period_end=True).order_by(
            "plan_renews_at"
        )
        pending_cancellations = pending_cancel_qs.count()

        # Upcoming churn — top 20 by soonest renewal, fetch emails in one go.
        churn_rows = list(pending_cancel_qs[:20])
        churn_uids = [r.user_id for r in churn_rows]
        users_map = {}
        if churn_uids:
            try:
                users_map = get_users_map(churn_uids)
            except SupabaseAdminError as e:
                logger.warning("adminBillingOverview: supabase fetch failed: %s", e)

        upcoming_churn = [
            UpcomingChurnRow(
                user_id=strawberry.ID(str(r.user_id)),
                email=(users_map.get(r.user_id).email if users_map.get(r.user_id) else ""),
                plan=r.plan,
                period=period_for_price(r.stripe_price_id) or "unknown",
                plan_renews_at=r.plan_renews_at,
                monthly_cents=monthly_cents_for_price(r.stripe_price_id),
            )
            for r in churn_rows
        ]

        return AdminBillingOverview(
            currency=(getattr(dj_settings, "STRIPE_CURRENCY", "usd") or "usd").lower(),
            is_test_mode=is_stripe_test_mode(),
            paying_subscribers=paying_count,
            mrr_cents=mrr_cents,
            arr_cents=mrr_cents * 12,
            billing_exempt_count=billing_exempt_count,
            pending_cancellations=pending_cancellations,
            breakdown=breakdown,
            upcoming_churn=upcoming_churn,
        )

    @strawberry.field(name="adminSubscribers")
    def admin_subscribers(
        self,
        info: Info,
        page: int = 1,
        per_page: int = 50,
        plan: Optional[str] = None,
        period: Optional[str] = None,
        email_contains: Optional[str] = None,
        include_exempt: bool = False,
    ) -> AdminSubscriberPage:
        """Lista paginada de suscriptores de pago con filtros.

        Pagina sobre ``AccountProfile`` (donde vive el estado de billing) y trae
        los emails de la página en bloque desde Supabase. Filtros por plan y
        periodo se hacen en SQL; el de email se aplica EN MEMORIA post-fetch
        porque Supabase no expone búsqueda bulk por email (mismo tradeoff que
        ``adminUsers``).

        Args:
            info: Contexto GraphQL; debe ser admin.
            page: Página 1-based.
            per_page: Tamaño de página (acotado a 1..200).
            plan: Filtra por plan válido (se ignora si no es un Plan conocido).
            period: ``"monthly"``/``"annual"``, mapeado a price_ids de settings.
            email_contains: Subcadena case-insensitive (filtrado local).
            include_exempt: Si ``True``, incluye exentos y sin suscripción.

        Returns:
            ``AdminSubscriberPage`` con las filas, paginación y total.

        Raises:
            GraphQLError: si el solicitante no es admin (vía ``_admin_user_id``).
        """
        _admin_user_id(info)

        from core.billing.plans import (
            monthly_cents_for_price,
            period_for_price,
        )

        # NOTE: paginación duplicada — extraer paginate() + constantes
        per_page = max(1, min(per_page, 200))
        page = max(1, page)

        paid_plans = [Plan.PRO.value, Plan.STUDIO.value]
        qs = AccountProfile.objects.filter(plan__in=paid_plans)
        if not include_exempt:
            qs = qs.filter(is_billing_exempt=False).exclude(stripe_subscription_id="")
        if plan:
            normalized_plan = plan.lower()
            if normalized_plan in {p.value for p in Plan}:
                qs = qs.filter(plan=normalized_plan)
        if period:
            # Filter by period via the underlying price_id columns.
            normalized_period = period.lower()
            from django.conf import settings as dj_settings

            ids: list[str] = []
            if normalized_period == "monthly":
                ids = [
                    getattr(dj_settings, "STRIPE_PRICE_PRO_MONTHLY", ""),
                    getattr(dj_settings, "STRIPE_PRICE_STUDIO_MONTHLY", ""),
                ]
            elif normalized_period == "annual":
                ids = [
                    getattr(dj_settings, "STRIPE_PRICE_PRO_ANNUAL", ""),
                    getattr(dj_settings, "STRIPE_PRICE_STUDIO_ANNUAL", ""),
                ]
            ids = [i for i in ids if i]
            if ids:
                qs = qs.filter(stripe_price_id__in=ids)

        qs = qs.order_by("-plan_renews_at", "user_id")

        total = qs.count()
        offset = (page - 1) * per_page
        rows = list(qs[offset : offset + per_page])

        # Bulk-fetch emails for just this page.
        uids = [r.user_id for r in rows]
        users_map = {}
        if uids:
            try:
                users_map = get_users_map(uids)
            except SupabaseAdminError as e:
                logger.warning("adminSubscribers: supabase fetch failed: %s", e)

        # Apply email filter post-fetch (Supabase doesn't expose query-by-email
        # bulk lookup; we filter the page locally — known tradeoff, same pattern
        # as adminUsers).
        if email_contains:
            needle = email_contains.strip().lower()
            rows = [
                r
                for r in rows
                if users_map.get(r.user_id)
                and needle in users_map[r.user_id].email.lower()
            ]

        result_rows = [
            AdminSubscriberRow(
                user_id=strawberry.ID(str(r.user_id)),
                email=(users_map.get(r.user_id).email if users_map.get(r.user_id) else ""),
                plan=r.plan,
                period=period_for_price(r.stripe_price_id) or "",
                monthly_cents=monthly_cents_for_price(r.stripe_price_id),
                plan_renews_at=r.plan_renews_at,
                cancel_at_period_end=r.cancel_at_period_end,
                is_billing_exempt=r.is_billing_exempt,
                stripe_customer_id=r.stripe_customer_id,
                stripe_subscription_id=r.stripe_subscription_id,
            )
            for r in rows
        ]

        return AdminSubscriberPage(
            rows=result_rows,
            page=page,
            per_page=per_page,
            has_next=(offset + per_page) < total,
            total=total,
        )
