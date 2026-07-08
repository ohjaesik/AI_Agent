# app/monitoring/metrics.py

from __future__ import annotations

import json
import time
from collections import defaultdict
from threading import Lock
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class InMemoryMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self.request_count: dict[tuple[str, str, int], int] = defaultdict(int)
        self.request_latency_sum: dict[tuple[str, str, int], float] = defaultdict(float)
        self.request_latency_max: dict[tuple[str, str, int], float] = defaultdict(float)

    def observe(self, method: str, path: str, status_code: int, latency_seconds: float) -> None:
        key = (method, path, status_code)
        with self._lock:
            self.request_count[key] += 1
            self.request_latency_sum[key] += latency_seconds
            self.request_latency_max[key] = max(self.request_latency_max[key], latency_seconds)

    def render_prometheus(self) -> str:
        lines = [
            "# HELP ax_http_requests_total Total HTTP requests.",
            "# TYPE ax_http_requests_total counter",
        ]
        with self._lock:
            for (method, path, status), count in sorted(self.request_count.items()):
                labels = f'method="{method}",path="{path}",status="{status}"'
                lines.append(f"ax_http_requests_total{{{labels}}} {count}")

            lines.extend([
                "# HELP ax_http_request_latency_seconds_sum Total HTTP request latency seconds.",
                "# TYPE ax_http_request_latency_seconds_sum counter",
            ])
            for (method, path, status), value in sorted(self.request_latency_sum.items()):
                labels = f'method="{method}",path="{path}",status="{status}"'
                lines.append(f"ax_http_request_latency_seconds_sum{{{labels}}} {value:.6f}")

            lines.extend([
                "# HELP ax_http_request_latency_seconds_max Max HTTP request latency seconds.",
                "# TYPE ax_http_request_latency_seconds_max gauge",
            ])
            for (method, path, status), value in sorted(self.request_latency_max.items()):
                labels = f'method="{method}",path="{path}",status="{status}"'
                lines.append(f"ax_http_request_latency_seconds_max{{{labels}}} {value:.6f}")

        return "\n".join(lines) + "\n"


metrics = InMemoryMetrics()


def log_event(event: dict[str, Any]) -> None:
    print(json.dumps(event, ensure_ascii=False, default=str), flush=True)


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        start = time.perf_counter()
        status_code = 500
        try:
            response: Response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            latency = time.perf_counter() - start
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            metrics.observe(request.method, path, status_code, latency)
            log_event(
                {
                    "event": "http_request",
                    "method": request.method,
                    "path": path,
                    "status_code": status_code,
                    "latency_seconds": round(latency, 6),
                }
            )
