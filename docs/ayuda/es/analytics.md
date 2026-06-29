# Analíticas

La pestaña **Analíticas** es tu tablero de control: convierte tu actividad —updates, tareas completadas, horas registradas, ideas— en gráficas y paneles que te dicen *cómo* vas, no solo qué te falta. Es una vista de **solo lectura**: no editas nada aquí, pero sí eliges el **rango de fechas** que alimenta todos los paneles.

---

## 1. Anatomía general

[imagen: analytics-01-overview.png]

De arriba hacia abajo, Analíticas se arma así:

1. **Título + selector de rango** — arriba. El rango (7d/30d/90d/1a/Todo) alimenta **todos** los paneles a la vez.
2. **Cadencia y actividad** — el pulso reciente: cuántos días estuviste activo y la curva diaria.
3. **Paneles de proyectos** — más activos, backlog, estado/categoría, esfuerzo, durmiendo.
4. **Paneles de ideas** — el embudo de ideas y las ideas estancadas.

> **Nota:** en **móvil** verás una tira de **chips** (Actividad · Cadencia · Estado · …) y **un solo panel** a la vez: toca un chip para cambiar de panel. En **escritorio** se muestran todos apilados. Mientras recalcula tras cambiar el rango, junto al título aparece **“actualizando…”**.

---

## 2. Rango de fechas y Cadencia

[imagen: analytics-02-range.png]

El selector de rango es lo único que “editas” aquí. Debajo, **Cadencia** te da tu pulso: **Días activos** (cuántos días del rango tuvieron al menos un update o una tarea completada) y **Eventos** (el total de esas interacciones).

**Cómo se usa**
- Juntos son tu “pulso”: muchos eventos pero pocos días activos = trabajas a ráfagas.
- Los valores se recalculan según el rango elegido.

**Cómo editar**
- Toca **7d / 30d / 90d / 1a / Todo** para cambiar el rango.
- Es lo **único** editable de la vista; **recalcula todos los paneles** de golpe.
- El valor por defecto al entrar es **30 días**.

---

## 3. Actividad por día

[imagen: analytics-03-activity.png]

Dos líneas día a día: la **verde** son updates (registros de log) y la **azul** son tareas completadas. El eje X se etiqueta cada pocos días.

**Cómo se usa**
- Busca **tendencia**, no días sueltos: ¿subes, bajas o mantienes el ritmo?
- Pasa el cursor por un punto para ver el detalle de ese día en un tooltip.
- Picos de azul sin verde = cerraste tareas pero no documentaste avances (o al revés).

**Cómo editar**
- Solo lectura. Cambia lo que ves ajustando el **rango de fechas** (sección 2).
- Con rangos largos (1a / Todo) la curva se suaviza y las etiquetas se espacian.

---

## 4. Más activos

[imagen: analytics-04-topprojects.png]

Top 5 proyectos por interacciones (updates + tareas completadas) en el rango. El número grande son las interacciones; la flecha es el cambio frente al periodo anterior (**▲ sube**, **▼ baja**, – igual).

**Cómo se usa**
- Confirma **dónde se fue tu energía** realmente en el rango.
- La flecha compara contra el periodo anterior del mismo largo: detecta proyectos que se enfrían (▼).
- Bajo cada nombre aparece el estado del proyecto (active, stalled, launched…).

**Cómo editar**
- Solo lectura. Si no hubo actividad en el rango, verás **“Sin actividad en este rango.”**

---

## 5. Por día de la semana

[imagen: analytics-05-heatmap.png]

Un mapa de calor de Lunes a Domingo. Más **intenso** = más interacciones ese día; el número dentro de cada celda es el conteo.

**Cómo se usa**
- Revela tu **patrón semanal**: en qué días rindes más y cuándo bajas.
- Útil para planear: agenda lo difícil en tus días fuertes.

**Cómo editar**
- Solo lectura. Acumula sobre todo el rango elegido.

---

## 6. Backlog

[imagen: analytics-06-backlog.png]

Salud de tus pendientes. El subtítulo es el total de tareas abiertas; cada tarjeta destaca un grupo accionable.

**Cómo se usa**
- **Vencidas** y **Próximas (7d)** = qué atender ya para no acumular retraso.
- **Quick wins** = proyectos con ≤2 tareas abiertas (ciérralos rápido).
- **Casi listos** = proyectos con ≥80% completado, a un empujón de terminar.

**Cómo editar**
- Solo lectura; para mover números, ve a **Tareas** o **Proyectos** y avanza pendientes.

---

## 7. Por estado y categoría

[imagen: analytics-07-breakdown.png]

Cómo se reparten tus proyectos. A la izquierda, barras por **estado** (cada color = una etapa del ciclo); a la derecha, tus **categorías** con nº de proyectos e interacciones. El subtítulo cuenta el total de proyectos.

**Cómo se usa**
- Mira el **balance**: demasiados “Estancado” o “Idea” frente a “Activo” es una señal.
- El lado de categoría muestra dónde se concentran tus proyectos y tu actividad.

**Cómo editar**
- Solo lectura. Los colores de categoría son los que definiste al crearlas.
- Si no hay categorías verás **“Sin categorías.”**; sin proyectos, **“Sin datos.”**

---

## 8. Esfuerzo y Funnel de ideas

[imagen: analytics-08-effort.png]

**Esfuerzo** reparte tus horas registradas por proyecto. El número grande son las horas totales; **Cobertura** avisa cuántas tareas llevan horas (si no, el total subestima).

[imagen: analytics-09-effort.png]

**Funnel de ideas** muestra **Creadas** → **Promovidas** → **Tasa** de conversión a proyecto.

**Cómo se usa**
- Esfuerzo: descubre a qué le dedicas tiempo de verdad.
- Cobertura baja = registra horas en más tareas para que el total sea fiable.
- Funnel: una tasa muy baja sugiere que acumulas ideas sin decidir.

**Cómo editar**
- Solo lectura. Las horas vienen de las **horas registradas en tus tareas**.
- Sin horas en el rango: **“Sin tareas con horas registradas en este rango.”**

---

## 9. Durmiendo · Ideas estancadas

[imagen: analytics-10-sleeping.png]

**Durmiendo** lista proyectos sin actividad reciente (≥7 días). La etiqueta agrupa la gravedad (**7-14d** → **15-30d** → **30+d**) y a la derecha van los días exactos sin actividad.

[imagen: analytics-11-sleeping.png]

**Ideas estancadas** son ideas que llevan 30+ días sin promover a proyecto; a la derecha, su antigüedad.

**Cómo se usa**
- Es tu lista de **rescate**: reactiva un proyecto o suelta una idea para liberar espacio.
- “Durmiendo” complementa la alerta de **Today**, pero aquí ves la lista completa.
- Para actuar, abre el proyecto o la idea desde sus pestañas respectivas.

**Cómo editar**
- Solo lectura. Si todo va al día: **“Nada durmiendo. Buen ritmo.”** y **“Sin ideas estancadas.”**

> **Nota:** todos los paneles son **solo lectura**: Analíticas no cambia tus datos, los *refleja*. La única palanca es el **rango de fechas** de arriba. Si un panel sale vacío, casi siempre es por falta de datos en ese rango — amplíalo o registra más actividad.
