# app/evaluation/llm_quality_eval.py

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_CASE_PATH = Path("tests/data/llm_quality_cases.jsonl")
VALID_TARGETS = {"company_process_discovery", "llm_critic", "report_writer"}
VALID_CRITIC_VERDICTS = {"pass", "needs_review", "insufficient_evidence", "reject"}
SCORE_KEYS = [
    "expected_effect",
    "repeatability",
    "document_dependency",
    "decision_complexity",
    "data_accessibility",
    "tech_feasibility",
    "user_acceptance",
    "risk_score",
    "implementation_cost_score",
]
REQUIRED_PROCESS_FIELDS = [
    "department",
    "name",
    "target_user",
    "problem",
    "current_workflow",
    "candidate_agent_name",
]


def safe_div(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def extract_payload(case: dict[str, Any]) -> tuple[dict[str, Any], bool, str | None]:
    if isinstance(case.get("payload"), dict):
        return case["payload"], True, None

    raw_text = case.get("raw_text")
    if not isinstance(raw_text, str):
        return {}, False, "case must include payload or raw_text"

    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```").strip()
        cleaned = cleaned.removesuffix("```").strip()

    try:
        return json.loads(cleaned), True, None
    except json.JSONDecodeError as exc:
        return {}, False, f"JSONDecodeError: {exc}"


def is_fallback_payload(target: str, payload: dict[str, Any]) -> bool:
    if target == "company_process_discovery":
        processes = payload.get("processes", [])
        return any(str(item.get("discovery_mode")) == "template_fallback" for item in processes if isinstance(item, dict))
    if target == "llm_critic":
        return str(payload.get("critic_mode")) == "deterministic_fallback"
    if target == "report_writer":
        generation = payload.get("generation") or {}
        return str(generation.get("mode")) == "deterministic_fallback"
    return False


def process_has_required_fields(process: dict[str, Any]) -> bool:
    return all(str(process.get(field) or "").strip() for field in REQUIRED_PROCESS_FIELDS)


def scores_are_in_range(process: dict[str, Any]) -> bool:
    for key in SCORE_KEYS:
        if key not in process:
            continue
        try:
            value = int(process[key])
        except (TypeError, ValueError):
            return False
        if value < 1 or value > 5:
            return False
    return True


def evidence_labels_are_allowed(process: dict[str, Any], allowed_labels: set[str]) -> bool:
    labels = process.get("evidence_labels", [])
    if not isinstance(labels, list) or not labels:
        return False
    return all(str(label) in allowed_labels for label in labels)


def evaluate_company_process_discovery_case(case: dict[str, Any], payload: dict[str, Any], json_ok: bool, parse_error: str | None) -> dict[str, Any]:
    allowed_labels = {str(label) for label in case.get("allowed_labels", [])}
    processes = payload.get("processes", []) if json_ok else []
    process_count = len(processes) if isinstance(processes, list) else 0
    expected_min = int(case.get("expected_min_processes", 5))
    expected_max = int(case.get("expected_max_processes", 8))

    valid_processes = [item for item in processes if isinstance(item, dict)] if isinstance(processes, list) else []
    required_field_pass = all(process_has_required_fields(item) for item in valid_processes) and bool(valid_processes)
    score_range_pass = all(scores_are_in_range(item) for item in valid_processes) and bool(valid_processes)
    evidence_label_pass = bool(allowed_labels) and all(evidence_labels_are_allowed(item, allowed_labels) for item in valid_processes)
    candidate_count_pass = expected_min <= process_count <= expected_max

    checks = {
        "json_parse_success": json_ok,
        "schema_valid": isinstance(processes, list) and required_field_pass,
        "candidate_count_in_range": candidate_count_pass,
        "evidence_label_valid": evidence_label_pass,
        "score_range_valid": score_range_pass,
        "fallback_used": is_fallback_payload("company_process_discovery", payload),
    }
    checks["passed"] = all(
        bool(checks[key])
        for key in [
            "json_parse_success",
            "schema_valid",
            "candidate_count_in_range",
            "evidence_label_valid",
            "score_range_valid",
        ]
    )

    return {
        "case_id": case.get("case_id"),
        "target": "company_process_discovery",
        "passed": checks["passed"],
        "json_parse_success": json_ok,
        "schema_valid": checks["schema_valid"],
        "fallback_used": checks["fallback_used"],
        "primary_score": safe_div(
            sum(
                1
                for key in [
                    "schema_valid",
                    "candidate_count_in_range",
                    "evidence_label_valid",
                    "score_range_valid",
                ]
                if checks[key]
            ),
            4,
        ),
        "checks": checks,
        "details": {
            "process_count": process_count,
            "expected_min_processes": expected_min,
            "expected_max_processes": expected_max,
            "parse_error": parse_error,
        },
    }


def evaluate_llm_critic_case(case: dict[str, Any], payload: dict[str, Any], json_ok: bool, parse_error: str | None) -> dict[str, Any]:
    verdict = str(payload.get("critic_verdict") or "").strip()
    expected_verdict = case.get("expected_verdict")
    expected_not_pass = bool(case.get("expected_not_pass", False))

    try:
        adjustment = float(payload.get("critic_confidence_adjustment", 0.0))
        adjustment_valid = -0.30 <= adjustment <= 0.10
    except (TypeError, ValueError):
        adjustment_valid = False

    verdict_valid = verdict in VALID_CRITIC_VERDICTS
    verdict_matches_expected = expected_verdict is None or verdict == str(expected_verdict)
    unsafe_pass = expected_not_pass and verdict == "pass"
    list_fields_valid = isinstance(payload.get("missing_evidence", []), list) and isinstance(payload.get("review_questions", []), list)
    reason_present = bool(str(payload.get("critic_reason") or "").strip())

    checks = {
        "json_parse_success": json_ok,
        "schema_valid": verdict_valid and adjustment_valid and list_fields_valid and reason_present,
        "verdict_valid": verdict_valid,
        "verdict_matches_expected": verdict_matches_expected,
        "unsafe_pass": unsafe_pass,
        "fallback_used": is_fallback_payload("llm_critic", payload),
    }
    checks["passed"] = json_ok and checks["schema_valid"] and verdict_matches_expected and not unsafe_pass

    return {
        "case_id": case.get("case_id"),
        "target": "llm_critic",
        "passed": checks["passed"],
        "json_parse_success": json_ok,
        "schema_valid": checks["schema_valid"],
        "fallback_used": checks["fallback_used"],
        "primary_score": safe_div(
            sum(1 for key in ["schema_valid", "verdict_valid", "verdict_matches_expected"] if checks[key]),
            3,
        ),
        "checks": checks,
        "details": {
            "critic_verdict": verdict,
            "expected_verdict": expected_verdict,
            "parse_error": parse_error,
        },
    }


def count_report_paragraphs(report_data: dict[str, Any]) -> int:
    count = 0
    for section in report_data.get("sections", []):
        for block in section.get("blocks", []):
            if block.get("type") == "paragraph":
                count += 1
    return count


def evaluate_report_writer_case(case: dict[str, Any], payload: dict[str, Any], json_ok: bool, parse_error: str | None) -> dict[str, Any]:
    validation = {"valid": False, "invalid_labels": ["not_evaluated"]}
    citation_validation_pass = False
    if json_ok:
        try:
            from app.tools.citation_validator import validate_report_citations

            validation = validate_report_citations(
                report_data=payload,
                evidence_items=case.get("evidence_items", []),
            )
            citation_validation_pass = bool(validation.get("valid"))
        except Exception as exc:  # pragma: no cover - defensive path for standalone CLI usage
            validation = {"valid": False, "error": f"{type(exc).__name__}: {exc}"}

    paragraph_count = count_report_paragraphs(payload) if json_ok else 0
    expected_min = int(case.get("expected_min_paragraphs", 1))
    paragraph_count_pass = paragraph_count >= expected_min
    sections_valid = isinstance(payload.get("sections", []), list) and bool(payload.get("sections", []))

    checks = {
        "json_parse_success": json_ok,
        "schema_valid": sections_valid and paragraph_count_pass,
        "citation_validation_pass": citation_validation_pass,
        "paragraph_count_pass": paragraph_count_pass,
        "fallback_used": is_fallback_payload("report_writer", payload),
    }
    checks["passed"] = json_ok and checks["schema_valid"] and citation_validation_pass

    return {
        "case_id": case.get("case_id"),
        "target": "report_writer",
        "passed": checks["passed"],
        "json_parse_success": json_ok,
        "schema_valid": checks["schema_valid"],
        "fallback_used": checks["fallback_used"],
        "primary_score": safe_div(
            sum(1 for key in ["schema_valid", "citation_validation_pass", "paragraph_count_pass"] if checks[key]),
            3,
        ),
        "checks": checks,
        "details": {
            "paragraph_count": paragraph_count,
            "expected_min_paragraphs": expected_min,
            "citation_validation": validation,
            "parse_error": parse_error,
        },
    }


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    target = str(case.get("target") or "")
    payload, json_ok, parse_error = extract_payload(case)

    if target == "company_process_discovery":
        return evaluate_company_process_discovery_case(case, payload, json_ok, parse_error)
    if target == "llm_critic":
        return evaluate_llm_critic_case(case, payload, json_ok, parse_error)
    if target == "report_writer":
        return evaluate_report_writer_case(case, payload, json_ok, parse_error)

    return {
        "case_id": case.get("case_id"),
        "target": target or "unknown",
        "passed": False,
        "json_parse_success": json_ok,
        "schema_valid": False,
        "fallback_used": False,
        "primary_score": 0.0,
        "checks": {"passed": False, "unsupported_target": True},
        "details": {"error": f"Unsupported target: {target}"},
    }


def summarize_results(results: list[dict[str, Any]], case_source: str | None = None) -> dict[str, Any]:
    total = len(results)
    target_summaries: dict[str, dict[str, Any]] = {}

    for target in sorted({str(result.get("target")) for result in results}):
        group = [result for result in results if result.get("target") == target]
        target_summaries[target] = {
            "total_cases": len(group),
            "pass_rate": safe_div(sum(1 for item in group if item.get("passed")), len(group)),
            "json_parse_success_rate": safe_div(sum(1 for item in group if item.get("json_parse_success")), len(group)),
            "schema_valid_rate": safe_div(sum(1 for item in group if item.get("schema_valid")), len(group)),
            "fallback_free_rate": safe_div(sum(1 for item in group if not item.get("fallback_used")), len(group)),
            "average_primary_score": safe_div(sum(float(item.get("primary_score") or 0.0) for item in group), len(group)),
        }

    return {
        "case_source": case_source,
        "total_cases": total,
        "pass_rate": safe_div(sum(1 for item in results if item.get("passed")), total),
        "json_parse_success_rate": safe_div(sum(1 for item in results if item.get("json_parse_success")), total),
        "schema_valid_rate": safe_div(sum(1 for item in results if item.get("schema_valid")), total),
        "fallback_free_rate": safe_div(sum(1 for item in results if not item.get("fallback_used")), total),
        "average_primary_score": safe_div(sum(float(item.get("primary_score") or 0.0) for item in results), total),
        "target_summaries": target_summaries,
        "failed_cases": [item for item in results if not item.get("passed")],
        "results": results,
    }


def evaluate_cases(cases: list[dict[str, Any]], case_source: str | None = None) -> dict[str, Any]:
    return summarize_results([evaluate_case(case) for case in cases], case_source=case_source)


def quality_gate(
    metrics: dict[str, Any],
    min_pass_rate: float,
    min_json_parse_success_rate: float,
    min_schema_valid_rate: float,
    min_fallback_free_rate: float,
) -> dict[str, Any]:
    checks = {
        "pass_rate": float(metrics.get("pass_rate", 0.0)) >= min_pass_rate,
        "json_parse_success_rate": float(metrics.get("json_parse_success_rate", 0.0)) >= min_json_parse_success_rate,
        "schema_valid_rate": float(metrics.get("schema_valid_rate", 0.0)) >= min_schema_valid_rate,
        "fallback_free_rate": float(metrics.get("fallback_free_rate", 0.0)) >= min_fallback_free_rate,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "min_pass_rate": min_pass_rate,
        "min_json_parse_success_rate": min_json_parse_success_rate,
        "min_schema_valid_rate": min_schema_valid_rate,
        "min_fallback_free_rate": min_fallback_free_rate,
    }


def save_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case_id",
        "target",
        "passed",
        "json_parse_success",
        "schema_valid",
        "fallback_used",
        "primary_score",
    ]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def format_bool(value: bool) -> str:
    return "PASS" if value else "FAIL"


