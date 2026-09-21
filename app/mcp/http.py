"""ASGI entrypoint for the MCP Streamable HTTP transport and request guard."""

import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

from app.core.config import get_settings
from app.monitoring.metrics import log_event, metrics
from app.mcp.server import mcp

app = mcp.streamable_http_app()


class MCPRequestGuardMiddleware(BaseHTTPMiddleware):
    """Apply origin, body-size, rate-limit, request-id, and audit protections."""

    def __init__(self, app):  # type: ignore[no-untyped-def]
        super().__init__(app)
        settings = get_settings()
        self.allowed_origins = {
            item.strip() for item in settings.mcp_allowed_origins.split(",") if item.strip()
        }
        self.limit = max(1, settings.mcp_rate_limit_per_minute)
        self.max_bytes = max(1024, settings.mcp_max_request_bytes)
        self.requests: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request, call_next):  # type: ignore[no-untyped-def]
        client = request.client.host if request.client else "unknown"
        origin = request.headers.get("origin")
        if self.allowed_origins and origin and origin not in self.allowed_origins:
            return PlainTextResponse("Origin is not allowed.", status_code=403)
        try:
            content_length = int(request.headers.get("content-length", "0") or 0)
        except ValueError:
            return PlainTextResponse("Invalid content length.", status_code=400)
        if content_length > self.max_bytes:
            return PlainTextResponse("Request body is too large.", status_code=413)

        now = time.monotonic()
        bucket = self.requests[client]
        while bucket and now - bucket[0] >= 60:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return PlainTextResponse("MCP rate limit exceeded.", status_code=429)
        bucket.append(now)
        if len(self.requests) > 10_000:
            self.requests = defaultdict(
                deque,
                {key: values for key, values in self.requests.items() if values and now - values[-1] < 60},
            )

        request_id = request.headers.get("x-request-id") or f"mcp-{time.time_ns()}"
        request.state.request_id = request_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        metrics.observe(request.method, request.url.path, response.status_code, time.perf_counter() - started)
        log_event({
            "event": "mcp_request",
            "request_id": request_id,
            "client": client,
            "path": request.url.path,
            "status": response.status_code,
        })
        return response


app.add_middleware(MCPRequestGuardMiddleware)
