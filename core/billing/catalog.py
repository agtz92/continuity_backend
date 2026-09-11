"""The one product catalog: identifiers, prices and fees for every channel.

All three channels — RevenueCat Web Billing, the App Store and Google Play —
sell the same four products under the same identifiers, so one mapping answers
"what plan and period is this, and what is it worth" regardless of who sold it.

**Price parity is a product requirement**, and it is structural here rather
than a thing to remember: there is a single set of amounts, so the three
channels cannot drift apart by accident. Charging differently per channel
would take a deliberate change to this file.

This replaced `plans.py`, which mapped Stripe price ids. Stripe is no longer
an issuer — see `docs/pagos-unificados/PLAN.md`. It is still the card
processor underneath Web Billing, which is why a card fee appears in the net
revenue maths below and nowhere else.
"""

from __future__ import annotations

from django.conf import settings

from core.assistant.models import (
    STORE_SOURCES,
    AccountProfile,
    BillingSource,
    Plan,
)


# (plan, period) -> setting name holding the product identifier.
# The same identifier is used on every channel on purpose: one product id per
# plan+period keeps the mapping (and the reporting) single-valued.
_PRODUCT_SETTINGS = {
    (Plan.PRO.value, "monthly"): "STORE_PRODUCT_PRO_MONTHLY",
    (Plan.PRO.value, "annual"): "STORE_PRODUCT_PRO_ANNUAL",
    (Plan.STUDIO.value, "monthly"): "STORE_PRODUCT_STUDIO_MONTHLY",
    (Plan.STUDIO.value, "annual"): "STORE_PRODUCT_STUDIO_ANNUAL",
}

# (plan, period) -> setting holding the gross amount in cents. One entry per
# product, shared by every channel: that is what makes price parity structural
# instead of a convention someone has to remember.
_AMOUNT_SETTINGS = {
    (Plan.PRO.value, "monthly"): "PRICE_PRO_MONTHLY_AMOUNT_CENTS",
    (Plan.PRO.value, "annual"): "PRICE_PRO_ANNUAL_AMOUNT_CENTS",
    (Plan.STUDIO.value, "monthly"): "PRICE_STUDIO_MONTHLY_AMOUNT_CENTS",
    (Plan.STUDIO.value, "annual"): "PRICE_STUDIO_ANNUAL_AMOUNT_CENTS",
}

# RevenueCat's `store` field -> our BillingSource.
#
# The full documented set is AMAZON, APP_STORE, MAC_APP_STORE, PADDLE,
# PLAY_STORE, PROMOTIONAL, RC_BILLING, ROKU, STRIPE and TEST_STORE. Only the
# four below are mapped, and the omissions are deliberate: an unmapped store
# makes `source_for_store` return None, which drops the event as unusable
# rather than granting a plan we can't attribute to a channel we sell on.
#
# Worth knowing about two of the unmapped ones:
#   - TEST_STORE is RevenueCat's virtual store for testing without Apple or
#     Google. Its purchases will not grant anything here.
#   - PROMOTIONAL is a comp granted from RevenueCat's dashboard. We comp
#     through `is_billing_exempt` instead, so those events stay unusable on
#     purpose — two ways to give away a plan is one too many.
_STORE_TO_SOURCE = {
    "APP_STORE": BillingSource.APPLE.value,
    "MAC_APP_STORE": BillingSource.APPLE.value,
    "PLAY_STORE": BillingSource.GOOGLE.value,
    # Web Billing. Confirmed against RevenueCat's webhook docs, not guessed:
    # this used to also accept a `WEB_BILLING` spelling that does not exist.
    "RC_BILLING": BillingSource.WEB.value,
}


def _product_ids(key: str) -> list[str]:
    """Todos los ids configurados en un ajuste, en orden.

    Cada `STORE_PRODUCT_*` acepta **una lista separada por comas**, y esto no es
    una comodidad: es obligatorio por cómo funciona RevenueCat Web Billing.

    Sus productos son **inmutables**. Su propia documentación lo dice: "once
    you've saved the product, it's only possible to add prices for new
    currencies, and not edit existing ones… if you need to change pricing, we
    recommend you create a new product and replace the existing product in your
    offering". O sea que **cada cambio de precio crea un id nuevo**.

    Los suscriptores que ya pagaban conservan el id viejo, y sus renovaciones
    siguen llegando con él. Con un solo id por plan+periodo, el webhook las
    descartaría como inservibles y esa gente perdería su plan al renovar —
    silenciosamente, y solo los que ya te pagaban.

    Por eso la lista. El **primero es el canónico**: el que se ofrece a quien
    compra hoy. Los demás son historia que hay que seguir honrando.
    """
    raw = getattr(settings, key, "") or ""
    return [pid.strip() for pid in raw.split(",") if pid.strip()]


def product_id_for(plan: str, period: str) -> str | None:
    """El id que se vende HOY, o None si no está configurado."""
    key = _PRODUCT_SETTINGS.get((plan, period))
    if not key:
        return None
    ids = _product_ids(key)
    return ids[0] if ids else None


