# app/company_bootstrap/state.py

from __future__ import annotations

import json
from typing import Annotated, Any, TypedDict


def merge_unique_dicts(left: list[dict[str, Any]] | None, right: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in (left or []) + (right or []):
        try:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            key = str(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)

    return result


def merge_unique_strings(left: list[str] | None, right: list[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    for item in (left or []) + (right or []):
        if item in seen:
            continue
        seen.add(item)
        result.append(item)

    return result


class BootstrapState(TypedDict, total=False):
    # Inputs
    company_name: str
    official_urls: list[str]
    dart_api_key: str | None
    corp_code: str | None
    stock_code: str | None
    create_project: bool
    index: bool
    reset_company_chunks: bool

    # Company Profile Agent outputs
    dart_company: Any
    company_id: int
    resolved_company_name: str
    company_profile: dict[str, Any]

    # Source Ingestion Agent outputs
    official_docs: list[Any]
    combined_text: str
    official_sources: list[dict[str, Any]]
    document_ids: list[int]
    chunk_count: int
    source_count: int

    # Process Discovery Agent outputs
    process_specs: list[dict[str, Any]]
    process_ids: list[int]
    project_id: int | None
    discovery_mode: str | None

    # Runtime contracts
    agent_contracts: Annotated[list[dict[str, Any]], merge_unique_dicts]
    agent_tool_calls: Annotated[list[dict[str, Any]], merge_unique_dicts]
    agent_decisions: Annotated[list[dict[str, Any]], merge_unique_dicts]

    # Result
    result: dict[str, Any]

    # Logs
    warnings: Annotated[list[str], merge_unique_strings]
    audit_logs: Annotated[list[dict[str, Any]], merge_unique_dicts]
    errors: Annotated[list[str], merge_unique_strings]
