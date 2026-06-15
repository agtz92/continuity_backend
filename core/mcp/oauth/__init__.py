"""OAuth 2.1 authorization server for the MCP connector (Fase 1).

Public-client (PKCE) auth-code + refresh flow, with RFC 8414 / 9728 discovery
and RFC 7591 dynamic client registration. The actual user login is delegated to
the existing Supabase frontend (the consent page calls `approve` with a Supabase
Bearer). See docs/mcp-connector/PLAN.md §4.2.
"""
