# app/company_bootstrap/bootstrap.py

from __future__ import annotations

import argparse
import json

from app.company_bootstrap.service import bootstrap_company
from app.db.database import SessionLocal


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap AX analysis DB from official company sources.")
    parser.add_argument("--company-name", type=str, required=True)
    parser.add_argument("--official-url", action="append", default=[])
    parser.add_argument("--dart-api-key", type=str, default=None)
    parser.add_argument("--corp-code", type=str, default=None)
    parser.add_argument("--stock-code", type=str, default=None)
    parser.add_argument("--no-project", action="store_true")
    parser.add_argument("--no-index", action="store_true")
    parser.add_argument("--reset-company-chunks", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with SessionLocal() as db:
        result = bootstrap_company(
            db=db,
            company_name=args.company_name,
            official_urls=args.official_url,
            dart_api_key=args.dart_api_key,
            corp_code=args.corp_code,
            stock_code=args.stock_code,
            create_project=not args.no_project,
            index=not args.no_index,
            reset_company_chunks=args.reset_company_chunks,
        )

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
