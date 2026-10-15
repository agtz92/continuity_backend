"""Diagnóstico: los caminos por los que una tarea compleja se queda a medias.

Salen de revisar las conversaciones reales (`assistant_message` +
`core_activity`). Los tests marcados `xfail(strict=True)` describen el
comportamiento que QUEREMOS y hoy fallan a propósito: documentan un bug
vivo. Cuando se arregle, el `xfail` estricto se vuelve error y obliga a
quitar la marca — así el arreglo no puede llegar sin su prueba.

Los que no llevan marca fijan comportamiento que ya funciona y no debe
regresar.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any
from unittest import mock

import jwt
import pytest
from django.conf import settings as django_settings
from django.core.cache import cache
from django.test import Client

from core import auth as auth_module
from core.assistant import anthropic_client
from core.assistant.models import Conversation, Message, MessageRole
from core.models import Project, Task


# --------------------------------------------------------------------------
# Plumbing
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _force_test_auth_settings(settings, monkeypatch):
    settings.SUPABASE_URL = ""
    settings.SUPABASE_JWT_SECRET = "test-jwt-secret"
    monkeypatch.setattr(auth_module, "_jwks_client", None)


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


class _Ev:
    def __init__(self, **kw: Any):
        for k, v in kw.items():
            setattr(self, k, v)


_USAGE = {
    "input_tokens": 1,
    "output_tokens": 1,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
}


class _Stream:
    """Like the SDK stream, but it also emits `input_json_delta` events.

    The conftest fake only emits text deltas, which hides the case that
    matters here: while the model writes a long tool_use input (note
    bodies, detailed prompts) the SDK yields hundreds of `input_json_delta`
    events and *no* text — and the view forwards nothing.
    """

    def __init__(self, blocks, stop_reason, json_chunks=0, raise_on_enter=None):
        self.blocks = blocks
        self.stop_reason = stop_reason
        self.json_chunks = json_chunks
        self.raise_on_enter = raise_on_enter

    def __enter__(self):
        if self.raise_on_enter is not None:
            raise self.raise_on_enter
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for b in self.blocks:
            if b["type"] == "text":
                yield _Ev(
                    type="content_block_delta",
                    delta=_Ev(type="text_delta", text=b["text"]),
                )
        for _ in range(self.json_chunks):
            yield _Ev(
                type="content_block_delta",
                delta=_Ev(type="input_json_delta", partial_json='"x'),
            )

    def get_final_message(self):
        return _Ev(content=self.blocks, stop_reason=self.stop_reason, usage=_Ev(**_USAGE))


class _Client:
    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []
        self.messages = self

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            return _Stream([{"type": "text", "text": "ok"}], "end_turn")
        return self.script.pop(0)


def _text(t):
    return {"type": "text", "text": t}


def _tool(i, name, inp=None):
    return {"type": "tool_use", "id": i, "name": name, "input": inp or {}}


def _jwt(user_id):
    return jwt.encode(
        {
            "sub": str(user_id),
            "aud": "authenticated",
            "exp": int(dt.datetime.now(dt.timezone.utc).timestamp()) + 3600,
        },
        django_settings.SUPABASE_JWT_SECRET,
        algorithm="HS256",
    )


def _post(user_id, payload):
    return Client().post(
        "/api/assistant/chat/",
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {_jwt(user_id)}",
    )


def _chunks(response) -> list[bytes]:
    return list(response.streaming_content)


def _frames(chunks: list[bytes]) -> list[tuple[str, dict]]:
    out = []
    for raw in b"".join(chunks).decode().split("\n\n"):
        raw = raw.strip()
        if not raw or raw.startswith(":"):
            continue
        kind, data = "", {}
        for line in raw.splitlines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        out.append((kind, data))
    return out


def _run(user_id, client, payload):
    with mock.patch.object(anthropic_client, "_build_anthropic_client", return_value=client):
        return _chunks(_post(user_id, payload))


# --------------------------------------------------------------------------
# A. Silencio en el cable mientras el modelo escribe un tool_use largo
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_long_tool_input_keeps_the_connection_alive(user_a, make_profile):
    make_profile(user_a, plan="studio")
    client = _Client(
        [
            _Stream(
                [_text("Agrego las notas:"), _tool("tu_1", "list_projects")],
                "tool_use",
                json_chunks=500,  # ~ unos miles de tokens de cuerpo de nota
            ),
            _Stream([_text("Listo.")], "end_turn"),
        ]
    )
    chunks = _run(user_a, client, {"content": "crea notas con prompts"})

    # Entre el texto inicial y el tool_use_start pasan 500 eventos del SDK.
    # Antes no salía ni un byte por el cable en ese tramo.
    joined = b"".join(chunks).decode()
    head, _, _ = joined.partition("event: tool_use_start")
    after_text = head.split("Agrego las notas:", 1)[1]
    assert ": ping" in after_text or "event: progress" in after_text


class _StreamWithBlockStart(_Stream):
    """Emits the `content_block_start` the real SDK sends before a tool_use."""

    def __iter__(self):
        for b in self.blocks:
            if b["type"] == "tool_use":
                yield _Ev(
                    type="content_block_start",
                    content_block=_Ev(type="tool_use", id=b["id"], name=b["name"]),
                )
        yield from super().__iter__()


@pytest.mark.django_db
def test_a_tool_use_announces_itself_before_its_input_is_written(user_a, make_profile):
    make_profile(user_a, plan="studio")
    client = _Client(
        [
            _StreamWithBlockStart([_tool("tu_1", "list_projects")], "tool_use"),
            _Stream([_text("Listo.")], "end_turn"),
        ]
    )
    frames = _frames(_run(user_a, client, {"content": "lista"}))
    kinds = [k for k, _ in frames]
    assert kinds.index("tool_use_pending") < kinds.index("tool_use_start")
    assert dict(frames)["tool_use_pending"] == {"name": "list_projects"}


@pytest.mark.django_db
def test_a_slow_tool_keeps_the_connection_alive(user_a, make_profile, monkeypatch):
    import time as _time

    from core.assistant import tools as tools_pkg

    make_profile(user_a, plan="studio")
    real_call = tools_pkg.call

    def slow_call(*a, **kw):
        _time.sleep(0.3)
        return real_call(*a, **kw)

    monkeypatch.setattr(tools_pkg, "call", slow_call)
    monkeypatch.setattr(anthropic_client, "KEEPALIVE_SECONDS", 0.05)
    client = _Client(
        [
            _Stream([_tool("tu_1", "create_project", {"name": "Lento"})], "tool_use"),
            _Stream([_text("Listo.")], "end_turn"),
        ]
    )
    joined = b"".join(_run(user_a, client, {"content": "crea Lento"})).decode()

    between = joined.split("event: tool_use_start", 1)[1].split("event: tool_result", 1)[0]
    assert ": ping" in between
    # The tool ran on the request's own connection: its write is visible here.
    assert Project.objects.filter(user_id=user_a, name="Lento").exists()


# --------------------------------------------------------------------------
# B. "Voy a hacerlo" … y se termina el turno sin hacerlo
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_turn_that_only_announces_work_gets_nudged_to_do_it(user_a, make_profile):
    make_profile(user_a, plan="studio")
    client = _Client(
        [
            # Texto real de prod, conversación 689f91, 2026-09-11 19:08:27.
            _Stream(
                [
                    _text(
                        "Entendido. Voy a crear un proyecto **Finanzas personales** "
                        "con tareas estructuradas y luego agregaré notas.\n\n"
                        "Primero, déjame proponerte la estructura:"
                    )
                ],
                "end_turn",
            ),
            _Stream([_tool("tu_1", "list_projects")], "tool_use"),
            _Stream([_text("Creado.")], "end_turn"),
        ]
    )
    _run(user_a, client, {"content": "Crea el proyecto de finanzas"})
    assert len(client.calls) >= 2, "el loop debió empujar al modelo a ejecutar"


@pytest.mark.django_db
def test_a_genuine_question_is_not_nudged(user_a, make_profile):
    """Contraparte del anterior: preguntar NO es dejar la tarea a medias.
    Cualquier detector de "promesa sin acción" tiene que dejar pasar esto."""
    make_profile(user_a, plan="studio")
    client = _Client([_Stream([_text("¿Confirmas que borro estas 10 tareas?")], "end_turn")])
    _run(user_a, client, {"content": "Borra las tareas de Continuity"})
    assert len(client.calls) == 1


@pytest.mark.django_db
def test_the_nudge_happens_once_per_turn(user_a, make_profile):
    make_profile(user_a, plan="studio")
    announce = lambda: _Stream([_text("Voy a crear el proyecto ahora.")], "end_turn")  # noqa: E731
    client = _Client([announce(), announce(), announce()])
    _run(user_a, client, {"content": "Crea el proyecto"})
    assert len(client.calls) == 2


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Primero, déjame proponerte la estructura:", True),
        ("Listo, creé las 3 tareas.\n\nI'll keep an eye on the deadlines.", True),
        ("Listo, creé las 3 tareas. Let me know if you want changes.", False),
        ("Voy a crear esto.\n\nHecho: 3 tareas creadas.", False),
        ("¿Lo creo así?", False),
    ],
)
def test_announcement_detector(text, expected):
    assert anthropic_client._announces_without_acting([_text(text)]) is expected


# --------------------------------------------------------------------------
# C. Truncado en max_tokens con SOLO tool_use (sin prosa)
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_pure_tool_truncation_no_longer_leaves_the_thread_ending_on_the_user(
    user_a, make_profile
):
    """Antes, un turno truncado sin texto no persistía NADA del asistente: el
    hilo terminaba en el mensaje del usuario, la firma de los 32 turnos
    "NO_REPLY" de prod. Ahora se guarda un placeholder y se reintenta."""
    make_profile(user_a, plan="studio")
    client = _Client([_Stream([_tool("tu_1", "create_note")], "max_tokens")])
    frames = _frames(_run(user_a, client, {"content": "notas largas"}))

    assert not any(k == "error" for k, _ in frames)
    conv = Conversation.objects.get(user_id=user_a)
    rows = list(Message.objects.filter(conversation=conv).order_by("created"))
    assert [r.role for r in rows] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.ASSISTANT,
    ]
    assert "create_note" in rows[1].content[0]["text"]
    # El reintento le dijo al modelo qué no corrió, como mensaje de usuario.
    # (`messages` es la lista viva del loop: se busca, no se toma la cola.)
    convo = client.calls[1]["messages"]
    i = next(
        i
        for i, m in enumerate(convo)
        if m["role"] == "user"
        and isinstance(m["content"], list)
        and "NONE of those calls" in m["content"][0].get("text", "")
    )
    assert "create_note" in convo[i]["content"][0]["text"]
    assert convo[i - 1]["role"] == "assistant"
    # Lo que añadió el loop alterna (el historial previo no es asunto suyo).
    roles = [m["role"] for m in convo[i - 2 :]]
    assert all(a != b for a, b in zip(roles, roles[1:])), roles


@pytest.mark.django_db
def test_truncation_gives_up_after_two_retries(user_a, make_profile):
    make_profile(user_a, plan="studio")
    client = _Client([_Stream([_tool(f"tu_{i}", "create_note")], "max_tokens") for i in range(3)])
    frames = _frames(_run(user_a, client, {"content": "notas largas"}))

    assert len(client.calls) == 3
    assert any(k == "error" for k, _ in frames)


@pytest.mark.django_db
def test_truncation_mid_tool_use_retries_in_smaller_pieces(user_a, make_profile):
    make_profile(user_a, plan="studio")
    client = _Client(
        [
            _Stream([_tool("tu_1", "create_note")], "max_tokens"),
            _Stream([_tool("tu_2", "list_projects")], "tool_use"),
            _Stream([_text("Listo, en dos partes.")], "end_turn"),
        ]
    )
    frames = _frames(_run(user_a, client, {"content": "notas largas"}))
    assert len(client.calls) >= 2
    done = next(p for k, p in frames if k == "done")
    assert done["ok"] is True


# --------------------------------------------------------------------------
# D. Error transitorio de Anthropic a mitad del turno (529 / conexión)
# --------------------------------------------------------------------------


class OverloadedError(Exception):
    """Mismo nombre de clase que el SDK; la vista lo mira por nombre."""


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(anthropic_client, "RETRY_BACKOFF_SECONDS", (0, 0))


def _overloaded_script(failures=1):
    return [
        _Stream(
            [_text("Creo el proyecto:"), _tool("tu_1", "create_project", {"name": "Finanzas"})],
            "tool_use",
        ),
        *[
            _Stream([], "end_turn", raise_on_enter=OverloadedError("overloaded"))
            for _ in range(failures)
        ],
        _Stream([_text("Proyecto creado.")], "end_turn"),
    ]


@pytest.mark.django_db
def test_work_done_before_an_upstream_error_is_kept(user_a, make_profile):
    """Cuando el error persiste más allá de los reintentos."""
    make_profile(user_a, plan="studio")
    client = _Client(_overloaded_script(failures=3))
    frames = _frames(_run(user_a, client, {"content": "crea Finanzas"}))

    assert Project.objects.filter(user_id=user_a, name="Finanzas").exists()
    conv = Conversation.objects.get(user_id=user_a)
    roles = list(
        Message.objects.filter(conversation=conv).order_by("created").values_list("role", flat=True)
    )
    # usuario → tool_use → tool_result: lo hecho queda en el hilo.
    assert roles == [MessageRole.USER, MessageRole.ASSISTANT, MessageRole.TOOL]
    assert next(p for k, p in frames if k == "done")["ok"] is False


@pytest.mark.django_db
def test_a_transient_upstream_error_is_retried(user_a, make_profile):
    make_profile(user_a, plan="studio")
    client = _Client(_overloaded_script())
    frames = _frames(_run(user_a, client, {"content": "crea Finanzas"}))
    assert next(p for k, p in frames if k == "done")["ok"] is True
    assert Project.objects.filter(user_id=user_a, name="Finanzas").count() == 1


class _StreamThatDiesAfterText(_Stream):
    def __iter__(self):
        yield from super().__iter__()
        raise OverloadedError("overloaded")


@pytest.mark.django_db
def test_an_error_after_streaming_text_is_not_retried(user_a, make_profile):
    """Reintentar reescribiría la prosa que el usuario ya vio."""
    make_profile(user_a, plan="studio")
    client = _Client([_StreamThatDiesAfterText([_text("Te cuento:")], "end_turn")])
    frames = _frames(_run(user_a, client, {"content": "hola"}))
    assert len(client.calls) == 1
    assert next(p for k, p in frames if k == "done")["ok"] is False


# --------------------------------------------------------------------------
# E. Reintentar después de un corte duplica el trabajo
# --------------------------------------------------------------------------


@pytest.mark.django_db
def test_after_a_cut_the_next_message_sees_what_already_ran(user_a, make_profile):
    """En prod (2026-09-11) cada "?" / "continua" tras un corte creó OTRO
    proyecto con 8 tareas: el historial no tenía nada del turno muerto.
    Con la persistencia incremental, el siguiente mensaje sí ve el
    tool_result del create — que es lo que evita el duplicado."""
    make_profile(user_a, plan="studio")
    conv = Conversation.objects.create(user_id=user_a, title="t")

    first = _Client(
        [
            _Stream([_tool("tu_1", "create_project", {"name": "Finanzas"})], "tool_use"),
            _Stream([_tool("tu_2", "list_projects")], "tool_use"),
        ]
    )
    with mock.patch.object(anthropic_client, "_build_anthropic_client", return_value=first):
        resp = _post(user_a, {"content": "crea Finanzas", "conversation_id": str(conv.id)})
        stream = iter(resp.streaming_content)
        for _ in range(4):  # meta, tool_use_start, tool_result, …
            next(stream, None)
        resp.close()  # el proxy corta

    second = _Client([_Stream([_text("Ya lo había creado.")], "end_turn")])
    _run(user_a, second, {"content": "?", "conversation_id": str(conv.id)})

    sent = json.dumps(second.calls[0]["messages"])
    assert "create_project" in sent and "Finanzas" in sent
    assert Project.objects.filter(user_id=user_a, name="Finanzas").count() == 1
    assert Task.objects.filter(user_id=user_a).count() == 0
