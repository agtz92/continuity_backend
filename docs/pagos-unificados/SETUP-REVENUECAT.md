# Configurar RevenueCat — checklist de alta

> **Plan de ejecución:** [`PLAN.md`](PLAN.md) · **Modelo del dominio:**
> [`../integracion-pagos-web-y-movil.md`](../integracion-pagos-web-y-movil.md)
> (ojo: su §8 quedó desactualizada, la Fase D la corrige; la lista buena de
> variables es la de este documento, sacada de `continuity/settings.py`).

Qué hay que dejar creado en RevenueCat y en Render **antes** de poder cerrar el
paso A6 y arrancar las fases B (web) y C (móvil). El backend ya está escrito
contra este contrato; esto es configuración, no código.

Escrito el 2 de septiembre de 2026, contra el commit `b62db8b`.

---

## 0. El orden importa

1. Crear cuenta y proyecto.
2. Crear los 4 productos.
3. Crear los entitlements y el offering.
4. **Poner `REVENUECAT_WEBHOOK_AUTH` en Render y esperar el redeploy.**
5. Recién entonces configurar el webhook en RevenueCat.

El paso 4 va antes del 5 a propósito: con la variable vacía el endpoint
responde 401 a todo (es el default deliberado — un webhook de cobros sin
autenticar es peor que no tenerlo). Si configuras el webhook primero, las
primeras entregas rebotan y RevenueCat las reintenta con backoff.

---

## 1. Cuenta y proyecto

- Un solo proyecto para Continuity. Dentro de él conviven las tres *apps*
  (plataformas) que RevenueCat distingue: **App Store**, **Play Store** y
  **Web Billing**.
- Guarda las **API keys públicas** de iOS y Android: las necesita la Fase C
  (`react-native-purchases`). No van al backend — el backend nunca llama a la
  API de RevenueCat, sólo recibe su webhook.

---

## 2. Los 4 productos

Un producto por plan y periodo. **El mismo identificador en los tres canales**
— es lo que hace que `catalog.py` resuelva `product_id → (plan, periodo)` sin
preguntar quién lo vendió.

| Plan | Periodo | Precio USD | Variable de entorno | Identificador sugerido |
|---|---|---:|---|---|
| Pro | mensual | $9 | `STORE_PRODUCT_PRO_MONTHLY` | `it.continuu.pro_monthly` |
| Pro | anual | $84 | `STORE_PRODUCT_PRO_ANNUAL` | `it.continuu.pro_annual` |
| Studio | mensual | $19 | `STORE_PRODUCT_STUDIO_MONTHLY` | `it.continuu.studio_monthly` |
| Studio | anual | $190 | `STORE_PRODUCT_STUDIO_ANNUAL` | `it.continuu.studio_annual` |

Sobre los identificadores: el estilo con prefijo es por Apple, donde los
product ids son únicos dentro de la cuenta y **no se pueden reutilizar aunque
borres el producto** — un `pro_monthly` pelado se quema fácil. El formato exacto
que acepta cada consola confírmalo al crearlos; no lo des por bueno desde aquí.

Los productos hay que crearlos **primero en cada tienda** (App Store Connect y
Play Console) y luego importarlos/declararlos en RevenueCat. Los de Web Billing
se crean en RevenueCat directamente.

> **Los precios no se hardcodean en el móvil.** El paywall los lee de la tienda
> (Fase C), o la moneda local sale mal. Los importes de la tabla viven en el
> backend sólo para estimar ingreso neto en el panel de admin.

---

## 3. Entitlements y offering

**Crea dos entitlements: `pro` y `studio`.** Asocia cada uno a sus dos
productos (mensual y anual).

Detalle que ahorra confusión: **al backend los entitlements le dan igual**.
`store_webhooks.py` sólo mira `product_id` del evento y lo resuelve con
`plan_for_product()`; nunca lee identificadores de entitlement. Hacen falta
para el SDK del móvil y para el paywall, no para el webhook.

Por eso mismo hacen falta **dos** y no uno: un único entitlement no distinguiría
Pro de Studio en la app.

**Offering:** uno (`default`) con los 4 packages. Lo consume el paywall de la
Fase C.

---

## 4. Webhook

**URL:** `https://continuity-backend.onrender.com/api/billing/revenuecat/`

(La ruta vieja `/api/billing/store-webhook/` sigue respondiendo lo mismo, por
compatibilidad. Para una configuración nueva usa la de arriba.)

**Authorization header:** aquí está la trampa. RevenueCat manda **verbatim** lo
que escribas en ese campo, y el backend compara la cadena completa con
`hmac.compare_digest`. Así que si en el dashboard pones:

```
Bearer un-secreto-largo-y-aleatorio
```

entonces `REVENUECAT_WEBHOOK_AUTH` en Render tiene que valer **exactamente**
`Bearer un-secreto-largo-y-aleatorio`, con el `Bearer ` incluido. Cualquier
diferencia = 401 en todas las entregas.

Genera el secreto con algo como:

```bash
python3 -c "import secrets; print('Bearer ' + secrets.token_urlsafe(32))"
```

**Eventos:** manda todos. El endpoint ya clasifica y responde 200 a los que
decide ignorar (un no-200 provoca reintento, y reintentar algo que elegimos no
aplicar sólo genera ruido). El mapeo que ya está implementado:

| Trato | Eventos |
|---|---|
| Da/mantiene acceso | `INITIAL_PURCHASE`, `RENEWAL`, `PRODUCT_CHANGE`, `UNCANCELLATION`, `SUBSCRIPTION_EXTENDED`, `BILLING_ISSUE`, `NON_RENEWING_PURCHASE` |
| Revoca | `EXPIRATION`, `REFUND`, `SUBSCRIPTION_PAUSED` |
| Registra sin actuar | `TEST`, `TRANSFER`, `INVOICE_ISSUANCE`, `TEMPORARY_ENTITLEMENT_GRANT` |

Dos decisiones que conviene conocer antes de que te sorprendan:

- **`CANCELLATION` no corta el acceso.** Significa "se apagó la renovación
  automática"; la persona conserva lo que pagó hasta que expire. Sólo revoca si
  el `cancel_reason` es un reembolso (`CUSTOMER_SUPPORT`, `REFUND`,
  `DEVELOPER_INITIATED`).
- **`BILLING_ISSUE` mantiene el acceso.** La tienda está reintentando el cobro;
  quitar el plan ahí castiga a quien se le venció la tarjeta.
- **`TRANSFER` no se automatiza.** Mueve una titularidad entre cuentas y
  necesita decisión humana. Queda registrado en la tabla y ya.

---

## 5. `app_user_id` — lo que más fácil se rompe

RevenueCat identifica a la persona con `app_user_id`, y el backend espera que
**sea el UUID del usuario de Supabase** (`AccountProfile.user_id`). O sea que la
app tiene que llamar a `Purchases.logIn(<uuid de supabase>)` al iniciar sesión.

Si no, la compra llega con un `$RCAnonymousID:…`, `_parse_user_id()` devuelve
`None` y la compra **no se puede atribuir** hasta que la app haga `logIn` y
RevenueCat mande un `TRANSFER` — que, como está arriba, no se automatiza.

Es trabajo de la Fase C, pero anótalo ahora porque es el error clásico y sólo
se ve cuando alguien ya pagó.

---

## 5b. La llave pública web (frontend)

La web vende con `@revenuecat/purchases-js`, así que necesita la **public API
key** de la app de Billing: RevenueCat → **Web** → tu proveedor → *App info* →
*Public API Key* (el ojito la revela).

Va en el entorno del frontend (Vercel y `.env` local):

```bash
NEXT_PUBLIC_REVENUECAT_WEB_KEY=rcb_...
```

Es publishable — va al navegador a propósito, como la anon key de Supabase.

**Sin ella la web no puede vender.** La página de billing sigue mostrando plan
y consumo, pero no ofrece comprar: es preferible no enseñar un botón a
enseñar uno que truena al hacer clic.

---

## 6. Variables en Render

Servicio `continuity-backend`. Sólo la primera es obligatoria de verdad; las
demás ya traen el valor correcto por default y las listo para que sepas que
existen y qué mueven.

**Hay que ponerlas:**

```bash
REVENUECAT_WEBHOOK_AUTH=Bearer …          # exactamente igual que en el dashboard
STORE_PRODUCT_PRO_MONTHLY=it.continuu.pro_monthly
STORE_PRODUCT_PRO_ANNUAL=it.continuu.pro_annual
STORE_PRODUCT_STUDIO_MONTHLY=it.continuu.studio_monthly
STORE_PRODUCT_STUDIO_ANNUAL=it.continuu.studio_annual
```

Sin los `STORE_PRODUCT_*`, una compra activa de un producto que no reconocemos
se **rechaza a propósito** (queda logueada como error y `outcome="unusable"`):
otorgar un plan por default ahí dejaría que un producto mal configurado
regalara Studio.

**Sobre `BILLING_TEST_MODE` — déjala apagada en Render:**

RevenueCat entrega sandbox y producción **al mismo endpoint**, así que esta
bandera es lo único que los separa. Apagada (producción), un evento con
`environment: SANDBOX` se **registra pero no se aplica**: queda con
`outcome="sandbox_ignored"` y no mueve el plan de nadie. Encendida
(local/staging), se procesa normal.

Por eso puedes hacer la compra de prueba contra producción sin ensuciar
datos: el payload se guarda igual —que es lo que necesitas para leer los
campos de la §7— pero tu cuenta no se promueve a Studio.

La bandera también pinta la insignia "sandbox" en el panel de admin.

**Ya tienen el default correcto — tócalas sólo si cambia el negocio:**

