# app/ops/worker_probe.py

"""node worker 프로세스가 받을 수 있는 probe script.

격리 실행 모드에서 worker가 payload를 읽고 결과를 반환하는 최소 동작을 확인한다.
"""

from __future__ import annotations

import argparse
import json
import socket
from urllib.parse import urlparse

from sqlalchemy import text

from app.core.config import get_settings
from app.db.database import engine


def probe_database() -> dict[str, object]:
    """probe_database 함수. node worker 프로세스가 받을 수 있는 probe script. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"name": "database", "ok": True, "message": "connection ok"}
    except Exception as exc:
        return {"name": "database", "ok": False, "message": f"{type(exc).__name__}: {exc}"}


def probe_vllm() -> dict[str, object]:
    """probe_vllm 함수. node worker 프로세스가 받을 수 있는 probe script. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    settings = get_settings()
    parsed = urlparse(settings.vllm_base_url)
    if not parsed.hostname:
        return {"name": "vllm", "ok": False, "message": "VLLM_BASE_URL host is empty"}
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=3):
            return {"name": "vllm", "ok": True, "message": f"endpoint reachable: {parsed.hostname}:{port}"}
    except Exception as exc:
        return {"name": "vllm", "ok": False, "message": f"{type(exc).__name__}: {exc}"}


def run_probe(check_vllm: bool = True) -> dict[str, object]:
    """run_probe 함수. 외부 API, graph, worker, 평가 루틴 같은 실행 단위를 호출하고 결과를 반환한다."""
    checks = [probe_database()]
    if check_vllm:
        checks.append(probe_vllm())
    return {"ok": all(bool(item["ok"]) for item in checks), "checks": checks}


def parse_args() -> argparse.Namespace:
    """CLI 실행 인자를 정의하고 argparse Namespace로 변환한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-vllm", action="store_true")
    return parser.parse_args()


def main() -> None:
    """해당 모듈을 script로 실행했을 때 호출되는 진입점이다."""
    args = parse_args()
    print(json.dumps(run_probe(check_vllm=not args.skip_vllm), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
