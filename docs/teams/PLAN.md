# Teams — Plan de implementación (v2: jefe y asistentes)

> **Pagos, precios y suscripciones — fuente de verdad:** [Integración de pagos web y móvil](../integracion-pagos-web-y-movil.md)
> y [pagos-unificados/PLAN.md](../pagos-unificados/PLAN.md). Lo que este documento diga
> sobre cobros, planes o tiendas es contexto; ante cualquier diferencia, mandan esos.

> **⚑ ESTADO (2026-09-14): PROPUESTA v2 — reemplaza la v1 del 2026-06-29.**
> Código verificado por lectura directa el 2026-09-14. Donde afirmo cómo se comporta
> algo hoy, lo he leído; donde infiero o hace falta verificar con un tercero, lo marco.
> **Nada de esto está implementado.**

> **Concepto.** Un usuario crea un **Team** e invita a otros. Un **jefe** (`lead`) ve el
> **board de equipo** de cada miembro —completo— y puede agendarle tareas directamente.
> Un **asistente** (`member`) ve solo lo suyo, pero puede **proponerle** tareas al jefe.
> El *workspace personal* de cada persona sigue siendo invisible para todos.
> Es el **primer acceso cruzado entre usuarios** de Continuity: el grueso del riesgo está
> en la frontera de seguridad, no en las pantallas.

---

## 0. Qué cambia respecto a la v1, y por qué

La v1 (junio) sigue siendo correcta en su principio rector y en la forma de los modelos.
Cinco cosas cambian, y cuatro de ellas salen de leer el código de hoy, no de una opinión.

| # | v1 (junio) | v2 (ahora) | Por qué |
|---|---|---|---|
| 1 | Privacidad = "solo contexto del team" | **Dos espacios: board de equipo (visible al jefe) + workspace personal (invisible)** | Es la misma frontera técnica, mejor contada. Resuelve "quiero ver el board del otro" sin permisos por ítem ni invertir la promesa de privacidad. §1.2 |
| 2 | Asignan `owner`/`admin`; `member` no asigna | **Asignación bidireccional asimétrica**: el jefe asigna directo, el asistente **propone** | Un asistente ejecutivo real le agenda cosas al jefe: es literalmente su trabajo. Con la v1 no podía. §1.5 |
| 3 | `Plan.TEAMS` nuevo en el enum | **NO se toca el enum `Plan`.** Un asiento concede un plan existente (`studio`) | Añadir un valor al enum rompe cuatro tablas de lookup con tres modos de fallo distintos, uno de ellos un 500 en `/usage/`. §5.1 |
| 4 | Suscripción per-seat en **Stripe** | **Paquetes de asientos en RevenueCat**, y verificar antes de codear | Stripe dejó de ser emisor en agosto. Las columnas `stripe_*` que cita la v1 ya no existen. §5.5 |
| 5 | Teams vive entero en `/settings/teams` | Gestión en ajustes; **ver el board es una vista del dashboard** | Ver el trabajo del equipo es uso diario, no configuración. §7 |

Se conservan sin cambio: el principio de "Teams como capa de acceso" (§3), el modelo B de
asignación (la tarea nace con `user_id` del asignado), la prioridad absoluta de los tests
de aislamiento, y los no-goals de la v1.

---

## 1. El producto: jefe y asistentes

### 1.1 En una frase

**Un jefe delega trabajo, ve en qué va y se entera de lo que se está enfriando en su equipo
— sin dejar de respetar que el espacio personal de cada quien es suyo.**

No es un Trello con varios cursores. Continuity no compite en colaboración en tiempo real
y no debería intentarlo: su diferencia es el **cierre forzado**, y la versión en equipo de
eso es §1.3.

### 1.2 Los dos espacios — la decisión de privacidad

Cada persona tiene **dos espacios**, y la frontera entre ellos es un predicado, no una
lista de permisos:

```
┌─────────────────────────────┐      ┌─────────────────────────────┐
│   BOARD DE EQUIPO           │      │   WORKSPACE PERSONAL        │
│   team_id = <el team>       │      │   team_id IS NULL           │
│                             │      │                             │
│   • proyectos del equipo    │      │   • sus proyectos           │
│   • tareas del equipo       │      │   • sus tareas, ideas,      │
│   • su actividad ahí        │      │     rutinas, notas          │
│                             │      │                             │
│   El jefe lo ve COMPLETO    │      │   NADIE más lo ve. Nunca.   │
└─────────────────────────────┘      └─────────────────────────────┘
```

Por qué así y no de otra forma:

- **Cumple lo que se pidió** ("ver el board de otras personas del equipo") sin inventar un
  modelo de permisos por ítem. El jefe ve el board del asistente entero, no fragmentos.
- **No añade superficie de seguridad.** Un fallo de autorización expone como mucho el board
  de equipo — que es justamente lo que el jefe ya tenía derecho a ver. El material sensible
  (el workspace personal) nunca entra en una query de teams.
- **Es enforceable con un `WHERE`.** `team_id IS NOT NULL AND team_id = <team>`. No hay ACL
  que mantener, ni un flag `is_private` por fila que alguien se olvide de comprobar.
- **No rompe la marca.** El producto se vende sobre "tu relación con tu trabajo sin
  terminar". Eso se conserva intacto en el espacio personal.