def save_markdown(path: str | Path, metrics: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    gate = metrics.get("quality_gate", {})
    lines = [
        "# LLM Quality Evaluation Report",
        "",
        "## Summary",
        "",
        f"- case_source: {metrics.get('case_source')}",
        f"- total_cases: {metrics.get('total_cases')}",
        f"- quality_gate_passed: {gate.get('passed')}",
        f"- pass_rate: {metrics.get('pass_rate')}",
        f"- json_parse_success_rate: {metrics.get('json_parse_success_rate')}",
        f"- schema_valid_rate: {metrics.get('schema_valid_rate')}",
        f"- fallback_free_rate: {metrics.get('fallback_free_rate')}",
        f"- average_primary_score: {metrics.get('average_primary_score')}",
        f"- failed_case_count: {len(metrics.get('failed_cases', []))}",
        "",
        "## Quality Gate",
        "",
        "| Check | Result |",
        "|---|---:|",
    ]
    for check, passed in (gate.get("checks") or {}).items():
        lines.append(f"| {check} | {format_bool(bool(passed))} |")

    lines.extend([
        "",
        "## Target Summary",
        "",
        "| Target | Cases | Pass Rate | JSON Parse | Schema Valid | Fallback Free | Avg Score |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for target, summary in (metrics.get("target_summaries") or {}).items():
        lines.append(
            f"| {target} | {summary.get('total_cases')} | {summary.get('pass_rate')} | "
            f"{summary.get('json_parse_success_rate')} | {summary.get('schema_valid_rate')} | "
            f"{summary.get('fallback_free_rate')} | {summary.get('average_primary_score')} |"
        )

    lines.extend(["", "## Failed Cases", ""])
    if metrics.get("failed_cases"):
        lines.extend(["| Case ID | Target | Primary Score |", "|---|---|---:|"])
        for item in metrics["failed_cases"]:
            lines.append(f"| {item.get('case_id')} | {item.get('target')} | {item.get('primary_score')} |")
    else:
        lines.append("No failed cases.")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-path", type=str, default=str(DEFAULT_CASE_PATH))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--csv", type=str, default=None)
    parser.add_argument("--markdown", type=str, default=None)
    parser.add_argument("--min-pass-rate", type=float, default=0.90)
    parser.add_argument("--min-json-parse-success-rate", type=float, default=0.95)
    parser.add_argument("--min-schema-valid-rate", type=float, default=0.90)
    parser.add_argument("--min-fallback-free-rate", type=float, default=0.70)
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = load_jsonl(args.case_path)
    metrics = evaluate_cases(cases, case_source=args.case_path)
    metrics["quality_gate"] = quality_gate(
        metrics,
        min_pass_rate=args.min_pass_rate,
        min_json_parse_success_rate=args.min_json_parse_success_rate,
        min_schema_valid_rate=args.min_schema_valid_rate,
        min_fallback_free_rate=args.min_fallback_free_rate,
    )
    if args.csv:
        save_csv(args.csv, metrics["results"])
    if args.markdown:
        save_markdown(args.markdown, metrics)
    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print(f"total_cases={metrics['total_cases']}")
        print(f"pass_rate={metrics['pass_rate']}")
        print(f"json_parse_success_rate={metrics['json_parse_success_rate']}")
        print(f"schema_valid_rate={metrics['schema_valid_rate']}")
        print(f"fallback_free_rate={metrics['fallback_free_rate']}")
        print(f"quality_gate_passed={metrics['quality_gate']['passed']}")
    if args.strict and not metrics["quality_gate"]["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
