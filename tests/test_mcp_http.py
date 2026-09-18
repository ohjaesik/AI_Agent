import asyncio
from types import SimpleNamespace

from app.mcp.http import MCPRequestGuardMiddleware


def test_mcp_guard_rejects_oversized_request():
    middleware = MCPRequestGuardMiddleware(lambda request: None)
    middleware.max_bytes = 10
    request = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"content-length": "11"},
    )
    response = asyncio.run(middleware.dispatch(request, lambda _: None))
    assert response.status_code == 413


def test_mcp_guard_rejects_invalid_content_length():
    middleware = MCPRequestGuardMiddleware(lambda request: None)
    request = SimpleNamespace(
        client=SimpleNamespace(host="127.0.0.1"),
        headers={"content-length": "not-a-number"},
    )
    response = asyncio.run(middleware.dispatch(request, lambda _: None))
    assert response.status_code == 400
