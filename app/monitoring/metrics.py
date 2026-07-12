# app/monitoring/metrics.py

"""FastAPI 요청/latency Prometheus metric을 수집한다.

API middleware가 요청 수, 상태 코드, 처리 시간을 기록하고 /metrics endpoint에서 노출한다.
"""

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
    """프로세스 메모리에 HTTP/Agent 실행 횟수와 latency 집계를 보관하는 metric store다."""
    def __init__(self) -> None:
        self._lock = Lock()
        self.request_count: dict[tuple[str, str, int], int] = defaultdict(int)
        self.request_latency_sum: dict[tuple[str, str, int], float] = defaultdict(float)
        self.request_latency_max: dict[tuple[str, str, int], float] = defaultdict(float)
        self.agent_node_count: dict[tuple[str, str, str], int] = defaultdict(int)
        self.agent_node_latency_sum: dict[tuple[str, str, str], float] = defaultdict(float)
        self.agent_node_latency_max: dict[tuple[str, str, str], float] = defaultdict(float)

    def observe(self, method: str, path: str, status_code: int, latency_seconds: float) -> None:
        """HTTP 요청 1건의 count, latency sum, max latency를 누적한다."""
        key = (method, path, status_code)
        with self._lock:
            self.request_count[key] += 1
            self.request_latency_sum[key] += latency_seconds
            self.request_latency_max[key] = max(self.request_latency_max[key], latency_seconds)

    def observe_agent_node(self, node_name: str, mode: str, status: str, latency_seconds: float) -> None:
        """LangGraph node 실행 1건의 mode/status별 count와 latency를 누적한다."""
        key = (node_name, mode, status)
        with self._lock:
            self.agent_node_count[key] += 1
            self.agent_node_latency_sum[key] += latency_seconds
            self.agent_node_latency_max[key] = max(self.agent_node_latency_max[key], latency_seconds)

    def render_prometheus(self) -> str:
        """현재 누적 metric을 Prometheus text exposition format으로 렌더링한다."""
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

            lines.extend([
                "# HELP ax_agent_node_runs_total Total LangGraph agent node runs.",
                "# TYPE ax_agent_node_runs_total counter",
            ])
            for (node_name, mode, status), count in sorted(self.agent_node_count.items()):
                labels = f'node="{node_name}",mode="{mode}",status="{status}"'
                lines.append(f"ax_agent_node_runs_total{{{labels}}} {count}")

            lines.extend([
                "# HELP ax_agent_node_latency_seconds_sum Total LangGraph agent node latency seconds.",
                "# TYPE ax_agent_node_latency_seconds_sum counter",
            ])
            for (node_name, mode, status), value in sorted(self.agent_node_latency_sum.items()):
                labels = f'node="{node_name}",mode="{mode}",status="{status}"'
                lines.append(f"ax_agent_node_latency_seconds_sum{{{labels}}} {value:.6f}")

            lines.extend([
                "# HELP ax_agent_node_latency_seconds_max Max LangGraph agent node latency seconds.",
                "# TYPE ax_agent_node_latency_seconds_max gauge",
            ])
            for (node_name, mode, status), value in sorted(self.agent_node_latency_max.items()):
                labels = f'node="{node_name}",mode="{mode}",status="{status}"'
                lines.append(f"ax_agent_node_latency_seconds_max{{{labels}}} {value:.6f}")

        return "\n".join(lines) + "\n"


metrics = InMemoryMetrics()


def log_event(event: dict[str, Any]) -> None:
    """운영 로그 수집기가 읽기 쉽도록 event dict를 한 줄 JSON으로 출력한다."""
    print(json.dumps(event, ensure_ascii=False, default=str), flush=True)


def record_agent_node(node_name: str, mode: str, status: str, latency_seconds: float) -> None:
    """node worker 실행 결과를 metric store와 JSON log 양쪽에 기록한다."""
    metrics.observe_agent_node(node_name=node_name, mode=mode, status=status, latency_seconds=latency_seconds)
    log_event(
        {
            "event": "agent_node_run",
            "node": node_name,
            "mode": mode,
            "status": status,
            "latency_seconds": round(latency_seconds, 6),
        }
    )


class RequestMetricsMiddleware(BaseHTTPMiddleware):
    """FastAPI 요청을 감싸 latency와 status code metric을 자동 기록하는 middleware다."""
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        """요청 처리 전후 시간을 측정하고 route pattern 기준으로 metric label을 기록한다."""
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
