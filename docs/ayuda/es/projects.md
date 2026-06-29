# Proyectos

La pestaña **Proyectos** es tu lista maestra: todos tus proyectos en una sola tabla, con su estado, prioridad, categoría, progreso de tareas y próximo paso. Desde aquí buscas, filtras, ordenas, abres cada proyecto para ver su detalle y creas nuevos.

---

## 1. La lista de proyectos

[imagen: projects-01-overview.png]

De arriba hacia abajo, la vista se arma así:

1. **Encabezado** — el título “Todos los proyectos”, el buscador y el botón **Nuevo** (en escritorio).
2. **Barra de filtros** — estado, categoría, prioridad y orden (sección 2). En móvil son dos botones que abren hojas.
3. **Lista de filas** — una por proyecto: icono de estado, nombre, chips y progreso de tareas.
4. **Botón Crear (FAB)** — flotante abajo a la derecha para añadir un proyecto sin salir de la vista.

> **Nota:** el orden por defecto es **Inteligente** — primero los proyectos con tareas vencidas, luego los que vencen hoy, luego los que llevan días sin actividad, y al final el resto, dentro de cada grupo por prioridad y actividad reciente.

---

## 2. Barra de filtros y búsqueda

[imagen: projects-02-filters.png]

Acota la lista por estado, categoría, prioridad y vencimiento, o busca por texto. En escritorio cada chip muestra **cuántos proyectos** caen en él.

**Cómo se usa**
- El buscador filtra por nombre, descripción, próximo paso, motivación y categoría.
- Toca un chip de **Estado**, **Categoría** o **Prioridad** para filtrar; vuelve a “Todos” para quitarlo.
- Los estados sin proyectos no se muestran; el número en cada chip es su conteo.
- El selector de **Orden** cambia cómo se acomoda la lista (sección 4).

**Cómo editar**
- Los filtros son **acumulativos**: estado + categoría + prioridad + vencimiento a la vez.
- Si nada coincide, aparece **“Limpiar filtros”** para volver a “Todos”.

---

## 3. Hoja de filtros (móvil)

[imagen: projects-03-filtersheet.png]

En móvil, “Filtrar” abre una hoja con todas las opciones. El botón inferior muestra **cuántos proyectos coincidirían** antes de aplicar; si son 0 dice “Ningún proyecto coincide”.

**Cómo se usa**
- Abre con el botón **Filtrar**; su insignia muestra cuántos filtros tienes activos.
- Elige uno por grupo: **Estado**, **Prioridad**, **Categoría** (si tienes) y **Fecha de vencimiento**.
- El botón **Aplicar (N)** trae el conteo en vivo; **“Limpiar”** reinicia a Todos.

**Cómo editar**
- **Fecha de vencimiento**: Cualquiera, Vencidas, Próximos 7 días o Sin fecha.
- En escritorio estos mismos filtros viven en la barra etiquetada (sección 2), sin hoja.

---

## 4. Ordenar proyectos

[imagen: projects-04-sort.png]

Cinco modos para acomodar la lista. La opción activa lleva una palomita; en escritorio es el menú desplegable de “Orden”.

**Qué hace cada modo**
- **Inteligente** — vencidas primero, luego de hoy, luego sin actividad, luego por prioridad.
- **Por prioridad** — Crítica → Alta → Media → Baja.
- **Actividad reciente** — lo más movido recientemente arriba.
- **Nombre** — alfabético.
- **Por estado** — agrupa por estado en su orden natural.

**Cómo editar**
- El modo elegido se mantiene mientras navegas en la vista.

---

## 5. Anatomía de una fila

[imagen: projects-05-card.png]

Todo lo que dice de un vistazo cada proyecto en la lista: de izquierda a derecha, franja de prioridad, chevron, icono de estado, nombre + chips, y la barra de progreso de tareas.

**Qué muestra**
- **Franja de color** a la izquierda = prioridad (roja crítica, naranja alta, verde media, azul baja).
- **Icono cuadrado** = estado del proyecto (Activo, Estancado, Idea, Lanzado…).
- **Chip de categoría** con su color, si el proyecto tiene una.
- **Badge** de urgencia: **N vencidas**, **N hoy**, **Nd sin actividad** o **Nh pendientes**.
- **→ Próximo paso** bajo el nombre, y la **barra hecho/total** de tareas a la derecha.

**Cómo se usa**
- **Toca la fila** para desplegar el detalle del proyecto (sección 6).
- El badge ámbar “sin actividad” es solo una pista visual (7+ días), no un estado.
- En móvil, categoría e idle se ocultan para ahorrar espacio; el progreso se simplifica a “hecho/total”.

---

## 6. Abrir un proyecto

[imagen: projects-06-detail.png]

Tocar una fila la expande **en línea** (la fila se ilumina), con próximo paso, tareas y actividad. “Abrir proyecto” lleva a la vista completa de pantalla.

**Cómo se usa**
- **Próximo paso** arriba, siempre visible; debajo Por qué importa, Descripción, Tareas, Actividad y Notas.
- En **Tareas**: marca el ✓ para completar, **Agregar tarea**, o edita/elimina cada una.
- **Registrar update** deja una entrada de bitácora y “despierta” al proyecto.
- **Abrir proyecto** (↗) salta a la vista de detalle completa.

**Cómo editar**
- **Editar** abre el formulario del proyecto (nombre, estado, prioridad, categoría, fechas…).
- **Eliminar** borra el proyecto (pide confirmación).
- Las listas largas de tareas o actividad se recortan con un “mostrar más”.

---

## 7. Crear y estado vacío

[imagen: projects-07-create.png]

Cuando todavía no tienes proyectos, ves el estado vacío con el atajo **“Agrega tu primer proyecto”**.

[imagen: projects-08-create.png]

En móvil, el botón flotante **+** despliega “Nuevo proyecto” y el acceso a **Loop** (asistente IA).

**Cómo se usa**
- En escritorio, el botón **Nuevo** del encabezado abre el formulario de proyecto.
- En móvil, el botón flotante **+** hace lo mismo (y ofrece abrir Loop).
- El estado vacío incluye un atajo directo: **“Agrega tu primer proyecto”**.

**Cómo editar**
- Si los filtros dejan la lista vacía, verás **“No hay proyectos que coincidan…”** con **Limpiar filtros**.
- La búsqueda sin resultados muestra el texto buscado para que ajustes el término.
