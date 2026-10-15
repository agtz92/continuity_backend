# Crews — Plan de implementación (v3)

> **Pagos, precios y suscripciones — fuente de verdad:** [`../integracion-pagos-web-y-movil.md`](../integracion-pagos-web-y-movil.md).
> Planes, precios y copy del producto de equipo: [`PLANES.md`](PLANES.md).

> **⚑ ESTADO (2026-09-15): PROPUESTA v3.** Reemplaza la v2 del 2026-09-14, que a su vez
> reemplazó la v1 de junio. Código verificado por lectura directa. **Nada está implementado.**

> **Concepto.** Un usuario crea un **Crew** y invita a otros. Es un **producto aparte con
> su propia suscripción**, que no toca el plan personal de nadie. Dentro, un **lead** ve el
> tablero de equipo de cada miembro, reparte trabajo y conduce la **Revisión**, el ritual
> semanal donde cada proyecto sale con una decisión. El **espacio personal de cada persona
> sigue siendo invisible para todos.** Es el primer acceso cruzado entre usuarios de
> Continuity: el grueso del riesgo está en la frontera de seguridad, no en las pantallas.

## Qué cambia respecto a la v2

La v2 se escribió antes de tres decisiones que la invalidan en sus partes de cobro y de IA.

| # | v2 | v3 | Por qué |
|---|---|---|---|
| 1 | "Team" | **"Crew"** en modelos y rutas | Es el nombre del producto. Nombra al grupo y al espacio con la misma palabra, que es como lo dice un builder, y deja "team" libre para hablar de la gente. |
| 2 | El asiento concede el plan `studio` | **El crew tiene su propia suscripción** y no toca `AccountProfile.plan` | Evita las siete tablas de lookup que rompe un plan nuevo, y evita que el dueño pague IA para su equipo. §5. |
| 3 | Loop fuera del crew | **El Loop personal lee o escribe en el crew según el plan personal** | La IA la paga cada quien. Dos puertas: el plan dice qué herramienta tienes, el rol dice qué alcanza. §6. |
| 4 | Cementerio fuera (personal por naturaleza) | **Cementerio compartido, y es un destino más** | Matar junto es la tesis del producto. §4.7. |
| 5 | Sin ritual | **La Revisión del equipo**, pieza nueva y la más grande | Es lo único que compra Duo. §4.6. |
| 6 | Pulso con marcador por persona | **Pulso habla del trabajo, nunca de la persona** | §1.7. |

---

## 0. Cómo leer este documento

- **Decidido**: acordado con el dueño.
- **Propuesta**: recomendación mía, sin validar.
- **Abierto**: sin recomendación firme; necesita decisión.

---

## 1. El producto

### 1.1 En una frase

**Un jefe reparte trabajo, ve qué se está enfriando, y una vez por semana el equipo decide
qué sigue vivo.**

### 1.2 Los dos espacios *(decidido)*

Cada persona tiene dos espacios, y la frontera entre ellos es un predicado, no una lista de
permisos:

```
BOARD DE EQUIPO                      ESPACIO PERSONAL
crew_id = <el crew>                  crew_id IS NULL

proyectos, tareas y actividad        sus proyectos, tareas, ideas,
del equipo                           rutinas y notas

El lead lo ve COMPLETO               NADIE más lo ve. Nunca.
```

Dos consecuencias que se leen mal si no se dicen:

- **Tu trabajo del equipo sí aparece en tu Hoy personal**, etiquetado con el código del
  crew. La frontera es sobre **quién te ve** y **contra qué cuota cuenta**, no sobre
  esconderte tu propio trabajo.
- **El filtro lleva siempre las dos condiciones juntas**, `user_id__in=...` **y**
  `crew_id=...`. La segunda no es redundante: es lo único que impide que un lead vea el
  trabajo que su asistente hace para otro crew. Alguien con dos jefes es el caso normal.

### 1.3 Pulso: el diferenciador *(decidido)*

Continuity ya calcula, en un solo sitio, cuántos días lleva un proyecto sin moverse y en qué
tramo cae (`core/services/cooling.py`: templado 0-7, enfriándose 8-21, frío 22+), ya marca
como `stalled` lo que lleva 14 días quieto (`services/stalled.py`, cron horario) y ya deriva
"atorado" de tener una tarea abierta con un blocker sin resolver.

**Nada de eso se vuelve a escribir.** Aplicado al board de equipo sale una pantalla que
ningún competidor tiene: qué empezó tu equipo y nadie ha tocado en dos semanas.

En Table, **cada miembro recibe su propio Pulso** antes de que el lead pregunte. Ese es el
producto: el lead deja de perseguir.

### 1.4 La Revisión del equipo *(decidido que se construye; el alcance es propuesta)*

**Es una pieza nueva.** No extiende nada existente y no depende de la sección "Sunday Review"
del sitio, que es material de marca y se queda como está.

Una vez por semana, a la hora que el crew elija, se abre una Revisión. Lista los
proyectos del crew que piden decisión y cada uno sale con una: **sigue, se pausa o se
mata**, reusando los campos de cierre que ya existen en `Project`. Termina con un registro de
qué se decidió y por quién.

- **En Duo** la conduce el lead y los dos ven el resultado.
- **En Table** cada miembro contesta su parte cuando quiera y **el lead abre una Revisión ya
  contestada**. La decisión sobre un proyecto la toma quien hace el trabajo.

**No es un correo.** El correo, el Telegram o el push son la invitación a abrirla, nunca el
contenido. Un digest semanal no sostiene a Duo (ver `PLANES.md` §1.6).

### 1.5 Roles *(decidido)*

Dos, y la propiedad no es un rol.

| Rol | Qué puede |
|---|---|
| **`lead`** | Ver el board de equipo de cualquier miembro · asignar directo · conducir la Revisión · invitar, quitar y cambiar roles |
| **`member`** | Ver **su** board y los proyectos del equipo donde participa · **proponer** tareas · declarar algo atorado con su razón · decidir el estado de lo suyo en la Revisión |

**El dueño es `Crew.user_id`**, no un rol: es quien paga, quien puede borrarlo y quien
siempre tiene además rol `lead`. Puede haber varios `lead`; dueño hay uno.

`admin` y `viewer` quedan fuera a propósito. Añadir un rol es una fila en un enum. Quitarlo
cuando ya hay gente asignada, no.

### 1.6 Asignación bidireccional asimétrica *(decidido)*

| Quién a quién | Qué pasa |
|---|---|
| `lead` a cualquiera | **Directo.** La tarea nace en la lista del asignado. |
| `member` a cualquiera (incluido un lead) | **Propuesta.** El destinatario acepta o rechaza. |

**Una propuesta no es una `Task`.** Es una fila de `TaskProposal`. La alternativa, una `Task`
en estado `proposed`, obligaría a filtrar ese estado en el dashboard, en Today, en Tasks, en
el calendario y en las doce tools de lectura del asistente; olvidarlo en uno solo mete tareas
ajenas en la vista de alguien. Con tabla aparte, **la invariante "toda `Task` de la base
pertenece a quien la tiene" queda intacta** y no se toca ni una query existente. Al aceptar se
llama al `create_task()` de siempre, que es donde ya vive la comprobación de cuota.

### 1.7 Dos restricciones de diseño *(decididas)*

**1. Pulso habla del trabajo, nunca de la persona.** "Este proyecto lleva 14 días quieto", no
"Ana no ha tocado nada". Sin esto el producto se vuelve un tablero de vigilancia, que es lo
contrario de la marca.

En la práctica: la **carga** se puede mostrar ("Ana tiene 11 cosas abiertas" describe reparto
de trabajo), las **vencidas por persona no** (califican a la persona). Regla para quien
implemente: *si la frase se puede leer en voz alta en una junta sin que alguien se sienta
señalado, pasa.*

**2. El miembro tiene agencia desde Micro.** Puede proponer trabajo, declarar algo atorado con
su razón, y decidir el estado de lo suyo. Si el asiento 2 siente que la app es el látigo del
jefe, no entra, y un producto de dos asientos donde uno no entra se cancela solo.

---

## 2. Decisiones de producto cerradas

| # | Decisión |
|---|---|
| 1 | Dirección B2B, producto aparte con suscripción propia |
| 2 | Privacidad: dos espacios (§1.2) |
| 3 | Asignación modelo B: la tarea nace con `user_id` del asignado |
| 4 | Asignación bidireccional asimétrica (§1.6) |
| 5 | Roles `lead` + `member` (§1.5) |
| 6 | El crew **no vende IA** (§6) |
| 7 | Pulso completo desde Micro; lo que acota Micro es el tamaño |
| 8 | Lo que compra Duo es la Revisión; lo que compra Table es dejar de perseguir |
| 9 | Cementerio compartido desde Micro, como destino propio |
| 10 | Pulso habla del trabajo, nunca de la persona (§1.7) |
| 11 | **Loop no contesta ni cierra una Revisión** (§6) |

