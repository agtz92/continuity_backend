# Integración de pagos web y móvil

> **Este documento es la verdad absoluta sobre cobros, precios y suscripciones
> en Continuity.** Cubre los tres canales de venta (Stripe en web, App Store y
> Google Play) y la capa que los unifica. Si otro `.md` del repo contradice algo
> de aquí, gana este. Los documentos que hablaban de billing antes de esta
> integración apuntan aquí desde su encabezado.

Última actualización: 2026-08-05.

> ⚠️ **La decisión cambió el 5 de agosto y este documento todavía no lo refleja.**
> Describe la arquitectura implementada: Stripe directo en web + tiendas vía
> RevenueCat. Se decidió **mover también la web a RevenueCat Web Billing**, con lo
> que Stripe deja de ser un emisor de titularidad y pasa a ser sólo el procesador
> de tarjeta por debajo.
>
> Mientras esa migración no termine, lee este documento como **el estado actual
> del código** (que sigue siendo cierto y está probado), y el plan de a dónde va
> en [`pagos-unificados/PLAN.md`](pagos-unificados/PLAN.md). Cerrar esa migración
> incluye actualizar las secciones 2, 3, 4, 5, 6, 8 y 9 de aquí.

---

## 0. Por qué existe

Hasta ahora sólo se podía pagar en la web, con Stripe. La app móvil tenía
billing **read-only**: mostraba el plan y mandaba al navegador
(`mobile/AGENTS.md`, regla 10). Esa decisión evitaba la complejidad de los pagos
in-app, pero a cambio pierde a todo usuario que vive en el teléfono y no termina
el salto al navegador.

La decisión es abrir el cobro dentro de la app **manteniendo los mismos precios
en USD** que la web. Eso implica aceptar la comisión de las tiendas sin
trasladarla al usuario.

### Lo que cuesta y por qué se acepta

| Canal | Comisión efectiva | Nota |
|---|---|---|
| Web (Stripe) | ~3.2–6.2% | 2.9% + $0.30 **por cargo**. Un plan mensual paga ese fijo 12 veces al año; uno anual, una. |
| App Store / Google Play | **15%** | Mientras se facture menos de $1M USD/año. En Apple hay que **inscribirse** al Small Business Program; en Google Play es automático. |
| App Store / Google Play | 30% | Al superar ese umbral. |

El sobrecosto real de vender in-app frente a Stripe es de **~9 a 12 puntos**, no
de 30. Se compensa con los suscriptores que hoy simplemente no llegan al
checkout. La aritmética exacta está en
`core/billing/plans.py::net_monthly_cents_for_profile`, que es también lo que
alimenta el MRR neto del panel de admin.

---

## 1. Precios — fuente de verdad

**Los mismos números en los tres canales.** Todos en USD.

| Plan | Mensual | Anual (equivalente mensual) | Cargo anual único |
|---|---:|---:|---:|
| Free | $0 | $0 | — |
| Pro | **$9.00** | **$7.00** | **$84.00** |
| Studio | **$24.00** | **$19.00** | **$228.00** |

Dónde vive cada copia:

> ⚠️ **La tabla de arriba no coincide con `settings.py`.** El código tiene Studio a
> **$19.00 mensual / $190.00 anual** (`PRICE_STUDIO_MONTHLY_AMOUNT_CENTS=1900`,
> `PRICE_STUDIO_ANNUAL_AMOUNT_CENTS=19000`); este doc dice $24.00 / $228.00. Uno de
> los dos está mal y **no es una discrepancia que un agente deba resolver solo**: es
> lo que le cobras a la gente. Decide cuál manda y alinea el otro.

| Uso | Lugar |
|---|---|
| Texto que ve el usuario en la web | `frontend/messages/{es,en}.json` → `marketing.pricing.tiers.*` |
| Identificadores de producto de tienda | env `STORE_PRODUCT_{PRO,STUDIO}_{MONTHLY,ANNUAL}` |
| **Importes, los tres canales** | env `PRICE_{PRO,STUDIO}_{MONTHLY,ANNUAL}_AMOUNT_CENTS` |

Ya no hay identificadores de precio de Stripe ni importes de tienda aparte: Stripe
dejó de ser emisor (sigue siendo el procesador de tarjeta bajo Web Billing) y hay
**un solo juego de importes** para los tres canales.