> **Coste que hay que aceptar:** algo solo es visible si está en el board de equipo. Si el
> asistente crea una tarea suelta, el jefe no la ve. Se mitiga en UX, no en el modelo:
> cuando estás dentro de la vista de equipo, **crear crea con `team_id` por defecto**, y
> mover algo entre espacios es una acción explícita de un clic (`setTaskTeam` / `setProjectTeam`).

### 1.3 El diferenciador: el enfriamiento del equipo

Aquí es donde esto deja de ser "otro gestor de tareas compartido".

Continuity ya calcula, en un solo sitio (`core/services/cooling.py`), cuántos días lleva un
proyecto sin moverse y en qué tramo cae (templado 0-7 · enfriándose 8-21 · frío 22+), y ya
marca como `stalled` los proyectos activos que llevan 14 días quietos (`services/stalled.py`,
cron horario). Y ya deriva "atorado" de si hay una tarea abierta con un blocker sin resolver.

**Nada de eso hay que escribirlo otra vez.** Aplicado al board de equipo sale gratis una
pantalla que ningún competidor tiene:

> *"Tres cosas que tu equipo empezó y nadie ha tocado en 14 días. Dos están atoradas
> esperando algo. Decide: se retoman, se pausan o se matan."*

Esa pantalla —no el board— es el argumento de venta de Teams. El board es la mesa; el
enfriamiento del equipo es por lo que pagas.

**Implementación:** `team_stall_digest(scope)` en `team_views.py` reutiliza
`cooling.classify` y `Project.stalled_at` sobre `user_id__in=<miembros>, team_id=<team>`.
Es una query, no un subsistema.

### 1.4 Roles

Dos roles y punto. La v1 dejaba abierto si arrancar con cuatro (`owner/admin/member/viewer`);
la respuesta para "jefe y asistentes" es que dos bastan, y el cuarto (`viewer`) no tiene
usuario real todavía.

| Rol | Quién es | Qué puede |
|---|---|---|
| **`lead`** | El jefe | Ver el board de equipo de **cualquier** miembro · asignar directo a cualquiera · invitar, quitar y cambiar roles · aceptar/rechazar propuestas dirigidas a él |
| **`member`** | El asistente | Ver **su** board de equipo y los proyectos de equipo en los que participa · **proponer** tareas a cualquier miembro · aceptar/rechazar propuestas dirigidas a él |

**La propiedad del Team no es un rol**, es `Team.user_id` (reutiliza el scope de
`TimestampedModel`). El dueño es quien paga y quien puede borrar el team; siempre tiene
además rol `lead`. Puede haber varios `lead` en un team; dueño solo hay uno.

> ⚠️ `admin` y `viewer` se dejan fuera **a propósito**. Añadir un rol después es una fila
> en un enum; quitarlo cuando ya hay gente asignada a él, no.

### 1.5 Asignación bidireccional asimétrica

| Quién → a quién | Qué pasa |
|---|---|
| `lead` → cualquier miembro | **Directo.** La tarea nace en la lista del asignado, ya aceptada. |
| `member` → cualquier miembro (incl. un `lead`) | **Propuesta.** Le llega al destinatario, que acepta o rechaza. Al aceptar, se crea la tarea. |

Esto cubre el caso real del asistente ejecutivo —agendarle algo al jefe— sin abrir la puerta
a que cualquiera le llene la lista a cualquiera.

**Decisión de modelado que importa:** una propuesta **no es una `Task`**. Es una fila de
`TaskProposal`. La alternativa —crear la `Task` con un estado `proposed`— obligaría a
filtrar por ese estado en el dashboard, en Today, en Tasks, en el calendario y en las 12
tools de lectura del asistente; olvidarse en uno solo mete tareas ajenas en la vista de
alguien. Con una tabla aparte, **la invariante "toda `Task` de la base pertenece a quien la
tiene" se mantiene intacta** y no se toca ni una query existente. Al aceptar se llama al
`create_task()` de siempre.

Efecto secundario deseable: la cuota se comprueba **al aceptar**, dentro de `create_task`,
que es donde ya vive `check_entity_quota`.

---

## 2. Decisiones de producto cerradas

| # | Decisión | Estado |
|---|---|---|
| 1 | Dirección **B2B** | Cerrada (v1) |
| 2 | Privacidad = **dos espacios**: board de equipo visible al jefe, personal invisible | **Cerrada (v2, 14 sep)** — sustituye la redacción de la v1 |
| 3 | Asignación **modelo B** (la tarea nace con `user_id` del asignado) | Cerrada (v1) |
| 4 | Asignación **bidireccional asimétrica** (jefe directo / asistente propone) | **Cerrada (v2, 14 sep)** |
| 5 | Roles: **`lead` + `member`** | **Cerrada (v2, 14 sep)** |
| 6 | Cobro B2B propio | Cerrada (v1) — pero **no** como plan nuevo en el enum; ver §5 |

---

## 3. Principio rector: Teams como capa de acceso

Sin cambios respecto a la v1, porque sigue siendo correcto.

Continuity es mono-usuario por diseño: `TimestampedModel.user_id` en cada tabla, cada query
del service layer hace `filter(user_id=...)`, no hay modelo `User` de Django (auth = JWT de
Supabase → `info.context.user_id`), y RLS está habilitado (`0011_enable_rls`) pero **la
defensa real es el filtro del ORM**, no las policies.

