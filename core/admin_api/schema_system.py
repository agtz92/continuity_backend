"""Admin GraphQL — área de sistema: cola de notificaciones, stats globales,
bitácora de auditoría y conexiones MCP (+ reintento de jobs y revocar MCP).

Extraído de schema.py (split de AdminQuery por área, ver AUDITORIA_CODIGO.md).
Se re-fusiona en `AdminQuery`/`AdminMutation` vía merge_types en schema.py.
"""

from __future__ import annotations

import uuid
from typing import Optional

import strawberry
from django.db.models import Q
from graphql import GraphQLError
from strawberry.types import Info

from core.services import mcp_connections as mcp_connections_svc
from core.notifications.models import Notification, NotificationStatus

from .audit import record as audit_record
from .models import AdminAuditLog
from .permissions import _admin_user_id
from .services import stats as stats_svc
from .types import *  # noqa: F401,F403


@strawberry.type
class AdminSystemQuery:
    @strawberry.field(name="adminNotificationJobs")
    def admin_notification_jobs(
        self,
        info: Info,
        page: int = 1,
        per_page: int = 50,
        status: Optional[str] = None,
        channel: Optional[str] = None,
        kind: Optional[str] = None,
        user_id: Optional[strawberry.ID] = None,
    ) -> AdminNotificationJobPage:
        """Cola de notificaciones paginada y filtrable para depurar envíos.

        Permite al admin inspeccionar los jobs de la tabla ``Notification`` (su
        estado, intentos, error, etc.) filtrando por estado/canal/tipo/usuario.
        Pide ``per_page + 1`` filas para saber si hay página siguiente sin un
        ``COUNT`` extra.

        Args:
            info: Contexto GraphQL; debe ser admin.
            page: Página 1-based.
            per_page: Tamaño de página (acotado a 1..200).
            status: Filtra por estado (se normaliza a minúsculas).
            channel: Filtra por canal exacto.
            kind: Filtra por tipo exacto.
            user_id: Filtra por destinatario.

        Returns:
            ``AdminNotificationJobPage`` con los jobs y paginación.

        Raises:
            GraphQLError: si el solicitante no es admin (vía ``_admin_user_id``).
        """
        _admin_user_id(info)
        # NOTE: paginación duplicada — extraer paginate() + constantes
        per_page = max(1, min(per_page, 200))
        page = max(1, page)
        offset = (page - 1) * per_page

        qs = Notification.objects.all()
        if status:
            qs = qs.filter(status=status.lower())
        if channel:
            qs = qs.filter(channel=channel)
        if kind:
            qs = qs.filter(kind=kind)
        if user_id:
            qs = qs.filter(user_id=uuid.UUID(str(user_id)))

        rows = list(qs[offset : offset + per_page + 1])
        has_next = len(rows) > per_page
        rows = rows[:per_page]
        return AdminNotificationJobPage(
            jobs=[
                AdminNotificationJob(
                    id=strawberry.ID(str(n.id)),
                    user_id=strawberry.ID(str(n.user_id)),
                    channel=n.channel,
                    kind=n.kind,
                    dedupe_key=n.dedupe_key,
                    body=n.body,
                    scheduled_for=n.scheduled_for,
                    status=n.status,
                    attempts=n.attempts,
                    external_message_id=n.external_message_id,
                    error=n.error,
                    created=n.created,
                    sent_at=n.sent_at,
                )
                for n in rows
            ],
            page=page,
            per_page=per_page,
            has_next=has_next,
        )

    # TODO: refactor — mover esta agregación (186 líneas, 5 niveles) a admin_api/services/stats.py (ver AUDITORIA_CODIGO.md)

    @strawberry.field(name="adminSystemStats")
    def admin_system_stats(self, info: Info) -> AdminSystemStats:
        """Panel global de métricas del sistema (la "home" del admin).

        Agrega de golpe todas las cifras del dashboard: usuarios y planes,
        engagement (DAU/WAU/MAU + series diarias), objetos de producto, CMS y
        salud de la cola de notificaciones. Es deliberadamente caro y se sirve a
        una sola pantalla; los usuarios salen de Supabase auth (fuente real) y el
        resto del ORM local. Si Supabase falla se degrada a una lista vacía en
        vez de romper toda la query.

        Args:
            info: Contexto GraphQL; debe ser admin.

        Returns:
            ``AdminSystemStats`` con todas las secciones del panel.

        Raises:
            GraphQLError: si el solicitante no es admin (vía ``_admin_user_id``).
                Un fallo de Supabase NO lanza: se loguea y degrada.
        """
        _admin_user_id(info)
        s = stats_svc.compute_system_stats()
        return AdminSystemStats(
            total_users=s.total_users,
            total_accounts=s.total_accounts,
            admins=s.admins,
            plan_counts=[
                PlanCount(plan=p.label, count=p.count) for p in s.plan_counts
            ],
            dau=s.dau,
            wau=s.wau,
            mau=s.mau,
            signups_series=[
                SeriesPoint(date=p.date, value=p.value)
                for p in s.signups_series
            ],
            activity_series=[
                SeriesPoint(date=p.date, value=p.value)
                for p in s.activity_series
            ],
            activity_by_kind=[
                LabeledCount(label=lc.label, count=lc.count)
                for lc in s.activity_by_kind
            ],
            project_state_counts=[
                LabeledCount(label=lc.label, count=lc.count)
                for lc in s.project_state_counts
            ],
            tasks_open=s.tasks_open,
            tasks_done_30d=s.tasks_done_30d,
            ideas_total=s.ideas_total,
            blog_posts_published=s.blog_posts_published,
            blog_posts_draft=s.blog_posts_draft,
            pages_published=s.pages_published,
            pending_jobs=s.pending_jobs,
            failed_jobs=s.failed_jobs,
            job_status_counts=[
                JobStatusCount(status=lc.label, count=lc.count)
                for lc in s.job_status_counts
            ],
            recent_signups=[
                RecentSignup(
                    user_id=strawberry.ID(str(r.user_id)),
                    email=r.email,
                    created_at=r.created_at,
                    plan=r.plan,
                )
                for r in s.recent_signups
            ],
        )

    @strawberry.field(name="adminAuditLog")
    def admin_audit_log(
        self,
        info: Info,
        page: int = 1,
        per_page: int = 50,
        actor_user_id: Optional[strawberry.ID] = None,
        action_contains: Optional[str] = None,
        target_user_id: Optional[strawberry.ID] = None,
    ) -> AdminAuditPage:
        """Bitácora de auditoría admin, paginada y filtrable.

        Expone las entradas de ``AdminAuditLog`` (qué admin hizo qué, sobre qué
        objeto) para investigar acciones. El filtro por usuario objetivo cubre
        tanto ``target_type="user"`` como ``"account_profile"`` porque distintas
        acciones registran el mismo UUID bajo uno u otro tipo.

        Args:
            info: Contexto GraphQL; debe ser admin.
            page: Página 1-based.
            per_page: Tamaño de página (acotado a 1..200).
            actor_user_id: Filtra por el admin que ejecutó la acción.
            action_contains: Subcadena (icontains) sobre el nombre de acción.
            target_user_id: Filtra por usuario objetivo (user o account_profile).

        Returns:
            ``AdminAuditPage`` con las entradas y paginación.

        Raises:
            GraphQLError: si el solicitante no es admin (vía ``_admin_user_id``).
        """
        _admin_user_id(info)
        # NOTE: paginación duplicada — extraer paginate() + constantes
        per_page = max(1, min(per_page, 200))
        page = max(1, page)
        offset = (page - 1) * per_page

        qs = AdminAuditLog.objects.all()
        if actor_user_id:
            qs = qs.filter(actor_user_id=uuid.UUID(str(actor_user_id)))
        if action_contains:
            qs = qs.filter(action__icontains=action_contains)
        if target_user_id:
            qs = qs.filter(
                Q(target_type="user", target_id=str(target_user_id))
                | Q(target_type="account_profile", target_id=str(target_user_id))
            )

        items = list(qs[offset : offset + per_page + 1])
        has_next = len(items) > per_page
        items = items[:per_page]
        return AdminAuditPage(
            entries=[
                AdminAuditEntry(
                    id=strawberry.ID(str(e.id)),
                    actor_user_id=strawberry.ID(str(e.actor_user_id)),
                    action=e.action,
                    target_type=e.target_type,
                    target_id=e.target_id,
                    payload=e.payload or {},
                    created=e.created,
                )
                for e in items
            ],
            page=page,
            per_page=per_page,
            has_next=has_next,
        )

    @strawberry.field(name="adminMcpConnections")
    def admin_mcp_connections(
        self, info: Info, limit: int = 50
    ) -> list[AdminMcpConnection]:
        _admin_user_id(info)
        return [
            AdminMcpConnection(
                user_id=strawberry.ID(str(c["user_id"])),
                client_id=c["client_id"],
                client_name=c["client_name"],
                connected_at=c["connected_at"],
            )
            for c in mcp_connections_svc.list_all_connections(limit=limit)
        ]

    @strawberry.field(name="adminMcpConnectionEvents")
    def admin_mcp_connection_events(
        self, info: Info, limit: int = 50
    ) -> list[AdminMcpConnectionEvent]:
        _admin_user_id(info)
        return [
            AdminMcpConnectionEvent(
                user_id=strawberry.ID(str(e.user_id)),
                client_id=e.client_id,
                client_name=e.client_name,
                event=e.event,
                created=e.created,
            )
            for e in mcp_connections_svc.recent_events(limit=limit)
        ]

    @strawberry.field(name="adminMcpStats")
    def admin_mcp_stats(self, info: Info) -> AdminMcpStats:
        _admin_user_id(info)
        s = mcp_connections_svc.connection_stats()
        return AdminMcpStats(
            active_connections=s["active_connections"],
            distinct_users=s["distinct_users"],
            by_client=[
                LabeledCount(label=k, count=v) for k, v in s["by_client"].items()
            ],
        )


