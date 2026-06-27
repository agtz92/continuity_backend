"""Helpers de error/auth compartidos por los resolvers GraphQL de core.

Extraídos de schema.py (ver AUDITORIA_CODIGO.md) para que `Query` (schema.py) y
`Mutation` (schema_mutations.py) los compartan sin acoplarse entre sí.
"""

import functools
import uuid

from graphql import GraphQLError
from strawberry.types import Info
from django.core.exceptions import ValidationError

from .services.projects import NotFoundError
from .quotas import EntityQuotaExceeded


def _user_id(info: Info) -> uuid.UUID:
    """Extrae el `user_id` autenticado del contexto o rechaza la petición.

    Centraliza el gate de auth para que todo resolver empiece con un `uid`
    fiable. El `user_id` lo inyecta el middleware de auth (Supabase JWT) en
    `info.context`; su ausencia significa petición sin token válido.

    Raises:
        GraphQLError: con `extensions.code = "UNAUTHENTICATED"` si no hay
            usuario en el contexto.
    """
    user_id = getattr(info.context, "user_id", None)
    if not user_id:
        raise GraphQLError(
            "Not authenticated", extensions={"code": "UNAUTHENTICATED"}
        )
    return user_id


def _quota_error(e: EntityQuotaExceeded) -> GraphQLError:
    """Traduce un tope de cuota a `GraphQLError` con los datos para la UI.

    Expone en `extensions` el detalle accionable (qué cuota, uso actual, tope y
    plan) para que el cliente pueda mostrar el paywall/upsell correcto sin tener
    que parsear el mensaje.
    """
    return GraphQLError(
        str(e),
        extensions={
            "code": "QUOTA_EXCEEDED",
            "kind": e.kind,
            "current": e.current,
            "cap": e.cap,
            "plan": e.plan,
        },
    )


def _closure_error(e: ValidationError) -> GraphQLError:
    """Traduce el `ValidationError` de cierre de proyecto a `GraphQLError`.

    Cambiar de estado a pausado/matado exige notas de cierre; cuando faltan, el
    servicio levanta un `ValidationError` de Django. Aquí se aplana a un código
    propio (`CLOSURE_NOTES_REQUIRED`) que la UI usa para abrir el modal de notas
    en vez de tratarlo como error genérico.
    """
    msg = "; ".join(e.messages) if hasattr(e, "messages") else str(e)
    return GraphQLError(msg, extensions={"code": "CLOSURE_NOTES_REQUIRED"})


def gql_error_handler(fn):
    """Traduce las excepciones de dominio UNIFORMES a `GraphQLError`.

    Centraliza el mapeo que se repetía en ~30 mutations:
    ``NotFoundError`` → ``NOT_FOUND`` (preservando el mensaje del servicio, que
    siempre es ``"<Entidad> not found"``) y ``EntityQuotaExceeded`` →
    ``QUOTA_EXCEEDED`` (vía :func:`_quota_error`).

    Deliberadamente NO captura ``ValidationError``: su mapeo es heterogéneo
    (``CLOSURE_NOTES_REQUIRED`` en cierre de proyecto vs. ``BAD_INPUT`` en
    rutinas/perfil/preferencias), así que cada resolver que lo necesita lo
    maneja explícito. ``UNAUTHENTICATED`` lo levanta ``_user_id`` antes de
    entrar al cuerpo, así que tampoco aplica aquí.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except NotFoundError as e:
            raise GraphQLError(str(e), extensions={"code": "NOT_FOUND"})
        except EntityQuotaExceeded as e:
            raise _quota_error(e)

    return wrapper
