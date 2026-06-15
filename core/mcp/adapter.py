"""Translate Continuity tools (`core.assistant.tools`) into MCP tool defs.

The registry already carries everything an MCP `tools/list` entry needs
(name, description, JSON schema). This adds MCP `annotations` derived from
the `mutates` flag so Claude can apply the right human-in-the-loop UX:

- read-only tools  → ``readOnlyHint: true``
- ``delete_*``     → ``destructiveHint: true`` (Claude confirms before running)
"""

from __future__ import annotations

from core.assistant.tools import Tool


def tool_to_mcp(tool: Tool) -> dict:
    annotations: dict = {
        "title": tool.name,
        "readOnlyHint": not tool.mutates,
    }
    if tool.mutates:
        # Deletions are irreversible → flag destructive so the client confirms.
        annotations["destructiveHint"] = tool.name.startswith("delete_")
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": tool.input_schema,
        "annotations": annotations,
    }
