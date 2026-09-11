"""Un plan puede tener varios product ids, y hay que honrarlos todos.

RevenueCat Web Billing **no deja editar un producto**. Su documentación:

    "Once you've saved the product, it's only possible to add prices for new
    currencies, and not edit existing ones. If you need to change pricing, we
    recommend you create a new product with the desired pricing, and replace
    the existing product in your offering."

Así que cada cambio de precio en el canal web crea un **id nuevo**. Los
suscriptores que ya pagaban conservan el viejo en su suscripción, y sus
renovaciones siguen llegando con ese id durante meses o años.

Con un solo id por (plan, periodo) el webhook los descartaría como inservibles
y esa gente perdería su plan al renovar. Silenciosamente, y **solo los que ya te
pagaban** — el peor grupo posible al que fallarle.

De ahí que cada `STORE_PRODUCT_*` acepte una lista separada por comas: el
primero es el que se vende hoy, los demás son historia que hay que seguir
reconociendo.
"""

import pytest
from django.test import override_settings

from core.billing import catalog


@override_settings(STORE_PRODUCT_PRO_MONTHLY="it.continuu.pro_monthly")
def test_un_solo_id_sigue_funcionando():
    """La forma de siempre no se rompe: un valor suelto es una lista de uno."""
    assert catalog.product_id_for("pro", "monthly") == "it.continuu.pro_monthly"
    assert catalog.plan_for_product("it.continuu.pro_monthly") == "pro"
    assert catalog.period_for_product("it.continuu.pro_monthly") == "monthly"


@override_settings(
    STORE_PRODUCT_PRO_MONTHLY="it.continuu.pro_monthly_v2,it.continuu.pro_monthly"
)
def test_los_ids_viejos_siguen_otorgando_el_plan():
    # El canónico es el primero: es el que se ofrece a quien compra hoy.
    assert catalog.product_id_for("pro", "monthly") == "it.continuu.pro_monthly_v2"

    # Pero la renovación de quien compró el viejo TIENE que seguir valiendo.
    for pid in ("it.continuu.pro_monthly_v2", "it.continuu.pro_monthly"):
        assert catalog.plan_for_product(pid) == "pro", pid
        assert catalog.period_for_product(pid) == "monthly", pid


@override_settings(
    STORE_PRODUCT_STUDIO_ANNUAL="  it.continuu.studio_annual_v2 , it.continuu.studio_annual  "
)
def test_tolera_espacios_alrededor_de_las_comas():
    """Una variable de entorno escrita a mano lleva espacios. No es excusa."""
    assert (
        catalog.product_id_for("studio", "annual") == "it.continuu.studio_annual_v2"
    )
    assert catalog.plan_for_product("it.continuu.studio_annual") == "studio"


@override_settings(STORE_PRODUCT_PRO_ANNUAL="")
def test_sin_configurar_sigue_devolviendo_none():
    """Vacío no puede convertirse en un id vacío que mapee a algo."""
    assert catalog.product_id_for("pro", "annual") is None
    assert catalog.plan_for_product("") is None


@override_settings(STORE_PRODUCT_PRO_MONTHLY="it.continuu.pro_monthly")
def test_un_id_desconocido_no_otorga_nada():
    """El caso que protege el dinero: lo que no reconocemos no da plan."""
    assert catalog.plan_for_product("it.continuu.inventado") is None
    assert catalog.period_for_product("it.continuu.inventado") is None
