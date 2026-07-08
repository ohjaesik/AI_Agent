# app/evaluation/external_holdout_builder.py

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

SUPPORTED_DATASET_TYPES = {"online_retail", "bank_marketing", "credit_default", "process_mining"}
CSV_ENCODINGS = ("utf-8-sig", "utf-8", "cp949", "euc-kr", "latin-1")
REQUIRED_SCORE_KEYS = [
    "expected_effect",
    "repeatability",
    "document_dependency",
    "data_accessibility",
    "tech_feasibility",
    "risk_score",
]


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def normalize_value(value: Any) -> str:
    return str(value or "").replace("\ufeff", "").replace("\u00a0", " ").strip()


def read_text_with_fallback(path: str | Path) -> tuple[str, str]:
    input_path = Path(path)
    last_error: UnicodeDecodeError | None = None
    for encoding in CSV_ENCODINGS:
        try:
            return input_path.read_text(encoding=encoding), encoding
        except UnicodeDecodeError as error:
            last_error = error
    if last_error:
        raise last_error
    return input_path.read_text(encoding="utf-8"), "utf-8"


def read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    text, _ = read_text_with_fallback(path)
    reader = csv.DictReader(text.splitlines())
    rows: list[dict[str, str]] = []
    for row in reader:
        normalized = {normalize_key(key): normalize_value(value) for key, value in row.items() if key is not None}
        if any(normalized.values()):
            rows.append(normalized)
    return rows


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return default


def truthy(value: Any) -> bool:
    return normalize_value(value).lower() in {"1", "true", "yes", "y", "default", "failure"}


def first_value(row: dict[str, str], aliases: list[str]) -> str:
    for alias in aliases:
        key = normalize_key(alias)
        if row.get(key):
            return row[key]
    return ""


def score_rationale(*keys: str) -> dict[str, str]:
    selected = set(keys) | {"expected_effect", "repeatability"}
    return {key: "derived_from_external_dataset" for key in REQUIRED_SCORE_KEYS if key in selected}


def base_case(
    *,
    case_id: str,
    process_id: int,
    candidate_agent_name: str,
    expected_status: str,
    expected_requires_human_review: bool,
    evidence_labels: list[str],
    context_count: int,
    evidence_count: int,
    data_accessibility: int,
    risk_score: int,
    rationale: dict[str, str],
    final_score: float,
    saving_rate: float,
    compliance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "case_id": case_id,
        "process_id": process_id,
        "candidate_agent_name": candidate_agent_name,
        "initial_status": "recommended",
        "evidence_labels": evidence_labels,
        "context_count": context_count,
        "evidence_count": evidence_count,
        "data_accessibility": data_accessibility,
        "risk_score": risk_score,
        "score_rationale": rationale,
        "final_score": final_score,
        "saving_rate": saving_rate,
        "expected_status": expected_status,
        "expected_requires_human_review": expected_requires_human_review,
    }
    if compliance:
        payload["compliance"] = compliance
    return payload


def map_online_retail(row: dict[str, str], case_id: str, process_id: int) -> dict[str, Any]:
    description = first_value(row, ["Description", "description", "item_description"])
    quantity = parse_float(first_value(row, ["Quantity", "quantity"]), default=0.0)
    unit_price = parse_float(first_value(row, ["UnitPrice", "unit_price", "price"]), default=0.0)
    customer_id = first_value(row, ["CustomerID", "customer_id", "customer"])

    if not description or quantity == 0 or unit_price == 0:
        return base_case(
            case_id=case_id,
            process_id=process_id,
            candidate_agent_name="Retail Transaction Data Readiness Agent",
            expected_status="evidence_insufficient",
            expected_requires_human_review=True,
            evidence_labels=[],
            context_count=1 if description else 0,
            evidence_count=0,
            data_accessibility=2,
            risk_score=2,
            rationale=score_rationale("data_accessibility"),
            final_score=2.1,
            saving_rate=18.0,
        )

    if customer_id:
        return base_case(
            case_id=case_id,
            process_id=process_id,
            candidate_agent_name="Retail Customer Segmentation Agent",
            expected_status="human_review_required",
            expected_requires_human_review=True,
            evidence_labels=["[external-online-retail]"],
            context_count=2,
            evidence_count=1,
            data_accessibility=4,
            risk_score=3,
            rationale=score_rationale("document_dependency", "data_accessibility", "risk_score"),
            final_score=3.3,
            saving_rate=35.0,
            compliance={"process_id": process_id, "compliance_level": "sensitive_review", "human_review_required": True, "blocked": False},
        )

    return base_case(
        case_id=case_id,
        process_id=process_id,
        candidate_agent_name="Retail Inventory Reorder Agent",
        expected_status="recommended",
        expected_requires_human_review=False,
        evidence_labels=["[external-online-retail]", "[transaction-log]"],
        context_count=3,
        evidence_count=2,
        data_accessibility=4,
        risk_score=1,
        rationale=score_rationale("document_dependency", "data_accessibility", "tech_feasibility", "risk_score"),
        final_score=4.1,
        saving_rate=48.0,
    )