---

## 3. Principio rector: el crew es una capa de acceso

Continuity es mono-usuario por diseño: `TimestampedModel.user_id` en cada tabla, cada query
del service layer hace `filter(user_id=...)`, no hay modelo `User` de Django (auth = JWT de
Supabase) y RLS está habilitado (`0011_enable_rls`) pero **la defensa real es el filtro del
ORM**.

No se migra nada a `crew_id` como llave de tenencia ni se introduce una jerarquía. El
crew se monta **encima**: los datos siguen perteneciendo a un `user_id`, y el acceso
cruzado se concede solo vía membresía más un autorizador explícito.

### 3.1 La invariante de seguridad, y cómo se hace imposible romperla

> **El conjunto de `user_id` que toca cualquier query se deriva siempre de una llamada a
> `assert_crew_access` en la misma función. Nunca del input de la petición.**

La disciplina no sostiene eso durante dos años de cambios, así que se hace estructural con un
objeto que **solo el autorizador puede construir**:

```python
# core/services/crews.py
@dataclass(frozen=True)
class CrewScope:
    """Prueba de que el solicitante puede leer a estos usuarios en este crew.

    Solo `assert_crew_access` la construye. Toda funcion que lee datos de
    otro usuario la exige como parametro, asi que es imposible escribir una
    lectura cruzada sin haber pasado por la autorizacion: no compila, y no hace
    falta recordarlo en la revision de codigo.
    """
    crew_id: uuid.UUID
    member_ids: tuple[uuid.UUID, ...]
    capability: str


def assert_crew_access(requesting_user_id, *, crew_id,
                            target_user_id=None, capability) -> CrewScope:
    # 1) miembro activo del crew?            si no -> FORBIDDEN
    # 2) su rol permite `capability`?             si no -> FORBIDDEN
    # 3) si hay target: miembro del MISMO?        si no -> FORBIDDEN
```

Y la segunda mitad:

> **Los servicios existentes (`projects.py`, `tasks.py`, `ideas.py`) nunca aprenden qué es un
> crew.** No ganan un parámetro de usuario objetivo, no ganan un `if crew`. Siguen
> recibiendo un `user_id` y filtrando por él.

Todo el acceso cruzado vive en **un módulo nuevo, `core/services/crew_views.py`**, que
resuelve el scope en el borde y luego consulta. Un solo archivo que auditar.

**Matriz de capabilities:**

| Capability | `lead` | `member` |
|---|:--:|:--:|
| `VIEW_MEMBER_BOARD` | Sí | No |
| `VIEW_CREW` | Sí | Sí |
| `ASSIGN_DIRECT` | Sí | No |
| `PROPOSE` | Sí | Sí |
| `RUN_REVIEW` (abrir y cerrar la Revisión) | Sí | No |
| `ANSWER_REVIEW` (decidir lo suyo) | Sí | Sí |
| `MANAGE_MEMBERS` | Sí | No |
| `MANAGE_BILLING` | solo el dueño | No |

---

## 4. Backend

Todo en la app `core`, con el reparto de schema que documenta [`../../CLAUDE.md`](../../CLAUDE.md).

### 4.1 Modelos nuevos

```python
class CrewRole(models.TextChoices):
    LEAD   = "lead", "Lead"
    MEMBER = "member", "Member"


class Crew(TimestampedModel):        # user_id = el dueno (paga y puede borrarlo)
    name = models.CharField(max_length=120)
    class Meta:
        indexes = [models.Index(fields=["user_id"])]


class CrewMembership(models.Model):
    crew = models.ForeignKey(Crew, on_delete=models.CASCADE,
                                 related_name="memberships")
    user_id   = models.UUIDField(db_index=True)
    role      = models.CharField(max_length=16, choices=CrewRole.choices)
    status    = models.CharField(max_length=16, default="active")   # active | removed
    joined_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["crew", "user_id"],
                                               name="uniq_member_per_crew")]
        indexes = [models.Index(fields=["user_id", "status"])]   # "mis crews", caliente


class CrewInvitation(models.Model):
    crew   = models.ForeignKey(Crew, on_delete=models.CASCADE,
                                    related_name="invitations")
    email       = models.EmailField()
    role        = models.CharField(max_length=16, choices=CrewRole.choices,
                                   default=CrewRole.MEMBER)
    token_hash  = models.CharField(max_length=64, unique=True)   # sha256, NO el token
    expires_at  = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    invited_by_user_id = models.UUIDField()


class TaskProposal(TimestampedModel):     # user_id = el destinatario (quien acepta)
    crew     = models.ForeignKey(Crew, on_delete=models.CASCADE,
                                      related_name="proposals")
    from_user_id  = models.UUIDField(db_index=True)
    title         = models.CharField(max_length=500)
    note          = models.CharField(max_length=500, blank=True, default="")
    due_date      = models.DateTimeField(null=True, blank=True)
    effort_hours  = models.FloatField(null=True, blank=True)
    project       = models.ForeignKey("Project", null=True, blank=True,
                                      on_delete=models.SET_NULL)
    status        = models.CharField(max_length=16, default="pending")  # pending|accepted|declined
    resolved_at   = models.DateTimeField(null=True, blank=True)
    created_task  = models.ForeignKey("Task", null=True, blank=True,
                                      on_delete=models.SET_NULL)


class UserProfile(models.Model):
    """Identidad minima para pintar una lista de miembros sin N+1 contra Supabase."""
    user_id      = models.UUIDField(primary_key=True)
    email        = models.CharField(max_length=320, blank=True, default="")
    display_name = models.CharField(max_length=120, blank=True, default="")
    avatar       = models.CharField(max_length=64, blank=True, default="")
    updated_at   = models.DateTimeField(auto_now=True)
```

**`token_hash`, no `token`.** El repo ya decidió guardar hasheados los códigos de OAuth del
conector "so a DB leak can't replay them". Una invitación es la misma clase de credencial de
un solo uso. El token en claro solo existe en el correo.

**`UserProfile`, tabla y no `get_users_map` on-demand.** El patrón best-effort que usan
`feedback` y `adminUsers` hace una llamada HTTP a Supabase y **devuelve "" si no hay service
role key**. Aceptable en un panel de admin, inaceptable en una pantalla de uso diario.

### 4.2 Cambios aditivos en `Project` y `Task`

```python
# Project y Task
crew = models.ForeignKey(Crew, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="projects")  # / "tasks"

# Solo Task
assigned_by_user_id = models.UUIDField(null=True, blank=True)
```

**`crew` también en `Project`.** Sin eso no hay board: Continuity es un producto centrado
en proyectos, y el enfriamiento se calcula sobre proyectos.

**`SET_NULL` en ambos:** borrar un crew **no borra el trabajo de nadie**, lo devuelve al
espacio personal de su dueño. Misma decisión que ya se tomó para `QuickNote.category`.

> **Migración:** aditiva (dos columnas nulables, una más en `Task`, y las tablas nuevas). Si
> toca SQL crudo de Postgres, usar `migrations/_pg.postgres_only()`, que pasa `params=None`
> para que psycopg3 no interprete los `%I` de `format()` como placeholders.

### 4.3 La frontera: `core/services/crew_views.py`

El único módulo autorizado a consultar datos de un `user_id` que no es el del solicitante.
Toda función pública empieza por `assert_crew_access`.

```python
def member_board(requesting_user_id, *, crew_id, member_id) -> BoardData:
    scope = assert_crew_access(requesting_user_id, crew_id=crew_id,
                                    target_user_id=member_id,
                                    capability=Capability.VIEW_MEMBER_BOARD)
    return _board(scope, member_ids=(member_id,))


def pulse(requesting_user_id, *, crew_id, only_self=False) -> Pulse:
    """Pulso. `only_self=True` es el Pulso propio del miembro (Table)."""
```

Y el filtro, **siempre con las dos condiciones**:

```python
Project.objects.filter(user_id__in=scope.member_ids, crew_id=scope.crew_id)
```

### 4.4 Asignación y propuestas — `core/services/crews.py`

```python
def assign_task(requesting_user_id, *, crew_id, to_user_id, **fields) -> Task:
    scope = assert_crew_access(..., capability=Capability.ASSIGN_DIRECT)
    task = tasks_svc.create_task(to_user_id, **fields)       # el de siempre
    Task.objects.filter(pk=task.pk).update(crew_id=crew_id,
                                           assigned_by_user_id=requesting_user_id)
    log_event(to_user_id, kind=ActivityKind.TASK_ASSIGNED, ...)
    notify_assignment(to_user_id, task, by=requesting_user_id)
    return task

def propose_task(...) -> TaskProposal
def accept_proposal(user_id, *, proposal_id) -> Task     # -> create_task normal
def decline_proposal(user_id, *, proposal_id) -> None
```

`create_task` no cambia de firma.

### 4.5 Pulso — `crew_views.pulse()`

