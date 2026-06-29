# Quick Notes — Plan de implementación

> **⚑ ESTADO (2026-06-28): ENVIADO — este documento es el diseño-de-registro (as-built).**
> La feature está en producción (web + móvil). Modelos `QuickNote`/`NoteSection`, servicio
> `core/services/quick_notes.py`, migración `core/migrations/0020_*`. Se conserva como
> referencia de arquitectura, no como pendiente.

> Notas tipo Notion dentro de Continuity: categorizables, ligables a un proyecto o
> en standalone, con **secciones plegables** (acordeón) tipo *toggle* de Notion.
> Objetivo: cerrar el círculo y dejar de depender de Notion para el día a día.

Wireframes: [`wireframe-web.html`](wireframe-web.html) · [`wireframe-mobile.html`](wireframe-mobile.html)

---

## 1. Concepto y diferencia con "Ideas"

| | **Ideas** (existe) | **Quick Notes** (nuevo) |
|---|---|---|
| Estructura | Plana: `title / description / why` | Nota con **N secciones plegables** ordenables |
| Categoría | No tiene | Sí (reusa `Category`) |
| Proyecto | No (solo se *promueve* a proyecto) | Opcional: ligada a `Project` o suelta |
| Propósito | Parking lot de ideas sin empezar | Cuaderno de referencia del día a día |

`Quick Notes` ≠ `ProjectNote`. `ProjectNote` ya existe y vive **dentro** de un
proyecto (sub-notas). Quick Notes es una sección **top-level** propia; el enlace a
proyecto es solo para filtrar/contextualizar, no lo encierra en él.

**Decisión de alcance** (mantenerlo simple, como pediste): **un solo nivel** de
acordeón — una nota tiene secciones plegables; las secciones no anidan más secciones.
Cubre el caso del screenshot de Notion sin volverse un editor de bloques completo.

---

## 2. Backend (Django + Strawberry GraphQL)

Todo en la app `core`. Sigue el patrón de `Idea` / `ProjectNote`.

### 2.1 Modelos — `core/models.py`

```python
class QuickNote(TimestampedModel):
    title = models.CharField(max_length=255, blank=True, default="")
    category = models.ForeignKey(
        Category, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="quick_notes",
    )
    project = models.ForeignKey(
        Project, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="quick_notes",
    )
    pinned = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-pinned", "-updated_at"]
        indexes = [
            models.Index(fields=["user_id", "-updated_at"]),
            models.Index(fields=["user_id", "category"]),
            models.Index(fields=["user_id", "project"]),
        ]


class NoteSection(TimestampedModel):
    """Bloque plegable (toggle) dentro de una QuickNote."""
    note = models.ForeignKey(QuickNote, on_delete=models.CASCADE, related_name="sections")
    heading = models.CharField(max_length=255, blank=True, default="")
    body = models.TextField(blank=True, default="")
    position = models.PositiveIntegerField(default=0)
    collapsed = models.BooleanField(default=False)  # estado plegado por defecto
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "created"]
        indexes = [models.Index(fields=["note", "position"])]
```

Reutilizamos `Category` tal cual (hoy solo la usan los proyectos; añadir el FK
inverso `quick_notes` no rompe nada). `on_delete=SET_NULL` en `project`/`category`
para que borrar un proyecto/categoría no borre la nota.

### 2.2 Servicio — `core/services/quick_notes.py` (archivo nuevo)

Funciones, todas con `user_id` como primer argumento y filtrando por él:

- `list_quick_notes(user_id, *, search=None, category_id=None, project_id=None, pinned=None)`
- `get_quick_note(user_id, note_id)` → `NotFoundError` si no existe
- `create_quick_note(user_id, *, title, category_id, project_id)` → check quota, `log_event`, `bump_context_version`
- `update_quick_note(user_id, note_id, **fields)` (incluye `pinned`)
- `delete_quick_note(user_id, note_id)`
- `add_section(user_id, note_id, *, heading, body, position)` → check quota de secciones
- `update_section(user_id, section_id, **fields)`
- `delete_section(user_id, section_id)`
- `reorder_sections(user_id, note_id, ordered_ids)` → reasigna `position`

Validar siempre que `category`/`project` referenciados pertenezcan al `user_id`.

### 2.3 GraphQL — `core/schema.py`

```python
@strawberry.type
class NoteSection:
    id: strawberry.ID
    heading: str
    body: str
    position: int
    collapsed: bool
    updated_at: dt.datetime

@strawberry.type
class QuickNote:
    id: strawberry.ID
    title: str
    pinned: bool
    category: Optional[Category]
    project: Optional["Project"]
    sections: List[NoteSection]
    created: dt.datetime
    updated_at: dt.datetime

@strawberry.input
class QuickNoteInput:
    title: Optional[str] = ""
    category_id: Optional[strawberry.ID] = None
    project_id: Optional[strawberry.ID] = None
    pinned: Optional[bool] = False

@strawberry.input
class NoteSectionInput:
    heading: Optional[str] = ""
    body: Optional[str] = ""
    position: Optional[int] = 0
    collapsed: Optional[bool] = False
```

