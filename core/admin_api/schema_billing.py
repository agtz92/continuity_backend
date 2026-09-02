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

        Calcula MRR/ARR (bruto y **neto** de comisiones) y el desglose por
        (plan, periodo) y por **fuente de cobro**, sumando el equivalente
        mensual de cada suscripción de pago activa. Excluye exentos.

        Cuenta suscripciones de **todas las fuentes** (web, App Store, Google
        Play) filtrando por ``billing_transaction_id``, una sola columna que
        vale para las tres. Antes filtraba por el id de suscripción de Stripe,
        lo que dejaba fuera todo lo vendido en las tiendas y habría hecho caer
        el MRR justo cuando el canal móvil empieza a crecer.
        Ver ``docs/integracion-pagos-web-y-movil.md``.

        Los importes salen de ``monthly_cents_for_profile`` /
        ``net_monthly_cents_for_profile``, que despachan por fuente. Los emails
        de la churn próxima se traen en bloque (best-effort) y quedan "" si
        Supabase falla, para no tumbar el panel.

        Args:
            info: Contexto GraphQL; debe ser admin.

        Returns:
            ``AdminBillingOverview`` con MRR/ARR bruto y neto, desglose por
            plan/periodo y por fuente, conteos y churn próxima.

        Raises:
            GraphQLError: si el solicitante no es admin (vía ``_admin_user_id``).
        """
        _admin_user_id(info)

        from django.db.models import Q
        from django.conf import settings as dj_settings

        from core.billing.catalog import (
            monthly_cents_for_profile,
            net_monthly_cents_for_profile,
            period_for_profile,
        )

        paid_plans = [Plan.PRO.value, Plan.STUDIO.value]
        # "Has a paid entitlement from someone" — one column now covers every
        # channel, so this no longer has to enumerate them.
        paying_qs = AccountProfile.objects.filter(
            Q(plan__in=paid_plans)
            & Q(is_billing_exempt=False)
            & ~Q(billing_transaction_id="")
        )

        # Aggregate breakdown by (plan, period) and by billing source. We work
        # on model instances rather than values_list because the amount
        # helpers dispatch on several columns at once.
        bucket: dict[tuple[str, str], dict] = {}
        source_bucket: dict[str, dict] = {}
        mrr_cents = 0
        net_mrr_cents = 0
        paying_count = 0
        for profile in paying_qs.iterator():
            period = period_for_profile(profile) or "unknown"
            monthly = monthly_cents_for_profile(profile)
            net_monthly = net_monthly_cents_for_profile(profile)
            key = (profile.plan, period)
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

            # Una fila con suscripción pero sin fuente es un dato a medias:
            # se agrupa aparte en vez de atribuirla a un canal por defecto.
            source = profile.billing_source or "unknown"
            s_slot = source_bucket.setdefault(
                source, {"count": 0, "gross": 0, "net": 0}
            )
            s_slot["count"] += 1
            s_slot["gross"] += monthly
            s_slot["net"] += net_monthly

            mrr_cents += monthly
            net_mrr_cents += net_monthly
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

        by_source = [
            SourceBreakdown(
                source=source,
                count=slot["count"],
                gross_monthly_cents=slot["gross"],
                net_monthly_cents=slot["net"],
            )
            for source, slot in sorted(source_bucket.items())
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
                period=period_for_profile(r) or "unknown",
                plan_renews_at=r.plan_renews_at,
                monthly_cents=monthly_cents_for_profile(r),
            )
            for r in churn_rows
        ]

        return AdminBillingOverview(
            currency=(getattr(dj_settings, "BILLING_CURRENCY", "usd") or "usd").lower(),
            is_test_mode=bool(getattr(dj_settings, "BILLING_TEST_MODE", False)),
            paying_subscribers=paying_count,
            mrr_cents=mrr_cents,
            net_mrr_cents=net_mrr_cents,
            arr_cents=mrr_cents * 12,
            net_arr_cents=net_mrr_cents * 12,
            billing_exempt_count=billing_exempt_count,
            pending_cancellations=pending_cancellations,
            breakdown=breakdown,
            by_source=by_source,
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

        from django.db.models import Q

        from core.assistant.models import BillingSource
        from core.billing.catalog import (
            monthly_cents_for_profile,
            net_monthly_cents_for_profile,
            period_for_profile,
        )
        from core.billing.catalog import product_id_for

        # NOTE: paginación duplicada — extraer paginate() + constantes
        per_page = max(1, min(per_page, 200))
        page = max(1, page)

        paid_plans = [Plan.PRO.value, Plan.STUDIO.value]
        qs = AccountProfile.objects.filter(plan__in=paid_plans)
        if not include_exempt:
            # Paga por cualquiera de los tres canales, no sólo por Stripe.
            qs = qs.filter(is_billing_exempt=False).exclude(billing_transaction_id="")
        if plan:
            normalized_plan = plan.lower()
            if normalized_plan in {p.value for p in Plan}:
                qs = qs.filter(plan=normalized_plan)
        if period:
            # El periodo no es una columna: vive codificado en el identificador
            # de producto. Con un solo catálogo compartido por los tres canales,
            # dos ids bastan para cubrir web, App Store y Google Play.
            normalized_period = period.lower()
            candidates = [
                pid
                for pid in (
                    product_id_for(Plan.PRO.value, normalized_period),
                    product_id_for(Plan.STUDIO.value, normalized_period),
                )
                if pid
            ]
            if candidates:
                qs = qs.filter(billing_product_id__in=candidates)

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
                period=period_for_profile(r) or "",
                monthly_cents=monthly_cents_for_profile(r),
                # Vacío sólo si la fila quedó a medias; no se inventa un canal.
                billing_source=r.billing_source or "unknown",
                net_monthly_cents=net_monthly_cents_for_profile(r),
                plan_renews_at=r.plan_renews_at,
                cancel_at_period_end=r.cancel_at_period_end,
                is_billing_exempt=r.is_billing_exempt,
                billing_customer_id=r.billing_customer_id,
                billing_transaction_id=r.billing_transaction_id,
                billing_product_id=r.billing_product_id,
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
