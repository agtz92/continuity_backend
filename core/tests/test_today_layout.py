"""Tests for the Today layout preferences.

Covers the GraphQL surface (todayLayout query, updateTodayLayout and
resetTodayLayout mutations) plus the underlying service rules:

* lazy-create on first read
* canonical default order
* hide/order persistence and isolation between users
* validation of unknown ids and locked sections
* graceful handling of sections added to code after a user has saved
"""

import uuid

import pytest
from django.core.exceptions import ValidationError

from core.services import preferences as preferences_svc
from core.services.preferences import (
    NON_HIDEABLE_TODAY_IDS,
    DEFAULT_RAIL_IDS,
    TODAY_SECTION_IDS,
)


TODAY_LAYOUT_QUERY = """
    query { todayLayout { order hidden rail } }
"""

UPDATE_MUTATION = """
    mutation U($order: [String!], $hidden: [String!], $rail: [String!]) {
        updateTodayLayout(order: $order, hidden: $hidden, rail: $rail) {
            order
            hidden
            rail
        }
    }
"""

RESET_MUTATION = """
    mutation { resetTodayLayout { order hidden rail } }
"""


# La columna principal por defecto ya no es la lista canónica entera: las
# secciones que arrancan en el lateral salen de `order`. Este helper evita
# repetir esa resta en cada test.
def main_default() -> list[str]:
    return [s for s in TODAY_SECTION_IDS if s not in DEFAULT_RAIL_IDS]


# ---------------------------- service layer ---------------------------- #


@pytest.mark.django_db
def test_get_layout_lazy_creates_with_defaults(user_a):
    layout = preferences_svc.get_today_layout(user_a)
    assert layout["order"] == main_default()
    assert layout["hidden"] == []
    assert layout["rail"] == list(DEFAULT_RAIL_IDS)


@pytest.mark.django_db
def test_update_persists_order_and_hidden(user_a):
    new_order = list(reversed(TODAY_SECTION_IDS))
    preferences_svc.update_today_layout(
        user_a, order=new_order, hidden=["done-today", "sleeping"]
    )

    layout = preferences_svc.get_today_layout(user_a)
    # El rail sigue en su valor por defecto, así que sus ids se descuentan del
    # orden de la columna principal aunque se hayan mandado en `order`.
    assert layout["order"] == [s for s in new_order if s not in DEFAULT_RAIL_IDS]
    assert layout["hidden"] == ["done-today", "sleeping"]


@pytest.mark.django_db
def test_unknown_section_id_raises(user_a):
    with pytest.raises(ValidationError):
        preferences_svc.update_today_layout(user_a, hidden=["not-a-section"])
    with pytest.raises(ValidationError):
        preferences_svc.update_today_layout(user_a, order=["bogus"])


@pytest.mark.django_db
def test_non_hideable_section_cannot_be_hidden(user_a):
    locked = next(iter(NON_HIDEABLE_TODAY_IDS))
    with pytest.raises(ValidationError):
        preferences_svc.update_today_layout(user_a, hidden=[locked])


@pytest.mark.django_db
def test_partial_update_does_not_clobber_other_field(user_a):
    preferences_svc.update_today_layout(user_a, hidden=["done-today"])
    preferences_svc.update_today_layout(
        user_a, order=list(reversed(TODAY_SECTION_IDS))
    )

    layout = preferences_svc.get_today_layout(user_a)
    assert layout["hidden"] == ["done-today"]
    assert layout["order"] == [
        s for s in reversed(TODAY_SECTION_IDS) if s not in DEFAULT_RAIL_IDS
    ]


@pytest.mark.django_db
def test_reset_wipes_layout(user_a):
    preferences_svc.update_today_layout(
        user_a,
        order=list(reversed(TODAY_SECTION_IDS)),
        hidden=["done-today"],
    )

    layout = preferences_svc.reset_today_layout(user_a)
    assert layout["order"] == main_default()
    assert layout["hidden"] == []
    assert layout["rail"] == list(DEFAULT_RAIL_IDS)


@pytest.mark.django_db
def test_missing_sections_appended_when_canonical_list_grows(user_a):
    # Simulate a user who saved before "launched-with-tasks" existed.
    partial = [s for s in TODAY_SECTION_IDS if s != "launched-with-tasks"]
    preferences_svc.update_today_layout(user_a, order=partial)

    layout = preferences_svc.get_today_layout(user_a)
    # The missing canonical id is appended at the end so it's visibly new.
    assert layout["order"][-1] == "launched-with-tasks"
    # Entre las dos columnas cubren la lista canónica entera.
    assert set(layout["order"]) | set(layout["rail"]) == set(TODAY_SECTION_IDS)


@pytest.mark.django_db
def test_dedups_order_input(user_a):
    dup_order = ["today-focus", "today-focus", "done-today"]
    preferences_svc.update_today_layout(user_a, order=dup_order)

    layout = preferences_svc.get_today_layout(user_a)
    # Stored order keeps the first occurrence; missing canonical ids
    # are then appended.
    assert layout["order"][:2] == ["today-focus", "done-today"]
    assert len(layout["order"]) == len(TODAY_SECTION_IDS) - len(DEFAULT_RAIL_IDS)


@pytest.mark.django_db
def test_users_are_isolated(user_a, user_b):
    preferences_svc.update_today_layout(user_a, hidden=["done-today"])
    preferences_svc.update_today_layout(user_b, hidden=["sleeping"])

    a = preferences_svc.get_today_layout(user_a)
    b = preferences_svc.get_today_layout(user_b)
    assert a["hidden"] == ["done-today"]
    assert b["hidden"] == ["sleeping"]


