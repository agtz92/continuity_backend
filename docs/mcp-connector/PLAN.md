# Plan: Conector MCP remoto de Continuity para Claude

> **⚑ ESTADO (actualizado 2026-06-26): BACKEND CONSTRUIDO Y EN VIVO, FALTA EL LANZAMIENTO EN UI.**
> El servidor MCP está implementado, desplegado y testeado: ruta `/mcp/` (`continuity/urls.py`),
> OAuth 2.1 completo (`core/mcp/oauth/`), adaptador/policy/authz/jsonrpc (`core/mcp/`), y
> write-tools gateadas por plan (`core/mcp/policy.py`: pro/studio con `writes: True`). Lo que
> resta es de **producto, no de ingeniería**: la pantalla de ajustes del conector todavía se
> muestra como *"Coming soon"* (i18n `settings…claude.statusComingSoon`) a la espera del switch
> de lanzamiento, más límites por-plan del canal y observabilidad. Las fases ✅ abajo reflejan
> esto. Decisiones tomadas: conector **MCP remoto**, **multi-tenant** (cualquier usuario de
> Continuity conecta su cuenta desde Claude).

## 1. Qué vamos a construir

Un **servidor MCP remoto** (HTTP) montado en el backend Django que expone las tools de
Continuity (proyectos, tareas, ideas, notas, analytics, búsqueda) a
**Claude.ai / Claude Desktop / Claude Code**. Cualquier usuario podrá ir a
*Settings → Connectors* en Claude, pegar la URL del conector, autenticarse con su cuenta de
Continuity (login Supabase existente), y a partir de ahí Claude puede leer y actuar sobre
**sus** datos.

```
Claude.ai ──OAuth──▶ Continuity (login Supabase existente)
   │                        │  emite access token (sub = uuid Supabase)
   └──MCP/HTTP + Bearer──▶ /mcp/  ──▶ tools._REGISTRY.call(name, user_id, args, plan)
                                            └──▶ core/services/*  (misma lógica que GraphQL y el asistente in-app)
```

## 2. Modelo de costos — IMPORTANTE

Los dos canales de IA tienen modelos de costo **opuestos**:

| Canal | Quién llama a Anthropic | Quién paga los tokens |
|---|---|---|
| Asistente in-app (`core/assistant`, usa `ANTHROPIC_API_KEY`) | **Nuestro backend** | **Nosotros** |
| **Conector MCP (este plan)** | **Claude**, con la suscripción/API del usuario | **El usuario** |

**El conector MCP NO genera cargos de Anthropic para nosotros.** La inferencia del modelo
corre del lado de Claude. Nuestro servidor solo recibe JSON-RPC (`tools/list`, `tools/call`)
y responde con datos de la DB. El token OAuth que emitimos es para acceder a **nuestra API**,
no es un token de Anthropic ni consume nada de Anthropic.

Por lo tanto, las **cuotas / rate-limit del conector NO protegen una factura de IA**, sino
**nuestra infraestructura**:

- **Render (compute):** cada `tools/call` es un request a Django.
- **Supabase/Postgres:** cada tool pega a la DB (lecturas; y escrituras en write tools).
- **Egress / ancho de banda.**

El vector de abuso es un loop automatizado martillando `tools/call` y cargando Postgres —
no quema de créditos de IA. Mitigación barata: reusar `is_ratelimited` (ya existe en
`core/auth.py`) + límites por plan. Es protección de infra, no de IA.

## 3. Por qué encaja casi perfecto con lo que ya tienes

`core/assistant/tools/` ya es, en la práctica, un servidor MCP sin el transporte:

| Lo que pide MCP | Lo que ya existe | Archivo |
|---|---|---|
| `tools/list` (schemas JSON) | `schemas_for_anthropic(plan)` | `core/assistant/tools/__init__.py` |
| `tools/call` (dispatch + scoping + truncado + manejo de errores) | `call(name, user_id, args, plan)` | mismo |
| Gating por tier | `plan_required` + `_plan_allows` | mismo |
| Lógica de negocio | `core/services/*` | reusada por GraphQL y asistente |
| Identidad del usuario | `verify_supabase_jwt` → `sub` UUID | `core/auth.py` |

