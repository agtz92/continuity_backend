# Plan — unificar los tres canales de cobro en RevenueCat

> **Fuente de verdad del dominio:** [`../integracion-pagos-web-y-movil.md`](../integracion-pagos-web-y-movil.md).
> Este documento es el **plan de ejecución** de la migración; aquél describe el
> modelo. Al terminar cada fase, actualiza aquél y marca aquí.

Handoff para el agente que implemente. Fecha objetivo: **miércoles 12 de agosto de 2026**.
Escrito el 5 de agosto.

---

## 0. Qué cambió y por qué (contexto obligatorio)

La primera integración dejó **Stripe directo en web** y añadió App Store / Google
Play vía RevenueCat. Eso ya está construido y probado (459 tests en verde).

El 5 de agosto se decidió **mover también la web a RevenueCat Web Billing**, con
lo que los tres canales pasan por un solo proveedor. Razones, para que no se
re-litigue:

- **No hay suscriptores vivos.** Migrar cuesta cero hoy y deja de ser gratis en
  cuanto haya gente pagando. Es el único momento barato.
- **No se pierde funcionalidad.** RevenueCat Web Billing tiene discounts con
  duración configurable (los cupones de retención), customer portal sin código,
  introductory offers (el trial de 14 días) y una encuesta de cancelación con
  oferta cuyo default ya dispara en "too expensive" y "don't use the app" — el
  mismo mapeo por motivo que hoy está hecho a mano.
- **El costo no fue el criterio.** RevenueCat elimina el 0.7% de Stripe Billing y
  cobra 0% hasta $2,500 MTR y 1% después; el fee de tarjeta se paga igual porque
  Stripe sigue siendo la pasarela por debajo. La diferencia real ronda los $7
  USD/mes en el punto de cruce.
- **El criterio fue la simplicidad:** un dashboard, un webhook, y menos código
  propio que mantener.

**Riesgo aceptado explícitamente:** RevenueCat queda como punto único de falla
para el 100% del ingreso. Por eso las pruebas end-to-end no son trámite.

**Lo que NO cambia:** los precios ($9 / $84 / $19 / $190 USD, idénticos en los
tres canales), la capa de titularidad `core/billing/entitlements.py`, y la regla
de que nada que venga de un cobro escribe `plan` fuera de `apply_entitlement()`.

---

## 1. Antes de escribir código — tres cosas que hay que verificar

> **Alta de la cuenta:** [`SETUP-REVENUECAT.md`](SETUP-REVENUECAT.md) — qué crear
> en el dashboard y qué variables poner en Render. Las tres incógnitas de abajo
> no se pueden resolver hasta tener eso arriba.

No las adivines. Cada una cambia el código y ninguna está confirmada:

1. ~~**El valor exacto de `store` que RevenueCat manda para Web Billing.**~~
   ✅ **Resuelto (7 sep) por documentación, no por compra.** Es **`RC_BILLING`**.
   El `WEB_BILLING` que aceptábamos en paralelo **no existe**; era una
   invención defensiva y se quitó. El conjunto documentado completo es
   `AMAZON`, `APP_STORE`, `MAC_APP_STORE`, `PADDLE`, `PLAY_STORE`,
   `PROMOTIONAL`, `RC_BILLING`, `ROKU`, `STRIPE`, `TEST_STORE`; mapeamos
   cuatro y el resto cae como `unusable` a propósito (ver el comentario de
   `_STORE_TO_SOURCE`). Cubierto por `TestStoreMapping`.
2. **Si los eventos de Web Billing traen `expiration_at_ms`** como los de tienda,
   o usan otro campo para el fin de periodo. **Parcialmente resuelto:** el campo
   es parte del esquema común y vino presente en el evento de prueba de
   RevenueCat; falta verlo en un evento `RC_BILLING` real. El código ya lo lee,
   así que no hay nada que cambiar salvo que aparezca vacío.