> **Cómo se sostiene la paridad.** `core/billing/catalog.py` (que reemplazó a
> `store_plans.py`) tiene **un solo juego de importes**, compartido por los tres
> canales, así que no pueden separarse por descuido. Cobrar distinto por canal
> exigiría un cambio deliberado en ese archivo — es el único lugar que
> hay que tocar — y hazlo a sabiendas.

> **Advertencia sobre monedas.** La paridad que se puede garantizar es **en
> dólares**. Apple y Google fijan el precio local con su propia matriz de
> conversión e impuestos incluidos, así que en MXN o EUR el importe de tienda no
> coincidirá con el de Stripe salvo que fijes precios locales a mano en ambos
> lados. No está hecho.

---

## 2. El modelo: una sola titularidad, tres emisores

El problema real de tener tres canales no es cobrar: es que **tres fuentes
distintas escriben la misma fila** de `AccountProfile`. Una llegada tardía de
Stripe no puede degradar a alguien que hoy le paga a Apple.

Por eso hay un **único punto de escritura**:

```
Stripe webhook ─┐
App Store ──────┼──→ core/billing/entitlements.py::apply_entitlement() ──→ AccountProfile
Google Play ────┘
```

`core/billing/entitlements.py` es el módulo que manda. Nadie más escribe `plan`,
`billing_source`, `plan_renews_at` ni los ids por fuente.

### Vocabulario compartido

Cada canal traduce su jerga a tres estados (`EntitlementStatus`):

| Estado | Significa | Ejemplos |
|---|---|---|
| `ACTIVE` | Tiene derecho al plan ahora | Stripe `active`/`trialing`/`past_due`; `INITIAL_PURCHASE`, `RENEWAL`, `BILLING_ISSUE` |
| `TERMINAL` | Se acabó el derecho | Stripe `canceled`/`unpaid`; `EXPIRATION`, reembolso |
| `IGNORE` | En vuelo o irrelevante | Stripe `incomplete`; `TEST`, `TRANSFER` |

Dos sutilezas que cuestan dinero si se invierten:

- **`incomplete` de Stripe no es terminal.** Es un checkout a medias; tratarlo
  como baja borra la suscripción que el usuario ya tiene.
- **"Cancelado" en las tiendas no es "córtale ya".** Significa que se apagó la
  renovación automática; el usuario conserva lo que pagó hasta que termine el
  periodo. Sólo `EXPIRATION` o un reembolso revocan.

### Reglas que aplica `apply_entitlement`

1. **Ningún evento pisa la titularidad viva de otra fuente.** Un evento de
   Stripe rezagado no degrada a un suscriptor de App Store, ni al revés.
2. **Los conflictos se resuelven por duración, nunca por orden de llegada.**
   Si dos canales reclaman al mismo usuario, gana el que corre más tiempo y el
   perdedor queda en el audit log con acción `billing.entitlement_conflict` y
   `action_required` — hay que cancelarlo y reembolsarlo a mano.
3. **Los eventos de tienda fuera de orden no acortan el acceso.** Una
   suscripción de tienda sólo se extiende; un evento que termina *antes* de lo
   que ya tenemos describe el pasado. (Deliberadamente sólo para tiendas: en
   Stripe, pasar de anual a mensual sí mueve la fecha hacia atrás.)
4. **`is_billing_exempt` se respeta en un solo lugar** — el camino de revocación.
   Las cuentas de cortesía/beta tienen su plan por exención, no por compra.
5. **Las filas antiguas siguen protegidas.** Todo suscriptor anterior a esta
   integración tiene `billing_source=""`. Leer eso literalmente como "no hay
   nada que cuidar" apagaría el guard justo para quienes ya pagan, así que
   `_effective_source()` las resuelve como Stripe (era el único canal cuando se
   escribieron).

### Campos nuevos en `AccountProfile`

| Campo | Para qué |
|---|---|
| `billing_source` | `""` \| `stripe` \| `apple` \| `google`. `""` = free o exento. |
| `store_product_id` | Equivalente de `stripe_price_id` en las tiendas: codifica plan + periodo. |
| `store_transaction_id` | Id estable de la suscripción. Apple: `original_transaction_id`. Google: purchase token. Indexado porque los webhooks llegan con eso. |

Migración: `core/assistant/migrations/0012_accountprofile_billing_source_and_more.py`
(aditiva, sin backfill — las filas existentes quedan en `""` y `_effective_source()`
las interpreta correctamente).

