"""ASGI entrypoint for embedding or serving the MCP Streamable HTTP transport."""

from app.mcp.server import mcp

app = mcp.streamable_http_app()