3. **Cómo se obtiene el enlace al customer portal**: si lo genera el SDK web en
   cliente o hace falta una llamada de servidor. De esto depende si sobrevive
   alguna mutation de GraphQL o si se van todas.

Si algo sigue sin confirmarse, **implementa el resto y deja el hueco marcado con
`TODO(verificar)`** en vez de inventar el contrato.

---

## 2. Fase A — Backend (empezar por aquí)

### A1. Nueva fuente `web` — ✅ HECHO (5 ago)

> **Desviación respecto a lo escrito abajo:** `BillingSource.STRIPE` **no** se
> borró. Quitarlo arrastra media fase A5 (webhook de Stripe, `services.py`,
> `stripe_client.py`) dentro de este paso y convierte un refactor revisable en
> un cambio grande. Quedó marcado como deprecado en el enum, sin nadie que lo
> escriba, y **se borra en A5**. Como no hay ninguna fila con esa fuente, no
> cuesta nada.
>
> Se añadió además `EXTERNALLY_MANAGED_SOURCES` como estaba previsto.


`core/assistant/models.py`:

```python
class BillingSource(models.TextChoices):
    WEB = "web", "Web (RevenueCat Web Billing)"
    APPLE = "apple", "App Store"
    GOOGLE = "google", "Google Play"
```

`STRIPE` desaparece como fuente: Stripe deja de ser un emisor de titularidad y
pasa a ser sólo el procesador de tarjeta debajo de Web Billing.

Los conjuntos de `models.py` se redefinen:

- `STORE_SOURCES = {APPLE, GOOGLE}` — se queda igual. Sigue siendo la distinción
  útil: son los que se gestionan en la app nativa de la tienda.
- **Nuevo** `EXTERNALLY_MANAGED_SOURCES = {WEB, APPLE, GOOGLE}` — es decir,
  todas. Ya no tenemos portal propio para ninguna; web se gestiona en el customer
  portal de RevenueCat. Esto es lo que sustituye a `_reject_if_store_managed`.

### A2. Consolidar las columnas de billing — ✅ HECHO (5 ago)

> **Precondición verificada contra la base real** (Supabase, sólo lectura):
> 19 perfiles, **0 con suscripción**, 0 con price id, 0 de pago no exentos, 16
> exentos. Los 2 `stripe_customer_id` que había eran clientes creados sin
> llegar a suscribirse; se descartan con el rename sin consecuencia.
> Migración: `0013_remove_accountprofile_store_product_id_and_more`.
>
> **Radio real del cambio, más amplio de lo que decía este plan:** al colapsar
> las columnas también hubo que renombrar los campos GraphQL del admin
> (`stripeCustomerId`/`stripeSubscriptionId` → `billingCustomerId`/
> `billingTransactionId`) y sus consumidores en el frontend. Dejarlos habría
> significado un campo llamado `stripeSubscriptionId` devolviendo un purchase
> token de Play. De paso, el deep link al dashboard de Stripe se volvió
> condicional a la fuente (`customerUrl` en `admin/billing/page.tsx`): para una
> compra de tienda ese enlace siempre daba 404.
>
> **`_effective_source()` se borró** y `_has_live_entitlement()` pasó a
> apoyarse en `billing_transaction_id` en vez de en la fuente — falla del lado
> seguro: lo peor de una fuente en blanco es un conflicto que se registra,
> mientras que lo peor de "no hay nada que cuidar" es degradar a quien paga.
> Eso hizo fallar 3 tests cuyos fixtures traían transaction id **sin declarar
> fuente**; se corrigieron los fixtures, no la lógica.


Con cero filas de pago, es el momento de quitar el prefijo `stripe_`, que ya
miente. En `AccountProfile`:

| Quitar | Poner |
|---|---|
| `stripe_customer_id` | `billing_customer_id` |
| `stripe_subscription_id` | `billing_transaction_id` |
| `stripe_price_id` | `billing_product_id` |
| `store_transaction_id` | *(se funde en `billing_transaction_id`)* |
| `store_product_id` | *(se funde en `billing_product_id`)* |

