# Tareas

La pestaña **Tareas** reúne *todas* tus tareas en un solo lugar y las agrupa por urgencia: lo **vencido** arriba, lo de **hoy** después, y luego lo **próximo**, lo que falta **agendar** y lo **completado**.

---

## 1. Anatomía general

[imagen: tasks-01-overview.png]

De arriba hacia abajo, la vista de Tareas se arma así:

1. **Encabezado** — título “Todas las tareas”, buscador y botón **Nuevo** (en escritorio).
2. **Barra de rango + filtro** — solo en móvil: **Hoy · Semana · Todas** y el botón **Filtrar**.
3. **Grupos por urgencia** — Vencidas, Hoy, Próximas, Asignar día y Completadas, cada uno plegable.
4. **Botón Crear (FAB)** — flotante abajo a la derecha, para añadir una tarea sin salir de la vista.

> **Nota:** los grupos **solo aparecen cuando tienen tareas**. El grupo **Hoy** se muestra siempre (si no hay nada, dice “Todo en orden — nada para hoy ✨”). Es normal que un usuario nuevo vea pocos grupos al inicio.

---

## 2. Encabezado y búsqueda

[imagen: tasks-02-header.png]

El buscador filtra al instante por título de tarea o nombre de proyecto. El botón **Nuevo** aparece junto al buscador **solo en escritorio**; en móvil usa el botón flotante **+**.

**Cómo se usa**
- Escribe en **Buscar tareas o proyecto…** para filtrar por **título** o por **nombre de proyecto**.
- Mientras buscas, **todos los grupos se abren** automáticamente para que veas las coincidencias.
- Si nada coincide, verás **“No hay tareas que coincidan con ‘…’”**.
- **Nuevo** abre el editor para crear una tarea.

---

## 3. Grupos por urgencia

[imagen: tasks-03-buckets.png]

Tus tareas se reparten solas en cinco grupos plegables, ordenados por prioridad. Cada grupo lleva un contador con su color; el de **Hoy** añade un chip de **tiempo estimado total**.

**Cómo se usa**
- **Vencidas** — con fecha pasada y sin completar. Van primero, de la más atrasada a la menos.
- **Hoy** — vencen hoy. **Siempre visible**; suma el tiempo estimado en su chip.
- **Próximas** — con fecha futura, ordenadas por fecha.
- **Asignar día** — sin fecha; aquí les pones una.
- **Completadas** — las hechas; aparece si activas “Mostrar completadas” en filtros.

**Cómo editar**
- **Toca el título** de un grupo para plegarlo o desplegarlo. Tu preferencia se mantiene mientras navegas.
- El **rango** (móvil) cambia qué grupos se ven: **Hoy** deja solo Vencidas + Hoy; **Semana** añade Próximas a 7 días; **Todas** muestra todo.
- Una tarea se mueve sola de grupo según su fecha y si está hecha.

---

## 4. Anatomía de una tarea

[imagen: tasks-04-row.png]

De izquierda a derecha: **círculo ✓**, título + chips (**esfuerzo**, **Bloqueada**), línea de proyecto + fecha, y **✕** para eliminar.

**Cómo se usa**
- El **borde** tiñe el estado: **rojo** si está vencida, **naranja** si es para hoy.
- El chip **⏱ 2h** es el **esfuerzo estimado** en horas (si lo definiste).
- La línea inferior muestra el **proyecto** y la **fecha** (o **“Para hoy”**).
- **🔒 Bloqueada** aparece si la tarea tiene bloqueadores; la fila se atenúa.

**Cómo editar**
- **Toca el texto** de la tarea para abrir su **editor** (título, proyecto, fecha, esfuerzo, bloqueadores).
- En el grupo **Asignar día**, toca **📅 Agregar fecha** para programarla.
- **✕** a la derecha **elimina** la tarea (en escritorio aparece al pasar el cursor).

---

## 5. Rango y filtros *(filtro: solo móvil)*

[imagen: tasks-05-filters.png]

La barra de **rango** (Hoy · Semana · Todas) acota por horizonte de fecha. El botón **Filtrar** lleva un insignia verde que cuenta cuántos filtros tienes activos.

**Cómo se usa — Rango**
- **Hoy** deja solo **Vencidas** y **Hoy**.
- **Semana** añade las **Próximas** a 7 días.
- **Todas** muestra todos los grupos, incl. **Asignar día**.
- El rango vive **solo en móvil**; en escritorio ves todos los grupos.

[imagen: tasks-06-filters.png]

La hoja de filtros se abre desde abajo. El botón inferior dice **“Aplicar (N)”** con cuántas tareas quedarán; si quedan **0**, se desactiva con **“Ninguna tarea coincide”**.

**Cómo se usa — Filtros**
- **Por proyecto** — toca los chips para **incluir** solo esos proyectos; **Sin proyecto** capta las tareas sueltas. Sin chips activos = todos.
- **Mostrar completadas** — activa o no el grupo **Completadas**.
- **Mostrar bloqueadas** — incluye u oculta las tareas con bloqueadores.
- **Limpiar** reinicia el filtro; **Aplicar** lo confirma y cierra la hoja.

---

## 6. Completar una tarea

[imagen: tasks-07-complete.png]

Un toque en el círculo la marca como hecha, con confirmación instantánea: el círculo se pone **verde**, el título se tacha y aparece un aviso **“✓ Tarea completada”**.

**Cómo se usa**
- **Toca el círculo ✓** a la izquierda para marcarla como hecha.
- La fila se **desvanece** y pasa al grupo **Completadas**.
- Para **deshacer**, abre “Mostrar completadas” en filtros y vuelve a tocar el círculo (queda verde) — se desmarca.
- Las completadas se ordenan por **fecha de finalización**, lo más reciente arriba.

**Cómo editar**
- El grupo **Completadas** es accesible en cualquier rango, justo para poder deshacer un error.

---

## 7. Crear y estado vacío

[imagen: tasks-08-create.png]

Sin tareas verás **“Aún no hay tareas.”** y un botón para crear la primera. El **+** flotante siempre está disponible.

**Cómo se usa**
- **Crear primera tarea** (estado vacío) o **Nuevo** (escritorio) abren el editor de tarea.
- En móvil, el botón flotante **+** es la vía principal; despliega la acción “Nueva tarea” y el acceso a **Loop** (asistente IA).
- Al guardar, la tarea cae sola en el grupo que le toca según su fecha.

**Cómo editar**
- El **+** flotante no se oculta ni se reordena: es parte fija de la vista.
- Para borrar todas y volver al estado vacío, elimina cada tarea con su **✕**.
