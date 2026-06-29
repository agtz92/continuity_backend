# Performance del sitio de marketing (continuu.it)

Registro de las mejoras de rendimiento del sitio público (`/`, `/blog`, `/resources`,
`/recursos`, `/[slug]` CMS, legales) hechas en junio 2026. Resume el **qué** y el **porqué**;
el detalle operativo vive en `frontend/CLAUDE.md` (sección "Render: marketing ESTÁTICO vs
herramienta DINÁMICA" + "Higiene del bundle de marketing") y `backend/CLAUDE.md`.

## Problema

Las páginas de marketing se sentían **muy lentas en producción**, peor en **Safari iOS** que en
Chrome. Diagnóstico (medido sobre producción):

1. **Todo se renderizaba dinámico (SSR por request).** El root layout leía 4 cookies
   (`getLocale`/`getMessages`/`resolveTheme`/`resolvePalette`), lo que "contamina" toda la app a
   dinámico y anula el prerender/ISR.
2. **Payload GraphQL inflado.** Las queries de lista traían `content_html` completo de 20-50
   artículos solo para render de tarjetas; `publicHelpCategories` hacía un `COUNT` por categoría (N+1).
3. **Imágenes sin optimizar.** Portadas servidas crudas desde Supabase (un PNG de **2.8 MB**) con
   `<img>` plano en vez de `next/image`.
4. **~1 MB de JS para parsear/ejecutar.** Páginas de contenido estático arrastraban Apollo Client
   (~117 KB, sin usarse en marketing), supabase-js (~186 KB, solo para el toggle de login) y
   framer-motion. El CPU del iPhone lo sufre mucho más que Chrome de escritorio → de ahí la brecha.

## Cambios

### 1. Backend — payload de las queries públicas (`backend/core/cms/schema_public.py`)
- Las queries de lista (`publicBlogPosts`, `publicHelpResources`) hacen `.defer("content_html",
  "content_json")` y serializan con `include_content=False` (sin tocar el campo diferido → sin N+1).
- `publicHelpResources`/frontend dejaron de pedir `contentHtml` en las vistas de lista.
- `publicHelpCategories` pasó de un `COUNT` por categoría a **una query anotada** (`Count(filter=...)`).

### 2. Frontend — marketing ESTÁTICO (ISR), herramienta DINÁMICA
- **Root layout cookie-free** (`src/app/layout.tsx`): síncrono, `lang="en"` fijo; el no-flash
  script aplica `data-theme` **y `data-palette`** en cliente.
- **Route groups** (no cambian URLs): `(marketing-en)` y `(marketing-es)` con provider i18n de
  locale fijo + `dynamic = "force-static"`; `(app)` con provider de cookie → dinámico.
- **Idioma en la URL** (no cookie): inglés en paths base, español bajo `/es`; `/resources` ↔
  `/recursos` se mantienen. i18n estático request-independiente en `src/i18n/static.ts`; el switcher
  navega vía `src/i18n/marketingHref.ts`. hreflang/canonical + `/es` en el sitemap.
- Resultado: marketing sale `○`/`●` (estático) en `next build`; solo la herramienta sale `ƒ`.

### 3. Frontend — imágenes
- Portadas con **`next/image`** (WebP/AVIF responsive + lazy): el PNG de 2.8 MB pasa a ~21-40 KB
  según ancho. Cuerpo del artículo: `lazyLoadContentImages` (`src/lib/contentHtml.ts`) añade
  `loading="lazy" decoding="async"`.
- Nota: la subida de imágenes (`src/lib/cmsStorage.ts`) **ya comprime** a WebP (máx 1920px, q0.8),
  pero tiene fallbacks silenciosos que dejan pasar el original (decode/encode falla, o no reduce) y
  no hay tope de tamaño — de ahí el PNG grande. `next/image` lo mitiga al servir.

### 4. Frontend — peso del JS (lo que más pega en Safari iOS)
- **Apollo fuera de marketing**: `<Providers>` (Apollo + Toaster) se movió del root a `(app)/layout.tsx`.
- **supabase-js diferido**: `MarketingNav`/`RedirectIfAuthed` lo cargan con `await import(...)` en un
  `useEffect` en vez de import estático.
- **framer-motion fuera de marketing**: `MarketingNav` anima con CSS (`.ls-nav-enter`) y `CTAButton`
  hace el scale hover/tap con `motion-safe:hover:scale-[...]`. framer solo en secciones del landing.

## Resultados

- Páginas de marketing: de **dinámicas** a **estáticas (ISR)** servidas desde CDN.
- `/resources/[category]/[slug]` y `/blog`: **First Load JS 233 kB → 130 kB** (−44%); los chunks
  iniciales no contienen Apollo/supabase/framer.
- Imágenes de la página: de **~3.3 MB → ~120 KB**.

## Cómo NO regresar (invariantes)

- El **root layout no debe leer cookies** (mata el static de toda la app).
- En componentes always-on de marketing (nav/footer/shells): **no** importar `@/lib/supabase`
  estático, **no** usar framer-motion, **no** usar Apollo. Portadas con `next/image`, cuerpo con
  `lazyLoadContentImages`.
- Detalle y ejemplos: `frontend/CLAUDE.md`.

## Landing page (junio 2026, segunda pasada)

La landing (`/`, `/es`) seguía lenta en iPhone aunque ya fuera estática: **todas las
secciones eran framer-motion con `initial opacity:0` + `whileInView`**, así que el HTML
estático llegaba invisible y no aparecía hasta que framer hidrataba (cargaba "por partes",
hero lento). Cambios:

- **Reveals → CSS puro**: `.ls-reveal` (scroll-into-view vía `animation-timeline: view()`)
  y `.ls-fade-up` (entrada al cargar, above-the-fold) en `globals.css`. Estado base visible
  → reduced-motion / Safari viejo solo muestran el contenido. framer salió de ~10 secciones.
- **Glows `blur-[120px]` → `radial-gradient`** en `Hero.tsx` / `FinalCall.tsx` (el blur grande
  era un killer de repaint en scroll iOS).
- **Demos de Features lazy** (`next/dynamic`, `ssr:false`): framer ahora solo viaja en esos
  chunks, fuera del bundle crítico.
- **Lenis**: `import("lenis")` dinámico tras el gate touch/reduced-motion → teléfonos no lo bajan.

Guía de **cómo mantener** la landing con estas invariantes: [`landing-page.md`](./landing-page.md).

## Pendientes (siguientes ganancias para Safari iOS)

- **Fuentes** (~565 KB en 16 woff2): recortar ejes/pesos de Fraunces (variable, 3 ejes) o subsetear.
- **`backdrop-blur` restantes**: tarjetas de `HowItWorks`/`LoopSociety` y `DeviceFrame` usan
  `backdrop-blur-sm` (4px, tolerable); el header fijo aún tiene `backdrop-filter` (se recalcula en
  cada frame de scroll) — candidato a quitar si el scroll sigue pesado. (Los `blur-[120px]` grandes
  ya se reemplazaron por gradientes.)
- **Endurecer `cmsStorage.ts`**: segundo intento de compresión en JPEG, rechazar si sigue grande, y
  re-comprimir lo ya subido con el comando backend `core/management/commands/compress_storage.py`.
