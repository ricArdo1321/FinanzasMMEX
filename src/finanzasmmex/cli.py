import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any, NoReturn

from .staging.repo import StagingRepo

VALID_EXIT_CODES = {0, 2, 3, 4, 5}


class ContractArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("add_help", False)
        super().__init__(*args, **kwargs)
        self.add_argument(
            "-h",
            "--help",
            action="store_true",
            dest="_contract_help",
            help="Show this help message",
        )

    def error(self, message: str) -> NoReturn:
        _emit(
            False,
            errors=[
                {
                    "code": "VALIDATION_ERROR",
                    "message": message,
                    "details": {"usage": self.format_usage().strip()},
                }
            ],
            exit_code=2,
        )


def _emit(
    ok: bool,
    data: Any = None,
    errors: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
    exit_code: int | None = None,
) -> NoReturn:
    """Encapsula la respuesta en el contrato JSON estándar."""
    normalized_errors = [
        {
            "code": str(error.get("code", "ERROR")),
            "message": str(error.get("message", "")),
            "details": error.get("details", {}),
        }
        for error in (errors or [])
    ]
    resolved_exit_code = exit_code if exit_code is not None else (0 if ok else 5)
    if resolved_exit_code not in VALID_EXIT_CODES:
        resolved_exit_code = 5

    response = {
        "ok": ok,
        "data": data,
        "errors": normalized_errors,
        "warnings": warnings or [],
        "run_id": str(uuid.uuid4()),
    }
    print(json.dumps(response, ensure_ascii=False))
    sys.exit(resolved_exit_code)


def main() -> None:
    argv = sys.argv[1:]
    parser = ContractArgumentParser(description="FinanzasMMEX CLI")
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        parser_class=ContractArgumentParser,
    )

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
        choices=["gmail", "mp", "scraping-be", "scraping-cmr", "drop", "manual", "all"],
        default="all",
        help="Source to ingest",
    )
    run_parser.add_argument(
        "--writer",
        choices=["ofx", "sql"],
        default="ofx",
        help="Writer mode",
    )

    help_parsers = {"init": init_parser, "run": run_parser}
    if argv in (["-h"], ["--help"]):
        _emit(True, data={"help": parser.format_help()})
    if len(argv) >= 2 and argv[-1] in ("-h", "--help") and argv[0] in help_parsers:
        _emit(True, data={"help": help_parsers[argv[0]].format_help()})

    args = parser.parse_args(argv)

    try:
        if args.command == "init":
            schema_path = Path(args.schema)
            if not schema_path.is_file():
                _emit(
                    False,
                    errors=[
                        {
                            "code": "VALIDATION_ERROR",
                            "message": "Schema file does not exist",
                            "details": {"schema_path": args.schema},
                        }
                    ],
                    exit_code=2,
                )
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
            _emit(
                True,
                data={
                    "message": f"Stub: Ingestion for {args.source} executed",
                    "source": args.source,
                    "writer": args.writer,
                },
            )
    except Exception as e:
        _emit(
            False,
            errors=[
                {
                    "code": "TEMPORARY_FAILURE",
                    "message": str(e),
                    "details": {"exception_type": type(e).__name__},
                }
            ],
            exit_code=5,
        )


if __name__ == "__main__":
    main()