def map_bank_marketing(row: dict[str, str], case_id: str, process_id: int) -> dict[str, Any]:
    has_loan = normalize_value(first_value(row, ["loan", "housing", "default"])).lower() in {"yes", "true", "1"}
    campaign = parse_int(first_value(row, ["campaign", "previous"]), default=0)
    data_accessibility = 4 if row else 2
    risk_score = 4 if has_loan or campaign >= 3 else 3

    return base_case(
        case_id=case_id,
        process_id=process_id,
        candidate_agent_name="Bank Marketing Targeting Agent",
        expected_status="human_review_required",
        expected_requires_human_review=True,
        evidence_labels=["[external-bank-marketing]"],
        context_count=2,
        evidence_count=1,
        data_accessibility=data_accessibility,
        risk_score=risk_score,
        rationale=score_rationale("data_accessibility", "risk_score"),
        final_score=3.0,
        saving_rate=32.0,
        compliance={"process_id": process_id, "compliance_level": "enhanced_review", "human_review_required": True, "blocked": False},
    )


def map_credit_default(row: dict[str, str], case_id: str, process_id: int) -> dict[str, Any]:
    default_next_month = truthy(first_value(row, ["default_payment_next_month", "default", "y", "target"]))
    delinquency = max(
        parse_int(first_value(row, ["PAY_0", "pay_0", "pay_status", "delay"]), default=0),
        parse_int(first_value(row, ["PAY_2", "pay_2"]), default=0),
        parse_int(first_value(row, ["PAY_3", "pay_3"]), default=0),
    )
    limit_balance = parse_float(first_value(row, ["LIMIT_BAL", "limit_bal", "credit_limit"]), default=0.0)

    automated_final_decision = default_next_month and delinquency >= 2
    if automated_final_decision:
        return base_case(
            case_id=case_id,
            process_id=process_id,
            candidate_agent_name="Automated Credit Rejection Agent",
            expected_status="excluded",
            expected_requires_human_review=True,
            evidence_labels=["[external-credit-default]"],
            context_count=2,
            evidence_count=1,
            data_accessibility=4,
            risk_score=5,
            rationale=score_rationale("data_accessibility", "risk_score"),
            final_score=2.0,
            saving_rate=25.0,
            compliance={"process_id": process_id, "compliance_level": "blocked", "human_review_required": True, "blocked": True},
        )

    return base_case(
        case_id=case_id,
        process_id=process_id,
        candidate_agent_name="Credit Risk Triage Agent",
        expected_status="human_review_required",
        expected_requires_human_review=True,
        evidence_labels=["[external-credit-default]"],
        context_count=2 if limit_balance else 1,
        evidence_count=1,
        data_accessibility=4 if limit_balance else 3,
        risk_score=4,
        rationale=score_rationale("data_accessibility", "risk_score"),
        final_score=3.1,
        saving_rate=30.0,
        compliance={"process_id": process_id, "compliance_level": "enhanced_review", "human_review_required": True, "blocked": False},
    )