Queda: `billing_source` + `billing_customer_id` + `billing_product_id` +
`billing_transaction_id`. Eso simplifica `entitlements.py` de forma importante:
`_external_id_for()` deja de necesitar el `if` por fuente y se vuelve un campo.

**Antes de hacerlo, confirma que la tabla no tiene filas con datos de pago**
(`AccountProfile.objects.exclude(stripe_subscription_id="").count()`). Si las
hay, para y pregunta — el plan asume cero.

`_effective_source()` (el que resuelve filas legacy como Stripe) se puede borrar:
sin filas legacy no tiene sentido. **Sus tests sí se adaptan, no se borran** —
el caso "una fuente no pisa la titularidad de otra" sigue siendo el corazón.

### A3 + A5 — ✅ HECHO (5 ago, juntas)

> Se hicieron **en un solo paso** porque, confirmada la decisión de no usar
> Stripe en absoluto, separarlas no tenía sentido: las funciones que A3 iba a
> conservar de `plans.py` sólo las usaba el camino de Stripe que A5 borra.
>
> **Borrado:** `webhooks.py` (webhook de Stripe), `stripe_client.py`,
> `services.py`, `schema.py` (las 6 mutations), `plans.py`,
> `tests/test_services.py`, la dependencia `stripe` de `requirements.txt`, y
> todos los settings `STRIPE_*`. `BillingSource.STRIPE` también se fue
> (migración `0014`). `BillingMutation` salió del `merge_types` raíz.
>
> **`store_plans.py` → `catalog.py`**, ahora con los helpers por perfil
> (`period_for_profile`, `monthly_cents_for_profile`,
> `net_monthly_cents_for_profile`). El neto del canal web pasó a ser
> `1 − fee de tarjeta − 1% de RevenueCat`; el de tienda sigue siendo la comisión.
>
> **Precios: un solo juego de importes** (`PRICE_*_AMOUNT_CENTS`) para los tres
> canales, con los valores reales por defecto (900 / 8400 / 1900 / 19000). Ya no
> hay herencia entre catálogos: la paridad dejó de depender de dejar una variable
> sin poner y pasó a ser que sólo existe un número.
>
> **`is_stripe_test_mode()` → `BILLING_TEST_MODE`**, un flag explícito. RevenueCat
> entrega sandbox y producción al mismo endpoint, así que no se puede inferir de
> un prefijo de clave como se hacía con Stripe.
>
> Suite: **448 tests** (459 − 12 de `test_services.py` + 1 nuevo del canal web).
>
> ⚠️ **Consecuencia inmediata, sin resolver:** seis archivos del frontend siguen
> llamando mutations que ya no existen —`settings/billing/page.tsx`,
> `onboarding/steps/Step4Plan.tsx`, `RetentionFlow.tsx`,
> `DowngradeConfirmModal.tsx`, `SwitchPeriodModal.tsx` y `lib/graphql/billing.ts`.
> El typecheck no lo detecta (GraphQL falla en runtime). **`/settings/billing` y
> el paso 4 del onboarding están rotos hasta que se haga la fase B.** Es lo
> siguiente que hay que tocar.

### A3. Un solo catálogo *(referencia original)*

`core/billing/plans.py` (mapeo por price id de Stripe) queda muerto. Fusiónalo en
`core/billing/store_plans.py` y renombra el módulo a `core/billing/catalog.py`:

- `plan_for_product` / `period_for_product` — ya existen, sirven tal cual.
- `amount_cents_for_product` — un solo juego de importes para los tres canales,
  que es lo que hace estructural la paridad de precios.
