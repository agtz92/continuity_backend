# Mantenimiento de la landing page (continuu.it)

Guía para cualquiera que edite o agregue secciones a la landing
(`frontend/src/components/landing/**`, servida en `/` y `/es`).

> **Principio rector — no negociable:**
> La landing debe ser **muy rápida en iPhone / Safari iOS** *sin* sacrificar el
> **look & feel ni las animaciones**. No es "rápido **o** bonito": las dos cosas.
> Cada cambio se evalúa contra esto. Safari iOS tiene mucho menos CPU/GPU que
> Chrome de escritorio — lo que ahí se siente fluido casi siempre vuela en desktop,
> pero **no al revés**. El iPhone es el dispositivo de referencia, no el laptop.

El **porqué** y el historial de las mejoras de performance del sitio de marketing
viven en [`marketing-performance.md`](./marketing-performance.md). Las reglas
operativas de render estático vs dinámico están en `frontend/CLAUDE.md`
(secciones "Render: marketing ESTÁTICO vs herramienta DINÁMICA" e "Higiene del
bundle de marketing"). Este documento es el **cómo mantenerlo** específico de la landing.

## La estrategia: rápido Y con animaciones

La clave es que "animado" no tiene que significar "JS pesado". El error que hacía
la landing lenta en iPhone era animar todo con framer-motion: el HTML estático
llegaba **invisible** (`opacity: 0`) y no aparecía hasta que framer hidrataba →
en iPhone se veía cargar "por partes" y el hero tardaba (mal LCP).

La solución no fue **quitar** animaciones, sino **moverlas a CSS** (que corre al
primer paint, sin esperar hidratación) y reservar el JS de animación solo para lo
que de verdad lo necesita y que además se carga tarde.

### Animaciones — usa CSS, no framer-motion

- **Reveals al hacer scroll:** clase `.ls-reveal` (definida en `src/app/globals.css`).
  Hace fade + lift cuando el elemento entra al viewport, vía `animation-timeline: view()`
  — **cero JS**. El estado base es **visible**, así que en Safari viejo o con
  `prefers-reduced-motion` el contenido simplemente se muestra (nunca se queda oculto).
- **Entrada al cargar (above-the-fold):** clase `.ls-fade-up` (+ `.ls-fade-up-1/2/3`
  para escalonar). Corre una vez al primer paint. Úsala en el hero y todo lo que se
  ve sin hacer scroll: **debe pintar inmediato, jamás depender de hidratación**.
- **Hover/tap:** CSS (`transition` + `motion-safe:hover:scale-[...]` /
  `motion-safe:hover:-translate-y-1.5`). Ver `CTAButton.tsx` y `Pricing.tsx`.
- **framer-motion solo en demos interactivos** (`Features/*Demo.tsx`): animaciones
  por pasos/estados que CSS no cubre bien. **Siempre lazy-loaded** (ver abajo), nunca
  en una sección always-on.

> Regla: si una animación se puede hacer con CSS, se hace con CSS. framer-motion es
> la excepción para gadgets interactivos complejos, y siempre detrás de `next/dynamic`.

### Efectos visuales — cuida el costo de pintado en iOS

- **Nada de `blur-[Npx]` grandes.** Un `blur()` de 100-140px sobre superficies
  grandes es de lo más caro que existe en Safari iOS (se recalcula en cada frame de
  scroll). Para glows/halos usa **`radial-gradient`** (ver `Hero.tsx` / `FinalCall.tsx`):
  ```
  background: radial-gradient(900px 600px at 50% 33%,
    color-mix(in srgb, var(--ls-ochre) 10%, transparent), transparent 70%);
  ```
  Mismo look, cero filtro.
- **`backdrop-blur` con moderación.** En tarjetas chicas (`-sm` = 4px) es tolerable;
  evita `backdrop-blur` en elementos grandes o fijos (el header) porque se recalcula
  al hacer scroll. Si una sección nueva lo necesita en muchas tarjetas a la vez,
  reconsidéralo.

### JS pesado — cárgalo tarde o no lo cargues

- **Demos de Features:** `next/dynamic(() => import(...), { ssr: false, loading })`
  en `FeaturesSection.tsx`. Así framer y el código del demo van en chunks aparte que
  solo se descargan al hacer scroll hasta esa sección — fuera del bundle crítico.
  El `loading` reserva altura (`min-h-[360px]`) para evitar layout shift.
- **Lenis (smooth-scroll):** `import("lenis")` es dinámico y **después** del gate de
  `prefers-reduced-motion` + touch, así que los teléfonos (touch) nunca lo descargan.
  Ver `primitives/LenisProvider.tsx`.
- **Prohibido en componentes always-on de marketing:** Apollo Client, `@/lib/supabase`
  estático, framer-motion. (Detalle en `frontend/CLAUDE.md` → "Higiene del bundle".)
- **Imágenes:** siempre `next/image` (nunca `<img>` crudo).

### Render

- La landing es **estática (ISR)**, no SSR. No leas cookies/headers ni en el root
  layout ni en las páginas de marketing (eso contamina toda la app a dinámico y mata
  el prerender). El idioma vive en la URL (`/` en, `/es` es), no en cookie.

## Checklist al agregar / editar una sección

- [ ] ¿La animación es CSS (`.ls-reveal` / `.ls-fade-up` / `transition`)? Si metiste
      framer-motion, ¿de verdad lo necesita y está lazy-loaded?
- [ ] El contenido above-the-fold, ¿se ve al primer paint (no arranca en `opacity:0`
      esperando JS)?
- [ ] ¿Glows con `radial-gradient`, no `blur-[Npx]`?
- [ ] ¿Imágenes con `next/image`?
- [ ] ¿Ningún import always-on de Apollo / supabase / framer?
- [ ] `prefers-reduced-motion`: el contenido se ve igual de completo (las clases
      `.ls-*` ya lo respetan; si animas a mano, añade el guard).

## Cómo verificar

```bash
cd frontend
# typecheck (node/pnpm no están en PATH del sandbox; usar el entry JS real)
/opt/homebrew/bin/node node_modules/typescript/bin/tsc --noEmit
# build: la landing DEBE salir con ○ (estático), no ƒ (dinámico)
/opt/homebrew/bin/node node_modules/next/dist/bin/next build
```

- En la tabla de rutas de `next build`: `/`, `/es`, `/welcome` deben ser **`○`**.
- **Presupuesto de bundle:** First Load JS de `/` ≈ **130 kB**. Si un cambio lo
  sube notoriamente, casi siempre es que algo pesado (framer/supabase/apollo) entró
  al bundle crítico — revísalo.
- **Prueba real:** ábrela en un **iPhone** (o Safari + throttling de CPU 4-6×), no
  solo en Chrome de escritorio. La brecha entre ambos es justo el problema que esta
  guía evita.

## Referencias

- Utilidades de animación: `frontend/src/app/globals.css` (`.ls-reveal`, `.ls-fade-up`, `.ls-nav-enter`, `.ls-float`).
- Reglas de bundle/estático: `frontend/CLAUDE.md`.
- Historial de performance del sitio: [`marketing-performance.md`](./marketing-performance.md).