Reúne, sobre `scope.member_ids` y `crew_id`:

- **Enfriándose**: proyectos por tramo de `cooling` y `stalled_at`, con su dueño y su siguiente paso.
- **Atorado**: tareas con blocker abierto, con la razón que escribió quien la declaró.
- **Carga por miembro**: cuántas cosas abiertas tiene cada quien. **Sin vencidas por persona**
  (§1.7).
- **Propuestas pendientes** dirigidas al solicitante.

`only_self=True` devuelve lo mismo acotado al propio miembro: es el Pulso propio de Table.

### 4.6 La Revisión del equipo

La pieza más grande y la única sin precedente en el código.

```python
class Review(models.Model):
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4)
    crew    = models.ForeignKey(Crew, on_delete=models.CASCADE,
                                     related_name="reviews")
    period_start = models.DateField()
    period_end   = models.DateField()
    status       = models.CharField(max_length=16, default="open")   # open | closed
    #: closed_by en NULL = la cerro el tiempo, no una persona.
    opened_at    = models.DateTimeField(auto_now_add=True)
    closed_at    = models.DateTimeField(null=True, blank=True)
    closed_by_user_id = models.UUIDField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["crew", "period_start"],
                                               name="uniq_review_per_period")]


class ReviewEntry(models.Model):
    """Un proyecto dentro de una Revision, y la decision de su dueno."""
    review        = models.ForeignKey(Review, on_delete=models.CASCADE,
                                      related_name="entries")
    project       = models.ForeignKey("Project", on_delete=models.CASCADE)
    member_user_id = models.UUIDField(db_index=True)
    decision      = models.CharField(max_length=16, default="pending")
    #: pending -> keep | pause | kill | unanswered (lo pone el cierre por tiempo)
    answered_at   = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["review", "project"],
                                               name="uniq_entry_per_project")]
```

**Qué es una Revisión, exactamente.** De esto depende la respuesta a "qué pasa si nadie la
cierra", así que va primero.

> **Una Revisión es un periodo, no una junta.**

Es la diferencia que lo decide todo. Una junta necesita que alguien la termine; un periodo
termina solo. Y **el producto entero existe porque las cosas que dependen de que un humano las
concluya se quedan a medias.** Si el mecanismo que cierra loops puede a su vez quedarse
abierto, el mecanismo contradice la tesis.

De ahí salen cuatro reglas:

1. **Se abre sola** a la hora que el crew configuró, desde el cron horario.
2. **La lista de proyectos se congela al abrirse.** Lo que se cree después espera a la
   siguiente. Si la lista creciera mientras la contestas, nunca se termina.
3. **Se cierra sola** al llegar `period_end`, o al abrirse la siguiente si el cron se saltó una
   vuelta. **Nadie tiene que cerrarla.**
4. **Lo que nadie contestó caduca con el periodo**, marcado `unanswered`. **No se arrastra.**

**Por qué no se arrastra**, que es la parte contraintuitiva: arrastrar lo no contestado hace
que la siguiente Revisión sea más larga, y una más larga se salta con más facilidad. A las tres
semanas tienes un backlog de rituales, que es exactamente la deriva contra la que se vende el
producto.

**Y no hace falta arrastrar nada, porque el criterio vuelve a elegirlo.** Un proyecto que nadie
decidió sigue activo, así que entra solo en la Revisión siguiente. Mientras tanto se enfría, y
el enfriamiento ya se ve en Pulso sin que la Revisión tenga que recordarlo. La presión la pone
el mecanismo que ya existe, no una pila que crece.

> **La pregunta se disuelve:** que nadie la cierre no es un fallo. Es una semana en la que
> nadie decidió, y el producto ya tiene cómo mostrarlo: esos proyectos aparecen más fríos.

**Quién la cierra.** Nadie tiene que hacerlo, pero el lead *puede* cerrarla antes de tiempo
**solo si todas las entradas están contestadas**. Es el gesto de "ya terminamos", no un
trámite: si falta una respuesta, el botón no está. `closed_by_user_id` en `NULL` significa que
la cerró el tiempo.

> ⚠️ **Propuesta:** contar las veces seguidas que un proyecto queda `unanswered` y mostrarlo en
> Pulso ("lleva 3 revisiones sin que nadie decida"). Convierte el no-evento en señal y cuesta
> una consulta.

**Qué proyectos entran.** Los del crew en estado `active` o `stalled`: los que piden decisión.
No entran las `idea` (todavía no son un compromiso) ni lo ya decidido (`paused`, `killed`,
`launched`, `archived`).

**Cómo se contesta** *(propuesta)*:

- **Una a la vez, no en lista.** Una lista se hojea, se contesta en diagonal y se sale. De una
  en una el ritual conserva su función, que es obligarte a mirar cada cosa.
- **"Sigue" exige un siguiente paso nuevo.** Si no lo exige, "sigue" es el botón que todo el
  mundo aprieta para salir del trámite y la Revisión se vuelve teatro. Un proyecto sin
  siguiente paso no sigue: está pausado y todavía no lo has dicho.
- `pause` y `kill` abren los campos de cierre que ya existen en `Project`.
- La pantalla trae el contexto que la app ya sabe (último movimiento, siguiente paso viejo con
  su antigüedad, qué está atorado) para no preguntar lo que se puede mirar.

**Servicio** `core/services/reviews.py`:

- `open_review(crew_id, period)`: crea la Revisión, congela sus entradas, y **cierra cualquier
  Revisión anterior que siguiera abierta**, marcando sus pendientes como `unanswered`.
  Idempotente por la restricción única de periodo, igual que los digests.
- `answer(user_id, entry_id, decision, **closure)`: **el miembro decide lo suyo.** `pause` y
  `kill` delegan en los servicios de proyecto que ya existen, con sus campos de cierre
  (`paused_context`, `paused_next_action`, `killed_reason`, `killed_learnings`). La Revisión no
  reimplementa el cierre, lo invoca.
- `close_review(lead_id, review_id)`: cierre anticipado. Rechaza si queda alguna entrada
  `pending`.
- `expire_due_reviews()`: lo que corre en el cron y cierra por tiempo.

**Cadencia:** día y hora por crew, con el mismo patrón que `NotificationSettings`. El cron
horario abre la Revisión a la hora local del crew y manda la invitación, que es un aviso y no
el contenido.

**Autorización:** abrir es del sistema. Cerrar antes de tiempo exige `RUN_REVIEW` (lead).
Contestar exige `ANSWER_REVIEW` **y** que la `ReviewEntry` sea del propio `member_user_id`.
**Un lead no contesta por otro**, y eso es el test 16 de §12.

### 4.7 Cementerio compartido *(decidido)*

Los proyectos del crew con `status="killed"`, con su razón. **Destino propio** en la
navegación, no un filtro dentro de Proyectos, por consistencia: en el espacio personal el
Cementerio es una vista propia y quien conoce la app lo busca donde siempre está.

**Aquí la razón es obligatoria.** En el espacio personal `killed_reason` puede quedar vacío. En
un crew no: matar algo que otros veían pide una línea que explique por qué, y esa línea **es el
contenido de la pantalla**. Sin ella el cementerio es una lista de lápidas sin epitafio.

**La fila invierte la jerarquía de una lista normal.** En una lista el título es el contenido;
aquí el título es lo que murió y lo que se lee es la razón. Contrato visual:

| Elemento | Cómo |
|---|---|
| Título | Tinta apagada y **tachado**. `spineStrikesTitle` ya devuelve `true` para `killed`. |
| Razón | **Tamaño de cuerpo, entre comillas.** Es el contenido, no un metadato. |
| Aprendizaje | Debajo, en tinta más apagada, si se escribió. |
| Espina | `--line-22` sólida, **la misma que archivado**. Lo único que los distingue es el tachado. |
| Quién y cuándo | Avatar y fecha, a la derecha. |

**"Vivió 68 días · murió con 4 tareas abiertas".** Sale de `created`, `killed_at` y el conteo
de tareas abiertas al morir. Es el dato más específico que puede dar la pantalla y hace la
muerte del proyecto concreta **sin reprochársela a nadie**: la frase habla del proyecto.

> **Atribuir quién lo mató no rompe §1.7.** Registrar quién tomó una decisión no es lo mismo
> que contar las vencidas de alguien. Un equipo necesita saber quién hizo la llamada: eso es
> memoria, no vigilancia.

**Agrupado por tiempo** (este mes / antes), no por persona ni por proyecto. Es un registro.

**Revivir.** Lo puede hacer un `lead` o el dueño del proyecto. Reusa el flujo de revivir que ya
existe.

**La misma muerte aparece en dos sitios, y está bien.** Un proyecto de crew tiene `crew_id`
puesto pero su `user_id` sigue siendo de una persona, así que al matarlo entra en el cementerio
compartido **y** en el personal de quien lo tenía, por la misma regla de §1.2 que hace que su
trabajo de equipo aparezca en su Hoy. En el personal sí alimenta su autopsia de IA; en el
compartido no.