El trabajo nuevo es **transporte MCP + OAuth**, no re-implementar tools. **Cero cambios en
`core/services/*`.**

## 4. Arquitectura — dos piezas

### 4.1 Transporte MCP (`/mcp/`) — WSGI-nativo, hand-rolled

**Decisión (resuelto el riesgo ASGI):** producción corre **WSGI** (`gunicorn
continuity.wsgi`) con workers **gthread**, elegidos precisamente porque el asistente **ya hace
streaming SSE bajo WSGI** (ver comentario en `render.yaml`). El transporte MCP "Streamable
HTTP" es **JSON-RPC 2.0 sobre POST + respuestas SSE** — exactamente lo que ya servimos hoy.

Por eso **no** migramos a ASGI/uvicorn ni usamos FastMCP. Implementamos `/mcp/` como una
**Django view hand-rolled** que maneja los métodos JSON-RPC del protocolo (`initialize`,
`tools/list`, `tools/call`, `ping`/`notifications`), reusando:
- `authenticate_request` (auth + rate-limit) de `core/auth.py`,
- `schemas_for_anthropic(plan)` para `tools/list`,
- `call(name, user_id, args, plan)` para `tools/call`,
- el mismo patrón SSE del asistente para respuestas en streaming.

El `user_id` sale del token validado por request. Un adaptador delgado traduce cada `Tool` del
`_REGISTRY` al formato de tool MCP (incluye `annotations`).

> Alternativa descartada para v1: **FastMCP como servicio ASGI separado** (uvicorn). Más
> cómodo si se quisieran features avanzados del SDK, pero exige un proceso/servicio nuevo en
> Render. Para exponer las tools existentes, hand-rolled es más simple y no toca el deploy.

Anotaciones MCP por tool (las consume Claude para human-in-the-loop):
- read tools → `readOnlyHint: true`
- write additive → sin hint especial
- write modifying/destructive → `destructiveHint: true` → Claude pide confirmación del lado
  del cliente, lo que evita reimplementar el flujo `PendingToolCall` de la Fase 2 del
  asistente para este canal.

### 4.2 OAuth 2.1 multi-tenant (el reto real)
Claude.ai exige metadata de descubrimiento + **Dynamic Client Registration**. Supabase **no**
lo ofrece. Solución: un mini servidor de autorización en Django que **delega el login al
frontend Supabase existente** y emite sus propios tokens.

Endpoints (estándar, acotados):
- `GET /.well-known/oauth-protected-resource` (RFC 9728) — apunta al authorization server.
- `GET /.well-known/oauth-authorization-server` (RFC 8414) — metadata.
- `POST /oauth/register` (RFC 7591 DCR) — Claude se auto-registra como cliente.
- `GET /oauth/authorize` — PKCE. Si no hay sesión, redirige al login del frontend
  (`continuu.it/login?next=...`); al volver autenticado (sesión Supabase), genera
  `authorization_code`.
- `POST /oauth/token` — canjea code→access token (+ refresh).

**Decisión de token:** el access token emitido es un JWT propio con `sub` = **UUID de
Supabase**, firmado por nosotros. Así, en `/mcp/` reutilizamos (o clonamos) `extract_user_id`
y todo el scoping por `user_id` y `plan_required` funciona idéntico al asistente in-app.
Alternativa (más estado, no necesaria): guardar el access/refresh token de Supabase del
usuario y mapearlo.

## 5. Fases de entrega

- ✅ **Fase 0 — Spike (HECHO).** Django view `/mcp/` hand-rolled (`initialize`,
  `notifications/*`, `ping`, `tools/list`, `tools/call`) exponiendo las tools según plan, **sin
  OAuth** (Bearer estático Supabase, reusando `authenticate_request`). Valida el adaptador
  `_REGISTRY → MCP` + la policy layer + el recording de interacciones `connector`. Detalle e
  instrucciones de prueba en §11.
- ✅ **Fase 1 — OAuth 2.1 multi-tenant (HECHO).** Discovery (RFC 8414/9728) + DCR (RFC 7591) +
  authorize (PKCE) + approve (login delegado a Supabase) + token (auth-code + refresh). El
  `/mcp/` valida el access token propio y anuncia OAuth en 401. Página de consentimiento en el
  frontend. Detalle en §12.
