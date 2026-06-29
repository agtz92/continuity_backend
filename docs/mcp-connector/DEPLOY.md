# Deploy — Conector MCP de Continuity

Checklist para poner en producción el conector (`/mcp/` + OAuth) y conectarlo a Claude real.
Asume el stack actual: **backend en Render** (WSGI gunicorn) y **frontend en Vercel**.

## 0. Qué se despliega solo

- **Migraciones:** `build.sh` corre `migrate` → `0021_interactionday` y
  `0022_oauthclient_…` aplican automáticamente en el deploy del backend.
- **Cron de limpieza:** el cron horario de `render.yaml` ya incluye `cleanup_oauth_tokens`.
- **Frontend:** la página de consentimiento (`/oauth/consent`), el `?next=` del login y el
  plugin "Conectar Claude" salen con el deploy normal del frontend. No hay env nuevas en el
  frontend (la URL del conector se deriva de `NEXT_PUBLIC_GRAPHQL_URL`).

## 1. Variables de entorno (Render — servicio `continuity-backend`)

| Variable | Valor | Notas |
|---|---|---|
| `FRONTEND_BASE_URL` | `https://<frontend>` (p. ej. `https://continuu.it`) | **Obligatoria.** Donde vive `/oauth/consent`. Sin esto, `authorize` redirige a `localhost:3000`. |
| `MCP_OAUTH_SIGNING_KEY` | *(generada por Render)* | Firma los access tokens MCP. Declarada `generateValue: true` → estable entre deploys. Si cambia, todos los tokens MCP se invalidan. |
| `CORS_ALLOWED_ORIGINS` | debe incluir el origin del frontend | Ya existe; verifícalo. La página de consentimiento hace `fetch` cross-origin a `/oauth/authorize/approve` con `Authorization`. |

Opcionales (tienen default sano):
`MCP_RATE_LIMIT_USER` (120/m), `MCP_RATE_LIMIT_IP` (300/m), `MCP_OAUTH_ACCESS_TTL` (3600),
`MCP_OAUTH_REFRESH_TTL` (2592000), `MCP_OAUTH_CODE_TTL` (300).

> El header `x-continuity-client` ya está permitido en `CORS_ALLOW_HEADERS` (métricas).

## 2. Verificación post-deploy (sin Claude)

Sustituye `$BE` por la URL del backend (p. ej. `https://continuity-backend.onrender.com`).

```bash
# 1) Discovery (sin auth)
curl -s $BE/.well-known/oauth-protected-resource | jq
curl -s $BE/.well-known/oauth-authorization-server | jq '.authorization_endpoint, .code_challenge_methods_supported'

# 2) /mcp/ sin token → 401 + WWW-Authenticate apuntando al metadata
curl -s -i -X POST $BE/mcp/ -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | grep -i "www-authenticate"

# 3) DCR: registrar un cliente de prueba
curl -s -X POST $BE/oauth/register -H "Content-Type: application/json" \
  -d '{"client_name":"smoke","redirect_uris":["https://example.com/cb"]}' | jq

# 4) /mcp/ con un Bearer de Supabase (dev fallback) — token de una sesión logueada
TOKEN=eyJhbGc...
curl -s -X POST $BE/mcp/ -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | jq '.result.tools[].name'
```

Espera: discovery devuelve JSON; (2) trae `WWW-Authenticate: Bearer resource_metadata="…"`;
(3) devuelve un `client_id` `mcp_…`; (4) lista tools del plan del usuario.

## 3. Conectar desde Claude real

1. Claude.ai (o Desktop) → **Settings → Connectors → Add custom connector**.
2. URL: `https://<backend>/mcp/`.
3. Claude descubre OAuth (vía el 401 + metadata), hace DCR y abre el navegador en
   `/oauth/authorize` → redirige a `FRONTEND_BASE_URL/oauth/consent`.
4. Inicia sesión en Continuity si hace falta (el consent usa la sesión Supabase) → **Permitir**.
5. Vuelve a Claude autorizado. Prueba: *"What did I work on last week?"* → Claude llama
   `get_analytics` / `list_tasks`.
6. En Continuity: **Settings → Plugins → Claude** ahora muestra la conexión activa (badge
   **Conectado**) con botón **Desconectar**.

## 4. Validaciones de seguridad en prod

- Revocar desde *Settings → Plugins → Claude* → Claude pierde acceso al expirar el access token
  (≤ `MCP_OAUTH_ACCESS_TTL`, default 1h) y no puede renovar.
- Confirmar que un usuario free solo ve lecturas + `set_project_priority` en `tools/list`, y que
  un `tools/call` de escritura le responde `isError` (gating por plan, server-side).
- Confirmar que dos cuentas distintas no ven datos cruzados (cada token porta su propio `sub`).

## 5. Rollback / seguridad

- El conector es **aditivo**: rutas nuevas (`/mcp/`, `/oauth/*`, `.well-known/*`) y modelos
  nuevos. No toca `/graphql/` ni el asistente in-app. Revertir = quitar las rutas o el deploy.
- **No** genera cargos de Anthropic (la inferencia corre en el Claude del usuario; ver PLAN §2).
- Las cuotas/rate-limit protegen infra, no una factura de IA.

## 6. Checklist

- [ ] `FRONTEND_BASE_URL` seteada en Render apuntando al frontend real.
- [ ] `MCP_OAUTH_SIGNING_KEY` presente (generada por Render).
- [ ] `CORS_ALLOWED_ORIGINS` incluye el origin del frontend.
- [ ] Deploy backend OK (migraciones aplicadas — revisar logs de `build.sh`).
- [ ] Deploy frontend OK (`/oauth/consent` responde; plugin "Claude" visible).
- [ ] Smoke tests §2 en verde.
- [ ] Conexión real desde Claude §3 funciona end-to-end.
- [ ] Revocación §4 funciona.
- [ ] (Opcional) Anunciar / listar en el directorio de connectors de Anthropic.
