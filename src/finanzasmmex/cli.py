import argparse
import json
import sys
import uuid
from typing import Any, Dict, List, Optional

from .staging.repo import StagingRepo


def _emit(
    ok: bool,
    data: Any = None,
    errors: Optional[List[Dict[str, Any]]] = None,
    warnings: Optional[List[str]] = None,
) -> None:
    """Encapsula la respuesta en el contrato JSON estándar."""
    response = {
        "ok": ok,
        "data": data,
        "errors": errors or [],
        "warnings": warnings or [],
        "run_id": str(uuid.uuid4()),
    }
    print(json.dumps(response, indent=2))
    sys.exit(0 if ok else 1)


def main() -> None:
    parser = argparse.ArgumentParser(description="FinanzasMMEX CLI")
    subparsers = parser.add_subparsers(dest="command")

    # init command
    init_parser = subparsers.add_parser("init", help="Initialize the database")
    init_parser.add_argument("--db", default="staging.db", help="Path to staging.db")
    init_parser.add_argument(
        "--schema",
        default="src/finanzasmmex/staging/schema.sql",
        help="Path to schema.sql",
    )

    # run command
    run_parser = subparsers.add_parser("run", help="Run ingestion jobs")
    run_parser.add_argument(
        "--source",
        choices=["gmail", "mp", "all"],
        default="all",
        help="Source to ingest",
    )

    args = parser.parse_args()

    try:
        if args.command == "init":
            repo = StagingRepo(args.db)
            repo.init_db(args.schema)
            _emit(
                True,
                data={
                    "message": f"Database initialized at {args.db}",
                    "db_path": args.db,
                },
            )
        elif args.command == "run":
            # To be implemented in Phase 1
            _emit(True, data={"message": f"Stub: Ingestion for {args.source} executed"})
        else:
            parser.print_help()
            sys.exit(0)
    except Exception as e:
        _emit(False, errors=[{"code": "INTERNAL_ERROR", "message": str(e)}])


if __name__ == "__main__":
    main()