**Query** (separada del dashboard para no inflarlo — las notas pueden ser muchas;
se carga *lazy* al abrir el tab):

```graphql
quickNotes(search: String, categoryId: ID, projectId: ID, pinned: Boolean): [QuickNote!]!
quickNote(id: ID!): QuickNote
```

**Mutations:**
`createQuickNote`, `updateQuickNote`, `deleteQuickNote`,
`addNoteSection`, `updateNoteSection`, `deleteNoteSection`, `reorderNoteSections`.

### 2.4 Quotas — `core/quotas.py`

```python
ENTITY_QUOTAS = {
    "quick_notes":          {FREE: 50,  PRO: 1000, STUDIO: None, ADMIN: None},
    "sections_per_note":    {FREE: 20,  PRO: None, STUDIO: None, ADMIN: None},
}
```

### 2.5 Activity log — `core/models.py` (`ActivityKind`)

Añadir `QUICK_NOTE_CREATED`, `QUICK_NOTE_DELETED` (opcional, para el feed/Log).

### 2.6 Migración

`core/migrations/00NN_quick_notes.py` con `CreateModel` de `QuickNote` y
`NoteSection`. Correr `python manage.py makemigrations` desde el `.venv` del repo.

### 2.7 Tests

- `core/tests/test_quick_notes.py`: CRUD, aislamiento por `user_id`, secciones,
  reorder, borrado en cascada, FK `SET_NULL` al borrar proyecto/categoría.
- Añadir caps a `test_tier_quotas.py`.

> Nota: los tests son lentos; correr con el pytest del `.venv` raíz (ver memoria).

---

## 3. Frontend (Next.js + Apollo)

Patrón de Ideas, pero con vista de dos paneles (lista + editor).

| Archivo | Acción |
|---|---|
| `src/lib/types.ts` | Añadir `QuickNote`, `NoteSection` |
| `src/lib/graphql.ts` | `QUICK_NOTES_QUERY` + mutations |
| `src/hooks/useQuickNotes.ts` | query con filtros (search/categoría/proyecto) |
| `src/hooks/useQuickNoteMutations.ts` | create/update/delete + secciones + reorder |
| `src/components/dashboard/TabBar.tsx` | nuevo tab `notes`, icono `NotebookPen`/`StickyNote` |
| `src/components/views/QuickNotesView.tsx` | **nuevo** — toolbar + chips + lista + editor |
| `src/components/notes/NoteCard.tsx` | tarjeta con franja de color de categoría |
| `src/components/notes/NoteEditor.tsx` | título inline, props (categoría/proyecto/pin), acordeón |
| `src/components/notes/NoteSection.tsx` | toggle plegable, editable, arrastrable |
| `messages/en.json` + `es.json` | namespace `views.quickNotes` y `modals.quickNote` |

- **Tipo de vista:** añadir `"notes"` a `DashboardView`.
- **Acento de color:** teal (`#2dd4bf`) para distinguir de Ideas (púrpura); cada
  tarjeta se tiñe con el color de **su categoría** (`Category.color`).
- **Reorder de secciones:** `@dnd-kit` o drag nativo; persistir con `reorderNoteSections`.
- **Editor inline** (no modal) en desktop por la riqueza del contenido; el botón
  "Nueva nota" abre una nota vacía directamente en el panel derecho.
- Reusar `Modal`, `Field`, `FAB` existentes para el selector de categoría/proyecto.

---

## 4. Mobile (Expo Router + Apollo + NativeWind)

| Archivo | Acción |
|---|---|
| `src/lib/types.ts` | `QuickNote`, `NoteSection` (compartir forma con web) |
| `src/lib/graphql.ts` | misma query + mutations |
| `src/hooks/useQuickNotes.ts` / `useQuickNoteMutations.ts` | **nuevos** |
| `src/app/(dashboard)/(more)/quick-notes.tsx` | lista (cards, search, chips, FAB) |
| `src/app/(dashboard)/(more)/quick-note.tsx` | **detalle/editor** con acordeón (pantalla, no modal, por la riqueza) |
| `src/app/(modals)/quick-note-meta.tsx` | sheet para categoría/proyecto/pin |
| `src/app/(dashboard)/(more)/_layout.tsx` | registrar las pantallas |
| `src/app/(dashboard)/(more)/more.tsx` | item "Quick Notes" con icono `NotebookPen` |
| `src/messages/en.json` + `es.json` | mismas claves i18n (ICU, llave simple) |

- **¿Tab o More?** Empezar bajo **More** (como Ideas). Si lo usas mucho, promover a
  5º tab del bottom bar más adelante.
- Recordatorios del repo móvil: usar `npm`/`npx expo install`; correr
  `npx expo export -p ios --clear` antes de `npx tsc --noEmit`; opacidad sobre
  colores de tema con `alpha(hex, n)`, no `bg-accent/15`; inyectar CSS vars en modales.

---

## 5. i18n (en/es)

Namespace nuevo en ambos repos:

```jsonc
"views": { "quickNotes": {
  "title": "Quick Notes", "subtitle": "...", "search": "Buscar en notas…",
  "newNote": "Nueva nota", "empty": "Aún no tienes notas.",
  "standalone": "nota suelta", "sections": "{count, plural, one {# sección} other {# secciones}}",
  "filters": { "all": "Todas", "byProject": "Por proyecto", "loose": "Sueltas", "pinned": "Fijadas" }
}},
"modals": { "quickNote": {
  "category": "Categoría", "project": "Proyecto", "pin": "Fijar",
  "addSection": "Agregar sección", "sectionHeading": "Título de la sección"
}}
```

---

## 6. Orden de entrega (fases)

1. **Backend** — modelos + migración + servicio + schema + quotas + tests. *(núcleo)*
2. **Web** — tab, query/mutations, lista + editor con acordeón. *(donde más valor)*
3. **Mobile** — lista + pantalla de detalle con acordeón.
4. **Pulido** — reorder drag&drop, fijar, búsqueda en cuerpos de sección, item en Log.

Cada fase es entregable de forma independiente; la web (fase 2) ya cierra el
caso de uso principal de reemplazar Notion en escritorio.

---

## 7. Decisiones tomadas

- **Cuerpo de sección:** Markdown **sin** checklists nativas. `body` se guarda como
  texto markdown; el editor usa un textarea monoespaciado. (Las checklists del
  wireframe son ilustrativas; no son parte de v1.)
- **Categorías:** **una sola** por nota (FK simple reusando `Category`). Migrable a
  multi-tag más adelante.
- **Promote a proyecto:** fuera de alcance v1.

## 8. Estado de implementación

- [x] **Fase 1 — Backend.** Modelos `QuickNote`/`NoteSection`, migración
  `0020_*`, servicio `core/services/quick_notes.py`, tipos+mutations en
  `core/schema.py`, quotas (`quick_notes` 50/1000, `sections_per_note` 20/∞),
  `ActivityKind` nuevos, tests `core/tests/test_quick_notes.py` (11 ✓).
- [x] **Fase 2 — Web.** Tipos, GraphQL, hooks `useQuickNotes`/
  `useQuickNoteMutations`, vista `QuickNotesView` (lista + editor con secciones
  plegables, reorder ▲▼, fijar, categoría/proyecto), tab `notes` en `TabBar` y
  `MoreSheet`, i18n en/es. `tsc --noEmit` limpio.
- [x] **Fase 3 — Mobile** (Expo Router). Tipos, GraphQL y hooks espejo de la web;
  pantalla lista `(more)/quick-notes.tsx` (búsqueda, chips de filtro, cards, FAB),
  editor `(more)/quick-note.tsx` (título, categoría en chips, proyecto vía
  `ProjectSelect`, secciones plegables con reorder ▲▼, fijar, borrar), componente
  `components/notes/NoteSectionCard.tsx`, registro en `(more)/_layout.tsx` + item
  en `more.tsx`, i18n en/es. Verificado: `expo export -p ios --clear` y
  `tsc --noEmit` ambos exit 0.
- [x] **Fase 4 — Pulido.**
  - **Log:** el backend ya emitía `quick_note_created/deleted`; ahora la vista Log
    (web `LogView.tsx` y móvil `(more)/log.tsx`) los mapea con icono `NotebookPen`,
    descripción i18n (`entries.quickNoteCreated/Deleted`) y filtro "deleted".
  - **Markdown:** renderer ligero **sin dependencias** (`components/notes/MarkdownText.tsx`
    en web y móvil) — subset: encabezados, listas, **negrita**, *cursiva*, `código`,
    enlaces. Cada sección tiene toggle vista/edición (👁/✎); en preview se renderiza
    el markdown, tocar para editar.
  - **Drag & drop:** web con `@dnd-kit` (handle ⠿ en cada sección + reorder por
    teclado). En móvil se conservan los botones ▲▼ (sin gesto nativo de arrastre).
  - Verificado: web `tsc` exit 0; móvil `expo export` + `tsc` exit 0.

> Migración: `0020_*` aplica limpio en BD de test (los tests la corren). **No**
> se corrió `migrate` contra la BD de Supabase de producción.

## 9. Integración en el onboarding (hecho)

- **Seed (Capa 1):** los usuarios **nuevos** reciben una nota de ejemplo "How to use
  Notes" con 2 secciones plegables (la 2ª inicia plegada) — `core/services/seed.py`,
  test extendido en `core/tests/test_seed.py` (5 ✓). No re-siembra a usuarios
  existentes.
- **Tour (Capa 2b):** paso dedicado de Notes entre routines y assistant.
  - *Web:* `data-tour="notes"` en `TabBar.tsx` + paso **condicional** en
    `DashboardTour.tsx` (solo si el tab es visible → desktop; en mobile-web se omite
    porque Notes vive en el `MoreSheet`). Claves `onboarding.tour.stepNotes` (en/es).
  - *Móvil:* coachmark en el array `STEPS` de `DashboardTour.tsx` (icono `NotebookPen`)
    + claves `onboarding.tour.stepNotes` (en/es).
  - No se tocó `TOTAL_STEPS` (no es un paso del onboarding, solo del tour).
- Verificado: backend tests ✓; web `tsc` ✓; móvil `expo export` + `tsc` ✓.
