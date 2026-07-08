# app/ingestion/ingest.py

from __future__ import annotations

import argparse
import json

from app.db.database import SessionLocal
from app.ingestion.service import ingest_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest a document into process_documents and RAG chunks.")
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--file", type=str, required=True)
    parser.add_argument("--process-id", type=int, default=None)
    parser.add_argument("--title", type=str, default=None)
    parser.add_argument("--document-type", type=str, default=None)
    parser.add_argument("--department", type=str, default=None)
    parser.add_argument("--security-level", type=str, default="internal")
    parser.add_argument("--contains-sensitive-info", action="store_true")
    parser.add_argument("--no-index", action="store_true")
    parser.add_argument("--chunk-size", type=int, default=800)
    parser.add_argument("--chunk-overlap", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=64)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with SessionLocal() as db:
        result = ingest_file(
            db=db,
            file_path=args.file,
            company_id=args.company_id,
            process_id=args.process_id,
            title=args.title,
            document_type=args.document_type,
            department=args.department,
            security_level=args.security_level,
            contains_sensitive_info=True if args.contains_sensitive_info else None,
            index=not args.no_index,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            batch_size=args.batch_size,
        )

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