**El compartido no incluye autopsia de IA.** Hoy la reflexión cruzada está gateada a Pro o
superior (`_AUTOPSY_PLANS` en `core/services/autopsy.py`) porque cuesta dinero producirla. El
cementerio del crew es **el registro**, y la lectura del patrón sigue viniendo del plan personal
de cada quien (§6).

> **La pantalla lo dice en voz alta.** Sin esa línea, el primero que entre va a preguntar dónde
> está la autopsia que sí tiene en su espacio personal, y la ausencia se va a leer como un bug.

### 4.8 Activity

Nuevos `ActivityKind`: `CREW_CREATED`, `MEMBER_JOINED`, `MEMBER_REMOVED`,
`TASK_ASSIGNED`, `TASK_PROPOSED`, `TASK_PROPOSAL_ACCEPTED`, `REVIEW_OPENED`, `REVIEW_CLOSED`.

`Activity` **no gana una columna `crew_id`**: se deriva del proyecto o la tarea que ya
referencia. Una columna más serían dos fuentes de verdad sobre "¿esto es del equipo?".

> **Verificar en la fase 2:** si ese cruce resulta caro (Activity es la tabla más grande),
> desnormalizar y aceptar el costo de mantenerlo. Medir antes de decidir.

Los kinds nuevos van al i18n del Log en **los dos clientes**.

### 4.9 Notificaciones

Nuevos `NotificationKind`: `CREW_ASSIGNMENT`, `CREW_PROPOSAL`, `REVIEW_OPEN`.

**No hace falta infraestructura nueva.** `dispatcher.enqueue()` crea la fila del outbox *e
intenta la entrega en el momento*, así que una asignación llega al instante. Push (Expo) está
encendido desde el 11 de septiembre y Telegram lleva vivo desde la fase 1 de notificaciones.

### 4.10 Schema GraphQL

- **Tipos e inputs** → `core/schema_types.py`: `Crew`, `CrewMember`,
  `CrewInvitation`, `TaskProposal`, `Pulse`, `Review`, `ReviewEntry`; extender `Task` con
  `crewId` y `assignedBy`.
- **Mutations** → `core/schema_mutations.py` con `@gql_error_handler`: `createCrew`,
  `renameCrew`, `deleteCrew`, `inviteMember`, `acceptInvite`, `removeMember`,
  `changeMemberRole`, `assignTask`, `proposeTask`, `acceptProposal`, `declineProposal`,
  `setTaskCrew`, `setProjectCrew`, `answerReviewEntry`, `closeReview`.
- **Queries** → `core/schema.py`, **fuera de `dashboard`**: `myCrews`, `crew(id)`,
  `memberBoard(crewId, memberId)`, `pulse(crewId, onlySelf)`, `currentReview`,
  `crewGraveyard`, `myProposals`.

> **Riesgo heredado y vigente:** no meter nada de crews en `DASHBOARD_QUERY`. Ese
> resolver es el round-trip único de arranque; añadirle una query de membresía le cuesta a los
> usuarios sin crew lo mismo que a los que sí lo tienen. Carga lazy, como Quick Notes.

### 4.11 Admin

Listar crews, asientos ocupados, estado de la suscripción. Con `_admin_user_id(info)` y
`audit_record(action="crew.*", target_type="crew")`.

---

## 5. Suscripción y cuotas del crew

### 5.1 Fila propia, no `AccountProfile`

```python
class CrewPlan(models.TextChoices):
    MICRO = "micro", "Micro"
    DUO  = "duo",  "Duo"
    TABLE = "table", "Table"
    GUILD = "guild", "Guild"


class CrewSubscription(models.Model):
    crew  = models.OneToOneField(Crew, on_delete=models.CASCADE,
                                      related_name="subscription")
    plan       = models.CharField(max_length=16, choices=CrewPlan.choices,
                                  default=CrewPlan.MICRO)
    seats_purchased = models.PositiveIntegerField(default=2)
    # Mismas columnas que AccountProfile, y por la misma razon.
    billing_source         = models.CharField(max_length=16, blank=True, default="")
    billing_customer_id    = models.CharField(max_length=255, blank=True, default="")
    billing_transaction_id = models.CharField(max_length=255, blank=True, default="",
                                              db_index=True)
    billing_product_id     = models.CharField(max_length=255, blank=True, default="")
    plan_renecrew_at         = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end   = models.BooleanField(default=False)
```

**Por qué fila propia y no el enum `Plan` de siempre.** Verifiqué qué hace el código con un
plan que no conoce, y son cuatro tablas de lookup con tres modos de fallo:

| Dónde | Con un plan desconocido | Consecuencia |
|---|---|---|
| `assistant/quotas.py:144` `PLAN_QUOTAS[profile.plan]` | **`KeyError`** (indexación directa) | `/usage/` da 500 y **la app no carga** |
| `quotas.py:210` `ENTITY_QUOTAS.get(kind,{}).get(plan)` | `None`, documentado como "unlimited" | Se regala el producto, en silencio |
| `assistant/tiers.py:52` | `MODE_NONE` | El plan más caro se queda sin Loop |
| `billing/entitlements.py` `_has_live_entitlement` | `False` | La suscripción queda fuera del guard de conflicto entre canales |

Con una fila propia, **ninguna de esas tablas se toca** y el plan personal del dueño sigue
siendo el suyo.

### 5.2 El webhook: un cliente distinto por crew *(propuesta)*

`apply_entitlement()` está construido para **rechazar** una segunda titularidad viva del mismo
usuario: la trata como cobro duplicado, lo escribe en auditoría y descarta una. Si el dueño
tiene Studio personal y compra un crew, eso se dispara.

**La salida más limpia es que el crew sea otro cliente ante el proveedor.** La compra usa
un `app_user_id` propio, `crew_<crew_id>`, en vez del uuid del comprador:

```python
# core/billing/store_webhooks.py  (_parse_user_id, hoy devuelve un UUID o None)
#   "crew_<uuid>"  -> titularidad de crew  -> CrewSubscription
#   "<uuid>"     -> titularidad personal      -> AccountProfile
```

Así las dos suscripciones no se ven ni siquiera en el proveedor, y `apply_entitlement` enruta
por prefijo antes de buscar perfil. Sigue siendo **un solo punto de escritura**, con dos
destinos.

Complemento: los ids de producto de crew viven en `catalog.py` con el mismo patrón,
**incluida la lista de ids por plan y periodo** para honrar precios retirados. De eso depende
poder subir el precio de Table más adelante sin tocar a quien ya pagaba (`PLANES.md` §11.3).

### 5.3 Cuotas del crew, separadas de las personales

```python
CREW_QUOTAS = {
    "seats":            {"micro": 2,  "duo": 2,  "table": 10, "guild": None},
    "projects":         {"micro": 3,  "duo": None, "table": None, "guild": None},
    "open_tasks":       {"micro": 50, "duo": None, "table": None, "guild": None},
}
```

En Guild el tope de asientos es `seats_purchased`, no `None`.

**Mismo patrón de límites que ya usa el producto:** nunca se borra nada; pasarse bloquea
crear, no usar; los asientos cuentan como límite bloqueante; el aviso ofrece siempre dos
salidas, subir de plan o ajustar.

### 5.4 El bug de cuota que hay que arreglar **antes** de la primera asignación

`tasks_total` está en `_BLOCKING_KINDS` y su contador es
`Task.objects.filter(user_id=user_id, done=False)`. O sea: **las tareas que el lead asigna
cuentan contra la cuota personal del miembro.** Un asistente en Free (tope 50) con 60 tareas
asignadas queda por encima de un blocking kind, y el efecto no es "no puedes aceptar más
tareas del equipo": es que **no puede crear nada en toda la aplicación**, incluidas sus ideas
privadas.

**Arreglo:** `_count()` excluye el trabajo de crew de los contadores personales
(`.filter(crew_id__isnull=True)` en `tasks_total`, `tasks_per_project` y `projects`).

Esto no es opcional ni se puede posponer a una fase posterior si se va a probar con gente real.

### 5.5 Ciclo de vida

| Movimiento | Qué pasa |
|---|---|
| Subir | Al momento, prorrateado. |
| Bajar | Al renovar. Si el crew excede el plan destino, **no se permite** hasta ajustar. El sistema nunca elige a quién sacar. |
| Cancelar | Pasa a Micro al terminar el periodo. Nada se borra. Si excede Micro, se bloquea crear. |
| Pago fallido | Sigue activo durante la gracia del proveedor (`entitlements.py` ya la trata como activa). Al vencer, como cancelar. |
| **El dueño borra su cuenta** | **Bloqueado** mientras sea dueño de un crew activo. Primero transfiere la propiedad o cancela y borra el crew. |

**Cuando alguien sale del crew:** se pregunta a quién pasar sus tareas y proyectos de ese
crew, con el dueño por defecto, y se guarda quién los tenía antes
(`previous_assignee_user_id`). Nada se mueve solo y nada se va con la persona.

