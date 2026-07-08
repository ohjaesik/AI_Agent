# app/company_bootstrap/bootstrap.py

from __future__ import annotations

import argparse
import json

from sqlalchemy.exc import ProgrammingError

from app.company_bootstrap.runner import run_bootstrap_supervisor_graph


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
    parser.add_argument("--thread-id", type=str, default="bootstrap-supervisor-cli")
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Initialize pgvector extension, create tables, and run lightweight migrations before bootstrapping.",
    )
    return parser.parse_args()


def initialize_database() -> None:
    from app.db.create_tables import main as create_tables
    from app.db.init_pgvector import main as init_pgvector
    from app.db.migrate_discovery_metadata import main as migrate_discovery_metadata
    from app.db.migrate_operational_hardening import main as migrate_operational_hardening

    init_pgvector()
    create_tables()
    migrate_discovery_metadata()
    migrate_operational_hardening()


def main() -> None:
    args = parse_args()

    if args.init_db:
        initialize_database()

    try:
        result = run_bootstrap_supervisor_graph(
            company_name=args.company_name,
            official_urls=args.official_url,
            dart_api_key=args.dart_api_key,
            corp_code=args.corp_code,
            stock_code=args.stock_code,
            create_project=not args.no_project,
            index=not args.no_index,
            reset_company_chunks=args.reset_company_chunks,
            thread_id=args.thread_id,
        )
    except ProgrammingError as exc:
        message = str(exc).lower()
        if "undefinedtable" in message or "relation \"companies\" does not exist" in message:
            raise RuntimeError(
                "Database tables are not initialized. Run:\n"
                "  python -m app.db.init_pgvector\n"
                "  python -m app.db.create_tables\n"
                "  python -m app.db.migrate_operational_hardening\n"
                "or rerun this command with --init-db."
            ) from exc
        raise

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
