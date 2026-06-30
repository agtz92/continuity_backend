# Teams — Plan de implementación

> **⚑ ESTADO (2026-06-29): PROPUESTA — diseño aprobado en lo macro, pendiente de codear.**
> Decisiones de producto cerradas con el dueño: **(1) dirección B2B**, **(2) privacidad =
> solo contexto del team**, **(3) asignación modelo B**, **(4) plan de billing nuevo "Teams"**.
> Quedan sub-decisiones tácticas marcadas como ⚠️ a lo largo del doc.

> **Concepto.** Un usuario crea un **Team** (unidad facturable B2B). El **owner** puede ver la
> actividad de los miembros *dentro del contexto del team*, asignarles tareas y revisar si están
> hechas. Es el **primer acceso cruzado entre usuarios** de Continuity — toda la app es hoy
> estrictamente mono-usuario, así que el grueso del riesgo está en la frontera de seguridad, no en
> las pantallas.

---

## 1. Principio rector: Teams como **capa de acceso**, no reescritura de tenancy

Continuity es mono-usuario por diseño: `TimestampedModel.user_id` en cada tabla, cada query del
service layer hace `filter(user_id=...)`, no hay modelo `User` de Django (auth = JWT Supabase →
`info.context.user_id`), y RLS está habilitado (`0011_enable_rls`) pero **la defensa real es el
filtro del ORM**, no las policies.

**Decisión de arquitectura:** NO migrar todo a `team_id` ni introducir una jerarquía Org→Team→User.
Se monta Teams **encima** del modelo per-usuario:

- El **Team es el tenant facturable** (una sola capa; el "org" y el "team" son lo mismo en v1).
- Los datos siguen perteneciendo a un `user_id`. El acceso cruzado se concede **solo** vía membresía
  + un helper de autorización explícito en el service layer.
- RLS real basado en membresía = **hardening de Fase 4**, no bloqueante para el MVP.

---

## 2. Decisiones de producto (cerradas) y sus implicaciones

| # | Decisión | Implicación |
|---|---|---|
| 1 | **Dirección B2B** | Plan de pago propio + **asientos (seats)** facturados por Stripe; roles de gestión. |
| 2 | **Privacidad = solo contexto del team** | El owner ve de un miembro **solo** lo etiquetado al team (`team_id` set) o asignado por el team. El workspace personal del miembro permanece privado. |
| 3 | **Asignación modelo B** | La tarea asignada se crea con `user_id` = **el miembro asignado** → aparece nativa en sus listas; el owner la ve por query de team. "¿Hecha?" = campo `done` existente. |
| 4 | **Plan "Teams" nuevo** | `Plan.TEAMS` en el enum; entitlement de miembros derivado de la membresía activa (plan efectivo). |

---

## 3. Backend (Django + Strawberry GraphQL)

Todo en la app `core`, siguiendo el patrón de los servicios por dominio.

### 3.1 Modelos nuevos — `core/models.py`

```python
class Team(TimestampedModel):           # user_id = owner (reusa el scope base)
    name = models.CharField(max_length=120)
    # billing vive en AccountProfile del owner (ver §3.5); aquí solo metadata
    class Meta:
        indexes = [models.Index(fields=["user_id"])]

class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user_id = models.UUIDField(db_index=True)            # miembro (UUID Supabase)
    role = models.CharField(max_length=16, choices=TeamRole.choices)   # owner|admin|member|viewer
    status = models.CharField(max_length=16, default="active")          # active|invited|removed
    joined_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "user_id"], name="uniq_member_per_team")]

class TeamInvitation(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=16, choices=TeamRole.choices, default="member")
    token = models.CharField(max_length=64, unique=True)   # un solo uso
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
```

**Roles** (`TeamRole`): `owner` (todo + billing), `admin` (gestiona miembros/asigna, no billing),
`member` (ejecuta su trabajo, ve contexto del team), `viewer` (solo lectura). ⚠️ Si quieres
arrancar aún más simple: `owner` + `member` y dejar `admin`/`viewer` para después.

**Identidad de usuarios — `UserProfile` ligero.** Hoy no hay modelo User, así que para listar
miembros (email/nombre/avatar) hace falta un perfil sincronizado desde Supabase. Mismo patrón
best-effort que ya usa el admin (`get_users_map` con service-role key en `feedback`/`adminUsers`).
⚠️ Decisión: tabla `UserProfile(user_id, email, display_name, avatar)` sincronizada en login/invite,
**o** resolver on-demand vía `get_users_map`. Recomiendo tabla ligera (evita N+1 al render de miembros).

### 3.2 Cambios en `Task` — `core/models.py`

Aditivo, no rompe nada:

```python
team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks")
assigned_by_user_id = models.UUIDField(null=True, blank=True)   # quién la asignó
```

