# app/tools/report_data_builder.py

from __future__ import annotations

from typing import Any

from app.chains.report_writer import generate_report_data_with_llm


def build_report_data(state: dict[str, Any]) -> dict[str, Any]:
    """
    Public report builder entrypoint used by graph nodes.

    Flow:
    1. Try vLLM/Gemma Report Writer Agent.
    2. If vLLM is unavailable, JSON parsing fails, or citation validation fails,
       the chain returns the deterministic fallback report.
    """
    return generate_report_data_with_llm(state)