---

## 6. Loop y el conector

**El crew no vende IA.** *(decidido)* Loop viene con el plan personal de cada quien.

**Y lo que ese Loop puede hacer dentro del crew depende de ese plan personal.** *(decidido)*
Se compone limpio, porque son dos preguntas independientes:

> **¿Puedo tocar esto?** lo responde el crew (tu rol).
> **¿Con qué herramienta?** lo responde tu plan personal.

| Plan personal | Modo de Loop | Dentro del crew |
|---|---|---|
| **Free** | `none` | Nada. No hay asistente que abrir. |
| **Pro** | `canned` | **Lee.** Acciones del catálogo determinista acotadas al crew. Se calculan en el servidor, así que no cuestan nada. |
| **Studio** | `llm` | **Lee y escribe**, con las mismas reglas que tendría esa persona a mano. |

**Las dos puertas se cruzan, no se suman.** Un Studio que es `member` en el crew **no puede
asignar**: sus escrituras entran como propuestas, igual que si usara la interfaz. Un `lead` en
Free no tiene Loop en absoluto. El plan nunca concede permisos del crew, y el rol nunca concede
herramientas.

Implementación, con las reglas que la mantienen barata y segura:

- **No se tocan las 44 tools existentes.** Se añaden tools nuevas que reciben un `CrewScope`:
  de lectura (`list_crew_projects`, `crew_pulse`, `list_crew_member_tasks`) y de escritura
  (`assign_crew_task`, `propose_crew_task`, `set_crew_project_state`), estas últimas con
  `plan_required=WRITE_TIER`, que hoy es `studio`.
- **Las tools de escritura llaman al mismo servicio que la interfaz.** `assign_crew_task` pasa
  por `crews.assign_task`, que ya exige `ASSIGN_DIRECT`. Si el rol no alcanza, la tool devuelve
  el mismo error que vería la persona. **No hay un camino de escritura paralelo**, que es lo
  que evita que la IA se convierta en un hueco de permisos.
- **"Mis proyectos" sigue significando los personales.** Si `list_projects` empieza a incluir
  los del crew en silencio, cambia la respuesta de todo el mundo, incluido el catálogo
  determinista y el conector. El crew se nombra explícitamente o no entra.
- **Invalidar la caché del conector al cambiar una membresía.** `authz.py` cachea el plan por
  TTL; si sacas a alguien y nada invalida, sigue leyendo desde Claude durante esa ventana.

> **La excepción, decidida:** *Loop no contesta ni cierra una Revisión.* Que un modelo decida
> si un proyecto se mata es justo la delegación que no se quiere. Loop puede prepararla,
> resumirla y recordártela; la decisión la firma la persona.
>
> **Se implementa por ausencia, no por comprobación:** no existe una tool que escriba
> `ReviewEntry.decision` ni que llame a `close_review`. Vale igual para el asistente y para el
> conector, porque lo que no está registrado no se puede llamar desde ninguno de los dos.

**El conector MCP sigue su propia política.** `core/mcp/policy.py` filtra por `Tool.mutates`,
no por `assistant_mode`, así que las tools de crew quedan expuestas ahí según esa tabla (hoy:
free y pro leen, studio y admin escriben). Son dos políticas a propósito: el conector gasta la
suscripción de Claude del usuario y el asistente gasta la nuestra. Cambiar una no mueve la otra.

## 7. Entrar a un Crew: el onboarding

El onboarding personal (5 pasos: nombre, tema, avatar, plan, personalizar Today) **no se
toca**. Este es otro, y el motivo es que **por la puerta del Crew entran dos personas
distintas con problemas opuestos**: quien lo crea necesita llenarlo, y quien es invitado
necesita entender qué acaba de aceptar.

### 7.1 Crear un Crew: una lista derivada, no un asistente de pasos

**Decisión de diseño *(propuesta)*: no se guarda progreso de onboarding.** Lo que falta se
**deriva** del estado del Crew, igual que el producto ya deriva "atorado" de los blockers y el
enfriamiento de la última actividad.

| Lo que falta | Cómo se sabe |
|---|---|
| Nombre | Siempre lo tiene: se pide al crear. |
| Gente | `CrewMembership` activas < 2 |
| Trabajo | Sin proyectos con `crew_id` |
| Ritual | Sin cadencia de Revisión configurada |

Tres cosas salen gratis de derivarlo:

1. **No hay migración ni estado que se desincronice.** Un asistente de pasos guarda "paso 3
   completado" y miente en cuanto alguien borra el único proyecto.
2. **Es re-entrable.** Si el único miembro se va, la lista vuelve sola. Eso es correcto: el
   Crew volvió a estar incompleto.
3. **Es el estado vacío para siempre**, no una pantalla que se ve una vez y se tira.

Lo único que se guarda es `Crew.setup_dismissed_at`, para que quien ya sabe lo que hace pueda
quitarse la tarjeta de encima.

**La lista, en orden:**

1. **Ponle nombre.** Se pide al crear, y de ahí sale el código de dos letras del switch.
2. **Invita a alguien.** Ver §7.2.
3. **Trae trabajo.** Ver §7.3.
4. **¿Cuándo es la Revisión?** Día y hora. Si no se agenda, el ritual no existe, y con él se
   cae lo único que compra Duo.

Termina diciendo la fecha concreta: *"Tu primera Revisión abre el domingo a las 20:00."*

> ⚠️ **Propuesta:** ofrecer **abrir una Revisión ahora mismo**, sin esperar al domingo. Deja
> que el equipo viva el ritual el día uno en vez de a los seis. En contra: con proyectos
> recién traídos no hay nada que decidir, así que enseña la forma pero no la tensión.

### 7.2 Invitar: se puede saltar, pero se dice la verdad

Un Crew de una persona no sirve, y bloquear el flujo hasta que invites es pedirle a alguien que
avale un producto que todavía no ha visto. **No se bloquea.** Se puede saltar, y entonces el
Crew enseña un estado vacío que no regatea:

> **Aquí no hay nadie más.**
> Un Crew de una persona es tu espacio personal con pasos de más. Invita a alguien y esto
> empieza a servir para algo.

Es el pilar honesto de la guía de voz aplicado a un estado vacío: decir para qué no sirve algo
convence más que insistir en para qué sí.

### 7.3 Traer trabajo, no sembrarlo

El onboarding personal **siembra contenido de ejemplo** (`core/services/seed.py`: un proyecto,
tareas, una rutina, una idea y una nota). **Un Crew no se siembra.** *(propuesta)*

Dos razones:

- En un espacio compartido, el contenido falso es peor: la segunda persona que llega no sabe
  qué es de verdad y qué es demo, y lo primero que hace es preguntar.
- **Mover un proyecto que ya existe es el momento "ajá" real.** Pasa de ser tuyo a ser visible
  para otra persona, que es exactamente lo que el producto vende. Un proyecto de ejemplo no
  enseña eso.

Así que el paso 3 ofrece **mover proyectos personales al Crew**, con un selector de los que ya
tienes, y crear uno nuevo como segunda opción. En Micro avisa del tope de 3 antes de mover, no
después.

### 7.4 Ser invitado: la pantalla que decide si entra o no

Es **la pantalla más importante de todo el producto de equipo**, porque es donde alguien decide
si esto es una herramienta o el látigo de su jefe. Si no queda claro, o no entra, o entra
sintiéndose vigilado, y §1.7 dice que un producto de dos asientos donde uno no entra se cancela
solo.

Ruta `/crew/invite/<token>`, y **tiene que funcionar sin sesión iniciada**: quien la abre puede
no tener cuenta todavía.

Lo que muestra, antes de pedir nada:

| | |
|---|---|
| **Quién te invita** | Nombre y avatar, y el nombre del Crew. |
| **Qué van a ver de ti** | Los proyectos y tareas **de este Crew**. Nada más. |
| **Qué no ve nadie** | Tu espacio personal: tus proyectos, ideas, rutinas y notas. Nunca. |
| **Qué puedes hacer tú** | Proponerle trabajo a quien sea, decir qué te tiene atorado, y decidir el estado de lo tuyo en la Revisión. |
| **Si te vas** | Tu trabajo **de este Crew se queda aquí**. Lo tuyo personal se va contigo. |

Esa última fila es la que suele faltar en los productos de equipo y la que duele descubrir
tarde. Va escrita desde el principio.

### 7.5 El invitado que no tiene cuenta

El caso que en la práctica mata las invitaciones de equipo. Encadenar aceptar → alta →
onboarding personal de 5 pasos → por fin el Crew es demasiado para alguien que solo quería ver
lo que su jefe le mandó.

**Propuesta: el onboarding personal se aplaza, no se salta.**