**Modelo B:** `assign_task(owner_id, team_id, member_id, ...)` **crea** la tarea con
`user_id=member_id`, `team_id=team_id`, `assigned_by_user_id=owner_id`. La tarea entra
automáticamente en el dashboard/listas del miembro (todo filtra por `user_id`). Sin tocar queries
existentes. El estado "hecha o no" es el `done`/`completed_at` que ya existe.

### 3.3 Autorización — la pieza de seguridad

Helper único en el service layer (p.ej. `core/services/teams.py`):

```python
def assert_team_access(requesting_user_id, *, team_id, target_user_id=None, capability):
    # 1) requesting_user_id es miembro activo de team_id?  si no -> FORBIDDEN
    # 2) su role permite `capability` (view_member | assign | manage_members | manage_billing)?
    # 3) si target_user_id: ese usuario es miembro del MISMO team? si no -> FORBIDDEN
```

**Toda** query/mutation de team lo invoca **antes** de cualquier lectura/escritura cruzada. Es la
versión application-layer del aislamiento (consistente con cómo protege hoy la app). Matriz:

| Capability | owner | admin | member | viewer |
|---|---|---|---|---|
| ver actividad/tareas de team de otro miembro | ✅ | ✅ | ❌ (solo lo suyo) | ✅ (lectura) |
| asignar tareas | ✅ | ✅ | ❌ | ❌ |
| invitar/quitar miembros, cambiar roles | ✅ | ✅ | ❌ | ❌ |
| gestionar seats/billing | ✅ | ❌ | ❌ | ❌ |

### 3.4 Schema GraphQL (repartido según `backend/CLAUDE.md`)

- **Tipos/inputs** → `core/schema_types.py`: `Team`, `TeamMember`, `TeamInvitation`, `TeamMemberInput`,
  `AssignTaskInput`; extender `Task` con `teamId`/`assignedByUserId`/`assignee`.
- **Mutations** (`core/schema_mutations.py`, con `@gql_error_handler`): `createTeam`, `renameTeam`,
  `deleteTeam`, `inviteMember`, `acceptInvite`, `removeMember`, `changeMemberRole`, `assignTask`,
  `reassignTask`/`unassignTask`.
- **Queries** (`core/schema.py`, **fuera del `dashboard`** → lazy al abrir Teams): `myTeams`,
  `team(id)`, `teamMemberTasks(teamId, memberId)`, `teamMemberActivities(teamId, memberId)`.
- **Helpers/auth** reusan `_user_id(info)` (`schema_helpers.py`); el cross-user pasa por
  `assert_team_access`.

### 3.5 Billing B2B — plan "Teams" + asientos

- `Plan.TEAMS = "teams"` en `core/assistant/models.py` (enum `Plan`).
- **Unidad facturable = el owner.** Su `AccountProfile` lleva la suscripción Stripe del Team
  (reusa `stripe_customer_id`/`stripe_subscription_id` + webhooks en `core/billing/`). La
  **cantidad** de la suscripción = nº de miembros activos (quantity-based / per-seat).
- **Plan efectivo del miembro.** Helper `effective_plan(user_id)` = `max(plan propio, mejor plan
  concedido por una membresía activa en un team de pago)`. Las cuotas y features Pro del miembro se
  evalúan contra el plan efectivo mientras pertenezca a un Team pago. (No se toca `AccountProfile.plan`
  del miembro; se deriva.)
- **Cuotas de las tareas de team.** Las tareas con `team_id` se rigen por el Team (no consumen la
  cuota personal free del miembro). ⚠️ Sub-decisión: cuota por-team (p.ej. `tasks_per_team`,
  `seats_max`) vs. ∞ dentro del plan Teams. Recomiendo límites generosos por-team configurables.
- **Añadir miembro = ajustar seats.** Invitar por encima de los asientos comprados incrementa la
  `quantity` de Stripe (con proración) tras confirmación del owner, o bloquea hasta comprar seats.
  ⚠️ Decisión UX: auto-incrementar vs. bloquear. Recomiendo auto-incrementar con aviso de costo.
- **Mobile:** billing **read-only** (regla del repo) → en móvil solo `Linking.openURL(".../settings/billing")`.

### 3.6 Activity log (reusar tabla `Activity`)

