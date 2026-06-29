"""Copy + rendering for product/lifecycle emails (bilingual: en/es).

Copy authored externally (docs/_archive/beta-lifecycle/EMAIL_BRIEF.md → beta-lifecycle-emails.md). Each
email_id has an `en` and `es` block: subject, preheader, cta, body. Bodies use
{{token}} placeholders, start with "{{greeting}}," and end with the signature
line; the CTA is injected from the `cta` field (before the signature). No
markdown dependency: a light renderer wraps paragraphs in <p>, turns "- " blocks
into <ul>, and preserves single line breaks.
"""

from __future__ import annotations

import html as _html
from typing import Any

DEFAULT_LOCALE = "en"

TEMPLATES: dict[str, dict[str, dict[str, str]]] = {
    "welcome_beta": {
        "en": {
            "subject": "You're in 🎉",
            "preheader": "One of {{spot_cap}} spots. Here's the deal.",
            "cta": "Open continuu",
            "body": """{{greeting}},

You're in. One of {{spot_cap}} people in the continuu beta.

The deal in plain terms: lifetime access, free, for as long as continuu exists. No trial clock, no upsell. In exchange, I ask one thing. Use it, and tell me what's broken. Every reply comes straight to me, and I read them all.

There are only {{spot_cap}} of these, so the spot stays yours as long as you're putting it to use. No rush. Just don't let it go cold.

The first step is small. Create one project. A title is enough.

One question before you go: what's the project you keep escaping from? Reply with one line.

Alfredo""",
        },
        "es": {
            "subject": "Estás dentro 🎉",
            "preheader": "Uno de {{spot_cap}} lugares. Aquí el trato.",
            "cta": "Abrir continuu",
            "body": """{{greeting}},

Estás dentro. Eres uno de {{spot_cap}} en la beta de continuu.

El trato, sin rodeos: acceso de por vida, gratis, mientras continuu exista. Sin reloj de prueba, sin venta escondida. A cambio te pido una cosa. Úsala y dime qué falla. Cada respuesta me llega directo a mí, y las leo todas.

Solo hay {{spot_cap}}, así que el lugar es tuyo mientras le des uso. Sin prisa. Solo no lo dejes enfriar.

El primer paso es pequeño. Crea un proyecto. Con el título basta.

Una pregunta antes de irte: ¿cuál es el proyecto del que sigues huyendo? Respóndeme en una línea.

Alfredo""",
        },
    },
    "welcome_regular": {
        "en": {
            "subject": "Welcome to continuu",
            "preheader": "Start with one project. That's it.",
            "cta": "Open continuu",
            "body": """{{greeting}},

Glad you're here. continuu is where your projects, tasks, routines, ideas, and notes live in one place, with a Today view that tells you what's next.

You don't need to set all that up now. Start with one project. A title is enough.

Open it up, add the first thing, and see how it feels. If something's confusing, reply to this email. It comes to me.

Alfredo""",
        },
        "es": {
            "subject": "Bienvenido a continuu",
            "preheader": "Empieza con un proyecto. Eso es todo.",
            "cta": "Abrir continuu",
            "body": """{{greeting}},

Qué bueno tenerte aquí. continuu es donde viven tus proyectos, tareas, rutinas, ideas y notas, en un solo lugar, con una vista Today que te dice qué sigue.

No tienes que armar todo eso ahora. Empieza con un proyecto. Con el título basta.

Ábrelo, agrega la primera cosa y mira cómo se siente. Si algo no se entiende, responde este correo. Me llega a mí.

Alfredo""",
        },
    },
    "inactivity_1": {
        "en": {
            "subject": "Stuck on the first step?",
            "preheader": "The first move isn't always obvious.",
            "cta": "Create your first project",
            "body": """{{greeting}},

You signed up a few days ago and haven't created anything yet. My guess is it's not lack of interest. It's that the first move isn't obvious.

So let me make it obvious. Pick one project you care about. Open continuu. Type the title. Done.

That's the whole first step. Everything else can wait until you're back inside.

If something got in the way, reply and tell me. I'd like to fix it.

Alfredo""",
        },
        "es": {
            "subject": "¿Atascado en el primer paso?",
            "preheader": "El primer paso no siempre es obvio.",
            "cta": "Crear tu primer proyecto",
            "body": """{{greeting}},

Te registraste hace unos días y todavía no has creado nada. Mi apuesta es que no es falta de interés. Es que el primer paso no es obvio.

Déjame hacerlo obvio. Elige un proyecto que te importe. Abre continuu. Escribe el título. Listo.

Ese es todo el primer paso. Lo demás puede esperar a que estés adentro.

Si algo se interpuso, respóndeme y dime qué fue. Me gustaría arreglarlo.

Alfredo""",
        },
    },
    "inactivity_2": {
        "en": {
            "subject": "What continuu is for",
            "preheader": "A quick reminder, in three lines.",
            "cta": "Try it out",
            "body": """{{greeting}},

A week in and continuu is still sitting untouched. No pressure. But here's a quick reminder of what it's for, in case it helps:

- Projects and tasks: the things you're trying to finish, and the next step on each.
- Routines: the stuff you want to do regularly without re-deciding every time.
- Ideas and notes: the thoughts you'd otherwise lose in a dozen apps.

All of it rolls up into one Today view that tells you what's next. That's the whole point. Less deciding, more doing.

The bar to start is low. One project, one line.

Alfredo""",
        },
        "es": {
            "subject": "Para qué sirve continuu",
            "preheader": "Un recordatorio rápido, en tres líneas.",
            "cta": "Probar la app",
            "body": """{{greeting}},

Llevas una semana y continuu sigue sin estrenar. Sin presión. Pero aquí va un recordatorio rápido de para qué sirve, por si ayuda:

- Proyectos y tareas: lo que quieres terminar, y el siguiente paso de cada uno.
- Rutinas: lo que quieres hacer seguido sin volver a decidirlo cada vez.
- Ideas y notas: las cosas que si no, se te pierden en diez apps.

Todo eso se junta en una sola vista Today que te dice qué sigue. Ese es el punto. Decidir menos, hacer más.

La barrera para empezar es baja. Un proyecto, una línea.

Alfredo""",
        },
    },
    "inactivity_3": {
        "en": {
            "subject": "Your beta spot",
            "preheader": "Two weeks unused. Here's the honest situation.",
            "cta": "Keep my spot",
            "body": """{{greeting}},

Time for an honest note. The beta is capped at {{spot_cap}} spots, and yours has been sitting unused for two weeks.

I'm not writing this to guilt you. A spot that's never used can't tell me anything, and that's the trade the beta runs on: access in exchange for real use and feedback.

If continuu isn't the right fit right now, that's completely fine. You can let the spot go and someone else can take it.

If you do want to keep it, the bar is low. Open the app and create one thing this week. That's it.

Alfredo""",
        },
        "es": {
            "subject": "Tu lugar en la beta",
            "preheader": "Dos semanas sin usarse. La situación, honesta.",
            "cta": "Conservar mi lugar",
            "body": """{{greeting}},

Toca una nota honesta. La beta tiene un tope de {{spot_cap}} lugares, y el tuyo lleva dos semanas sin usarse.

No te escribo para hacerte sentir mal. Un lugar que nunca se usa no me dice nada, y ese es el trato de la beta: acceso a cambio de uso real y feedback.

Si continuu no es para ti en este momento, no pasa nada. Puedes soltar el lugar y alguien más lo toma.

Si quieres conservarlo, la barrera es baja. Abre la app y crea una cosa esta semana. Eso es todo.

Alfredo""",
        },
    },
    "inactivity_4": {
        "en": {
            "subject": "I freed up your spot",
            "preheader": "No drama. Your account is still alive.",
            "cta": "Open continuu",
            "body": """{{greeting}},

I went ahead and freed up your beta spot. Three weeks without a single project felt like the honest call, rather than letting the spot sit frozen.

No drama, and nothing's lost. Your account is still alive on the regular plan, and your data is untouched.

If life clears up and you want back in, just reply. The door's open.

Alfredo""",
        },
        "es": {
            "subject": "Liberé tu lugar",
            "preheader": "Sin drama. Tu cuenta sigue viva.",
            "cta": "Entrar a continuu",
            "body": """{{greeting}},

Solté tu lugar en la beta. Tres semanas sin un solo proyecto me pareció la decisión honesta, en lugar de dejar el lugar congelado.

Sin drama, y no se pierde nada. Tu cuenta sigue viva en el plan normal, y tus datos están intactos.

Si las cosas se despejan y quieres volver, solo respóndeme. La puerta está abierta.

Alfredo""",
        },
    },
    "reengage_1": {
        "en": {
            "subject": "Right where you left it",
            "preheader": "It's been {{days_inactive}} days. Easy to pick back up.",
            "cta": "Pick it back up",
            "body": """{{greeting}},

You were actually using continuu, and then it went quiet about {{days_inactive}} days ago. I noticed.

No guilt here. Projects stall. That's half the reason continuu exists.

Last time, you were in the middle of {{last_project_title}}. Your projects are still there, right where you left them. Picking one back up costs you nothing.

Want to start small? Open the app and move one thing. Momentum does the rest.

Alfredo""",
        },
        "es": {
            "subject": "Justo donde lo dejaste",
            "preheader": "Pasaron {{days_inactive}} días. Retomar es fácil.",
            "cta": "Retomar",
            "body": """{{greeting}},

Estabas usando continuu de verdad, y luego se hizo silencio hace unos {{days_inactive}} días. Lo noté.

Sin culpas. Los proyectos se frenan. Esa es media razón por la que continuu existe.

La última vez estabas metido en {{last_project_title}}. Tus proyectos siguen ahí, justo donde los dejaste. Retomar uno no te cuesta nada.

¿Empezamos por algo pequeño? Abre la app y mueve una cosa. El impulso hace el resto.

Alfredo""",
        },
    },
    "reengage_2": {
        "en": {
            "subject": "Is continuu still useful to you?",
            "preheader": "A straight question, and an easy reply.",
            "cta": "Come back to continuu",
            "body": """{{greeting}},

Straight question: is continuu still useful to you?

If yes, come back. You don't need a fresh start. Your stuff is where you left it, and one small move gets you going again.

If no, I'd really like to know why. Reply to this email with one honest line. What didn't work? That feedback shapes what I build next.

Either answer helps me. Silence is the only one that doesn't.

Alfredo""",
        },
        "es": {
            "subject": "¿continuu te sigue sirviendo?",
            "preheader": "Una pregunta directa, y una respuesta fácil.",
            "cta": "Volver a continuu",
            "body": """{{greeting}},

Pregunta directa: ¿continuu te sigue sirviendo?

Si sí, vuelve. No necesitas empezar de cero. Tus cosas están donde las dejaste, y un movimiento pequeño te pone en marcha otra vez.

Si no, de verdad me gustaría saber por qué. Responde este correo con una línea honesta. ¿Qué no funcionó? Ese feedback define lo que construyo después.

Cualquier respuesta me ayuda. La única que no, es el silencio.

Alfredo""",
        },
    },
    "reclaim_warn": {
        "en": {
            "subject": "Last call on your beta spot",
            "preheader": "You were active once. That's why I'm asking first.",
            "cta": "Keep my spot",
            "body": """{{greeting}},

You were an active part of this beta once. That's why you're getting this note before anything happens, not after.

It's been a long stretch since you last opened continuu. The beta is capped, and I keep those spots for people who are actually building. Right now, yours is idle.

If you don't come back in the next few days, I'll free up your spot, and the lifetime deal goes with it.

Keeping it is simple. Move one thing this week. That's all it takes.

Alfredo""",
        },
        "es": {
            "subject": "Última llamada por tu lugar",
            "preheader": "Fuiste parte activa. Por eso te aviso primero.",
            "cta": "Conservar mi lugar",
            "body": """{{greeting}},

Alguna vez fuiste parte activa de esta beta. Por eso recibes esta nota antes de que pase nada, no después.

Llevas mucho sin abrir continuu. La beta tiene un tope, y guardo esos lugares para quienes de verdad están construyendo. Ahora mismo, el tuyo está quieto.

Si no vuelves en los próximos días, voy a liberar tu lugar, y el acceso de por vida se va con él.

Conservarlo es simple. Mueve una cosa esta semana. Con eso basta.

Alfredo""",
        },
    },
    "reclaim_final": {
        "en": {
            "subject": "Your spot, and a thank you",
            "preheader": "I freed it up. But first, genuinely, thanks.",
            "cta": "Open continuu",
            "body": """{{greeting}},

I freed up your beta spot today. Before anything else, a real thank you.

You used continuu when it was rough and unfinished, and the way you used it (and where you dropped off) helped me make it better. That's not a small thing. I mean it.

Nothing's lost. Your account stays on the regular plan, and your data is exactly where you left it.

And if you ever want back in, just reply. I'd be glad to have you.

Alfredo""",
        },
        "es": {
            "subject": "Tu lugar, y un gracias",
            "preheader": "Lo liberé. Pero primero, de verdad, gracias.",
            "cta": "Entrar a continuu",
            "body": """{{greeting}},

Hoy liberé tu lugar en la beta. Antes que nada, un gracias de verdad.

Usaste continuu cuando estaba en bruto y sin terminar, y la forma en que lo usaste (y dónde lo dejaste) me ayudó a mejorarlo. Eso no es poca cosa. Lo digo en serio.

No se pierde nada. Tu cuenta se queda en el plan normal, y tus datos están justo donde los dejaste.

Y si algún día quieres volver, solo respóndeme. Me daría gusto tenerte de vuelta.

Alfredo""",
        },
    },
}


