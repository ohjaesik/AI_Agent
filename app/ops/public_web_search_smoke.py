# app/ops/public_web_search_smoke.py

"""public web search provider 설정을 확인하는 smoke test script.

Brave/SerpAPI key와 provider 응답 구조를 실제 replan 전에 점검한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from app.company_bootstrap.public_web_search import discover_public_web_sources
from app.core.config import get_settings


def validate_provider_config() -> list[str]:
    """validate_provider_config 함수. public web search provider 설정을 확인하는 smoke test script. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    settings = get_settings()
    errors: list[str] = []
    if not settings.external_web_discovery_enabled:
        errors.append("EXTERNAL_WEB_DISCOVERY_ENABLED must be true for public web search smoke test.")
    provider = settings.external_web_search_provider.lower()
    if provider == "brave" and not settings.brave_search_api_key:
        errors.append("BRAVE_SEARCH_API_KEY is required when EXTERNAL_WEB_SEARCH_PROVIDER=brave.")
    elif provider == "serpapi" and not settings.serpapi_api_key:
        errors.append("SERPAPI_API_KEY is required when EXTERNAL_WEB_SEARCH_PROVIDER=serpapi.")
    elif provider not in {"brave", "serpapi"}:
        errors.append(f"Unsupported EXTERNAL_WEB_SEARCH_PROVIDER: {provider}")
    return errors


def run_smoke(company_name: str, query_terms: list[str], max_results: int) -> dict[str, Any]:
    """run_smoke 함수. 외부 API, graph, worker, 평가 루틴 같은 실행 단위를 호출하고 결과를 반환한다."""
    config_errors = validate_provider_config()
    if config_errors:
        return {"ok": False, "stage": "config", "errors": config_errors, "result": None}

    result = discover_public_web_sources(
        company_name=company_name,
        query_terms=query_terms,
        existing_urls=set(),
        max_results=max_results,
    )
    warnings = result.get("warnings", []) or []
    results = result.get("results", []) or []
    ok = bool(result.get("enabled")) and len(results) > 0 and not any(str(item).startswith("Search failed") for item in warnings)
    return {
        "ok": ok,
        "stage": "search",
        "provider": result.get("provider"),
        "query": result.get("query"),
        "result_count": len(results),
        "warnings": warnings,
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    """CLI 실행 인자를 정의하고 argparse Namespace로 변환한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--company-name", default="Samsung Electronics")
    parser.add_argument("--query-term", action="append", default=[])
    parser.add_argument("--max-results", type=int, default=3)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> None:
    """해당 모듈을 script로 실행했을 때 호출되는 진입점이다."""
    args = parse_args()
    payload = run_smoke(
        company_name=args.company_name,
        query_terms=args.query_term,
        max_results=args.max_results,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if args.strict and not payload["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
