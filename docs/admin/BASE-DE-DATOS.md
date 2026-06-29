# Admon → Base de datos

Hub de administración para **revisar la información relevante del proyecto y tomar acciones**.
Vive en *Admon → Sistema → Base de datos* (`/admin/database`,
`frontend/src/app/(app)/admin/database/page.tsx`). Gateado por `_admin_user_id` como todo el
admin.

## Qué muestra

### 1. Conector MCP (Claude) — datos en vivo
La única parte con datos embebidos (no tenía hogar propio):
- **Stats:** conexiones activas, usuarios conectados, desglose por cliente.
- **Conexiones activas:** cliente · usuario (UUID corto) · fecha de conexión · **Revocar**.
- **Auditoría reciente:** eventos `authorized` / `token_refreshed` / `revoked` / `admin_revoked`.

Datos desde GraphQL admin: `adminMcpStats`, `adminMcpConnections`, `adminMcpConnectionEvents`;
acción `adminRevokeMcpConnection(userId, clientId)` (escribe `AdminAuditLog` acción
`mcp.revoke_connection`). Backend: `core/services/mcp_connections.py`,
`core/admin_api/schema.py`. Modelo de auditoría: `OAuthConnectionEvent`.

**Cuándo actuar:** revoca una conexión si el usuario lo pide, si ves actividad sospechosa en la
auditoría, o ante un token comprometido. La revocación corta la renovación; el access token
vigente caduca dentro de su TTL (`MCP_OAUTH_ACCESS_TTL`, default 1h).

### 2. Catálogo de dominios
Tarjetas (qué es · cómo revisar · acciones · link) para el resto de datos relevantes: Usuarios,
Feedback, Billing, Jobs de notificaciones, Audit log, Stats. No duplican datos — enlazan a su
página y explican qué hacer.

## Convención — mantenerla viva

> **Cuando aparezca un nuevo dominio de datos relevante del proyecto, regístralo aquí.**

- Si **ya tiene** una página admin → añade una tarjeta al array `CATALOG` en
  `admin/database/page.tsx` (título, qué es, cómo revisar, acciones, `href`).
- Si **no tiene** hogar (datos nuevos, como pasó con el conector MCP) → añade un panel en vivo
  en esta página, alimentado por una query admin `_admin_user_id`-gateada, con la acción
  correspondiente.
- Acciones destructivas → siempre `confirm()` en el front y `audit_record(...)` en el back.

Así "Base de datos" se mantiene como el índice operativo único: un admin nuevo entra aquí y
entiende qué datos hay, cómo revisarlos y qué puede hacer.

## Relacionado
- Conector MCP: `docs/mcp-connector/PLAN.md` (§13 revocación, §14 rate por-plan + auditoría).
- Métricas de interacción por usuario/canal: `docs/admin-metrics/INTERACTIONS.md` (se ven en el
  detalle de usuario; candidatas a un panel agregado aquí en el futuro).
