"""Minimal JSON-RPC 2.0 helpers for the MCP transport.

MCP messages are JSON-RPC 2.0. We only need the request/response shapes and
the standard error codes — no batching state, no streaming.
"""

from __future__ import annotations

from typing import Any

# Standard JSON-RPC 2.0 error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def success(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def error(req_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def is_notification(message: dict) -> bool:
    """A JSON-RPC message with no `id` is a notification — no reply expected."""
    return "id" not in message


def notification(method: str, params: Any = None) -> dict:
    """A server→client JSON-RPC notification (no `id`)."""
    msg: dict = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    return msg
