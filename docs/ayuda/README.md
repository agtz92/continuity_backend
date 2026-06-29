# docs/ayuda — Recursos de ayuda para el CMS

Guías paso a paso de la herramienta pública de Continuity (excluye admin). Pensadas para publicarse como posts en el CMS: el **texto** va en Markdown y las **capturas** son PNG generados a partir de mockups HTML fieles a la UI real.

## Estructura

```
docs/ayuda/
  _base.css            Estilos compartidos (tokens del tema "Dark" real de la app)
  _shoot.mjs           Renderizador HTML→PNG (Chrome headless vía DevTools Protocol, sin deps)
  <vista>.html         Mockup en español  (enlaza _base.css)
  <vista>.en.html      Mockup en inglés
  es/<vista>.md        Texto del post en español, con placeholders [imagen: archivo.png]
  es/img/*.png         Capturas en español (2x retina)
  en/<vista>.md        Texto del post en inglés, con placeholders [image: archivo.png]
  en/img/*.png         Capturas en inglés
  es/index.md          Índice de todas las guías (es) — en/index.md para inglés
```

Vistas cubiertas: `today, projects, tasks, routines, ideas, notes, log, analytics, graveyard, appearance, plugins`.

## Convención de nombres de imagen

`<vista>-<NN>-<seccion>.png` — `NN` es el orden (2 dígitos) de cada captura en el documento y `<seccion>` es el id de su `<section class="step">`. El placeholder en el markdown usa exactamente ese nombre, así que basta subir las imágenes con su nombre y reemplazar el placeholder en el CMS.

## Regenerar capturas

Requiere Google Chrome y Node 21+ (usa el `WebSocket` global). Desde esta carpeta:

```bash
NODE=/opt/homebrew/bin/node
# una vista (es + en):
$NODE _shoot.mjs today.html    es/img today
$NODE _shoot.mjs today.en.html en/img today
# todas:
for v in today projects tasks routines ideas notes log analytics graveyard appearance plugins; do
  $NODE _shoot.mjs $v.html    es/img $v
  $NODE _shoot.mjs $v.en.html en/img $v
done
```

Argumentos de `_shoot.mjs`: `<archivoHTML> <carpetaSalida> <prefijo>`. El script recorta cada `<div class="shot">` a su tamaño exacto a 2x. Editar un mockup `.html` y volver a correrlo basta para actualizar sus PNG.

## Verificar que cada placeholder tenga su imagen

```bash
for md in es/*.md; do while read -r i; do [ -z "$i" ]&&continue; \
  [ -f "es/img/$i" ]||echo "FALTA $i ($md)"; \
  done < <(grep -oE '\[imagen: [^]]+\]' "$md"|sed 's/\[imagen: //;s/\]//'); done
```