- ✅ **Fase 2 — Write tools (HECHO).** Gateadas por plan en `core/mcp/policy.py`
  (`pro`/`studio`/`admin` → `writes: True`; `free`/`basic` solo lectura + `set_project_priority`).
  Additive sin fricción; modifying/destructive con `destructiveHint`. Reusa
  `core/assistant/tools/write.py`. Respeta quotas (`core/quotas.py`) y `bump_context_version`.
- **Fase 3 — Producción.** Rate limiting (✅ Fase 0). **Revocación + "Conexiones activas" +
  limpieza de tokens: ✅ HECHO** (ver §13). Pendiente: límites por-plan específicos del canal
  MCP, observabilidad/auditoría, publicación de la URL (deploy). Opcional: directorio de
  connectors de Anthropic.

## 6. Archivos nuevos (propuesta)

```
backend/core/mcp/
  __init__.py
  views.py             # Django view /mcp/: JSON-RPC (initialize, tools/list, tools/call) + SSE
  jsonrpc.py           # parseo/validación JSON-RPC 2.0 + errores
  adapter.py           # _REGISTRY → tools MCP (+ annotations por plan_required)
  oauth/
    metadata.py        # .well-known/* (RFC 8414 + 9728)
    register.py        # DCR (RFC 7591)
    authorize.py       # /oauth/authorize + PKCE + redirect a login frontend
    token.py           # /oauth/token (code→JWT, refresh)
    models.py          # OAuthClient, AuthCode, AccessGrant (+ migración)
    tokens.py          # firma/verifica el JWT propio (sub = uuid Supabase)
  tests/
    test_adapter.py        # cada tool se expone bien; scoping por user_id
    test_oauth_flow.py     # DCR → authorize(PKCE) → token → /mcp con Bearer
    test_mcp_tools_call.py # tools/list y tools/call end-to-end
docs/mcp-connector/PLAN.md  # este documento
```
Cambios mínimos en `continuity/asgi.py` (montar sub-app) y `continuity/urls.py` (rutas OAuth +
`.well-known`). **Cero cambios** en `core/services/*`.

## 7. Decisiones abiertas / riesgos

1. ~~**WSGI vs ASGI en producción.**~~ **RESUELTO.** Producción es WSGI (gunicorn gthread) y
   ya sirve SSE bajo WSGI. `/mcp/` se implementa hand-rolled como Django view (§4.1) → **cero
   cambios de deploy**. No se requiere ASGI/uvicorn.
2. **OAuth propio = responsabilidad de seguridad.** Emitir tokens implica PKCE, expiración,
   refresh y revocación correctos. Mitigación: scope mínimo, expiración corta + refresh,
   pantalla de revocación (Fase 3). Alternativa de menor código: gateway gestionado
   (Stytch/WorkOS/Auth0) delante — un vendor más.
3. **Cuotas y abuso = infra, no IA** (ver §2). Reusar rate-limit + límites por plan desde
   Fase 1.
4. **Confirmación de destructivos.** Confiar en `destructiveHint` + cliente Claude; además
   guardarraíl server-side (rate-limit estricto en `delete_*`, como en Phase 2 §2.6 del
   asistente).

## 8. Limitar capacidades por plan **desde el conector**

Política deseada (ejemplo): **plan básico** = solo **lectura** + **ajustar prioridad**; planes
superiores = **crear / modificar / borrar** completo. Sí se puede aplicar desde el conector.
Hay que entender dos cosas: **dónde** se aplica (enforcement) y **cómo** se expresa la política.

### 8.1 Enforcement — server-side, dos capas (nunca se confía en el modelo)

Igual que el asistente in-app, el conector aplica el límite en **dos puntos**, ambos en el
servidor:

1. **`tools/list` → filtrar.** Solo se anuncian a Claude las tools permitidas para el plan del
   usuario. El modelo ni ve las prohibidas. *(Esto es UX: evita que lo intente.)*
