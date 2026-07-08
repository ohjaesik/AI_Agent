# app/eval/recommendation_eval.py

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db.database import SessionLocal
from app.db.models import AnalysisResult


def load_gold(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    if "relevant_process_ids" not in data:
        raise ValueError("Gold JSON must include relevant_process_ids.")

    return data


def load_latest_priority_ranking(project_id: int) -> dict[str, Any]:
    with SessionLocal() as db:
        stmt = (
            select(AnalysisResult)
            .where(AnalysisResult.project_id == project_id)
            .where(AnalysisResult.node_name == "priority_ranking")
            .order_by(AnalysisResult.created_at.desc(), AnalysisResult.id.desc())
        )
        row = db.execute(stmt).scalars().first()

    if row is None:
        raise ValueError(f"priority_ranking result not found for project_id={project_id}")

    return row.result_json


def load_prediction(path: str | Path | None, project_id: int | None) -> dict[str, Any]:
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    if project_id is None:
        raise ValueError("Either --prediction-file or --project-id is required.")

    return load_latest_priority_ranking(project_id)


def evaluate_ranking(
    prediction: dict[str, Any],
    relevant_process_ids: list[int],
    k: int = 5,
) -> dict[str, Any]:
    items = prediction.get("items", [])
    ranked_process_ids = [int(item.get("process_id")) for item in items if item.get("process_id")]
    relevant = set(int(value) for value in relevant_process_ids)
    top_k = ranked_process_ids[:k]

    hits = [process_id for process_id in top_k if process_id in relevant]
    precision_at_k = len(hits) / k if k else 0.0
    recall_at_k = len(hits) / len(relevant) if relevant else 0.0
    hit_at_k = bool(hits)

    mrr = 0.0
    for rank, process_id in enumerate(ranked_process_ids, start=1):
        if process_id in relevant:
            mrr = 1.0 / rank
            break

    return {
        "k": k,
        "relevant_process_ids": sorted(relevant),
        "predicted_top_k": top_k,
        "hits": hits,
        "hit_at_k": hit_at_k,
        "precision_at_k": round(precision_at_k, 4),
        "recall_at_k": round(recall_at_k, 4),
        "mrr": round(mrr, 4),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate AX recommendation ranking.")
    parser.add_argument("--gold-file", type=str, required=True)
    parser.add_argument("--prediction-file", type=str, default=None)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--k", type=int, default=5)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    gold = load_gold(args.gold_file)
    prediction = load_prediction(args.prediction_file, args.project_id)
    metrics = evaluate_ranking(
        prediction=prediction,
        relevant_process_ids=gold["relevant_process_ids"],
        k=args.k,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