- `net_monthly_cents_for_profile` — recalcula por fuente:
  - `apple` / `google`: gross × (1 − `STORE_COMMISSION_RATE`)
  - `web`: gross × (1 − fee de tarjeta de Stripe) − fijo, **menos** el 1% de
    RevenueCat cuando aplique. Nuevo setting `REVENUECAT_FEE_PERCENT` (default
    0.01), y documenta que es 0 por debajo de $2,500 MTR — el dashboard puede
    sobreestimar el costo en cuentas chicas y eso está bien.

Conserva `monthly_cents_for_profile` y `period_for_profile` con el mismo nombre:
`core/admin_api/schema_billing.py` ya los usa y no debería enterarse del cambio.

### A4. Webhook

`core/billing/store_webhooks.py` es el único receptor. Cambios:

- Añadir el valor de web al mapeo de `store` (ver §1.1).
- El endpoint se llama `/api/billing/store-webhook/`. **Renómbralo a
  `/api/billing/revenuecat/`** — ya no son sólo tiendas. Deja la ruta vieja
  respondiendo también, para no romper el webhook si ya quedó configurado en el
  dashboard antes del cambio.
- Renombra el modelo `StoreWebhookEvent` → `BillingWebhookEvent` con su migración.
- Lo demás no se toca: la idempotencia por llave primaria, el reintento de filas
  con `outcome` vacío o `error`, y la clasificación de eventos ya sirven para web.

Ojo con la regla de orden en `entitlements.py::_grant`: hoy el guard de "evento
fuera de orden no acorta el acceso" aplica **sólo a tiendas**, porque en Stripe un
cambio de anual a mensual sí mueve la fecha hacia atrás. Con Web Billing hay que
volver a preguntarse si web se comporta como tienda. **Por defecto, deja web fuera
del guard** (comportamiento actual para no-tiendas) y anótalo.

### A5. Borrar el camino de Stripe directo

Se van completos:

- `core/billing/services.py`: `create_checkout_session`, `create_portal_session`,
  `apply_retention_coupon`, `cancel_subscription`, `reactivate_subscription`,
  `downgrade_subscription`, `coupon_for_reason`, `_ensure_customer`,
  `_normalize_locale`, `_REASON_TO_COUPON_ENV`, `sync_subscription_to_profile`.
  El módulo queda casi vacío; si no sobrevive nada, bórralo.
- `core/billing/webhooks.py` (webhook de Stripe) y su ruta.
- `core/billing/stripe_client.py`.
- `core/billing/schema.py`: las seis mutations. Si la §1.3 confirma que el portal
  necesita servidor, deja **una** mutation que devuelva esa URL y nada más.
