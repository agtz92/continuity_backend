# Cementerio de proyectos

La pestaña **Cementerio** (icono de lápida) guarda los proyectos que *mataste con intención*. No es un basurero: es una biblioteca de lo que no funcionó, con tus notas de cierre, qué aprendiste y si lo reiniciarías. Loop puede leerlas todas y buscar el patrón. Y si te arrepientes, cualquier proyecto se puede **revivir**.

---

## 1. Vista general

[imagen: graveyard-01-overview.png]

Una lista de los proyectos que mataste, del más reciente al más antiguo. De arriba hacia abajo:

1. **Encabezado** — icono de lápida 🪦, título y el subtítulo “una biblioteca de lo que no funcionó”.
2. **Métrica** — *“Reiniciarías N de M”*: cuántos de tus muertos dijiste que volverías a empezar.
3. **Autopsia** — el bloque morado con el patrón que Loop detecta entre tus muertes.
4. **Lápidas** — una tarjeta por proyecto muerto, ordenadas por fecha de muerte (la más reciente arriba).

> **Nota:** solo llegan aquí los proyectos que matas **con intención** (desde el proyecto → “Matar con intención”). Un proyecto que se queda **estancado** no entra solo: la app te empuja a decidir (seguir, pausar o matar), y solo al elegir “matarlo” pasa al cementerio con sus notas.

---

## 2. Autopsia (Loop)

[imagen: graveyard-02-autopsy.png]

El patrón que se repite entre tus proyectos muertos, escrito por Loop. Aparece cuando tienes **3+ proyectos muertos**; Loop calcula el patrón y lo guarda en caché.

**Cómo se usa**
- Es de **solo lectura**: resume el “por qué” común detrás de tus muertes.
- **“Pídele a Loop que profundice”** abre el asistente con un análisis más detallado.
- Con menos de 3 muertos verás un texto que dice que aún **no hay suficiente para analizar**.

**Cómo se actualiza**
- El patrón se **recalcula** la próxima vez que matas un proyecto.
- Si está desactualizado, lo verás marcado como tal bajo el texto.

---

## 3. Anatomía de una lápida

[imagen: graveyard-03-card.png]

Cada proyecto muerto es una tarjeta con borde rojo a la izquierda. Bajo el nombre verás **“Vivió N días”** y la **fecha de muerte**.

**Cómo se usa**
- **Vivió N días** = días desde que creaste el proyecto hasta hoy.
- **Matado el …** = la fecha en que lo cerraste con intención.
- El botón **Revivir** (arriba a la derecha) abre el flujo para traerlo de vuelta (sección 5).
- Debajo van las **notas de cierre** que escribiste al matarlo (sección 4).

**Cómo editar**
- El cementerio es de **solo lectura**: aquí no se editan las notas.
- Las tarjetas se ordenan solas por **fecha de muerte**, la más reciente primero.
- Para “sacar” un proyecto de aquí, usa **Revivir**.

---

## 4. Notas de cierre

[imagen: graveyard-04-closurenotes.png]

Lo que escribiste en el ritual de cierre al matar el proyecto: tres campos de texto (**Por qué se mató**, **Qué enseñó**, **Reiniciarías**) y una **reflexión de IA** opcional.

**Cómo se usa**
- **Por qué se mató** y **Qué enseñó** son las dos notas que siempre verás.
- **Reiniciarías** (con el icono ↻) aparece solo si lo respondiste; alimenta la métrica de arriba.
- La **reflexión de IA** (bloque morado ✦) aparece si Loop dejó una nota sobre ese proyecto.

**Cómo se llenan**
- Estas notas se escriben **una sola vez**, en el diálogo **“Matar con intención”** del proyecto.
- Aquí en el cementerio son de **solo lectura**: son un registro, no un formulario.

> El mismo bloque de notas se reutiliza para proyectos **pausados** (con “Dónde lo dejaste” y tu siguiente acción) en la tarjeta de “Bienvenido de vuelta”. En el cementerio siempre verás la variante de proyecto **muerto**.

---

## 5. Revivir un proyecto

[imagen: graveyard-05-revive.png]

Traer de vuelta un muerto, como proyecto **Activo** o como **Idea** para revalidar. Se abre con el botón **Revivir** de la lápida y te recuerda lo que dijiste que cambiarías.

**Cómo se usa**
- **Activo** ⚡ lo devuelve a tus proyectos en marcha de inmediato.
- **Idea (revalidar)** 💡 lo manda a Ideas para volver a probarlo antes de comprometerte.
- **Déjalo muerto** cierra el diálogo sin cambios.

**Ojo con el límite**
- Un muerto **no cuenta** para tu plan; al revivirlo como **Activo** vuelve a contar.
- Si ya llegaste al tope de proyectos activos, la app te avisará en lugar de revivirlo.
- El diálogo te muestra tu uso actual (p. ej. **3 / 5 activos**) antes de decidir.