@strawberry.type
class AdminSystemMutation:
    @strawberry.mutation(name="adminRevokeMcpConnection")
    def admin_revoke_mcp_connection(
        self, info: Info, user_id: strawberry.ID, client_id: str
    ) -> bool:
        """Revoca una conexión MCP de un usuario (acción de admin).

        Fuerza la desconexión de un cliente MCP por seguridad/soporte y deja
        rastro en la bitácora de auditoría.

        Args:
            info: Contexto GraphQL; debe ser admin.
            user_id: Dueño de la conexión a revocar.
            client_id: Cliente MCP a desconectar.

        Returns:
            ``True`` si se revocó al menos una conexión.

        Raises:
            GraphQLError: ``BAD_INPUT`` si ``user_id`` no es UUID válido, o el
                error de ``_admin_user_id`` si el solicitante no es admin.
        """
        actor = _admin_user_id(info)
        import uuid as _uuid

        try:
            uid = _uuid.UUID(str(user_id))
        except ValueError:
            raise GraphQLError("Invalid user_id", extensions={"code": "BAD_INPUT"})
        n = mcp_connections_svc.revoke_connection(uid, str(client_id), by_admin=True)
        audit_record(
            actor_user_id=actor,
            action="mcp.revoke_connection",
            target_type="mcp_connection",
            target_id=f"{user_id}:{client_id}",
            payload={"revoked": n},
        )
        return n > 0

    @strawberry.mutation(name="adminNotificationJobRetry")
    def admin_notification_job_retry(
        self, info: Info, id: strawberry.ID
    ) -> AdminNotificationJob:
        """Re-encola un job de notificación fallido o saltado.

        Lo devuelve a estado PENDING y limpia el error para que el worker lo
        reintente. Solo aplica a jobs FAILED o SKIPPED: reintentar uno enviado o
        pendiente no tiene sentido y se rechaza.

        Args:
            info: Contexto GraphQL; debe ser admin.
            id: ID del job de notificación.

        Returns:
            El ``AdminNotificationJob`` ya en estado PENDING.

        Raises:
            GraphQLError: ``NOT_FOUND`` si el job no existe (o id inválido);
                ``BAD_INPUT`` si el job no está en estado reintenta­ble; o el
                error de ``_admin_user_id`` si el solicitante no es admin.
        """
        actor = _admin_user_id(info)
        try:
            job = Notification.objects.get(id=uuid.UUID(str(id)))
        except (Notification.DoesNotExist, ValueError):
            raise GraphQLError("Job not found", extensions={"code": "NOT_FOUND"})
        if job.status not in {
            NotificationStatus.FAILED,
            NotificationStatus.SKIPPED,
        }:
            raise GraphQLError(
                f"Only failed or skipped jobs can be retried (current: {job.status})",
                extensions={"code": "BAD_INPUT"},
            )
        before = job.status
        job.status = NotificationStatus.PENDING
        job.error = ""
        job.save(update_fields=["status", "error"])
        audit_record(
            actor_user_id=actor,
            action="notification.retry",
            target_type="notification",
            target_id=job.id,
            payload={"before": before, "after": job.status},
        )
        return AdminNotificationJob(
            id=strawberry.ID(str(job.id)),
            user_id=strawberry.ID(str(job.user_id)),
            channel=job.channel,
            kind=job.kind,
            dedupe_key=job.dedupe_key,
            body=job.body,
            scheduled_for=job.scheduled_for,
            status=job.status,
            attempts=job.attempts,
            external_message_id=job.external_message_id,
            error=job.error,
            created=job.created,
            sent_at=job.sent_at,
        )
