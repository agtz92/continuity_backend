# Loop: tareas complejas que se detienen sin terminar — diagnóstico y plan

Fecha: 2026-10-15. Fuente: tablas `assistant_message` y `core_activity` de prod (Supabase `Continuity`), código en `core/assistant/` y pruebas nuevas.

## Lo que muestran los datos

182 turnos en total. 144 cerraron con `end_turn`. **32 terminaron sin ninguna respuesta del asistente** (el hilo acaba en el mensaje del usuario), 5 murieron después de un `tool_result` y 1 se truncó en `max_tokens`.

Caso testigo, 2026-09-11 (antes de `fea90d1`):

| hora (UTC) | mensaje del usuario | lo que pasó de verdad (`core_activity`) |
|---|---|---|
| 03:22:42 | "PONME LOS PROMPTS… EN LAS NOTAS" | proyecto + 8 tareas creados. Ninguna fila en el chat |
| 03:23:35 | "?" | **otro** proyecto + 8 tareas |
| 03:25:05 | "continua" | **otro** proyecto + 8 tareas |
| 03:27:10 | "haz los tasks" | **otro** proyecto |
| 03:29–03:30 | — | el usuario borra los 4 a mano |

En los cuatro turnos las tools sí corrieron. El stream murió cuando el modelo empezó a escribir las notas largas, y como el código de entonces persistía el turno al final, el chat no guardó nada. Por eso cada reintento volvía a crear todo. Lo mismo pasó a las 19:08 ("Ok", "?").

`fea90d1` ya corrige la persistencia (ahora es incremental), sube `max_tokens` y cambia a `gthread`. **No corrige por qué se corta el stream.**

## Causas que siguen vivas (reproducidas)

| # | Causa | Evidencia | Prueba |
|---|---|---|---|
| A | **Silencio en el cable.** Mientras el modelo escribe un `tool_use` largo, la vista no manda ni un byte, y cualquier proxy con idle-timeout corta la conexión | Medido contra la API real: Haiku escribiendo 6 notas pasó **63 s sin emitir nada** (6.9k tokens). Con el tope de 16k tokens serían unos 150 s | `test_long_tool_input_keeps_the_connection_alive` (xfail) |
| B | **"Voy a hacerlo" y cierra.** El modelo anuncia la acción y termina con `end_turn` sin llamar tools | Prod 09-11 19:08:27: "Voy a crear un proyecto… Primero, déjame…" y fin del turno | `test_a_turn_that_only_announces_work_gets_nudged_to_do_it` (xfail) |
| C | **Truncado a mitad de un `tool_use`.** El turno termina con error en lugar de reintentar en trozos más chicos. Si no había prosa, no queda ni rastro | Firma idéntica a los turnos `NO_REPLY` | `test_truncation_mid_tool_use_retries_in_smaller_pieces` (xfail) |
| D | **Un 529 o un error de conexión** a mitad del turno lo mata, porque no hay reintento dentro del loop | — | `test_a_transient_upstream_error_is_retried` (xfail) |
| E | **El cliente no detecta el corte.** `streamChat` resuelve igual aunque nunca llegue `done`, y la UI queda en silencio con la burbuja a medias | — | `assistantStream.test.ts` (`it.fails`) |

Los `xfail(strict=True)` y `it.fails` revientan en cuanto se arregla el bug, así que obligan a quitar la marca junto con el arreglo.

## Plan de corrección

### P0: que el turno no se corte y que el corte se vea

1. **Keepalive y progreso (A).** En `_stream_turn`:
   - En `content_block_start` de tipo `tool_use`, emitir un evento nuevo `tool_use_pending {name}`. Así la UI puede mostrar "escribiendo nota…".
   - Si pasan 10 s o más sin emitir nada, emitir un comentario SSE `: ping\n\n`.
   - Mantener el ping también mientras corre `tools_pkg.call`.

   Los clientes ignoran los comentarios, así que no hace falta release para que el ping funcione.
2. **El cliente detecta el corte (E), en web y en móvil.** Si el reader termina sin `done`, `streamChat` lanza `StreamCutError`. `useAssistant` responde así:
   - pinta "Se cortó la conexión; esto es lo que alcanzó a hacer";
   - recarga `/conversations/<id>/messages/`, que ya tiene todo gracias a la persistencia incremental;
   - refresca el dashboard.

   Espejo en `continuity-mobile/src/lib/assistantStream.ts`.
3. **Verificar el start command real en Render.** `fea90d1` dice que el dashboard "hay que ajustarlo a mano". Hay que confirmar que el servicio corre `gthread --timeout 120` y no el `sync` de 30 s.

### P1: que el modelo termine lo que empezó

4. **Truncado, reintento en trozos (C).** Ante `max_tokens` con `tool_use`:
   - guardar el texto o un placeholder;
   - añadir un mensaje de sistema: "tu respuesta se cortó antes de ejecutar X; repítelo en llamadas de como máximo 2 por respuesta";
   - seguir el loop, con un máximo de 2 reintentos y consumiendo presupuesto.

   Cuidar la alternancia de roles `assistant`/`user`.
5. **Empujón ante "promesa sin acción" (B).** Si `end_turn` llega sin tools en esa iteración, el texto no termina en `?` y contiene un anuncio ("voy a", "déjame", "procedo", "I'll", "let me", o termina en `:`), hacer **una** llamada extra con la instrucción "ejecuta ahora lo que anunciaste o pregunta explícitamente". Una sola vez por turno. El test de guarda `test_a_genuine_question_is_not_nudged` ya existe.

   Además, en `prompts.py`, añadir una regla explícita: "nunca anuncies una acción y cierres el turno: o llamas la tool en la misma respuesta o terminas con una pregunta". La regla 5 de brainstorming debe exigir que el turno cierre con una pregunta de aprobación.
6. **Reintento de errores transitorios (D).** Hacer 1 o 2 reintentos con backoff ante `OverloadedError`, `APIConnectionError`, `InternalServerError` y `RateLimitError`, **solo si esa iteración aún no emitió texto** (si no, se duplicaría la prosa).

### P2: blindaje y visibilidad

7. **Observabilidad.** Hoy un turno que falla no deja rastro en la BD (los 32 `NO_REPLY`). Guardar el resultado por turno (`stop_reason` = `error:<Clase>` / `cut`, iteraciones, duración, tools ejecutadas) y una consulta admin de "turnos sin cierre".
8. **Anti-duplicado barato.** `create_project` con el mismo nombre del mismo usuario en los últimos 10 min devuelve el existente con `already_exists: true`.

Orden sugerido: 1 → 2 → 3, luego 4, 5 y 6, y al final 7 y 8. Cada punto voltea su prueba de este documento.
