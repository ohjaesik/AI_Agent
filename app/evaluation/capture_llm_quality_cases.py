# app/evaluation/capture_llm_quality_cases.py

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT_PATH = Path("outputs/llm_quality_cases_real.jsonl")


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def dump_jsonl(path: str | Path, rows: list[dict[str, Any]], append: bool = False) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, default=str, separators=(",", ":")) + "\n")


def collect_allowed_labels(state: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    for source in state.get("official_sources", []) or []:
        label = source.get("label") if isinstance(source, dict) else None
        if label and str(label) not in labels:
            labels.append(str(label))
    for item in state.get("evidence_items", []) or []:
        label = item.get("citation_label") if isinstance(item, dict) else None
        if label and str(label) not in labels:
            labels.append(str(label))
    return labels


def build_discovery_case(state: dict[str, Any], case_prefix: str, expected_min_processes: int, expected_max_processes: int) -> dict[str, Any] | None:
    process_specs = state.get("process_specs")
    if not isinstance(process_specs, list) or not process_specs:
        return None

    allowed_labels = collect_allowed_labels(state)
    for process in process_specs:
        if not isinstance(process, dict):
            continue
        for label in process.get("evidence_labels", []) or []:
            if label and str(label) not in allowed_labels:
                allowed_labels.append(str(label))

    return {
        "case_id": f"{case_prefix}_company_process_discovery",
        "target": "company_process_discovery",
        "allowed_labels": allowed_labels,
        "expected_min_processes": expected_min_processes,
        "expected_max_processes": expected_max_processes,
        "payload": {
            "processes": process_specs,
            "warnings": state.get("warnings", []),
        },
    }


def evaluation_by_process_id(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in (state.get("agent_evaluation") or {}).get("items", []) or []:
        if isinstance(item, dict) and item.get("process_id") is not None:
            result[str(item.get("process_id"))] = item
    return result


def infer_expected_not_pass(candidate: dict[str, Any], evaluation: dict[str, Any]) -> bool:
    compliance = candidate.get("compliance") or {}
    if compliance.get("blocked"):
        return True
    return bool(
        evaluation.get("requires_additional_evidence")
        or evaluation.get("requires_human_review")
        or evaluation.get("issues")
    )


def build_critic_cases(state: dict[str, Any], case_prefix: str, freeze_current_verdict: bool = False) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    evaluations = evaluation_by_process_id(state)

    for index, candidate in enumerate((state.get("priority_ranking") or {}).get("items", []) or [], start=1):
        if not isinstance(candidate, dict):
            continue
        process_id = str(candidate.get("process_id"))
        evaluation = candidate.get("agent_evaluation") or evaluations.get(process_id) or {}
        critic = evaluation.get("llm_critic") if isinstance(evaluation, dict) else None
        if not isinstance(critic, dict) or not critic:
            continue

        case: dict[str, Any] = {
            "case_id": f"{case_prefix}_llm_critic_{process_id or index}",
            "target": "llm_critic",
            "expected_not_pass": infer_expected_not_pass(candidate, evaluation),
            "payload": critic,
            "metadata": {
                "process_id": candidate.get("process_id"),
                "candidate_agent_name": candidate.get("candidate_agent_name"),
                "status": candidate.get("status"),
                "confidence_score": evaluation.get("confidence_score") if isinstance(evaluation, dict) else None,
            },
        }
        if freeze_current_verdict and critic.get("critic_verdict"):
            case["expected_verdict"] = critic.get("critic_verdict")
        cases.append(case)

    return cases


def build_report_case(state: dict[str, Any], case_prefix: str, expected_min_paragraphs: int) -> dict[str, Any] | None:
    report_data = state.get("report_data")
    if not isinstance(report_data, dict) or not report_data:
        return None

    return {
        "case_id": f"{case_prefix}_report_writer",
        "target": "report_writer",
        "expected_min_paragraphs": expected_min_paragraphs,
        "evidence_items": state.get("evidence_items", []),
        "payload": report_data,
    }


def build_cases_from_state(
    state: dict[str, Any],
    case_prefix: str,
    expected_min_processes: int = 3,
    expected_max_processes: int = 8,
    expected_min_paragraphs: int = 1,
    freeze_current_verdict: bool = False,
) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    discovery_case = build_discovery_case(
        state,
        case_prefix=case_prefix,
        expected_min_processes=expected_min_processes,
        expected_max_processes=expected_max_processes,
    )
    if discovery_case:
        cases.append(discovery_case)

    cases.extend(
        build_critic_cases(
            state,
            case_prefix=case_prefix,
            freeze_current_verdict=freeze_current_verdict,
        )
    )

    report_case = build_report_case(
        state,
        case_prefix=case_prefix,
        expected_min_paragraphs=expected_min_paragraphs,
    )
    if report_case:
        cases.append(report_case)

    return cases


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, help="workflow/bootstrap final state JSON file")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--case-prefix", default="real_run")
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--expected-min-processes", type=int, default=3)
    parser.add_argument("--expected-max-processes", type=int, default=8)
    parser.add_argument("--expected-min-paragraphs", type=int, default=1)
    parser.add_argument(
        "--freeze-current-verdict",
        action="store_true",
        help="store the current llm_critic verdict as expected_verdict for regression comparison",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state = load_json(args.state)
    cases = build_cases_from_state(
        state,
        case_prefix=args.case_prefix,
        expected_min_processes=args.expected_min_processes,
        expected_max_processes=args.expected_max_processes,
        expected_min_paragraphs=args.expected_min_paragraphs,
        freeze_current_verdict=args.freeze_current_verdict,
    )
    dump_jsonl(args.output, cases, append=args.append)
    print(f"wrote_cases={len(cases)}")
    print(f"output={args.output}")
    print("targets=" + ",".join(sorted({str(case.get('target')) for case in cases})))


if __name__ == "__main__":
    main()