def product_ids_for(plan: str, period: str) -> list[str]:
    """**Todos** los ids de un plan+periodo: el vigente y los retirados.

    `product_id_for` devuelve solo el canónico, que es lo que quieres para
    *ofrecer* algo. Para **buscar** —"dame los suscriptores anuales"— hace falta
    la lista entera, o dejas fuera a quien compró con un id anterior, que es
    precisamente la gente que lleva más tiempo pagándote.
    """
    key = _PRODUCT_SETTINGS.get((plan, period))
    return _product_ids(key) if key else []


def _reverse_map() -> dict[str, tuple[str, str]]:
    """Build product id -> (plan, period), skipping unconfigured entries."""
    out: dict[str, tuple[str, str]] = {}
    for (plan, period), key in _PRODUCT_SETTINGS.items():
        for pid in _product_ids(key):
            out[pid] = (plan, period)
    return out


def plan_for_product(product_id: str) -> str | None:
    """Which plan a store product grants, or None if we don't know it."""
    if not product_id:
        return None
    match = _reverse_map().get(product_id)
    return match[0] if match else None


def period_for_product(product_id: str) -> str | None:
    """`"monthly"`/`"annual"` for a store product, or None if unknown."""
    if not product_id:
        return None
    match = _reverse_map().get(product_id)
    return match[1] if match else None


def source_for_store(store: str) -> str | None:
    """Map a store name from the webhook payload onto a `BillingSource`."""
    return _STORE_TO_SOURCE.get((store or "").upper())


def amount_cents_for_product(product_id: str) -> int:
    """Gross amount (cents) the user is charged for a product.

    This is what the *user* pays, not what we receive — fees come off
    afterwards, per channel. Returns 0 for unknown or unconfigured products,
    and callers must treat 0 as "no estimate" rather than "free".
    """
    if not product_id:
        return 0
    match = _reverse_map().get(product_id)
    if not match:
        return 0
    key = _AMOUNT_SETTINGS.get(match)
    if not key:
        return 0
    return int(getattr(settings, key, 0) or 0)


def monthly_cents_for_product(product_id: str) -> int:
    """Normalize a product to its monthly-equivalent cents (annual ÷ 12)."""
    amount = amount_cents_for_product(product_id)
    if amount <= 0:
        return 0
    if period_for_product(product_id) == "annual":
        return amount // 12
    return amount


def _float_setting(name: str, default: float) -> float:
    raw = getattr(settings, name, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if 0.0 <= value < 1.0 else default


def commission_rate() -> float:
    """Fraction of gross that Apple and Google keep.

    Defaults to 0.15 — the rate both stores charge on the first $1M of annual
    revenue (Apple via the Small Business Program, which requires enrolling;
    Google Play automatically). Raise `STORE_COMMISSION_RATE` to 0.30 if the
    business outgrows either threshold.
    """
    return _float_setting("STORE_COMMISSION_RATE", 0.15)


# ---------- Per-profile helpers ----------
#
# What reporting should call. They take the profile rather than a product id
# because the answer depends on who sold it, and the caller shouldn't have to
# know that.


def period_for_profile(profile: AccountProfile) -> str | None:
    """`"monthly"`/`"annual"` for this subscriber, whoever sold the plan."""
    return period_for_product(profile.billing_product_id)


def monthly_cents_for_profile(profile: AccountProfile) -> int:
    """Gross monthly-equivalent cents this subscriber is billed.

    "Gross" means what the user pays. Use `net_monthly_cents_for_profile` for
    what actually lands in the bank.
    """
    return monthly_cents_for_product(profile.billing_product_id)


def net_monthly_cents_for_profile(profile: AccountProfile) -> int:
    """Monthly-equivalent cents that reach us, after this channel's fees.

    The two channels lose money in genuinely different shapes:

    - **Stores** take a flat commission of the gross (15% by default).
    - **Web** pays a card processing fee — a percentage plus a fixed amount
      *per charge*, so an annual plan pays that fixed part once a year and a
      monthly one twice as many times as you'd guess — plus RevenueCat's own
      cut. RevenueCat is free below $2,500 of monthly tracked revenue, so on
      a small account this slightly *overstates* the cost. That is the safe
      direction to be wrong in for a dashboard.

    Stripe is not an issuer here; it is only the card processor underneath
    Web Billing, which is the sole reason a card fee appears at all.

    Both numbers are estimates for a dashboard, not accounting.
    """
    gross = monthly_cents_for_profile(profile)
    if gross <= 0:
        return 0

    if profile.billing_source in STORE_SOURCES:
        return int(round(gross * (1.0 - commission_rate())))

    card_pct = _float_setting("CARD_FEE_PERCENT", 0.029)
    revenuecat_pct = _float_setting("REVENUECAT_FEE_PERCENT", 0.01)
    fixed_cents = int(getattr(settings, "CARD_FEE_FIXED_CENTS", 30) or 30)
    # An annual plan is charged once a year, so amortize its fixed fee over
    # twelve months instead of applying it monthly.
    charges_per_month = 1 / 12 if period_for_profile(profile) == "annual" else 1
    net = gross * (1.0 - card_pct - revenuecat_pct) - fixed_cents * charges_per_month
    return max(0, int(round(net)))
