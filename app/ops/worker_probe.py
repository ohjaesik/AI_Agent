# app/ops/worker_probe.py

from __future__ import annotations

import argparse
import json
import socket
from urllib.parse import urlparse

from sqlalchemy import text

from app.core.config import get_settings
from app.db.database import engine


def probe_database() -> dict[str, object]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"name": "database", "ok": True, "message": "connection ok"}
    except Exception as exc:
        return {"name": "database", "ok": False, "message": f"{type(exc).__name__}: {exc}"}


def probe_vllm() -> dict[str, object]:
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
    checks = [probe_database()]
    if check_vllm:
        checks.append(probe_vllm())
    return {"ok": all(bool(item["ok"]) for item in checks), "checks": checks}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-vllm", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    print(json.dumps(run_probe(check_vllm=not args.skip_vllm), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