1. Acepta la invitación y se da de alta (Supabase). Lo mínimo: correo y contraseña, y su nombre.
2. **Aterriza directo en el Pulso del Crew.**
3. El resto del onboarding personal (tema, avatar, plan, personalizar Today) aparece **la
   primera vez que abre su espacio personal**, no antes.

> ⚠️ **Esto sí toca código existente**, y hay que decirlo: hoy el onboarding personal bloquea
> la app hasta completarse. Hace falta que `OnboardingProgress` distinga "pendiente porque
> acaba de llegar por invitación" de "pendiente porque no lo ha hecho", y que el gate no se
> dispare en las rutas del Crew. Es el único punto de este plan que modifica un flujo que ya
> funciona.

**Y el plan del invitado es Free**, con todo lo que eso implica: sin Loop, con sus cuotas
personales intactas. Trabaja en el Crew con lo que pagó el dueño (§1.2 de `PLANES.md`) sin que
nadie le venda nada el primer día.

### 7.6 Sin tour propio

La app tiene un tour de diez pasos que recorre cada sección. **El Crew no lleva uno.**
*(propuesta)*

Sus dos conceptos nuevos, Pulso y la Revisión, se entienden haciéndolos una vez, no viendo una
flecha que los señala. Y sus siete destinos ya tienen estado vacío. Si más adelante hace falta,
el tour del repo es *data-driven*: añadir un paso es una entrada en `steps.ts` y dos claves de
i18n, sin tocar componentes.

### 7.7 Dónde vive

| Qué | Dónde |
|---|---|
| Crear un Crew | `/settings/crews/new` |
| La lista derivada | Tarjeta en el Pulso del Crew, hasta completarse o descartarse |
| Aceptar invitación | `/crew/invite/<token>`, funciona sin sesión |
| Móvil | `(dashboard)/(more)/crew-new.tsx` y la invitación por deep link |

## 8. Web (Next.js + Apollo)

**Dos superficies.**

| Superficie | Dónde | Qué hay |
|---|---|---|
| **Gestión** | `/settings/crews` | Crear y renombrar, miembros, roles, invitaciones, asientos, cobro |
| **Uso diario** | `/dashboard/c/<slug>` | Pulso, proyectos, tareas, calendario, cementerio, registro, miembros |

**Navegación: siete destinos contra los diez del espacio personal.**

```
Equipo     Pulso · Miembros
Trabajo    Proyectos · Tareas · Calendario     (+ Atorado, el unico contador con color)
Registro   Cementerio · Log
```

Ausentes a propósito: **Hoy, Rutinas, Ideas, Notas** (personales por naturaleza) y
**Analítica** (Pulso y la Revisión son la analítica que importa). **La lista más corta es la
señal**: no hace falta cambiar de color para saber dónde estás.

- **URL:** el espacio personal se queda en `/dashboard` y el crew es
  `/dashboard/c/<slug>`. Ningún enlace existente se rompe y "personal es el default" queda
  impuesto por la forma de la ruta. La ruta catch-all `[[...slug]]` ya lo absorbe: es un
  segmento más en `lib/dashboardRoutes.ts`.
- **Chasis:** `[data-surface="crew"]` redeclara el juego completo de tokens, exactamente
  como ya hacen `[data-admin="true"]` y `[data-surface="marketing"]`. El fondo sube de `--bg`
  a `--surface`.
- **Switch de espacio:** arriba de la barra lateral, con Personal siempre primero. Colapsada
  enseña el código de dos letras, la convención que ya usan los chips de categoría.
- **Acción primaria:** el botón de captura cambia de significado, no de lugar. "+ Asignar
  tarea" para el lead, "+ Proponer tarea" para el miembro.
- **Componentes** (`src/components/crew/`): `CrewSwitcher`, `MemberList`,
  `InviteSheet`, `Pulse`, `MemberBoard`, `AssigneeSelect`, `ProposalInbox`, `ReviewSheet`,
  `MemberAvatar`.
- **`MemberAvatar`:** iniciales de dos letras, 22px, tinta apagada. A la derecha en listas de
  trabajo, a la izquierda en listas de personas. **Tooltip con el nombre completo** (`title`)
  **y `aria-label` con el mismo nombre**: el `title` no lo anuncia un lector de pantalla ni
  llega por teclado, que es el aviso que ya deja `Spine.tsx` sobre el suyo. Si es clickeable,
  el nombre aparece también en foco.
- **Rediseño:** las filas llevan espina (`Spine`), el enfriamiento se lee en el **contador de
  días**, nunca en la barra, y el asignado es metadato, no una pastilla de color.
- **i18n:** namespace `crew.*` en los dos idiomas, y el guardarraíl de `messages.test.ts`
  en verde. Las reglas completas en §10.

## 9. Móvil (Expo) — espejo, no encogimiento

Lo que cambia en móvil no es el tamaño: es **dónde va cada cosa**.

### 9.1 El chasis

- **El switch de espacio va en el header, nunca en la `BottomTabBar`.** Esa barra es para
  vistas; el espacio es contexto. Mezclarlos hace que cambiar de Crew se sienta como cambiar
  de pestaña.
- **La barra de abajo tiene distinto número de pestañas en cada espacio**, y eso es señal, no
  descuido: el personal lleva cinco (Hoy, Proyectos, Tareas, Rutinas, Más) y el crew lleva
  cuatro (Pulso, Proyectos, Tareas, Más), porque un crew no tiene Rutinas. Es la misma idea de
  "la lista más corta es la señal" de §8, aplicada donde solo caben cuatro iconos.
- Los otros tres destinos del crew (Miembros, Cementerio, Log) viven en la hoja de **Más**.
- **Ninguna hoja es `Modal`: todas son `BottomSheet`** (regla 6 de `AGENTS.md`). Aplica al
  switch, a Más, a asignar y a resolver propuestas.
- **No se dibuja barra de estado falsa.** En un teléfono real la pinta el sistema encima, y
  una pintada debajo se ve doblada.
- Todo lo tocable a **44 px mínimo**.

### 9.2 Pantallas

| Pantalla | Qué cambia respecto al escritorio |
|---|---|
| **Pulso** | Las secciones se apilan; el reparto pierde columnas y se queda con las abiertas. El FAB **asigna si eres lead y propone si eres member**. |
| **La Revisión** | A **pantalla completa con X propia**, como el chat (`fullScreenModal`). Las tres opciones se apilan a 56 px y el botón primario se ancla abajo, donde llega el pulgar. Es la pantalla que más gana en móvil. |
| **Tareas** | Los filtros por persona pasan de fila de botones a **tira de píldoras que se desliza**, con el avatar dentro. Las filas pierden la columna de hora: a 390 px solo cabe una a la derecha. |
| **Asignar / proponer** | `BottomSheet` con los miembros como **avatares tocables**, no un desplegable. El botón dice "Asignar" o "Proponer" según el rol. |
| **Personal · Hoy** | El chip del crew se encoge **al código de dos letras** y baja a la segunda línea junto al estado: al lado de la fecha no cabe. |
| **Cementerio** | La razón sigue siendo el contenido; se van los aprendizajes largos y la acción de revivir, que quedan en el detalle. |

### 9.3 La invitación es la que más importa en móvil

Un enlace de invitación **casi siempre se abre desde el correo, en el teléfono**. Es el primer
contacto de alguien con el producto, y muchas veces el único que tendrá ese día.

- La tabla de "qué ven / qué no ven / qué puedes / si te vas" **se apila**: en dos columnas a
  390 px la etiqueta se come 168 px y el texto queda ilegible.
- **Los dos botones van anclados abajo**, fuera del scroll.
- Tiene que renderizar **sin sesión iniciada** y aterrizar en el alta si no hay cuenta (§7.5).
- Entra por **deep link** a la app si está instalada, y si no, se queda en el navegador.

### 9.4 `MemberAvatar` en móvil

**No hay hover, así que el tooltip de web no existe aquí.** El nombre completo se muestra con
**pulsación larga**, y el avatar lleva `accessibilityLabel` con el nombre. Sin esto, el
requisito del tooltip simplemente no llega al teléfono.

### 9.5 Reglas del repo que aplican igual

- **No vende Guild** (solo web). Duo y Table sí.
- Admin excluido.
- Verificación **en este orden**: `npx expo export -p ios --clear` y luego `npx tsc --noEmit`,
  ambos en exit 0. El export es lo que regenera las typed routes.
- Cuidado con la trampa de NativeWind: un `className` que alterne entre `undefined` y string
  crashea Expo Go. Strings estables, o valores dinámicos por `style` inline.
- **i18n con ICU de llave simple.** `{count, plural, one {# tarea} other {# tareas}}`, nunca
  `{{count}}`, que no interpola y se imprime literal (regla 7 de su `AGENTS.md`). Móvil no
  tiene hoy ningún test que lo detecte: §10.5.

## 10. Localización: todo el texto, en los dos idiomas

Continuity es bilingüe desde la base. **Ninguna pantalla, correo ni notificación del Crew
puede llevar texto escrito a mano en el código**, y eso no es el último paso de cada fase:
es parte de la definición de "terminado".