2. **`tools/call` → re-verificar.** Antes de despachar, se vuelve a chequear la política y se
   rechaza con error JSON-RPC si no aplica. **Esta es la garantía real:** aunque el modelo o un
   cliente fabriquen la llamada a una tool no anunciada, el servidor la bloquea.

> Regla de oro: ocultar en `tools/list` es cosmético; el límite **de verdad** vive en el
> re-check de `tools/call`. Es el mismo doble chequeo que ya hacen `schemas_for_anthropic()`
> (filtra) + `call()` (rechaza por plan) en `core/assistant/tools/__init__.py`.

### 8.2 Por qué NO basta con `plan_required` actual

El modelo de hoy es un **rank monotónico de un solo campo** (`_PLAN_RANK =
{free, pro, studio, admin}`, `plan_required` por tool) **compartido** entre el asistente in-app
y el conector. La política deseada lo rebasa por dos motivos:

- **Granularidad.** "Ajustar prioridad" es más fino que la frontera de la tool: hoy la
  prioridad vive dentro de `update_project` (`write.py`), que también renombra, cambia status,
  fechas, etc. El rank no puede decir "prioridad sí, renombrar no" dentro de una misma tool.
- **Acoplamiento de canal.** `plan_required` es un único campo en el `Tool` compartido. Si lo
  bajas para abrir prioridad en el conector, también aflojas el asistente in-app. Quieres
  política **independiente por canal**.

(Además, "básico" no existe aún en `_PLAN_RANK` — hoy es `free/pro/studio/admin`. Mapear
"básico" → `free` o agregar el tier según convenga.)

### 8.3 Diseño recomendado

**(a) Hacer expresable "solo prioridad": una tool angosta.**
Agregar `set_project_priority(id, priority)` — wrapper delgado sobre
`projects_svc.update_project` que **solo** toca `priority`. Mantener `update_project`
(bundle) gateado a pro+. Así la política del conector referencia una tool específica en vez de
inspeccionar campos. *(Alternativa descartada: gating por-campo dentro del dispatcher cuando
`plan=free` y `tool=update_project` — funciona pero filtra política al handler y el modelo
sigue viendo el schema completo, confuso.)*

**(b) Clasificar read vs write.** Añadir un flag explícito al decorador `@tool`,
`mutates: bool = False`, y marcar `mutates=True` en las tools de `write.py`. Da una
clasificación limpia read/write para la capa de política (mejor que inferirla del módulo o del
`plan_required`).

**(c) Matriz de política propia del conector** (independiente del asistente in-app):

```python
# core/mcp/policy.py
# Capacidades que EXPONE el conector MCP, por plan. Independiente del asistente in-app.
MCP_TOOL_POLICY = {
    "free":   {"reads": True, "allow_extra": {"set_project_priority"}},  # lectura + prioridad
    "basic":  {"reads": True, "allow_extra": {"set_project_priority"}},  # (si se agrega el tier)
    "pro":    {"reads": True, "writes": True},                           # CRUD completo
    "studio": {"reads": True, "writes": True},
    "admin":  {"reads": True, "writes": True},
}

def mcp_tools_for(plan: str) -> list[Tool]:
    pol = MCP_TOOL_POLICY.get(plan, MCP_TOOL_POLICY["free"])
    out = []
    for t in all_tools():
        if not t.mutates and pol.get("reads"):
            out.append(t)                      # cualquier read
        elif t.mutates and pol.get("writes"):
            out.append(t)                      # cualquier write (pro+)
        elif t.name in pol.get("allow_extra", set()):
            out.append(t)                      # excepciones (prioridad en free)
    return out

def mcp_allows(plan: str, name: str) -> bool:
    return any(t.name == name for t in mcp_tools_for(plan))
```

- `tools/list` usa `mcp_tools_for(plan)` (en vez de `schemas_for_anthropic`).
- `tools/call` llama `mcp_allows(plan, name)` antes de `call(...)`; si es `False`, responde
  error JSON-RPC `-32601`/`-32600` ("tool not available on your plan").

Esto deja la política del conector en **un solo archivo legible**, sin tocar `core/services/*`
ni el gating del asistente in-app.

### 8.4 Relación con quotas (ortogonal)