---

## 3. Cómo entra el dinero de las tiendas

Endpoint: `POST /api/billing/store-webhook/` → `core/billing/store_webhooks.py`.

Se usa **RevenueCat** como intermediario. La alternativa nativa son dos
pipelines distintos: App Store Server Notifications v2 (JWS que hay que
verificar contra la cadena de certificados de Apple) y Google Play RTDN
(publicación en un tópico de Pub/Sub propio). Ambos hay que construirlos,
monitorearlos y mantenerlos por separado. RevenueCat los normaliza en un solo
JSON y una sola entrega, a cambio de ~1% del ingreso después del tramo gratuito.
Si algún día el 1% pesa más que el mantenimiento, migrar significa reescribir
sólo `store_webhooks.py` — `apply_entitlement` no se entera.

**Autenticación:** secreto compartido que RevenueCat repite en el header
`Authorization`, comparado en tiempo constante. `REVENUECAT_WEBHOOK_AUTH` vacío
⇒ el endpoint rechaza todo. Un webhook de cobro abierto es peor que no tenerlo.

**Idempotencia:** tabla `billing.StoreWebhookEvent`, con el id del evento como
llave primaria. No se usa el cache de Django a propósito: es `LocMemCache`, o
sea por proceso, y cada worker de gunicorn tendría su propia idea de qué ya
había visto. La fila marca *procesado*, no *visto*: si el `outcome` quedó vacío o
en `error`, una reentrega vuelve a intentarlo.

**Reconciliación:** esa misma tabla guarda el payload crudo. Cuando alguien diga
"pagué en mi iPhone y la app dice Free", es el único lugar donde sobrevive lo
que la tienda nos dijo y qué decidimos en ese momento.

### La app nunca se auto-otorga el plan

El cliente móvil **no** concede acceso leyendo el recibo local. Compra, y luego
pregunta al backend. La tienda es la autoridad sobre el *pago*; este endpoint es
la autoridad sobre la *titularidad*.

---

## 4. Guardas entre canales

Que existan dos formas de pagar hace real el peor caso: **el mismo usuario
suscrito dos veces**. Se bloquea en los dos sentidos.

**Backend** (`core/billing/services.py`): `_reject_if_store_managed()` corta
`create_checkout_session`, `create_portal_session`, `cancel_subscription`,
`reactivate_subscription`, `downgrade_subscription` y el flujo de retención
cuando `billing_source` es de tienda. Lanza `StoreManagedSubscriptionError`, que
GraphQL expone como código **`SUBSCRIPTION_STORE_MANAGED`** con la fuente.
Deliberadamente distinto de `NO_ACTIVE_SUBSCRIPTION`: el usuario **sí** tiene
suscripción, sólo que no es nuestra para cambiarla.

**Web** (`frontend/src/app/(app)/settings/billing/page.tsx`): si el plan viene de
una tienda, se muestra el estado pero se ocultan el portal, el checkout y los
botones de cancelar/bajar de plan, y aparece "tu suscripción se compró en {store}".

**Móvil** (`mobile/src/app/(dashboard)/(more)/billing.tsx`): "Administrar" lleva
al gestor nativo (`itms-apps://apps.apple.com/account/subscriptions` o la ficha
de Play) en vez de a la web.

**Doble checkout en web (arreglado).** El auto-checkout desde el landing
(`?upgrade=pro&period=monthly`) ahora hace `router.replace("/settings/billing")`
**antes** de irse a Stripe. Sin eso, la entrada quedaba en el historial: al
volver con Atrás después de pagar —cuando el webhook todavía no había promovido
el plan y `plan` seguía leyéndose "free"— el efecto se disparaba otra vez y
creaba una segunda suscripción en paralelo. Dos cobros reales.

**Migrar de Stripe a tienda (pendiente de producto).** Hoy el guard *impide* que
alguien con Stripe compre en la app. Falta decidir el flujo asistido:
cancelar en Stripe, esperar al fin del periodo y comprar en la tienda.

---

## 5. Reporte: bruto y neto

El MRR del admin contaba sólo suscripciones con `stripe_subscription_id`. Con
las tiendas, cada compra móvil habría valido $0 y el ingreso habría *bajado* en
el panel justo cuando el canal nuevo empezara a funcionar.

Ahora `core/admin_api/schema_billing.py`:

- Filtra por "tiene titularidad de pago" (Stripe **o** tienda), no por Stripe.
- Usa los helpers conscientes de la fuente de `core/billing/plans.py`:
  `period_for_profile`, `monthly_cents_for_profile`, `net_monthly_cents_for_profile`.
- Expone `mrrCents`/`arrCents` (**bruto**, lo que se le cobra al usuario) junto a
  `netMrrCents`/`netArrCents` (**neto**, ya sin comisión de tienda ni fee de
  Stripe), más un desglose `bySource`.
- `adminSubscribers` trae `billingSource`, `netMonthlyCents`, `storeProductId` y
  `storeTransactionId`.

Los netos son estimaciones para un tablero, no contabilidad.

---

## 6. Estado de la implementación

### Hecho

| Área | Qué |
|---|---|
| Modelo | `billing_source`, `store_product_id`, `store_transaction_id` + migración |
| Titularidad | `core/billing/entitlements.py` — punto único de escritura, con conflictos, orden y exención |
| Stripe | `sync_subscription_to_profile` ya sólo traduce y delega; guard simétrico en la rama activa |
| Stripe | `api_version` fijada + `period_end_from_subscription()` que lee las dos formas de `current_period_end` |
| Tiendas | `catalog.py` (catálogo, paridad, comisión) y `store_webhooks.py` (webhook, auth, idempotencia) |
| Cross-canal | Guards en las seis operaciones de Stripe + código `SUBSCRIPTION_STORE_MANAGED` |
| Web | `router.replace` contra el doble checkout; estado read-only si la compra es de tienda |
| Móvil | Deep link al gestor nativo; `store_managed` en el snapshot de uso |
| Admin | MRR/ARR bruto y neto, desglose por fuente, columnas de tienda |
| Tests | `core/billing/tests/test_entitlements.py` y `test_store_webhooks.py` (39 tests en billing; 459 en la suite completa) |

### Pendiente

| # | Qué falta | Bloqueado por |
|---|---|---|
| 1 | Firmar el *Paid Applications Agreement*, datos bancarios y fiscales | Trámite (tú) |
| 2 | **Inscribirse al Small Business Program de Apple** — sin esto pagas 30% en vez de 15% | Trámite (tú) |
| 3 | Crear los 4 productos en App Store Connect y Play Console con los importes de §1 | Trámite (tú) |
| 4 | Cuenta de RevenueCat, claves y apuntar su webhook a `/api/billing/store-webhook/` | Trámite (tú) |
| 5 | **Paywall nativo** en `mobile/(more)/billing.tsx`: cards de plan, precios **leídos de la tienda** (no hardcodeados), botón **Restaurar compras** (obligatorio para Apple), enlaces a términos/privacidad y texto de renovación automática | (3) y (4) |
| 6 | Flujo asistido de migración Stripe → tienda | Decisión de producto |
| 7 | Sandbox de ambas tiendas: comprar, renovar, cancelar, reembolsar, restaurar | (3) y (5) |

> El paywall no se codificó a ciegas a propósito: sin productos ni claves no se
> puede ejecutar ni probar, y código de compras sin probar es peor que no
> tenerlo. Todo lo que lo recibe —titularidad, webhook, guards, reporte— ya está
> hecho y probado.

---

## 7. Reglas para quien toque esto después

1. **Nada que venga de un cobro escribe `plan` o `billing_source` fuera de
   `apply_entitlement()`.** Si aparece un canal nuevo, tradúcelo a un
   `Entitlement`; no agregues un segundo escritor. Incluso `downgrade_subscription`,
   que refleja el cambio al instante para que la UI no espere al webhook, pasa
   por ahí.

   Hay exactamente **dos** escrituras legítimas de `plan` fuera de esa capa, y
   ninguna es una compra:
   - `core/assistant/quotas.py::_apply_enrollment_decision` — alta en la cohorte
     beta, que concede Pro por **exención**.
   - `core/admin_api/schema.py` — cambio manual de plan por un admin, auditado.

   Las dos conviven bien con la capa: `apply_entitlement` nunca degrada a una
   cuenta con `is_billing_exempt`.
2. **No traslades la comisión al precio.** La paridad en USD es una decisión de
   producto; `catalog.py` la sostiene por defecto.