def _sub(s: str, ctx: dict[str, Any]) -> str:
    for key, val in ctx.items():
        s = s.replace("{{" + key + "}}", str(val))
    return s


def _block_html(block: str) -> str:
    lines = [ln for ln in block.split("\n") if ln.strip()]
    if lines and all(ln.strip().startswith("- ") for ln in lines):
        items = "".join(f"<li>{_html.escape(ln.strip()[2:])}</li>" for ln in lines)
        return f"<ul>{items}</ul>"
    return "<p>" + "<br>".join(_html.escape(ln) for ln in lines) + "</p>"


def render(email_id: str, ctx: dict[str, Any], locale: str = DEFAULT_LOCALE) -> tuple[str, str, str]:
    """Return (subject, html, text) for `email_id` in `locale` (falls back to en)."""
    by_locale = TEMPLATES[email_id]
    tpl = by_locale.get(locale) or by_locale.get(DEFAULT_LOCALE) or next(iter(by_locale.values()))

    subject = _sub(tpl["subject"], ctx)
    preheader = _sub(tpl.get("preheader", ""), ctx)
    cta_label = tpl.get("cta", "")
    app_url = str(ctx.get("app_url", ""))
    body = _sub(tpl["body"], ctx)

    blocks = [b.strip() for b in body.split("\n\n") if b.strip()]
    # The last block is the signature ("Alfredo"); inject the CTA before it.
    signature = blocks.pop() if blocks and len(blocks[-1].split()) <= 3 else None

    html_parts = []
    if preheader:
        html_parts.append(
            f'<div style="display:none;max-height:0;overflow:hidden">{_html.escape(preheader)}</div>'
        )
    html_parts += [_block_html(b) for b in blocks]

    text_blocks = list(blocks)
    if cta_label and app_url:
        html_parts.append(f'<p><a href="{_html.escape(app_url)}">{_html.escape(cta_label)}</a></p>')
        text_blocks.append(f"{cta_label}: {app_url}")
    if signature:
        html_parts.append(_block_html(signature))
        text_blocks.append(signature)

    return subject, "\n".join(html_parts), "\n\n".join(text_blocks)