- `core/billing/tests/test_services.py`.
- Settings: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_*`,
  `STRIPE_COUPON_*`, `STRIPE_API_VERSION`. **Conserva** `STRIPE_FEE_PERCENT` y
  `STRIPE_FEE_FIXED_CENTS`: el fee de tarjeta se sigue pagando y se sigue usando
  para el neto.
- La dependencia `stripe` de `requirements.txt`.

> Esto borra código probado. Es intencional y está decidido. Lo que **no** se
> puede perder es la cobertura de `test_entitlements.py` y
> `test_store_webhooks.py`: adáptalos, no los borres.

### A6. Contrato con los clientes

`core/assistant/views.py`, endpoint `/usage/`:

- `store_managed` (bool) → **`externally_managed`** (bool), verdadero para las
  tres fuentes. Es un cambio incompatible: hay que tocar los dos clientes en la
  misma tanda (`frontend/src/lib/assistantApi.ts`, `mobile/src/lib/assistantApi.ts`).
- `billing_source` se queda, ahora con valor `web` en lugar de `stripe`.
- Añade `manage_url`: a dónde mandar a esta persona a gestionar su plan —
  customer portal de RevenueCat para `web`, deep link nativo para las tiendas.
  Que lo resuelva el servidor evita duplicar la lógica en dos clientes.

### A7. Verificación de la fase

```bash
../.venv/bin/python -m pytest -q
../.venv/bin/python manage.py makemigrations --check --dry-run
```

Ambos deben salir limpios. La suite completa iba en **459 tests** antes de esta
migración; espera que baje al borrar `test_services.py` y que suba al añadir los
casos de `web`. Si baja sin que subas nada, falta cobertura.

Grep de control — no debe quedar ningún escritor de `plan` fuera de la capa:

```bash
grep -rn "\.plan = " core/ --include="*.py" | grep -v tests | grep -v migrations
```

Sólo pueden aparecer: `entitlements.py` (dos), `assistant/quotas.py` (alta beta) y
`admin_api/schema.py` (cambio manual auditado).

---

## 3. Fase B — Web

- Reemplazar `frontend/src/app/(app)/settings/billing/page.tsx` por el SDK web de
  RevenueCat. La página deja de vender: muestra el plan y manda al customer portal.
- Borrar `RetentionFlow.tsx`, `DowngradeConfirmModal.tsx`, `SwitchPeriodModal.tsx`
  y `src/lib/graphql/billing.ts`. Esa funcionalidad pasa al portal de RevenueCat.
- `billingErrors.ts`: se van los códigos de las mutations borradas.
- i18n: limpiar `settings.billing.*` y `errors.*` de las llaves huérfanas en
  **es y en**. No dejes llaves muertas.

Verificación: `/opt/homebrew/bin/node node_modules/typescript/bin/tsc --noEmit` y
la suite de vitest. **Nota:** `src/components/today/todaySections.test.tsx` ya
fallaba antes de esta migración (le falta un `ApolloProvider` en su setup) y no
tiene relación con billing. No lo cuentes como regresión tuya, pero tampoco lo
uses como excusa si el número de fallos sube.

---

## 4. Fase C — Móvil

Bloqueada hasta tener las API keys de RevenueCat.

- Instalar `react-native-purchases` con `npx expo install` y generar un
  development build (no corre en Expo Go).
- Paywall en `mobile/src/app/(dashboard)/(more)/billing.tsx`: cards de plan,
  **precios leídos de la tienda** (nunca hardcodeados, o la moneda local sale
  mal), **botón de restaurar compras** (obligatorio para Apple), enlaces a
  términos y privacidad junto a la compra, y texto de renovación automática.
- La app **no** se auto-otorga el plan leyendo el recibo local: compra y luego
  pregunta al backend.
- Reescribir la **regla 10** de `mobile/AGENTS.md` en el mismo commit, quitando el
  "hasta que el paywall exista".

Verificación, **en este orden** (regla del repo): `npx expo export -p ios --clear`
y luego `npx tsc --noEmit`. Ambos exit 0.

---

## 5. Fase D — Cerrar la documentación

- Actualizar `../integracion-pagos-web-y-movil.md`: §2 (las fuentes ahora son
  web/apple/google), §3 (un solo webhook), §4 (los guards cambian de sentido:
  ya no hay canal propio que proteger), §5 (neto con el fee de RevenueCat), §6
  (estado real), §8 (env vars) y §9 (mapa de archivos).
- Las referencias cruzadas de los 16 documentos ya apuntan ahí y no hay que
  volver a tocarlas.

---

## 6. Orden sugerido

A1 → A2 → A3 → A4 → A5 → A6, corriendo la suite entre cada paso. A2 es el más
invasivo (toca modelo, migración y `entitlements.py`); si algo se va a torcer, se
tuerce ahí, y conviene que la suite esté verde antes de entrar.

B y C son independientes entre sí una vez que A6 fijó el contrato de `/usage/`.

---

## 7. Lo que no está decidido

- **Si el paywall móvil le vende a quien ya tiene entitlement web.** Con todo en
  RevenueCat el sistema lo sabe; es decisión de producto, pendiente del dueño.
- **Migración asistida entre canales.** No se construye hasta que alguien la pida.
- **Precios locales por moneda.** La paridad garantizada es en USD; Apple y Google
  convierten con su propia matriz. Nadie ha decidido igualar MXN o EUR a mano.