Nuevos `ActivityKind`: `TEAM_CREATED`, `MEMBER_JOINED`, `MEMBER_REMOVED`, `TASK_ASSIGNED`,
`TASK_COMPLETED_FOR_TEAM` (⚠️ opcional). Se emiten con `log_event(...)` + `bump_context_version(...)`
en el service layer, igual que el resto. `teamMemberActivities` filtra la actividad del miembro
**acotada al contexto del team** (decisión #2): solo eventos con `team_id`/`project` del team, no su
actividad personal.

### 3.7 Admin

Exponer en el panel admin (`core/admin_api/`): listar teams, seats ocupados, estado de suscripción;
con `_admin_user_id(info)` + `audit_record(action="team.*", target_type="team")`.

---

## 4. Web (Next.js + Apollo)

- **GraphQL ops** → `src/lib/graphql/teams.ts` (nuevo) + extender `tasks.ts` con `assignee`/`teamId`
  y `assignTask`. Barrel `index.ts`.
- **Navegación:** Teams es B2B/gestión → vive en **`/settings/teams`** (no como tab del dashboard del
  día a día). El selector de assignee sí aparece inline en `TaskModal.tsx`/`TaskRow.tsx`.
- **Componentes nuevos** (`src/components/teams/`): `TeamSettings`, `TeamMemberList` (con badges de
  rol + estado de seat), `InviteSheet`, `MemberActivityFeed`, `MemberTasksPanel`, `AssigneeSelect`.
- **Hooks:** `useTeamData` (queries lazy `myTeams`/`team`/`teamMember*`), `useTeamMutations`.
- **Identidad:** extender `ME_QUERY` con `teams { id role }` para gatear la UI (mostrar/ocultar Teams,
  permisos por rol). La autorización real es server-side; esto es solo UX.
- **i18n:** namespace `teams.*` en `messages/{en,es}.json`.
- **Billing:** página de seats/plan Teams en `/settings/billing` (reusa el flujo Stripe existente).

## 5. Mobile (Expo) — espejo

- Mismas queries/tipos. Pantalla bajo `(dashboard)/(more)/teams.tsx` + detalle por team/miembro.
- UI nativa: `BottomSheet` para invitar/asignar (no modal); `AssigneeSelect` reusa el patrón
  `BugTopicSelect`. Mutations vía hook espejo de web.
- **Billing read-only**; **admin excluido** (reglas del repo). Verificación:
  `npx expo export -p ios --clear` → `npx tsc --noEmit`.

---

## 6. Fases de entrega

1. **Fase 1 — Backend núcleo.** Modelos `Team`/`TeamMembership`/`TeamInvitation`/`UserProfile` +
   migración (cuidado con el bug de SQL crudo `%` bajo psycopg3 si la migración toca RLS). Service
   `teams.py`/`invitations.py` + `assert_team_access`. `assign_task` (modelo B). Schema (tipos,
   mutations, queries). `ActivityKind` nuevos. **Tests de aislamiento cruzado** (`user_a`/`user_b`):
   no-miembro no ve nada; member no ve a otro member; owner sí; respeto del contexto del team.
2. **Fase 2 — Billing B2B.** `Plan.TEAMS`, `effective_plan`, suscripción per-seat en Stripe +
   webhooks, gating de invitar por seats, admin de teams.
3. **Fase 3 — Web.** `/settings/teams`, AssigneeSelect en tareas, feeds de miembro, i18n, página de seats.
4. **Fase 4 — Mobile.** Espejo de la web con UI nativa.
5. **Fase 5 — Polish/hardening.** Notificaciones ("te asignaron una tarea"), help docs es/en en
   `docs/ayuda`, y **RLS real por membresía** como capa de defensa adicional.

---

## 7. Riesgos

1. **Frontera de seguridad (máxima prioridad).** Primer acceso cruzado de la app; un bug = fuga entre
   usuarios. Mitigación: un solo helper `assert_team_access` + suite de tests de aislamiento obligatoria.
2. **RLS engañoso.** RLS está "habilitado" pero no es lo que protege hoy; no asumir cobertura. La
   protección del MVP es application-layer; RLS real en Fase 5.
3. **Identidad de usuarios.** Sin modelo User → resolver email/nombre vía Supabase (service-role key
   best-effort) o `UserProfile` sincronizado.
4. **Billing per-seat.** Proración, downgrades al quitar miembros, y `effective_plan` deben quedar
   bien testeados (es donde se pierde dinero o se rompe el acceso).
5. **`DASHBOARD_QUERY`.** No meter datos de team ahí; queries de team siempre lazy/separadas.

---

## 8. No-goals (v1)

- Colaboración en tiempo real / edición concurrente.
- Hilos de comentarios o chat entre usuarios.
- Compartir el workspace **personal** completo de un miembro (decisión #2: solo contexto del team).
- Jerarquía Org→múltiples Teams anidados (un nivel: el Team es el tenant facturable).
- IAP / gestión de billing desde móvil.

---

## 9. Sub-decisiones tácticas pendientes (⚠️)

1. **Roles:** ¿arrancar con los 4 (`owner/admin/member/viewer`) o solo `owner/member`?
2. **Identidad:** tabla `UserProfile` sincronizada vs. resolver on-demand con `get_users_map`.
3. **Seats al invitar:** auto-incrementar la suscripción (proración) vs. bloquear hasta comprar.
4. **Cuotas de team:** límites por-team configurables vs. ∞ dentro del plan Teams.
5. **Onboarding del invitado:** si el invitado no tiene cuenta Continuity, el `acceptInvite` debe
   encadenar el signup de Supabase — definir ese flujo.
