"""MCP connector package.

The remote MCP connector that exposes Continuity's tools to Claude.ai /
Claude Desktop / Claude Code. See `docs/mcp-connector/PLAN.md`.

Today this package only contains the **policy layer** (`policy.py`) that
decides, per plan, what the connector exposes and dispatches — the actual
transport (`/mcp/` JSON-RPC view) and OAuth land in later phases.
"""
