import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, NoReturn

from .orchestrator.jobs import run_gmail_bancoestado_to_ofx, run_mp_to_ofx
from .secrets.vault import Vault
from .staging.repo import StagingRepo

VALID_EXIT_CODES = {0, 2, 3, 4, 5}
MP_VAULT_KEY = "mp_access_token"
MP_TOKEN_ENV = "MP_ACCESS_TOKEN"
DISABLE_VAULT_ENV = "FINANZASMMEX_DISABLE_VAULT"


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


def _vault_disabled() -> bool:
    return os.environ.get(DISABLE_VAULT_ENV, "").lower() in {"1", "true", "yes"}


def _read_vault_secret(key: str) -> str | None:
    if _vault_disabled():
        return None
    try:
        return Vault().get_secret(key)
    except Exception:
        return None


def _store_vault_secret(key: str, value: str) -> None:
    if _vault_disabled():
        return
    Vault().set_secret(key, value)


def _run_gmail(args: argparse.Namespace) -> NoReturn:
    if not args.input:
        _emit(
            False,
            errors=[
                {
                    "code": "CREDENTIALS_REQUIRED",
                    "message": (
                        "Gmail OAuth credentials are not configured; "
                        "use --input for offline ingestion"
                    ),
                    "details": {
                        "source": args.source,
                        "offline_flag": "--input",
                        "login_command": "finanzasmmex login --source gmail",
                    },
                }
            ],
            exit_code=3,
        )
    result = run_gmail_bancoestado_to_ofx(
        input_path=args.input,
        db_path=args.db,
        schema_path=args.schema,
        ofx_output_path=args.ofx_output,
        report_output_path=args.report_output,
    )
    _emit(
        True,
        data={
            "message": "BancoEstado Gmail ingestion completed",
            "source": args.source,
            "writer": args.writer,
            **result.as_dict(),
        },
    )


def _run_mp(args: argparse.Namespace) -> NoReturn:
    if args.input:
        result = run_mp_to_ofx(
            input_path=args.input,
            db_path=args.db,
            schema_path=args.schema,
            ofx_output_path=args.ofx_output,
            report_output_path=args.report_output,
        )
        _emit(
            True,
            data={
                "message": "Mercado Pago offline ingestion completed",
                "source": args.source,
                "writer": args.writer,
                **result.as_dict(),
            },
        )

    if _read_vault_secret(MP_VAULT_KEY) is None:
        _emit(
            False,
            errors=[
                {
                    "code": "CREDENTIALS_REQUIRED",
                    "message": (
                        "Mercado Pago access token is not configured; "
                        "run login first or use --input for offline ingestion"
                    ),
                    "details": {
                        "source": args.source,
                        "offline_flag": "--input",
                        "login_command": "finanzasmmex login --source mp",
                    },
                }
            ],
            exit_code=3,
        )

    _emit(
        False,
        errors=[
            {
                "code": "TEMPORARY_FAILURE",
                "message": (
                    "Mercado Pago online ingestion is not wired in this cut; "
                    "use --input <path> for offline mode"
                ),
                "details": {"source": args.source},
            }
        ],
        exit_code=5,
    )


def _run_login(args: argparse.Namespace) -> NoReturn:
    if args.source != "mp":
        _emit(
            False,
            errors=[
                {
                    "code": "VALIDATION_ERROR",
                    "message": "Unsupported login source",
                    "details": {"source": args.source},
                }
            ],
            exit_code=2,
        )
    token = os.environ.get(MP_TOKEN_ENV, "").strip()
    if not token:
        _emit(
            False,
            errors=[
                {
                    "code": "CREDENTIALS_REQUIRED",
                    "message": (
                        "Mercado Pago access token must be provided via "
                        f"the {MP_TOKEN_ENV} environment variable"
                    ),
                    "details": {
                        "source": args.source,
                        "expected_env": MP_TOKEN_ENV,
                    },
                }
            ],
            exit_code=3,
        )
    _store_vault_secret(MP_VAULT_KEY, token)
    _emit(
        True,
        data={
            "message": "Mercado Pago access token stored in vault",
            "source": args.source,
            "vault_key": MP_VAULT_KEY,
        },
    )


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
    run_parser.add_argument(
        "--input",
        help=(
            "Path to a BancoEstado email file or directory "
            "for offline Gmail ingestion"
        ),
    )
    run_parser.add_argument("--db", default="staging.db", help="Path to staging.db")
    run_parser.add_argument(
        "--schema",
        default="src/finanzasmmex/staging/schema.sql",
        help="Path to schema.sql",
    )
    run_parser.add_argument(
        "--ofx-output",
        default="reports/finanzasmmex.ofx",
        help="Path to write the OFX file",
    )
    run_parser.add_argument(
        "--report-output",
        default="reports/review.html",
        help="Path to write the HTML review report",
    )

    # login command
    login_parser = subparsers.add_parser(
        "login",
        help="Store credentials for a source in the Windows Credential Manager",
    )
    login_parser.add_argument(
        "--source",
        choices=["mp"],
        required=True,
        help="Credential source to configure",
    )

    help_parsers = {"init": init_parser, "run": run_parser, "login": login_parser}
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
            if args.writer == "sql":
                _emit(
                    False,
                    errors=[
                        {
                            "code": "VALIDATION_ERROR",
                            "message": "SQL writer is not available until Phase 2",
                            "details": {"writer": args.writer},
                        }
                    ],
                    exit_code=2,
                )
            if args.source not in {"gmail", "mp"}:
                _emit(
                    False,
                    errors=[
                        {
                            "code": "VALIDATION_ERROR",
                            "message": (
                                "Only gmail and mp sources are implemented "
                                "in this cut"
                            ),
                            "details": {"source": args.source},
                        }
                    ],
                    exit_code=2,
                )

            if args.source == "gmail":
                _run_gmail(args)
            else:
                _run_mp(args)
        elif args.command == "login":
            _run_login(args)
    except ValueError as e:
        _emit(
            False,
            errors=[
                {
                    "code": "VALIDATION_ERROR",
                    "message": str(e),
                    "details": {"exception_type": type(e).__name__},
                }
            ],
            exit_code=2,
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