`plan_required`/política = **qué** tools puede invocar. `core/quotas.py` = **cuántas** filas
(ej. Free 50 notas). Son límites distintos y **ambos** aplican en el conector: una write tool
permitida por plan igual puede toparse con la quota de entidad. No mezclar los dos conceptos.

### 8.5 Estado: **implementado** (capa de política + pruebas)

Ya construido y verde (24 tests):

```
backend/core/assistant/tools/__init__.py   # ✅ campo `mutates` en Tool + decorador @tool
backend/core/assistant/tools/write.py      # ✅ mutates=True en las 24 writes + tool angosta set_project_priority
backend/core/mcp/policy.py                 # ✅ MCP_TOOL_POLICY + mcp_tools_for / mcp_allows / mcp_call
backend/core/mcp/tests/test_policy_and_scope.py  # ✅ scope deseado + intentos de bypass (24 tests)
```

Notas de diseño confirmadas por las pruebas:
- `set_project_priority` es `plan_required="pro"` → el **asistente in-app** NO la da a free; el
  **conector** sí, vía `allow_extra` en la policy. Canales **decoplados** (test
  `test_channels_are_decoupled_for_priority`).
- `mcp_call` despacha por la **policy del conector**, no por `tools.call()` — por eso puede
  permitir la tool angosta a free sin tocar el gate `plan_required` del asistente.
- Cobertura de bypass: cross-user/IDOR (read, priority, delete), `user_id` forjado en args
  ignorado, la tool de prioridad no "contrabandea" un `update_project` completo, no hay tools de
  plan/billing/admin en el registro, tool desconocida → error, plan desconocido → tier más
  restrictivo.

> Pendiente (fases siguientes): conectar `mcp_tools_for` a `tools/list` y `mcp_call` a
> `tools/call` cuando exista el transporte `/mcp/`, derivando `plan` del `AccountProfile` del
> usuario autenticado (nunca del cliente).

## 9. Threat model — ¿el conector permite bypassear la seguridad?

**Conclusión: no agrega rutas de bypass de datos.** El conector es otro transporte delante de
la **misma** capa de tools que ya usa el asistente in-app, que trata al modelo como **input no
confiable**. Invariantes verificadas en el código:

| Vector | Por qué no aplica | Evidencia |
|---|---|---|
| Modelo accede a datos de otro usuario | El `user_id` lo inyecta el servidor desde el token; ningún handler lo lee de `args` | `grep args.get("user_id"/"owner"…)` → NINGUNO |
| IDOR con un `id` ajeno | Los services scopean por `user_id` (`filter(pk=id, user_id=user_id)`) → `NotFound` | `core/services/projects.py:44`, `assert_owned` |
| Escalar de plan | El plan sale de `AccountProfile` en la DB por el user autenticado, no del modelo/request/token | `views.py` `quota_snapshot.plan` / `get_or_create_profile` |
| Llamar tools admin | Las tools admin (gateadas por `_admin_user_id` en GraphQL) **no** están en el `_REGISTRY` del conector | `core/assistant/tools/` |
| Interacción no permitida por plan | `tools/call` re-verifica plan + existencia server-side (§8.1) | `call()` / `mcp_allows` |

El usuario **es el principal**: puede pedir a Claude lo que él ya tiene permitido. Un prompt
injection en sus datos, en el peor caso, daña **sus propios** datos (sigue scopeado a su
`user_id` y plan) — sin fuga cross-tenant.

**Dónde SÍ se concentra el riesgo nuevo: el OAuth (Fase 1).** La superficie nueva es la
emisión de tokens. Toda la seguridad cross-user se reduce a: *¿puede un atacante obtener un
token con `sub` = UUID de otra persona?* Controles obligatorios:
- **PKCE** en `/oauth/authorize` (anti-interceptación del code).
- **Validación firma + `audience` + `exp`** en cada request a `/mcp/` (reusar JWKS de Supabase
  o asumir la responsabilidad si se emite JWT propio).