| Variable | Default | Qué mueve |
|---|---:|---|
| `PRICE_PRO_MONTHLY_AMOUNT_CENTS` | `900` | Estimación de ingreso en admin |
| `PRICE_PRO_ANNUAL_AMOUNT_CENTS` | `8400` | ” |
| `PRICE_STUDIO_MONTHLY_AMOUNT_CENTS` | `1900` | ” |
| `PRICE_STUDIO_ANNUAL_AMOUNT_CENTS` | `19000` | ” |
| `BILLING_CURRENCY` | `usd` | Moneda de referencia |
| `STORE_COMMISSION_RATE` | `0.15` | Comisión de tienda. Subir a `0.30` al pasar $1M/año |
| `CARD_FEE_PERCENT` | `0.029` | Fee de tarjeta del canal web |
| `CARD_FEE_FIXED_CENTS` | `30` | ” (por cargo; el anual lo amortiza a 12 meses) |
| `REVENUECAT_FEE_PERCENT` | `0.01` | Corte de RevenueCat |

El 15% de `STORE_COMMISSION_RATE` asume estar en el **Small Business Program de
Apple, que hay que solicitar** — Google Play lo aplica solo. Si no te inscribes,
el número real es 30% y el panel te va a mentir a favor.

---

## 7. Las tres incógnitas que hay que resolver con la cuenta ya creada

Son las de [`PLAN.md` §1](PLAN.md). Ninguna se puede adivinar y las tres cambian
código:

1. ~~**Qué manda RevenueCat en el campo `store` para Web Billing.**~~
   ✅ **Resuelto: es `RC_BILLING`**, confirmado en la documentación de webhooks.
   Ya está fijo en `catalog.py::_STORE_TO_SOURCE`, sin `TODO`.
2. **Si los eventos de Web Billing traen `expiration_at_ms`** como los de
   tienda. De ese campo sale `period_end`, que alimenta `plan_renews_at` y la
   resolución de conflictos entre canales. Si viene con otro nombre, la fecha de
   renovación queda en `None` en silencio.
3. **Cómo se obtiene el enlace al customer portal**: si lo genera el SDK web en
   cliente o hace falta una llamada de servidor. Esto decide si sobrevive **una**
   mutation de GraphQL o se van todas — o sea, decide parte del diseño de la
   Fase B.

**Ojo con el evento de prueba del dashboard:** el botón *Send test webhook*
manda un fixture enlatado con `"store": "PLAY_STORE"` y
`"product_id": "test_product"`, sea cual sea tu configuración. Sirve para
comprobar la autenticación (un 200 significa que el secreto coincide), **no**
para conocer la forma de los eventos de un canal.

Para leer el payload de la nº2 sin adivinar:

```sql
select event_type, source, product_id, outcome, payload
from billing_storewebhookevent
order by received_at desc limit 5;
```

---

## 7b. Lo que RevenueCat controla y tú no

Descubierto el 8 de septiembre de 2026, probando el primer cobro.

**Los métodos de pago no son tuyos.** Stripe muestra la configuración que usa
Web Billing en solo lectura: *"RevenueCat is managing payment methods for you.
RevenueCat has not enabled you to manage payment methods from the dashboard."*
Ni desde Stripe ni desde el panel de RevenueCat puedes tocar qué redes de
tarjeta se aceptan.

Consecuencia concreta: **American Express queda rechazada** ("This card type
isn't accepted") y habilitarla es un ticket con su soporte, no un cambio tuyo.
En México eso no es marginal.

Vale la pena nombrarlo porque es la primera materialización del riesgo que el
plan aceptó de forma explícita —RevenueCat como punto único de falla del 100%
del ingreso—. No invalida la decisión; sí es un costo que no estaba anotado.

**Cuidado al buscar dónde arreglarlo:** en Stripe → Settings → Payments →
Payment methods aparecen cuatro configuraciones. La primera es tuya y **no es
la que usa el checkout**; las tres creadas el día que conectaste Stripe son de
la cuenta de RevenueCat. Editar la tuya no cambia nada.

---

## 8. Lo que **no** hay que configurar

- **Ninguna integración de Stripe.** Stripe sigue siendo la pasarela de tarjeta
  por debajo de Web Billing, pero eso lo maneja RevenueCat. Nosotros ya no
  tenemos integración propia: el paquete salió de `requirements.txt` y las
  llaves `STRIPE_*` salieron de `settings.py`. Si quedan en Render, bórralas —
  no las lee nadie.
- **Cupones de retención.** Los descuentos con duración configurable son de
  RevenueCat ahora; la encuesta de cancelación con oferta también. Por eso la
  Fase B borra `RetentionFlow.tsx` (421 líneas).

---

## 9. Cuando termines, qué se desbloquea

- **A6** — el contrato de `/usage/`: `store_managed` → `externally_managed`
  (verdadero para los tres canales) y un `manage_url` resuelto en el servidor.
  Es incompatible: hay que tocar web y móvil en la misma tanda. Hasta que esto
  no esté, un suscriptor web ve una página que le ofrece un checkout borrado.
- **Fase B** — ✅ hecha. La web vende con el Web SDK y el portal sale del
  `managementURL` del `CustomerInfo`. Sólo falta poner la llave de §5b.
- **Fase C** — el paywall nativo, que además necesita las API keys públicas.
