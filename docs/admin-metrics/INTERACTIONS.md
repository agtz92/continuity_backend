# Métricas de interacción por usuario y por canal

Permite al admin ver, por usuario, **cuántas interacciones** hizo desde cada canal
(web / móvil / connector), sin revelar información delicada. Pensado como primitivo
para construir métricas más ricas en el futuro.

## Qué cuenta como "interacción"

Una **acción con efecto**, bucketeada por canal:

| Canal | Qué cuenta | Cómo se detecta el source |
|---|---|---|
| `web` | Mutation GraphQL **o** mensaje al asistente | header `X-Continuity-Client: web` |
| `mobile` | Mutation GraphQL **o** mensaje al asistente | header `X-Continuity-Client: mobile` |
| `connector` | Tool call del connector MCP | ruta `/mcp/` (no depende de header) |
| `unknown` | Lo anterior sin header reconocible | fallback |

**No** cuenta: lecturas (queries), polling, mutations fallidas. Eso mantiene la métrica como
"actividad real" y reduce escrituras.

## Privacidad por diseño

Solo se guardan **contadores**. El modelo `InteractionDay` (`core/models.py`) tiene
únicamente `user_id`, `date`, `source`, `count`, `updated_at` — **nunca** contenido, texto de
queries, IPs ni user-agents. Por eso es seguro exponerlo en el admin: revela **volumen**, no
contenido. Hay un test que falla si alguien le agrega un campo con pinta de contenido
(`test_model_stores_only_counts_no_content`).

## Implementación (backend) — hecho

| Pieza | Archivo |
|---|---|
| Modelo `InteractionDay` + `InteractionSource` | `core/models.py`, migración `0021_interactionday.py` |
| Servicio: record + agregación + bulk | `core/services/interactions.py` |
| Recording de mutations (todas las apps) | extensión `core/interaction_tracking.py`, cableada en `core/schema.py` |
| Recording del asistente (1 por mensaje) | `core/assistant/views.py` (junto a `quotas.record`) |
| Exposición admin | `core/admin_api/schema.py`: `AdminUserSummary.interactions30d`, `AdminUserDetail.interactionsBySource` + `interactions30dTotal` |
| Tests | `core/tests/test_interactions.py` (20 tests) |

Detalles de diseño:
- **Best-effort:** `record_interaction` traga y loguea errores — una falla de métrica nunca
  rompe el request del usuario.
- **Una sola escritura por acción:** la extensión solo dispara en mutations exitosas; el
  asistente registra una vez por mensaje (junto a `quotas.record`, no por turno del modelo).
- **Ventana de 30 días** en las queries admin (acotada e indexada por `(date, source)` y
  `(user_id, -date)`).
- **`operation_type` se compara por `.name`** (el enum de Strawberry no es identity-equal al de
  graphql-core — bug encontrado y cubierto por test e2e).

## Pendiente (follow-ups, otros repos)

1. ✅ **Header de cliente** — HECHO. Web (`frontend/`) manda `X-Continuity-Client: web` y móvil
   (`mobile/`) `mobile`, en sus requests a `/graphql/` (Apollo `HttpLink`) y al asistente
   (`assistantApi.ts` + `assistantStream.ts`). El backend permite el header en CORS
   (`CORS_ALLOW_HEADERS` en `continuity/settings.py`). Sin header, caen en `unknown`.
2. ✅ **Connector** — HECHO (Fase 0 del conector). `core/mcp/views.py` llama
   `interactions.record_from_request(request)` por cada `tools/call` exitoso; el source se
   infiere de la ruta `/mcp/` → `connector`. Verificado en `core/mcp/tests/test_transport.py`
   (`test_tools_call_success_records_connector_interaction`).
3. ✅ **UI admin** (`frontend/`) — HECHO. Columna **"Interacciones (30d)"** en la lista de
   usuarios (`admin/users/page.tsx`, tabla desktop + cards móvil) y card **"Interacciones por
   canal (30d)"** en el detalle (`admin/users/[userId]/page.tsx`) con total + desglose
   web/móvil/conector/desconocido. Queries `ADMIN_USERS_QUERY` / `ADMIN_USER_QUERY` extendidas
   en `lib/graphql.ts`. Tests backend de exposición GraphQL en `core/tests/test_interactions.py`.

## Ideas futuras (habilitadas por este primitivo)

- Serie temporal por día/canal (el modelo ya es por día → trivial de agregar).
- Breakdown por tipo de acción (agregar una dimensión `kind` a `InteractionDay`).
- Métricas agregadas del sistema en `adminSystemStats` (DAU/WAU por canal).
- Detección de usuarios activos vs dormidos por canal.
