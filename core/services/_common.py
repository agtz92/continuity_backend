"""Shared primitives used across services.

Lives in its own module to keep the dependency graph acyclic:
`projects` and `activities` both need `NotFoundError` and would otherwise
import each other.
"""

import uuid


class NotFoundError(Exception):
    """Raised when an entity is missing or owned by another user."""


def existing_for_client_id(model, user_id, client_id):
    """Idempotencia de los `create*` que mandan su propio id (la cola offline
    de la app móvil).

    La app genera el UUID al crear sin red y lo reenvía hasta que el servidor
    contesta, así que el mismo id puede llegar dos veces: si la fila ya es de
    este usuario se devuelve tal cual (el reintento no duplica). Si el id es de
    otro usuario o no es un UUID se rechaza como `NotFoundError`, igual que
    cualquier id ajeno.

    Devuelve `(fila_existente_o_None, uuid_o_None)`; el uuid es el que hay que
    pasarle a `objects.create(id=...)`.
    """
    if not client_id:
        return None, None
    try:
        parsed = uuid.UUID(str(client_id))
    except ValueError:
        raise NotFoundError(f"{model.__name__} id is not valid")
    row = model.objects.filter(pk=parsed).first()
    if row is None:
        return None, parsed
    if str(row.user_id) != str(user_id):
        raise NotFoundError(f"{model.__name__} not found")
    return row, parsed