### 10.1 La regla que decide de quién es cada cadena

Hay dos clases de texto, y confundirlas es el error caro.

| | **Chrome del producto** | **Contenido del usuario** |
|---|---|---|
| Qué es | Etiquetas, botones, títulos, vacíos, errores, plantillas de frase | Nombre del crew, títulos de proyecto y tarea, `killed_reason`, la razón de un blocker, las notas de cierre |
| Quién lo escribe | Nosotros | Una persona del equipo |
| Se traduce | **Siempre** | **Nunca** |

**El corolario incómodo, y es el correcto:** en un crew con gente en dos idiomas, el chrome
sale en el idioma de quien mira y **el contenido sale tal como lo escribió su autor**. Si Ana
mata un proyecto con la razón "el cliente dejó de contestar", su compañero con la app en
inglés lee esa frase en español dentro de una pantalla en inglés. Traducirla automáticamente
inventaría matices que esa persona no dijo, y el Cementerio compartido existe justamente para
conservar sus palabras (§4.7).

> Esto refuerza una decisión que ya estaba tomada por otro motivo: **un Crew no se siembra con
> contenido de ejemplo** (§7.2). Bien, porque `core/services/seed.py` siembra en inglés duro,
> sin parámetro de idioma, y su copy es voz de marca deliberada. Si el Crew sembrara, heredaría
> ese problema.

### 10.2 El backend manda códigos, no frases

Ya es el patrón del repo en tres sitios independientes:

| Caso | El servidor manda | El cliente pone la frase |
|---|---|---|
| Log de actividad | `ActivityKind` + parámetros | `views.log.entries.<kind>` |
| Cementerio | La causa como código | `views.graveyard.cause.*` |
| Avisos de cuota | `kind`, `current`, `cap`, `plan` | `notifications.quotaWillExceed.<kind>.*` |

Aplicado al Crew: los `ActivityKind` nuevos, los estados de la Revisión, los roles (`lead`,
`member`) y el resultado de una propuesta **viajan como valores de enum**. Ningún resolver
devuelve una oración para pintar. Django tiene `USE_I18N = True` pero **sin `LOCALE_PATHS`, sin
`LANGUAGES`, sin `LocaleMiddleware` y con cero llamadas a `gettext`**: no hay a qué recurrir en
el servidor, así que el código es el único contrato.

> **⚠️ El seam está roto hoy, y el Crew lo empeora si no se toca.** `_quota_error`
> (`core/schema_helpers.py:44`) ya expone `code`, `kind`, `current`, `cap` y `plan` en
> `extensions`, pero el `errorLink` de **los dos clientes** (`frontend/src/lib/apollo.ts:78` y
> `continuity-mobile/src/lib/apollo.ts:44`) solo ramifica en `UNAUTHENTICATED` y
> `DB_UNAVAILABLE`, y para todo lo demás hace `toast.error(err.message)`: el mensaje en inglés
> que sale de `quotas.py:102`, con forma de diagnóstico (`"Quota exceeded for 'projects':
> 4/3 on plan 'free'"`). Las traducciones **ya existen y están muertas**: `errors.quota.default`
> y siete hermanas por cliente, con placeholders `{plan}`, `{current}` y `{cap}` que calzan
> exactamente con `extensions`, y **cero referencias** en ninguno de los dos repos.
>
> Los códigos nuevos del Crew (`CREW_SEAT_LIMIT`, `CREW_PROJECT_LIMIT`, `NOT_CREW_MEMBER`,
> `NOT_CREW_LEAD`) caerían por el mismo agujero. **Propuesta:** en la fase 4, añadir una rama
> por `code` antes del `err.message` en los dos `apollo.ts`. Cuesta unas diez líneas por
> cliente, arregla de paso las ocho cadenas muertas, y sin eso la mitad de los topes del Crew
> se ven en inglés.

### 10.3 Lo que sí se localiza en el servidor

Lo que sale de la app no lo pinta ningún cliente. Hoy hay **tres almacenes de cadenas en el
backend, con tres dialectos de plantilla distintos**, y conviene saber en cuál cae cada cosa
nueva antes de escribirla:

| Almacén | Dónde | Plantilla | Qué del Crew cae aquí |
|---|---|---|---|
| Notificaciones | `core/notifications/i18n/{en,es}.py` | `str.format` + escapes de MarkdownV2 | `crew.assignment.*`, `crew.proposal.*`, `crew.review.*` |
| Correos de ciclo de vida | `core/notifications/email_templates.py` | `{{token}}` | `crew.invite.*` |
| Asistente `canned` (Pro) | `core/assistant/canned.py:47` | `str.format`, **sin plurales** | Las acciones de crew, si las hay (§6) |

**La regla que hace que esto no se rompa solo:** `builders.py:38` resuelve el idioma con
`_resolve_locale(user_id)`, que lee `NotificationSettings.locale` **de quien recibe**. Un
builder de Crew que tomara el idioma de quien *provoca* el aviso le mandaría a Beto un correo
en el idioma de Ana. Cada aviso de la Revisión es uno por miembro, cada uno en el suyo.

- **El correo de invitación es el caso raro:** se lee **sin sesión iniciada** (§7.5), así que
  no hay `NotificationSettings` de donde sacar el idioma. Se usa el de quien invita como
  aproximación y la pantalla de invitación ofrece cambiarlo antes de aceptar.
- **Si el `canned` gana acciones de crew, sus etiquetas viven en el servidor.** Es el único
  seam invertido del repo y es deliberado (`canned.py:15`): el cliente solo renderiza lo que
  devuelve `catalogue()`, así que una acción nueva no necesita release de tienda. Tenerlo
  presente al decidir §6.
- `canned.py` **no tiene plurales** y hoy resuelve uno ramificando en Python
  (`canned.py:188`, `"más" if locale == "es" else "more"`). No copiar ese patrón.
- El idioma se lee hoy en **cinco sitios** con cinco helpers casi idénticos. Si el Crew añade
  un sexto, mejor extraer `get_locale(user_id)` primero.

### 10.4 Web: el guardarraíl ya existe, hay que mantenerlo verde

- Namespace `crew.*` en `frontend/messages/{en,es}.json`, anidado como el resto:
  `crew.pulse.*`, `crew.review.*`, `crew.members.*`, `crew.invite.*`, `crew.graveyard.*`,
  `crew.onboarding.*`, `crew.errors.*`.
- **`frontend/src/i18n/messages.test.ts` es la puerta**, y corre con `pnpm test`. Cuatro
  tests: paridad de claves, namespace inexistente, clave inexistente y **texto de interfaz
  escrito a mano**. Su cabecera lista las cadenas que ya se colaron a producción en el idioma
  equivocado. Si `src/components/crew/` entra sin claves, ese test se pone rojo, que es
  exactamente lo que se quiere.
- **Plurales con ICU**, no concatenando: el repo ya tiene 45 mensajes con
  `{count, plural, ...}`. "3 miembros", "1 proyecto enfriándose", "quedan 2 días".
- **Fechas y horas con el formateador de next-intl.** El Pulso vive de "14 días quieto" y la
  Revisión de "domingo 20:00".
- Hoy los dos archivos tienen **1475 claves y paridad exacta**. El test es lo que la sostiene.

### 10.5 Móvil: aquí no hay ninguna puerta

`continuity-mobile` tiene **1427 claves por idioma y paridad exacta hoy**, pero eso es
disciplina, no control: no hay test de i18n, **no hay runner de tests instalado**, no hay CI, y
`check-parity` compara tokens de diseño, no mensajes.

Y los dos modos de fallo de móvil son silenciosos y visibles para el usuario:

- `{{count}}` con llave doble **no interpola: se imprime literal** (regla 7 de su `AGENTS.md`).
- Sin el polyfill de `Intl.PluralRules`, Hermes hace que `i18next-icu` **devuelva el ICU en
  crudo** (`src/lib/i18n.ts:1`).

**Propuesta:** portar `messages.test.ts` a móvil como parte de la fase 5. Es el mismo archivo
con `useTranslations` cambiado por `t`, y hoy no se puede correr porque no hay runner: instalar
vitest es el 80% del trabajo. Sin esto, el Crew duplica la superficie de móvil sin red.

### 10.6 Ayuda: dos idiomas significa dos juegos de capturas

`backend/docs/ayuda` no es markdown traducido. Es un pipeline con **mockup por idioma**
(`<vista>.html` y `<vista>.en.html`), texto en `es/<vista>.md` y `en/<vista>.md`, y **capturas
propias de cada idioma** generadas con `_shoot.mjs`. Una guía del Crew son dos mockups y dos
juegos de PNG. Está en la fase 7 y hay que presupuestarla así.

### 10.7 El copy, en los dos idiomas