**No** se migra todo a `team_id` ni se introduce una jerarquía Org→Team→User. Teams se monta
**encima** del modelo per-usuario:

- El **Team es el tenant facturable** (una sola capa: "org" y "team" son lo mismo).
- Los datos siguen perteneciendo a un `user_id`. El acceso cruzado se concede **solo** vía
  membresía + un autorizador explícito.
- RLS real basado en membresía es **hardening de la fase 7**, no bloqueante para el MVP.

### 3.1 La invariante de seguridad, y cómo se hace imposible romperla

El enunciado:

> **El conjunto de `user_id` que toca cualquier query se deriva siempre de una llamada a
> `assert_team_access` en la misma función. Nunca del input de la petición.**

La disciplina no basta para sostener eso durante dos años de cambios, así que se hace
estructural con un objeto que **solo el autorizador puede construir**:

```python
# core/services/teams.py
@dataclass(frozen=True)
class TeamScope:
    """Prueba de que el solicitante puede leer a estos usuarios en este team.

    Solo `assert_team_access` la construye. Toda función que lee datos de otro
    usuario la exige como parámetro, así que es imposible escribir una lectura
    cruzada sin haber pasado por la autorización: no compila, no hace falta
    recordarlo en la revisión.
    """
    team_id: uuid.UUID
    member_ids: tuple[uuid.UUID, ...]   # exactamente a quién se puede leer
    capability: str


def assert_team_access(requesting_user_id, *, team_id, target_user_id=None,
                       capability) -> TeamScope:
    # 1) ¿requesting_user_id es miembro activo de team_id?      si no -> FORBIDDEN
    # 2) ¿su rol permite `capability`?                          si no -> FORBIDDEN
    # 3) si hay target_user_id: ¿es miembro activo del MISMO team? si no -> FORBIDDEN
    # -> devuelve el TeamScope con los member_ids permitidos
```

Y la segunda mitad de la invariante:

> **Los servicios existentes (`projects.py`, `tasks.py`, `ideas.py`…) nunca aprenden qué es
> un team.** No ganan un parámetro `target_user_id`, no ganan un `if team`. Siguen recibiendo
> un `user_id` y filtrando por él.

Todo el acceso cruzado vive en **un módulo nuevo, `core/services/team_views.py`**, que
resuelve el `TeamScope` en el borde y luego consulta. Un solo archivo que auditar, y el
`git blame` de la frontera de seguridad cabe en una pantalla.

**Capabilities** (el enum que `assert_team_access` comprueba):

| Capability | `lead` | `member` |
|---|:--:|:--:|
| `VIEW_MEMBER_BOARD` — ver el board de equipo de otro | ✅ | ❌ |
| `VIEW_TEAM` — ver el team y sus proyectos de equipo | ✅ | ✅ |
| `ASSIGN_DIRECT` — asignar sin aceptación | ✅ | ❌ |
| `PROPOSE` — proponer una tarea | ✅ | ✅ |
| `MANAGE_MEMBERS` — invitar, quitar, cambiar roles | ✅ | ❌ |
| `MANAGE_BILLING` — asientos y suscripción | solo el dueño (`Team.user_id`) | ❌ |

---

## 4. Backend

Todo en la app `core`, siguiendo el patrón de servicios por dominio y el reparto del schema
que documenta [`../../CLAUDE.md`](../../CLAUDE.md).

### 4.1 Modelos nuevos — `core/models.py`

```python
class TeamRole(models.TextChoices):
    LEAD   = "lead", "Lead"
    MEMBER = "member", "Member"


class Team(TimestampedModel):          # user_id = el dueño (paga y puede borrar)
    name = models.CharField(max_length=120)
    seats_purchased = models.PositiveIntegerField(default=1)
    class Meta:
        indexes = [models.Index(fields=["user_id"])]


class TeamMembership(models.Model):
    team      = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    user_id   = models.UUIDField(db_index=True)
    role      = models.CharField(max_length=16, choices=TeamRole.choices)
    status    = models.CharField(max_length=16, default="active")   # active | removed
    joined_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "user_id"],
                                               name="uniq_member_per_team")]
        indexes = [models.Index(fields=["user_id", "status"])]      # "mis teams", caliente


class TeamInvitation(models.Model):
    team        = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="invitations")
    email       = models.EmailField()
    role        = models.CharField(max_length=16, choices=TeamRole.choices, default=TeamRole.MEMBER)
    token_hash  = models.CharField(max_length=64, unique=True)   # sha256, NO el token
    expires_at  = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    invited_by_user_id = models.UUIDField()


class TaskProposal(TimestampedModel):   # user_id = el destinatario (quien acepta)
    team           = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="proposals")
    from_user_id   = models.UUIDField(db_index=True)
    title          = models.CharField(max_length=500)
    note           = models.CharField(max_length=500, blank=True, default="")
    due_date       = models.DateTimeField(null=True, blank=True)
    effort_hours   = models.FloatField(null=True, blank=True)
    project        = models.ForeignKey("Project", null=True, blank=True, on_delete=models.SET_NULL)
    status         = models.CharField(max_length=16, default="pending")  # pending|accepted|declined
    resolved_at    = models.DateTimeField(null=True, blank=True)
    created_task   = models.ForeignKey("Task", null=True, blank=True, on_delete=models.SET_NULL)


class UserProfile(models.Model):
    """Identidad mínima para pintar una lista de miembros sin N+1 contra Supabase."""
    user_id      = models.UUIDField(primary_key=True)
    email        = models.CharField(max_length=320, blank=True, default="")
    display_name = models.CharField(max_length=120, blank=True, default="")
    avatar       = models.CharField(max_length=64, blank=True, default="")
    updated_at   = models.DateTimeField(auto_now=True)
```