- **Binding code↔cliente**, expiración corta + refresh + **revocación** (pantalla "Conexiones
  activas").

Si el OAuth falla, el atacante obtiene datos **de una víctima** — pero **scopeado a ese único
usuario y limitado por su plan**. La frontera entre usuarios no la rompe la capa de tools; solo
la rompería un OAuth mal implementado. Por eso Fase 1 es la de mayor cuidado de seguridad.

Matiz: la confirmación de destructivos depende del cliente Claude (`destructiveHint`); un
usuario que auto-apruebe puede borrar **sus propios** datos (footgun personal, no bypass),
mitigado por rate-limit estricto en `delete_*` (§7).

## 10. Cómo se prueba en Claude

Al terminar Fase 1: Claude.ai → *Settings → Connectors → Add custom connector* → pegar
`https://<backend>/mcp/` → Claude descubre OAuth → login de Continuity → autorizar → preguntar
*"What did I work on last week?"* → Claude llama `get_analytics` / `list_tasks` con los datos
del usuario.

## 11. Estado de implementación — Fase 0 (HECHO)

Transporte `/mcp/` hand-rolled (WSGI-nativo) funcionando con Bearer estático. Archivos:

```
backend/core/mcp/jsonrpc.py            # helpers JSON-RPC 2.0 + códigos de error
backend/core/mcp/adapter.py            # Tool → MCP tool (inputSchema + annotations)
backend/core/mcp/views.py              # McpView: initialize / ping / tools.list / tools.call
backend/core/mcp/policy.py             # (Fase previa) gating por plan + dispatch
backend/continuity/urls.py             # path("mcp/", McpView.as_view())
backend/continuity/settings.py         # MCP_RATE_LIMIT_USER / _IP
backend/core/mcp/tests/test_transport.py  # 13 tests e2e (HTTP + JWT)
```

**Comportamiento:**
- `initialize` → negocia `protocolVersion` (soporta 2024-11-05 / 2025-03-26 / 2025-06-18),
  devuelve `capabilities.tools` + `serverInfo`.
- Notificaciones (sin `id`, p.ej. `notifications/initialized`) → **202 sin body**.
- `tools/list` → tools filtradas por el plan del usuario (`mcp_tools_for`), cada una con
  `inputSchema` + `annotations` (`readOnlyHint`; `destructiveHint` en `delete_*`).
- `tools/call` → despacha por `mcp_call` (gating server-side); el resultado va como
  `content:[{type:"text", text: <json>}]` con `isError` true en payloads de error. Cada call
  **exitoso** registra una interacción `connector` (`interactions.record_from_request`).
- Errores JSON-RPC estándar: método desconocido `-32601`, params inválidos `-32602`,
  parse `-32700`.

**Auth y rate-limit:** reusa `authenticate_request` (Bearer Supabase JWT) con grupos
`mcp:ip`/`mcp:user` y `MCP_RATE_LIMIT_*`. El plan sale de `AccountProfile`
(`get_or_create_profile`), nunca del cliente. Las invariantes de seguridad de §9 aplican
(verificado por `test_transport.py`: write denegado en free, IDOR cross-user → `isError`).

**Prueba local (sin OAuth):**
```bash
# token: en una sesión logueada, copia un Bearer de cualquier request a /graphql/
TOKEN=eyJhbGc...
# tools/list
curl -s -X POST http://localhost:8000/mcp/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq '.result.tools[].name'
# tools/call
curl -s -X POST http://localhost:8000/mcp/ \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"get_dashboard_summary","arguments":{}}}' | jq
```
Para Claude Desktop en local se puede usar `mcp-remote` apuntando a `http://localhost:8000/mcp/`
con el header `Authorization: Bearer $TOKEN` (mientras no exista OAuth).

**Limitaciones de Fase 0 (→ Fase 1):**
- Solo **Bearer estático** — falta OAuth 2.1 + DCR (sin esto, Claude.ai no puede auto-conectarse
  desde su UI; el badge "Próximamente" del plugin web sigue vigente).
- Solo **POST + application/json** — el GET SSE (server-stream) de Streamable HTTP devuelve 405.
- **Stateless** — sin `Mcp-Session-Id`; cada request autentica por su cuenta.

## 12. Estado de implementación — Fase 1 (HECHO)

Servidor OAuth 2.1 (public client / PKCE) que permite a Claude.ai conectarse a `/mcp/`. El login
se **delega al frontend Supabase**: la página de consentimiento llama a `approve` con un Bearer
de Supabase y el backend emite el código. El access token es un **JWT propio** (firma
`MCP_OAUTH_SIGNING_KEY`, `sub` = UUID Supabase) → `/mcp/` lo valida y reusa el mismo scoping.

**Archivos (backend):**
```
core/models.py                         # OAuthClient, OAuthAuthorizationCode, OAuthRefreshToken
core/migrations/0022_*                 # tablas OAuth
core/mcp/oauth/tokens.py               # mint/verify access JWT, refresh opaco, hashing, PKCE S256
core/mcp/oauth/views.py                # metadata, register, authorize, approve, token
core/mcp/authz.py                      # auth de /mcp/: MCP token → fallback Supabase + WWW-Authenticate
continuity/urls.py                     # .well-known/* + /oauth/{register,authorize,authorize/approve,token}
continuity/settings.py                 # FRONTEND_BASE_URL, MCP_OAUTH_{SIGNING_KEY,ACCESS_TTL,REFRESH_TTL,CODE_TTL}
core/mcp/tests/test_oauth.py           # 18 tests
```
**Archivos (frontend):**
```
src/app/(app)/oauth/consent/page.tsx   # pantalla de consentimiento (sesión Supabase → approve → redirect)
src/app/(app)/login/page.tsx           # soporte de ?next= (solo rutas relativas) para volver al consent
messages/{es,en}.json                  # settings.plugins.oauthConsent.*
```

**Endpoints:**
- `GET /.well-known/oauth-protected-resource` (+ `/mcp`) — RFC 9728.
- `GET /.well-known/oauth-authorization-server` — RFC 8414 (S256, grants, registration_endpoint).
- `POST /oauth/register` — DCR (RFC 7591), cliente público (`token_endpoint_auth_method: none`).
- `GET /oauth/authorize` — valida client/redirect_uri/PKCE-S256; redirige a
  `FRONTEND_BASE_URL/oauth/consent?…`. Errores con redirect_uri válido vuelven al cliente; client
  o redirect_uri inválidos → 400 sin redirect (anti open-redirect).
- `POST /oauth/authorize/approve` — requiere Bearer Supabase; crea el code (hash) y devuelve
  `{redirect_to}`.
- `POST /oauth/token` — `authorization_code` (valida code+PKCE+redirect+cliente, marca usado) y
  `refresh_token` (rota: revoca el viejo). Errores OAuth estándar (`invalid_grant`, etc.).

**Flujo end-to-end:** Claude descubre OAuth (401 con `WWW-Authenticate: resource_metadata=…`) →
DCR → abre `/oauth/authorize` → consent en el frontend (login Supabase) → approve → code →
`/oauth/token` (PKCE) → access+refresh → `/mcp/` con `Authorization: Bearer <access>`.

**Seguridad (cubierta por tests):** PKCE S256 obligatorio (rechaza `plain`); replay de code →
`invalid_grant`; rotación de refresh (reuso del viejo → `invalid_grant`); redirect_uri/cliente
mismatch → `invalid_grant`; approve sin sesión Supabase → 401; codes y refresh tokens **hasheados**
en DB. Las invariantes de §9 siguen aplicando (el token solo porta `sub`; el scoping y el plan
son server-side).

**Pendiente (Fase 3 / producción):**
- Pantalla "Conexiones activas" para **revocar** refresh tokens (modelo ya revocable).
- Cron de limpieza de codes/refresh expirados.
- Quitar el badge "Próximamente" del plugin web (`/settings/plugins/claude`) una vez **desplegado**
  en Render con `FRONTEND_BASE_URL` y `MCP_OAUTH_SIGNING_KEY` configurados.
- Validación estricta de `aud` del access token en `/mcp/` (hoy se valida firma+exp+typ).

## 13. Estado de implementación — Fase 3: revocación (HECHO)

Cierra la brecha de seguridad de un OAuth multi-tenant: el usuario puede **ver y revocar** las
conexiones, y los tokens caducos se purgan.

**Backend:**
```
core/services/mcp_connections.py            # list_connections / revoke_connection (por user_id)
core/schema.py                              # query mcpConnections + mutation revokeMcpConnection + tipo McpConnection
core/management/commands/cleanup_oauth_tokens.py  # purga codes usados/expirados + refresh expirados/revocados
render.yaml                                 # cron horario ahora corre también cleanup_oauth_tokens
core/mcp/tests/test_connections.py          # 7 tests (servicio + GraphQL + comando)
```

**Frontend:**
```
src/lib/graphql.ts                          # MCP_CONNECTIONS_QUERY + REVOKE_MCP_CONNECTION
src/app/(app)/settings/plugins/claude/page.tsx  # sección "Conexiones activas" + botón Desconectar; badge Conectado/Próximamente
messages/{es,en}.json                       # settings.plugins.claude.{connectionsTitle,connectedOn,disconnect,disconnected,disconnectError,statusConnected}
```

**Cómo funciona:**
- Una "conexión" = un `OAuthClient` con ≥1 refresh token **vivo** (no revocado, no expirado).
- `revokeMcpConnection(clientId)` marca `revoked_at` en todos los refresh vivos de ese
  `(user, client)`. El cliente ya no puede renovar; el access token (stateless) caduca dentro de
  su TTL (≤ `MCP_OAUTH_ACCESS_TTL`).
- El plugin web muestra las conexiones activas y, cuando hay alguna, oculta el banner
  "Próximamente" y marca el badge como **Conectado**.
- `cleanup_oauth_tokens` (cron horario) borra codes usados/expirados y refresh
  expirados/revocados (gracia 1 día).

**Nota de seguridad:** la revocación es inmediata para *nuevas* emisiones (refresh); el access
token vigente sobrevive hasta su `exp`. Para corte inmediato del access se necesitaría una
denylist por `jti` — fuera de alcance dado el TTL corto. Sin denylist, mantener
`MCP_OAUTH_ACCESS_TTL` bajo (default 1h).

**Pendiente (operación):** el deploy (configurar `FRONTEND_BASE_URL` + `MCP_OAUTH_SIGNING_KEY`
en Render). Los límites de rate por-plan y la auditoría de conexiones ya están hechos (§14).

**Guía de deploy + checklist:** `docs/mcp-connector/DEPLOY.md` (variables Render, smoke tests,
cómo conectar Claude real, validaciones de seguridad, rollback).

## 14. Rate-limit por-plan + auditoría de conexiones (HECHO)

**Rate-limit por-plan.** El límite de usuario del conector ahora depende del plan
(`MCP_RATE_LIMIT_BY_PLAN` en settings; default free 30/m · pro 120/m · studio 300/m ·
admin 600/m; plan desconocido → `MCP_RATE_LIMIT_USER`). Se resuelve en
`core/mcp/authz.py` tras autenticar (deja `request.mcp_plan` para el gating de tools). El
límite por **IP** sigue global (pre-auth). Recordatorio (PLAN §2): protege **infra**, no una
factura de IA, y de paso diferencia el throughput como beneficio de plan.

**Auditoría de conexiones.** Modelo `OAuthConnectionEvent` (append-only) con eventos
`authorized` (al emitir el primer token), `token_refreshed` (rotación), `revoked` (usuario) y
`admin_revoked` (admin). Solo evento + cliente + timestamp — sin payloads. Se escribe desde
`core/mcp/oauth/views.py` (token) y `core/services/mcp_connections.py` (revoke). Migración
`0023_oauthconnectionevent`.

**Admin GraphQL** (`core/admin_api/schema.py`, gateado por `_admin_user_id`):
`adminMcpStats`, `adminMcpConnections(limit)`, `adminMcpConnectionEvents(limit)` y la mutation
`adminRevokeMcpConnection(userId, clientId)` (con `audit_record` acción
`mcp.revoke_connection`).

**Admin UI:** se ve en *Admon → Sistema → Base de datos* (`/admin/database`). Ver
`docs/admin/BASE-DE-DATOS.md`.

**Tests:** `core/mcp/tests/` (69 en total) — incluye `test_per_plan_rate_limit`, eventos de
auditoría en authorize/refresh/revoke, y las queries/mutation admin (con gate de admin).