# ---------------------------- GraphQL layer ---------------------------- #


@pytest.mark.django_db
def test_query_returns_defaults_for_new_user(execute_query, user_a):
    result = execute_query(TODAY_LAYOUT_QUERY, user_id=user_a)
    assert result.errors is None
    assert result.data["todayLayout"]["order"] == main_default()
    assert result.data["todayLayout"]["hidden"] == []
    assert result.data["todayLayout"]["rail"] == list(DEFAULT_RAIL_IDS)


@pytest.mark.django_db
def test_query_unauthenticated_errors(execute_query):
    result = execute_query(TODAY_LAYOUT_QUERY, user_id=None)
    assert result.errors is not None
    assert result.errors[0].extensions["code"] == "UNAUTHENTICATED"


@pytest.mark.django_db
def test_mutation_updates_and_query_reflects_it(execute_query, user_a):
    new_order = list(reversed(TODAY_SECTION_IDS))
    res = execute_query(
        UPDATE_MUTATION,
        user_id=user_a,
        variable_values={"order": new_order, "hidden": ["done-today"]},
    )
    assert res.errors is None
    expected = [s for s in new_order if s not in DEFAULT_RAIL_IDS]
    assert res.data["updateTodayLayout"]["order"] == expected
    assert res.data["updateTodayLayout"]["hidden"] == ["done-today"]

    follow_up = execute_query(TODAY_LAYOUT_QUERY, user_id=user_a)
    assert follow_up.data["todayLayout"]["order"] == expected
    assert follow_up.data["todayLayout"]["hidden"] == ["done-today"]


@pytest.mark.django_db
def test_mutation_rejects_unknown_id(execute_query, user_a):
    res = execute_query(
        UPDATE_MUTATION,
        user_id=user_a,
        variable_values={"hidden": ["not-real"]},
    )
    assert res.errors is not None
    assert res.errors[0].extensions["code"] == "BAD_INPUT"


@pytest.mark.django_db
def test_mutation_rejects_locked_section(execute_query, user_a):
    locked = next(iter(NON_HIDEABLE_TODAY_IDS))
    res = execute_query(
        UPDATE_MUTATION,
        user_id=user_a,
        variable_values={"hidden": [locked]},
    )
    assert res.errors is not None
    assert res.errors[0].extensions["code"] == "BAD_INPUT"


@pytest.mark.django_db
def test_reset_mutation(execute_query, user_a):
    execute_query(
        UPDATE_MUTATION,
        user_id=user_a,
        variable_values={"hidden": ["done-today"]},
    )

    res = execute_query(RESET_MUTATION, user_id=user_a)
    assert res.errors is None
    assert res.data["resetTodayLayout"]["hidden"] == []
    assert res.data["resetTodayLayout"]["order"] == main_default()
    assert res.data["resetTodayLayout"]["rail"] == list(DEFAULT_RAIL_IDS)


@pytest.mark.django_db
def test_mutation_isolates_users(execute_query, user_a, user_b):
    execute_query(
        UPDATE_MUTATION,
        user_id=user_a,
        variable_values={"hidden": ["done-today"]},
    )

    res = execute_query(TODAY_LAYOUT_QUERY, user_id=user_b)
    assert res.data["todayLayout"]["hidden"] == []


# ------------------------- columna lateral (rail) ------------------------ #


@pytest.mark.django_db
def test_una_seccion_no_puede_estar_en_las_dos_columnas(user_a):
    """El rail manda: si un id está en las dos listas, sale de `order`.

    Un cliente puede mandar `order` con la lista entera sin saber del rail
    (la app nativa lo hace). Sin esta regla la sección se pintaría dos veces.
    """
    preferences_svc.update_today_layout(
        user_a, order=list(TODAY_SECTION_IDS), rail=["cooling"]
    )
    layout = preferences_svc.get_today_layout(user_a)
    assert layout["rail"] == ["cooling"]
    assert "cooling" not in layout["order"]


@pytest.mark.django_db
def test_vaciar_el_rail_a_proposito_se_respeta(user_a):
    """Quien deja el rail vacío no quiere que se le repueble en la carga siguiente."""
    preferences_svc.update_today_layout(user_a, rail=[])
    layout = preferences_svc.get_today_layout(user_a)
    assert layout["rail"] == []
    # Y entonces TODO vive en la columna principal.
    assert set(layout["order"]) == set(TODAY_SECTION_IDS)


@pytest.mark.django_db
def test_el_rail_conserva_su_propio_orden(user_a):
    preferences_svc.update_today_layout(user_a, rail=["cooling", "stopped"])
    assert preferences_svc.get_today_layout(user_a)["rail"] == ["cooling", "stopped"]


@pytest.mark.django_db
def test_cualquier_seccion_puede_ir_al_rail(user_a):
    """No hay lista blanca: el editor deja mover lo que sea a donde sea."""
    preferences_svc.update_today_layout(user_a, rail=["routines-today", "log-tail"])
    layout = preferences_svc.get_today_layout(user_a)
    assert layout["rail"] == ["routines-today", "log-tail"]
    assert "routines-today" not in layout["order"]


@pytest.mark.django_db
def test_rail_rechaza_ids_desconocidos(user_a):
    with pytest.raises(ValidationError):
        preferences_svc.update_today_layout(user_a, rail=["no-existe"])


@pytest.mark.django_db
def test_rail_dedupe(user_a):
    preferences_svc.update_today_layout(user_a, rail=["stopped", "stopped"])
    assert preferences_svc.get_today_layout(user_a)["rail"] == ["stopped"]