3. **No trates "cancelado" como "expirado"** en las tiendas.
4. **No subas `STRIPE_API_VERSION`** sin leer el comentario de
   `core/billing/stripe_client.py`.
5. **La regla 10 de `mobile/AGENTS.md` cambió.** Ya no es "nunca IAP": es
   "billing read-only **hasta** que el paywall nativo del pendiente 5 esté, y a
   partir de ahí StoreKit obligatorio, restaurar compras obligatorio, y nunca
   dirigir al usuario a pagar fuera de la app".
6. **Teams sigue siendo sólo un plan** (`docs/teams/PLAN.md`), sin código. Su
   modelo per-seat con proración no encaja en las tiendas: cuando se implemente,
   debería quedarse en Stripe/web.
7. **Las políticas de App Store y Google Play cambian seguido** —sobre todo lo
   relativo a enlaces de compra externos, que sigue en movimiento tras los
   litigios recientes en EE. UU. Confirma la política vigente antes de cada
   envío a revisión.

---

## 8. Variables de entorno

> Esta sección estaba desactualizada: listaba `STRIPE_*` y `STORE_PRICE_*_AMOUNT_CENTS`,
> que **ya no existen en `settings.py`**. Stripe dejó de ser emisor (sigue siendo el
> procesador de tarjeta bajo Web Billing) y los importes nunca tuvieron el prefijo
> `STORE_`. Ponerlas en Render no configuraba nada y daba la falsa impresión de que sí.
> Lo de abajo sale de leer `continuity/settings.py`, no de memoria.

```bash
# Tiendas (App Store / Google Play vía RevenueCat)
REVENUECAT_WEBHOOK_AUTH=            # secreto compartido; vacío ⇒ rechaza todo
STORE_PRODUCT_PRO_MONTHLY=
STORE_PRODUCT_PRO_ANNUAL=
STORE_PRODUCT_STUDIO_MONTHLY=
STORE_PRODUCT_STUDIO_ANNUAL=

# Precios — UN solo juego para los tres canales. Eso es lo que hace que la
# paridad sea estructural y no una convención que alguien tiene que recordar.
PRICE_PRO_MONTHLY_AMOUNT_CENTS=900
PRICE_PRO_ANNUAL_AMOUNT_CENTS=8400
PRICE_STUDIO_MONTHLY_AMOUNT_CENTS=1900
PRICE_STUDIO_ANNUAL_AMOUNT_CENTS=19000
BILLING_CURRENCY=usd

# Comisiones — sólo para estimar el neto en el panel de admin.
STORE_COMMISSION_RATE=0.15          # 0.30 mientras NO estés en el Small Business
                                    # Program de Apple: inscribirse es obligatorio,
                                    # no es automático como en Google Play.
CARD_FEE_PERCENT=0.029
CARD_FEE_FIXED_CENTS=30
REVENUECAT_FEE_PERCENT=0.01

# Sandbox y producción llegan al MISMO endpoint. Este flag es lo único que
# impide que una compra de prueba mueva el plan de alguien de verdad.
BILLING_TEST_MODE=False             # True sólo en local/staging
```

---

## 9. Mapa de archivos

| Archivo | Rol |
|---|---|
| `core/billing/entitlements.py` | **Punto único de escritura.** Conflictos, orden, exención |
| `core/billing/services.py` | Operaciones de Stripe + guards cross-canal |
| `core/billing/webhooks.py` | Webhook de Stripe |
| `core/billing/store_webhooks.py` | Webhook de tiendas (RevenueCat) |
|  `core/billing/catalog.py` | Catálogo de tienda, paridad de precios, comisión |
| `core/billing/plans.py` | Catálogo de Stripe + helpers por fuente |
| `core/billing/stripe_client.py` | SDK, `api_version` fijada, lectura de periodo |
| `core/billing/models.py` | `StoreWebhookEvent` |
| `core/assistant/models.py` | `AccountProfile`, `BillingSource`, `STORE_SOURCES` |
| `core/assistant/views.py` | `/usage/` expone `billing_source` y `store_managed` |
| `core/admin_api/schema_billing.py` | MRR bruto/neto y suscriptores por fuente |
| `frontend/src/app/(app)/settings/billing/page.tsx` | Página de billing web |
| `frontend/src/lib/billingErrors.ts` | Códigos de error → texto localizado |
| `mobile/src/app/(dashboard)/(more)/billing.tsx` | Pantalla de billing móvil |
