# app/evaluation/export_holdout_candidates.py

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.evaluation.holdout_candidate_exporter import export_unlabeled_holdout_candidates


def load_state(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-json", required=True, help="Graph state JSON file exported from app.main --state-json-output")
    parser.add_argument("--csv", default="outputs/unlabeled_holdout_candidates.csv")
    parser.add_argument("--jsonl", default="outputs/unlabeled_holdout_candidates.jsonl")
    parser.add_argument("--case-id-prefix", default="graph-holdout")
    parser.add_argument("--borderline-only", action="store_true")
    parser.add_argument("--max-cases", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = export_unlabeled_holdout_candidates(
        state=load_state(args.state_json),
        csv_path=args.csv,
        jsonl_path=args.jsonl,
        case_id_prefix=args.case_id_prefix,
        borderline_only=args.borderline_only,
        max_cases=args.max_cases,
    )
    print(f"exported_candidates={len(rows)}")
    print(f"csv={args.csv}")
    print(f"jsonl={args.jsonl}")


if __name__ == "__main__":
    main()