**`token_hash`, no `token`.** La v1 guardaba el token de invitación en claro. El repo ya
decidió lo contrario para los códigos de OAuth del conector (se guardan en sha256 "so a DB
leak can't replay them"); una invitación es la misma clase de credencial de un solo uso y
merece el mismo trato. El token en claro solo existe en el correo.

**`UserProfile`, no `get_users_map` on-demand.** Resolvido el ⚠️ #2 de la v1: una tabla
ligera, sincronizada al invitar y al login. `get_users_map` (el patrón best-effort de
`feedback`/`adminUsers`) hace una llamada HTTP a Supabase por lote y **devuelve "" cuando no
hay service-role key** — aceptable en un panel de admin, inaceptable en una pantalla que el
cliente ve todos los días. La tabla se rellena best-effort desde la misma fuente, pero se
sirve desde Postgres.

### 4.2 Cambios aditivos en `Project` y `Task`

```python
# Project
team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL,
                         related_name="projects")

# Task
team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL,
                         related_name="tasks")
assigned_by_user_id = models.UUIDField(null=True, blank=True)
```

**`team` en `Project` también** (la v1 solo lo ponía en `Task`). Sin eso no hay "board":
Continuity es un producto centrado en proyectos, y el enfriamiento —§1.3, la razón de ser de
Teams— se calcula sobre proyectos, no sobre tareas sueltas.

`SET_NULL` en ambos: **borrar un team no borra el trabajo de nadie**, lo devuelve al espacio
personal de su dueño. Es la misma decisión que ya se tomó para `QuickNote.category`/`project`.

> **Migración:** es puramente aditiva (tres columnas nulables + cuatro tablas). Si toca SQL
> crudo de Postgres, usar `migrations/_pg.postgres_only()` — pasa `params=None` para que
> psycopg3 no interprete los `%I` de `format()` como placeholders y reviente un `migrate`
> limpio.

### 4.3 La frontera: `core/services/team_views.py`

El único módulo del repo autorizado a consultar datos de un `user_id` que no es el del
solicitante. Toda función pública empieza por `assert_team_access` y recibe un `TeamScope`.

```python
def member_board(requesting_user_id, *, team_id, member_id) -> BoardData:
    """El board de equipo de un miembro. El espacio personal nunca entra aquí."""
    scope = assert_team_access(requesting_user_id, team_id=team_id,
                               target_user_id=member_id,
                               capability=Capability.VIEW_MEMBER_BOARD)
    return _board(scope, member_ids=(member_id,))


def team_stall_digest(requesting_user_id, *, team_id) -> StallDigest:
    """§1.3 — qué se está enfriando en el equipo. La pantalla que vende Teams."""
    scope = assert_team_access(requesting_user_id, team_id=team_id,
                               capability=Capability.VIEW_MEMBER_BOARD)
    ...  # cooling.classify + Project.stalled_at sobre scope.member_ids
```

Y el filtro, **siempre** con las dos condiciones juntas:

```python
Project.objects.filter(user_id__in=scope.member_ids, team_id=scope.team_id)
```

`team_id=scope.team_id` no es redundante: es lo que impide que un `lead` de un team vea el
trabajo que ese miembro hace **para otro team** (un asistente que trabaja para dos jefes es
el caso normal, no el raro).

### 4.4 Asignación y propuestas — `core/services/teams.py`

```python
def assign_task(requesting_user_id, *, team_id, to_user_id, **task_fields) -> Task:
    scope = assert_team_access(..., capability=Capability.ASSIGN_DIRECT)
    task = tasks_svc.create_task(to_user_id, **task_fields)     # el create_task de siempre
    Task.objects.filter(pk=task.pk).update(team_id=team_id,
                                           assigned_by_user_id=requesting_user_id)
    log_event(to_user_id, kind=ActivityKind.TASK_ASSIGNED, ...)
    notify_assignment(to_user_id, task, by=requesting_user_id)
    return task


def propose_task(requesting_user_id, *, team_id, to_user_id, **fields) -> TaskProposal
def accept_proposal(user_id, *, proposal_id) -> Task     # -> create_task normal
def decline_proposal(user_id, *, proposal_id) -> None
```

`create_task` no cambia de firma. La asignación es "crear una tarea del otro, y luego
marcarla como del equipo", no un modo nuevo dentro del creador de tareas.

### 4.5 Activity

Nuevos `ActivityKind`: `TEAM_CREATED`, `MEMBER_JOINED`, `MEMBER_REMOVED`, `TASK_ASSIGNED`,
`TASK_PROPOSED`, `TASK_PROPOSAL_ACCEPTED`.

`Activity` **no gana una columna `team_id`**: la actividad de equipo se deriva del
`project_id`/`entity_id` que ya lleva, cruzado con qué proyectos y tareas son del team. Una
columna más significaría mantener dos fuentes de verdad sobre "¿esto es del equipo?".

> ⚠️ **Verificar en la fase 2:** si ese cruce resulta caro (la actividad es la tabla más
> grande del sistema), la alternativa es desnormalizar `team_id` en `Activity` y aceptar el
> coste de mantenerlo. Medir antes de decidir; no adivinar.

Los kinds nuevos deben añadirse al i18n del Log en **ambos clientes** (`views.log.entries.*`).

### 4.6 Notificaciones

`NotificationKind.TEAM_ASSIGNMENT` (y `TEAM_PROPOSAL`). **No hace falta infraestructura
nueva**: `dispatcher.enqueue()` crea la fila del outbox *e intenta la entrega en el momento*,
así que una asignación llega al instante y no espera al cron horario. Push (Expo) ya está
encendido desde el 11 de septiembre, y Telegram lleva vivo desde la fase 1 de notificaciones.

Añadir los toggles por tipo a `NotificationSettings` y a `/settings/notifications` en los dos
clientes, con el mismo patrón que el digest diario.

### 4.7 Schema GraphQL

Reparto según `backend/CLAUDE.md`:

- **Tipos e inputs** → `core/schema_types.py`: `Team`, `TeamMember`, `TeamInvitation`,
  `TaskProposal`, `TeamBoard`, `StallDigest`; extender `Task` con `teamId`, `assignedBy`.
- **Mutations** → `core/schema_mutations.py`, con `@gql_error_handler`: `createTeam`,
  `renameTeam`, `deleteTeam`, `inviteMember`, `acceptInvite`, `removeMember`,
  `changeMemberRole`, `assignTask`, `proposeTask`, `acceptProposal`, `declineProposal`,
  `setTaskTeam`, `setProjectTeam`.
- **Queries** → `core/schema.py` (`class Query`), **fuera de `dashboard`**: `myTeams`,
  `team(id)`, `teamBoard(teamId, memberId)`, `teamStallDigest(teamId)`, `myProposals`.

> **Riesgo heredado de la v1 que sigue vigente:** no meter nada de teams en
> `DASHBOARD_QUERY`. Ese resolver es el round-trip único de arranque de la app; añadirle una
> query de membresía le cuesta a los usuarios sin team exactamente lo mismo que a los que
> sí lo tienen. Las queries de team se cargan lazy al abrir la vista, como ya hacen Quick Notes.

### 4.8 Admin

En `core/admin_api/`: listar teams, asientos ocupados vs. comprados, estado de la
suscripción. Con `_admin_user_id(info)` + `audit_record(action="team.*", target_type="team")`,
igual que el resto del panel.

---

## 5. Entitlement y cobro

Esta es la sección que más cambia respecto a la v1, y la que más fácil es equivocar.

### 5.1 Por qué **no** hay `Plan.TEAMS`

La v1 propone `Plan.TEAMS = "teams"` en el enum. Verifiqué qué hace el código de hoy ante un
plan que no conoce, y son **cuatro tablas de lookup independientes con tres modos de fallo
distintos**:

| Dónde | Código | Con un plan desconocido | Consecuencia |
|---|---|---|---|
| `assistant/quotas.py:144` | `PLAN_QUOTAS[profile.plan]` | **`KeyError`** — es indexación directa, no `.get()` | `get_usage()` revienta → **`/usage/` da 500 → la app no carga**, ni web ni móvil |
| `quotas.py:210` | `ENTITY_QUOTAS.get(kind, {}).get(plan)` | `None`, que el código documenta como **"unlimited"** | El plan más caro obtiene proyectos, tareas e ideas ilimitados por accidente, en silencio |
| `assistant/tiers.py:52` | `ASSISTANT_MODE_BY_PLAN.get(plan, MODE_NONE)` | `MODE_NONE` | El plan más caro se queda **sin asistente**, y el cliente pinta el cartel de "actualiza tu plan" |
| `billing/entitlements.py` | `_has_live_entitlement` → `plan in {PRO, STUDIO}` | `False` | Una suscripción Teams **no está protegida** por el guard de conflicto entre canales: un evento viejo de otra tienda la puede pisar |

Más `MCP_TOOL_POLICY` (cae a `free`, solo lectura), `DEEP_DAILY_CAP_BY_PLAN` (cae a 0) y
`catalog._PRODUCT_SETTINGS` (sin ids → no se puede vender).

Son siete sitios, y el peligroso no es el que revienta: es el que devuelve `None` y regala el
producto sin que nadie se entere.

### 5.2 La alternativa: **el asiento concede un plan existente**

```
Un asiento de Teams activo  →  effective_plan(user) == "studio"
```

Nada de lo anterior se toca. Las cuotas, el asistente, el conector, el modo profundo y el
guard de entitlement siguen funcionando porque el plan sigue siendo uno de los cuatro que ya
conocen. Comercialmente se cuenta igual de bien —*"un asiento de Teams incluye Studio"*— y
tiene una ventaja real: el asistente conversacional y la escritura por el conector, que son
lo que un equipo de verdad usa, entran por defecto.

Lo que distingue a Teams del Studio individual **no es el enum**, es:

- `TeamMembership` activa → desbloquea las vistas de equipo.
- `billing_product_id` → dice que lo que se compró fue un paquete de asientos.
- `Team.seats_purchased` → cuántos.

### 5.3 `effective_plan` y lo que cuesta

Hoy: `effective_plan(profile) -> str` en `core/quotas.py`, devuelve `profile.plan`. Tres
puntos de uso (`_get_plan`, `autopsy.py`, y ella misma).

Pasa a:

```python
def effective_plan(user_id: uuid.UUID) -> str:
    """El plan propio, o el mejor que le conceda una membresía de equipo activa y pagada."""
```

Son tres call sites, pero **`_get_plan` corre en cada `check_entity_quota`, o sea en cada
creación de cualquier cosa en la app**. Convertir una lectura de un campo en memoria en una
consulta de membresía es un impuesto sobre todas las escrituras del producto.

**Mitigación:** cachear el plan efectivo por usuario, invalidando en cada cambio de membresía
o de entitlement. `AccountProfile.context_version` y `services/_cache.py` ya son exactamente
ese patrón para el contexto del asistente; se replica, no se inventa.

### 5.4 El bug de cuota que hay que arreglar **antes** de la primera asignación

`tasks_total` está en `_BLOCKING_KINDS`, y su contador es:

```python
Task.objects.filter(user_id=user_id, done=False).count()
```

O sea: **las tareas que el jefe le asigna al asistente cuentan contra la cuota personal del
asistente.** Un asistente en Free (tope 50) con 60 tareas asignadas queda por encima de un
*blocking kind*, y el efecto de eso no es "no puedes aceptar más tareas de equipo": es que
**no puede crear nada en toda la aplicación**, incluidas sus propias ideas y notas
personales. La primera vez que un jefe asigna en volumen, rompe a su asistente.

Dos arreglos, y hacen falta **los dos**:

1. `_count()` excluye el trabajo de equipo de los contadores personales
   (`.filter(team_id__isnull=True)` en `tasks_total`, `tasks_per_project` y `projects`).
2. El asiento concede `studio` (§5.2), donde esos topes son ∞ de todas formas.

El (1) es el que importa: protege al miembro cuyo asiento caduca a mitad de mes.

> ⚠️ **Sub-decisión pendiente:** si el trabajo de equipo no cuenta en la cuota personal,
> necesita una cuota propia o es infinito. Recomiendo `tasks_per_team` y `projects_per_team`
> generosos y configurables por `AppConfig` (que ya existe para exactamente esto: mover un
> número sin desplegar).

### 5.5 El cobro: paquetes de asientos, y qué hay que verificar antes

La v1 dice "suscripción per-seat en Stripe, ajustando la `quantity`". **Eso ya no se puede
escribir tal cual:** desde agosto Stripe no es emisor —solo el procesador de tarjeta bajo
RevenueCat Web Billing— y las columnas `stripe_customer_id`/`stripe_subscription_id` que
cita la v1 se consolidaron en `billing_customer_id`/`billing_transaction_id`/`billing_product_id`.

**Lo que hay que verificar antes de escribir una línea** (la regla que el propio
`pagos-unificados/PLAN.md` se impuso: *"No las adivines"*):

1. **¿RevenueCat soporta suscripciones con cantidad (per-seat)?** Su modelo es
   *entitlement por suscriptor*, no cantidad por suscripción. Si no lo soporta, el diseño
   per-seat de la v1 no es implementable tal cual. **No dar esto por hecho.**
2. **¿Qué manda un evento de Web Billing** para un producto de varios asientos?
3. **¿Cómo se gestiona el alta/baja de asientos** desde el customer portal?

**Diseño recomendado, que no depende de (1):** vender **paquetes de asientos como productos
distintos** — `teams_5`, `teams_10`, `teams_25`, mensual y anual. Encaja tal cual en
`catalog.py`, que ya está construido sobre "un id de producto por plan+periodo" y ya acepta
**listas de ids por producto** para honrar precios retirados. Subir de paquete es un cambio
de producto, que es justo lo que RevenueCat sabe hacer. Sin cantidades, sin proración a mano.

Y resuelve el ⚠️ #3 de la v1 (auto-incrementar vs. bloquear): **se bloquea**. Invitar por
encima de `seats_purchased` propone subir de paquete. Nadie recibe un cargo que no aprobó.

Hay que ampliar además:

- `_has_live_entitlement` → incluir los productos de Teams, o el guard de conflicto entre
  canales deja la suscripción B2B desprotegida (§5.1, fila 4).
- El `Entitlement` que construye el webhook debe llevar el team, para escribir
  `Team.seats_purchased` además del plan del dueño.

### 5.6 El móvil no vende asientos

Consistente con lo que ya hace el repo (el panel de admin está excluido del móvil) y con la
regla de las tiendas: vender una suscripción B2B dentro de la app obliga a IAP y a la
comisión correspondiente. **Teams se compra en la web.** La app muestra el equipo, el board
y las asignaciones; para los asientos, `Linking.openURL(".../settings/teams")`.

---

## 6. Loop y el conector MCP — explícitamente fuera de v1

La v1 no los menciona, y conviene decidirlo a propósito en vez de por omisión.

**Las 44 tools del asistente resuelven el `user_id` en el servidor, siempre el del
solicitante.** Hacer que Loop conteste *"¿en qué va Ana?"* significa que cada tool de lectura
gane un camino de autorización cruzada — es duplicar la superficie de seguridad del producto
para una función que nadie ha pedido todavía.

**Decisión: Loop no sabe nada de teams en la v1.** Cuando entre (fase 7 como muy pronto):
solo lectura, solo para `lead`, y como **tools nuevas y separadas** (`team_member_board`,
`team_stall_digest`) que reciben un `TeamScope`, nunca como un parámetro añadido a las tools
existentes.

**El conector MCP no necesita cambios.** Filtra por `Tool.mutates` y por plan; como el
asiento concede `studio` (§5.2), un miembro de equipo obtiene escritura por el conector
automáticamente y sobre **sus propios datos**, que es lo correcto.

---

## 7. Web (Next.js + Apollo)

**Dos superficies, no una.** La v1 metía todo en `/settings/teams`; ver el trabajo del equipo
es uso diario y no cabe en ajustes.

| Superficie | Dónde | Qué hay |
|---|---|---|
| **Gestión** | `/settings/teams` | Crear/renombrar el team, miembros, roles, invitaciones, asientos, enlace a cobro |
| **Uso diario** | Vista `team` del dashboard | Digest de enfriamiento del equipo (§1.3), selector de miembro, su board, bandeja de propuestas |

La vista nueva es barata: el dashboard ya usa la ruta catch-all `[[...slug]]` con
`lib/dashboardRoutes.ts`, así que añadir `team` es una entrada más en el `TabBar` (y en el
`MoreSheet` en mobile-web), condicionada a tener membresía activa.

- **GraphQL** → `src/lib/graphql/teams.ts` nuevo; extender `tasks.ts` con `teamId`/`assignedBy`.
- **Componentes** (`src/components/teams/`): `TeamMemberList`, `InviteSheet`, `MemberBoard`,
  `TeamStallDigest`, `AssigneeSelect`, `ProposalInbox`.
- **Hooks:** `useTeamData` (lazy, `cache-and-network`, como `useQuickNotes`), `useTeamMutations`.
- **Identidad:** extender `ME_QUERY` con `teams { id role }` para gatear la UI. La
  autorización real es server-side; esto es solo para no pintar botones muertos.
- **Rediseño:** las filas de proyecto del board **llevan espina** (`Spine`), el enfriamiento
  se dice con `CoolingRule`, y no se inventa un cuarto color: el nombre del asignado es
  metadato (`Meta`), no una pastilla de color. Un avatar de equipo no es una señal.
- **i18n:** namespace `teams.*` en `messages/{en,es}.json`, en los dos idiomas.

## 8. Móvil (Expo) — espejo

- Pantalla `(dashboard)/(more)/team.tsx` + detalle por miembro. `BottomSheet` para invitar,
  asignar y resolver propuestas (no `Modal`).
- Mismos tipos y queries; `AssigneeSelect` sobre el patrón de `BugTopicSelect`.
- **No vende asientos** (§5.6); admin excluido.
- Verificación en este orden: `npx expo export -p ios --clear` → `npx tsc --noEmit`, ambos
  en exit 0 (regla 3 de `AGENTS.md`: el export es lo que regenera las typed routes).

---

## 9. Fases de entrega

Ordenadas por riesgo, no por visibilidad. La fase 1 no produce ni una pantalla y es la única
que no se puede hacer mal.

| Fase | Qué | Definition of done |
|---|---|---|
| **0 · Verificación** | Resolver las tres incógnitas de RevenueCat (§5.5). Cerrar las sub-decisiones de §13. | Respuestas escritas aquí. Si algo sigue sin confirmarse, `TODO(verificar)` en el código, no una invención. |
| **1 · Frontera de seguridad** | Modelos + migración aditiva · `assert_team_access` + `TeamScope` · `team_views.py` · invitaciones. **Sin UI.** | **La suite de aislamiento de §10 en verde.** Nada más cuenta. |
| **2 · Board y enfriamiento** | `team` en `Project`/`Task` · `member_board` · **`team_stall_digest`** · `assign_task` · `TaskProposal` · ActivityKinds. | Un `lead` lee el board de un miembro y su digest de enfriamiento por GraphQL; un no-miembro recibe FORBIDDEN. |
| **3 · Cuotas y entitlement** | Arreglar `_count` (§5.4) · `effective_plan(user_id)` + caché · `_has_live_entitlement`. | Un miembro con 200 tareas de equipo en Free sigue pudiendo crear en su espacio personal. |
| **4 · Cobro** | Paquetes de asientos en `catalog.py` · webhook · bloqueo por asientos · admin de teams. | Comprar Teams-5, invitar a 5, que el sexto se bloquee con la oferta de subir de paquete. |
| **5 · Web** | Ajustes + vista de dashboard + i18n. | Recorrido completo jefe↔asistente en un navegador. |
| **6 · Móvil** | Espejo con UI nativa. | Export + `tsc` limpios. |
| **7 · Hardening** | Notificaciones de asignación · docs de ayuda es/en en `docs/ayuda` · **RLS real por membresía** · (quizá) tools de equipo para Loop. | — |

Las fases 5 y 6 son independientes entre sí una vez que la 4 fija el contrato.

---

## 10. Los tests de aislamiento — la parte que no se negocia

Es la primera vez que un usuario puede leer datos de otro. La suite se escribe **en la fase
1, antes que cualquier pantalla**, y es la definition of done de esa fase.

Con tres usuarios: `lead_a` y `member_a` en el Team A; `outsider` sin membresía.

| # | Caso | Esperado |
|---|---|---|
| 1 | `outsider` pide `teamBoard` del Team A | FORBIDDEN |
| 2 | `outsider` pide `team(id)` del Team A | FORBIDDEN |
| 3 | `member_a` pide el board de otro miembro | FORBIDDEN (no tiene `VIEW_MEMBER_BOARD`) |
| 4 | `lead_a` pide el board de `member_a` | OK |
| 5 | **`lead_a` pide el board de `member_a` y este tiene trabajo personal** | El personal **no aparece** |
| 6 | **`member_a` está en el Team B con otro jefe** | `lead_a` **no ve** el trabajo del Team B |
| 7 | `member_a` intenta `assignTask` | FORBIDDEN (no tiene `ASSIGN_DIRECT`) |
| 8 | `member_a` hace `proposeTask` a `lead_a` | Crea `TaskProposal`, **no** crea `Task` |
| 9 | Una propuesta pendiente | **No** aparece en el dashboard, Today, Tasks ni calendario del destinatario |
| 10 | `outsider` acepta una propuesta que no es suya | FORBIDDEN |
| 11 | Miembro con `status="removed"` | Pierde el acceso inmediatamente |
| 12 | Se borra el Team A | El trabajo **sobrevive**, vuelve al espacio personal (`SET_NULL`) |
| 13 | Invitación caducada / ya aceptada | Rechazada |
| 14 | Se pide el board con un `member_id` de **otro** team | FORBIDDEN (paso 3 de `assert_team_access`) |
| 15 | Asignación masiva a un miembro Free | Su creación personal **no** se bloquea (§5.4) |

**Guard estructural, además de los casos:** un test que recorra los módulos de
`core/services/` —excepto `teams.py` y `team_views.py`— y falle si alguna función pública
ganó un parámetro que no sea el `user_id` del solicitante. La regla de §3.1 debe ser
verificable por una máquina, no recordada en una revisión de código.

---

## 11. Riesgos

1. **La frontera de seguridad.** Máxima prioridad. Un fallo aquí es una fuga entre cuentas.
   Mitigación: un solo autorizador, un solo módulo de lectura cruzada, el `TeamScope` que
   hace la autorización obligatoria por firma, y la suite de §10.
2. **RLS engañoso.** RLS está *habilitado* pero no es lo que protege hoy; no asumir
   cobertura. La protección del MVP es de capa de aplicación. RLS real por membresía en la fase 7.
3. **RevenueCat y los asientos.** El mayor riesgo de cronograma, porque depende de un
   tercero. Se ataca en la fase 0, antes de comprometerse.
4. **El impuesto de `effective_plan`.** Corre en cada escritura del producto. Si la caché se
   hace mal, Teams ralentiza la app también para quien no tiene equipo.
5. **La cuota de `tasks_total`** (§5.4). Rompe al asistente la primera vez que se asigna en
   volumen. Tiene que estar arreglado **antes** de la fase 2, no en la fase 3, si se va a
   probar con gente real.
6. **`DASHBOARD_QUERY`.** No meter teams ahí (heredado de la v1, sigue vigente).
7. **Doble mantenimiento web/móvil.** No hay capa compartida y no puede haberla sin montar
   antes infraestructura de monorepo: son tres repos git hermanos. Todo lo de Teams se
   escribe dos veces. Presupuestarlo.

---

## 12. No-goals de la v1

- Colaboración en tiempo real o edición concurrente.
- Hilos de comentarios o chat entre usuarios.
- Compartir el **workspace personal** de un miembro (decisión #2).
- Jerarquía Org → varios Teams anidados. Un nivel: el Team es el tenant facturable.
- Comprar o gestionar asientos desde el móvil (§5.6).
- **Loop consciente del equipo** (§6).
- Roles `admin` y `viewer` (§1.4).
- Privacidad por ítem. La única frontera es equipo/personal; no hay `is_private` por fila.

---

## 13. Sub-decisiones tácticas pendientes (⚠️)

De la v1 quedan resueltas: los roles (§1.4 — dos), la identidad (§4.1 — tabla `UserProfile`)
y los asientos al invitar (§5.5 — bloquear, no auto-incrementar). Siguen abiertas:

1. **Cuotas de equipo** (§5.4): `tasks_per_team` / `projects_per_team` configurables por
   `AppConfig` vs. ∞ dentro del paquete de asientos.
2. **Onboarding del invitado**: si quien recibe la invitación no tiene cuenta, `acceptInvite`
   tiene que encadenar el signup de Supabase. Hay que definir ese flujo (y el correo va por
   Resend, que ya está montado y **arranca en `dry_run`**).
3. **Un miembro en varios teams**: está soportado por el modelo, pero falta decidir la UX del
   selector de team y qué pasa cuando dos asientos le conceden planes distintos
   (`effective_plan` debe quedarse con el mejor; hay que testearlo).
4. **`Activity` y `team_id`** (§4.5): derivar vs. desnormalizar. Medir en la fase 2.
5. **Precio.** No hay ninguno definido. Los paquetes de asientos necesitan importes en
   `settings` (`PRICE_TEAMS_*_AMOUNT_CENTS`) y texto en los dos idiomas, y cualquier número
   que se elija tiene que entrar en la tabla de paridad de
   [`../integracion-pagos-web-y-movil.md`](../integracion-pagos-web-y-movil.md) §1.