def map_process_mining(row: dict[str, str], case_id: str, process_id: int) -> dict[str, Any]:
    activity = first_value(row, ["activity", "concept_name", "event", "task"])
    timestamp = first_value(row, ["timestamp", "time_timestamp", "complete_timestamp", "date"])
    resource = first_value(row, ["resource", "org_resource", "user", "role"])
    text = " ".join([activity, resource]).lower()

    if not activity or not timestamp:
        return base_case(
            case_id=case_id,
            process_id=process_id,
            candidate_agent_name="Process Event Log Readiness Agent",
            expected_status="evidence_insufficient",
            expected_requires_human_review=True,
            evidence_labels=[] if not activity else ["[external-process-log]"],
            context_count=1 if activity else 0,
            evidence_count=0,
            data_accessibility=2,
            risk_score=2,
            rationale=score_rationale("data_accessibility"),
            final_score=2.2,
            saving_rate=20.0,
        )

    if any(keyword in text for keyword in ["hire", "recruit", "interview", "disciplinary", "termination", "performance", "payroll"]):
        return base_case(
            case_id=case_id,
            process_id=process_id,
            candidate_agent_name="Workforce Process Monitoring Agent",
            expected_status="human_review_required",
            expected_requires_human_review=True,
            evidence_labels=["[external-process-log]"],
            context_count=2,
            evidence_count=1,
            data_accessibility=4,
            risk_score=4,
            rationale=score_rationale("data_accessibility", "risk_score"),
            final_score=3.0,
            saving_rate=28.0,
            compliance={"process_id": process_id, "compliance_level": "enhanced_review", "human_review_required": True, "blocked": False},
        )

    return base_case(
        case_id=case_id,
        process_id=process_id,
        candidate_agent_name="Process Bottleneck Discovery Agent",
        expected_status="recommended",
        expected_requires_human_review=False,
        evidence_labels=["[external-process-log]", "[event-log]"],
        context_count=3,
        evidence_count=2,
        data_accessibility=4,
        risk_score=1,
        rationale=score_rationale("document_dependency", "data_accessibility", "tech_feasibility", "risk_score"),
        final_score=4.0,
        saving_rate=45.0,
    )


def map_row(dataset_type: str, row: dict[str, str], case_id: str, process_id: int) -> dict[str, Any]:
    if dataset_type == "online_retail":
        return map_online_retail(row, case_id, process_id)
    if dataset_type == "bank_marketing":
        return map_bank_marketing(row, case_id, process_id)
    if dataset_type == "credit_default":
        return map_credit_default(row, case_id, process_id)
    if dataset_type == "process_mining":
        return map_process_mining(row, case_id, process_id)
    raise ValueError(f"Unsupported dataset_type: {dataset_type}")


def build_external_holdout_cases(
    dataset_type: str,
    input_path: str | Path,
    case_id_prefix: str,
    process_id_start: int = 10_000,
    max_cases: int | None = None,
) -> list[dict[str, Any]]:
    if dataset_type not in SUPPORTED_DATASET_TYPES:
        raise ValueError(f"dataset_type must be one of {sorted(SUPPORTED_DATASET_TYPES)}")
    rows = read_csv_rows(input_path)
    if max_cases is not None:
        rows = rows[:max_cases]
    return [
        map_row(
            dataset_type=dataset_type,
            row=row,
            case_id=f"{case_id_prefix}-{index:03d}",
            process_id=process_id_start + index,
        )
        for index, row in enumerate(rows, start=1)
    ]


def write_jsonl(path: str | Path, rows: list[dict[str, Any]], append: bool = False) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with output_path.open(mode, encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-type", required=True, choices=sorted(SUPPORTED_DATASET_TYPES))
    parser.add_argument("--input", required=True, help="External dataset CSV path")
    parser.add_argument("--output-jsonl", default="outputs/external_holdout_v2.jsonl")
    parser.add_argument("--case-id-prefix", default="external-holdout-v2")
    parser.add_argument("--process-id-start", type=int, default=10_000)
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--append", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = build_external_holdout_cases(
        dataset_type=args.dataset_type,
        input_path=args.input,
        case_id_prefix=args.case_id_prefix,
        process_id_start=args.process_id_start,
        max_cases=args.max_cases,
    )
    write_jsonl(args.output_jsonl, cases, append=args.append)
    print(f"dataset_type={args.dataset_type}")
    print(f"generated_cases={len(cases)}")
    print(f"output_jsonl={args.output_jsonl}")


if __name__ == "__main__":
    main()
