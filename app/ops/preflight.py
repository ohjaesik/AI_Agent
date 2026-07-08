# app/ops/preflight.py

from __future__ import annotations

import argparse
import json
import socket
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text

from app.agents.sandbox import assert_sandbox_available
from app.core.config import get_settings
from app.db.database import engine


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    message: str
    required: bool = True


def ok(name: str, message: str, required: bool = True) -> CheckResult:
    return CheckResult(name=name, status="ok", message=message, required=required)


def warn(name: str, message: str, required: bool = False) -> CheckResult:
    return CheckResult(name=name, status="warn", message=message, required=required)


def fail(name: str, message: str, required: bool = True) -> CheckResult:
    return CheckResult(name=name, status="fail", message=message, required=required)


def check_env() -> list[CheckResult]:
    settings = get_settings()
    results = []
    results.append(ok("DATABASE_URL", "configured") if settings.database_url else fail("DATABASE_URL", "missing"))
    results.append(ok("OPENAI_API_KEY", "configured") if settings.openai_api_key else fail("OPENAI_API_KEY", "missing"))

    if settings.app_env.lower() in {"production", "prod"}:
        if not settings.app_api_key:
            results.append(fail("APP_API_KEY", "required in production"))
        else:
            results.append(ok("APP_API_KEY", "configured"))
        if not settings.app_jwt_secret or len(settings.app_jwt_secret) < 32:
            results.append(fail("APP_JWT_SECRET", "32+ characters required in production"))
        else:
            results.append(ok("APP_JWT_SECRET", "configured"))
    else:
        results.append(warn("APP_ENV", f"running in {settings.app_env}; production checks are relaxed"))

    if settings.storage_backend.lower() in {"s3", "minio"}:
        missing = [name for name, value in {
            "S3_BUCKET": settings.s3_bucket,
            "S3_ACCESS_KEY_ID": settings.s3_access_key_id,
            "S3_SECRET_ACCESS_KEY": settings.s3_secret_access_key,
        }.items() if not value]
        if missing:
            results.append(fail("S3_STORAGE", f"missing: {', '.join(missing)}"))
        else:
            results.append(ok("S3_STORAGE", "configured"))
    else:
        Path(settings.local_storage_dir).mkdir(parents=True, exist_ok=True)
        results.append(ok("LOCAL_STORAGE_DIR", f"ready: {settings.local_storage_dir}"))

    return results


def check_database() -> CheckResult:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return ok("database", "connection ok")
    except Exception as exc:
        return fail("database", f"connection failed: {type(exc).__name__}: {exc}")


def check_vllm_endpoint() -> CheckResult:
    settings = get_settings()
    parsed = urlparse(settings.vllm_base_url)
    if not parsed.hostname:
        return warn("vLLM", "VLLM_BASE_URL host is empty")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=2):
            return ok("vLLM", f"endpoint reachable: {parsed.hostname}:{port}", required=False)
    except Exception as exc:
        return warn("vLLM", f"endpoint not reachable; LLM fallback will be used ({type(exc).__name__})")


def check_sandbox() -> CheckResult:
    try:
        assert_sandbox_available()
        return ok("agent_sandbox", "configured")
    except Exception as exc:
        return fail("agent_sandbox", f"sandbox unavailable: {type(exc).__name__}: {exc}")


def run_preflight(include_optional: bool = True) -> dict[str, object]:
    checks = []
    checks.extend(check_env())
    checks.append(check_database())
    checks.append(check_sandbox())
    if include_optional:
        checks.append(check_vllm_endpoint())

    failed_required = [item for item in checks if item.status == "fail" and item.required]
    warnings = [item for item in checks if item.status == "warn"]
    return {
        "ok": not failed_required,
        "failed_required_count": len(failed_required),
        "warning_count": len(warnings),
        "checks": [asdict(item) for item in checks],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="exit non-zero when required checks fail")
    parser.add_argument("--skip-optional", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_preflight(include_optional=not args.skip_optional)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in result["checks"]:
            print(f"[{item['status']}] {item['name']}: {item['message']}")
        print(f"preflight_ok={result['ok']}")

    if args.strict and not result["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