Los 20 artboards de `.design/` se escribieron en español y durante un tiempo fueron la única
copia que existía del producto. El inglés **no se tradujo, se escribió**: la guía de voz de
la marca vive en inglés y tiene léxico propio (*Loop*, *drift*, *graveyard*, *builder*,
*ship*, *killed*) que manda sobre la versión española de la misma pantalla.

**Hecho.** Lo escribió el agente de marca el 16 de septiembre. Las 190 claves en los dos
idiomas están en [`COPY.md`](COPY.md), listas para copiarse a `messages/{en,es}.json` sin
re-mapear nada. El glosario quedó así: **Pulse**, **Review**, **Drifting** (léxico de marca:
*the drift is what kills builders*), **Who's carrying what**, **Proposed to you** con
**Pass** en vez de *Reject*, **My Crew work**, y *lead* / *member* en minúscula dentro de
frase.

**La pasada en inglés encontró seis plurales rotos en el español y cuatro errores de
producto**, todos corregidos en `COPY.md`. El más serio: `crew.personal.quotaNote` decía
«tu jefe no ve nada», que contradice §1.7 y refuerza justo el miedo que la pantalla de
invitación existe para desactivar. Dice «nadie del Crew».

El ritual del Crew se llama **Revisión** y **Review**, sin apellido. El *Sunday Review* de la
guía de voz sigue siendo material de marca del producto personal y no se cruza con este.

---

## 11. Fases de entrega

Ordenadas por riesgo, no por visibilidad.

| Fase | Qué | Puerta de salida |
|---|---|---|
| **0 · Verificación** | Confirmar los puntos de precio en App Store Connect y Google Play. Cerrar las decisiones abiertas de §15. | Respuestas escritas. Si algo no se confirma, `TODO(verificar)` en el código, no una invención. El copy en los dos idiomas ya está en [`COPY.md`](COPY.md). |
| **1 · Frontera de seguridad** | Modelos, migración aditiva, `assert_crew_access` + `CrewScope`, `crew_views.py`, invitaciones con su encadenado de alta (§7.5). **Sin interfaz.** | **Los 16 tests de aislamiento de §12 en verde.** Nada más cuenta. |
| **2 · Board, Pulso y cementerio** | `crew` en `Project` y `Task`, asignación, propuestas, `pulse()`, cementerio compartido, ActivityKinds. | Un lead lee el board de un miembro por GraphQL; un no-miembro recibe FORBIDDEN. |
| **3 · Cuotas y suscripción** | Arreglar `_count` (§5.4), `CrewSubscription`, enrutado por `crew_` en el webhook, cuotas del crew. | Un miembro con 200 tareas de equipo en Free sigue pudiendo crear en su espacio personal. |
| **4 · Web** | Ajustes, vista de dashboard con los siete destinos, switch, namespace `crew.*` en los dos idiomas, la rama por `code` en `apollo.ts` (§10.2), y **el onboarding de §7** (crear, la lista derivada y la pantalla de invitación). | Recorrido completo lead ↔ miembro en un navegador, **en los dos idiomas**, con `pnpm test` en verde (§10.4). |
| **5 · La Revisión del equipo** | `Review`, `ReviewEntry`, servicio, cadencia, invitación, pantalla, contestación asíncrona. | Una Revisión que se abre sola, se contesta por partes y se cierra dejando registro. |
| **6 · Móvil** | Espejo con interfaz nativa. Portar `messages.test.ts` (§10.5), que hoy no tiene dónde correr. | Export y `tsc` limpios, y el test de i18n corriendo. |
| **7 · Endurecimiento** | Tools de crew para el Loop personal, RLS real por membresía, ayuda en `docs/ayuda`: **dos mockups y dos juegos de capturas** (§10.6). | |

**Micro puede salir antes que la Revisión.** Con las fases 1 a 4 el producto gratuito está
completo: dos personas, Pulso completo, repartir, proponer, matar juntos. **Duo y Table no se
pueden vender hasta que cierre la fase 5**, porque la Revisión es literalmente lo que compran.
Eso permite lanzar Micro, aprender con gente real, y encender el cobro después.

---

## 12. Los tests de aislamiento

Es la primera vez que un usuario puede leer datos de otro. La suite se escribe **en la fase 1,
antes que cualquier pantalla**, y es su criterio de terminado.

Con tres usuarios: `lead_a` y `member_a` en el Crew A; `outsider` sin membresía.

| # | Caso | Esperado |
|---|---|---|
| 1 | `outsider` pide el board del Crew A | FORBIDDEN |
| 2 | `outsider` pide `crew(id)` | FORBIDDEN |
| 3 | `member_a` pide el board de otro miembro | FORBIDDEN |
| 4 | `lead_a` pide el board de `member_a` | OK |
| 5 | **`member_a` tiene trabajo personal** | **No aparece** en el board |
| 6 | **`member_a` está en el Crew B con otro lead** | `lead_a` **no ve** nada del B |
| 7 | `member_a` intenta `assignTask` | FORBIDDEN |
| 8 | `member_a` hace `proposeTask` | Crea `TaskProposal`, **no** crea `Task` |
| 9 | Propuesta pendiente | **No** aparece en dashboard, Today, Tasks ni calendario del destinatario |
| 10 | `outsider` acepta una propuesta ajena | FORBIDDEN |
| 11 | Miembro con `status="removed"` | Pierde el acceso de inmediato |
| 12 | Se borra el Crew A | El trabajo **sobrevive** y vuelve al espacio personal |
| 13 | Invitación caducada o ya aceptada | Rechazada |
| 14 | Board con un `member_id` de otro crew | FORBIDDEN |
| 15 | Asignación masiva a un miembro Free | Su creación personal **no** se bloquea (§5.4) |
| 16 | **`lead_a` contesta la `ReviewEntry` de `member_a`** | **FORBIDDEN.** La decisión es de quien hace el trabajo |

**Guard estructural, además de los casos:** un test que recorra `core/services/` excepto
`crews.py` y `crew_views.py`, y falle si alguna función pública ganó un parámetro de
usuario objetivo. La regla de §3.1 debe ser verificable por una máquina.

---

## 13. Riesgos

1. **La frontera de seguridad.** Un fallo aquí es una fuga entre cuentas. Mitigación: un solo
   autorizador, un solo módulo que cruza, el `CrewScope` que hace la autorización
   obligatoria por firma, y la suite de §12.
2. **La Revisión es la pieza más grande y no tiene precedente en el código.** Duo depende
   entera de ella. Si llega recortada a un correo, hay que replantear qué vende Duo.
3. **RLS engañoso.** Está habilitado pero no es lo que protege hoy. La defensa del MVP es de
   capa de aplicación; RLS real por membresía en la fase 7.
4. **La cuota de `tasks_total`** (§5.4). Rompe al asistente la primera vez que se asigna en
   volumen. Tiene que estar arreglado antes de probar con gente real.
5. **El enrutado por `crew_` toca el único punto de escritura de titularidad.** Es el código con
   más cuidado invertido del repo. Cualquier cambio ahí va con sus tests.
6. **`DASHBOARD_QUERY`.** No meter crews ahí.
7. **Doble mantenimiento web y móvil.** Tres repos git hermanos, sin capa compartida y sin
   posibilidad de tenerla sin montar antes infraestructura de monorepo. Todo se escribe dos
   veces. Presupuestarlo.

---

## 14. No-goals de la v1

- Colaboración en tiempo real o edición concurrente.
- Hilos de comentarios o chat entre usuarios.
- Compartir el **espacio personal** de un miembro.
- Jerarquía de organizaciones sobre los crews.
- Roles `admin` y `viewer` (§1.5).
- Privacidad por ítem: la única frontera es equipo contra personal.
- Ideas, rutinas y notas compartidas.

---

## 15. Abierto

1. **Facturación fiscal para Guild.** Con "Contact us" como CTA es manejable a mano al
   principio, pero define el techo de lo que se puede vender.
2. **Si una invitación pendiente ocupa asiento.** Propuesta: sí, y caduca a los 7 días.
3. **Onboarding del invitado sin cuenta:** `acceptInvite` tiene que encadenar el alta de
   Supabase. El correo va por Resend, que ya está montado y **arranca en `dry_run`**.
4. **Una persona en varios crews:** el modelo lo soporta; falta la interfaz del selector.
5. **`Activity` y `crew_id`:** derivar o desnormalizar. Medir en la fase 2.
6. **El valor de enum `"table"`** se lee raro en un backend lleno de tablas: `crew.plan ==
   "table"` hace dudar un segundo. Con Micro quedó fijada la regla de que **el literal y el
   nombre comercial coinciden** (`micro`, `duo`, `table`, `guild`), así que o se acepta con
   un comentario, o se rompe esa regla para este único valor.
7. **«Log» contra «Bitácora».** La navegación del Crew dice «Log» en español y el producto
   lo llama «Bitácora» (`tabs.log`). O el Crew se alinea, o «Bitácora» se retira también del
   espacio personal. En inglés es *Log* en los dos casos.
