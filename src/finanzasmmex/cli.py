import argparse
import json
import os
import sys
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, NoReturn

from .etl.fitid import ensure_fitid
from .etl.normalize import parse_clp_amount
from .models import CanonicalTx
from .orchestrator.jobs import run_gmail_bancoestado_to_ofx, run_mp_to_ofx
from .secrets.vault import Vault
from .staging.repo import StagingRepo

VALID_EXIT_CODES = {0, 2, 3, 4, 5}
MP_VAULT_KEY = "mp_access_token"
MP_TOKEN_ENV = "MP_ACCESS_TOKEN"
DISABLE_VAULT_ENV = "FINANZASMMEX_DISABLE_VAULT"

VALID_OWNERS = {"ricardo", "laura", "joint"}
VALID_DIRECTIONS = {"debit", "credit"}
VALID_TX_TYPES = {
    "purchase",
    "bill_payment",
    "transfer_in",
    "transfer_out",
    "internal_transfer",
    "refund",
    "cash_withdrawal",
    "fee",
}
VALID_REVIEW_STATUSES = {"pending", "exported", "inserted", "rejected"}
RESOLVE_STATUSES = {"exported", "inserted", "rejected"}


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


def _validation_error(message: str, details: dict[str, Any] | None = None) -> NoReturn:
    _emit(
        False,
        errors=[
            {
                "code": "VALIDATION_ERROR",
                "message": message,
                "details": details or {},
            }
        ],
        exit_code=2,
    )


def _parse_iso_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        _validation_error(
            f"{field_name} must be ISO date YYYY-MM-DD",
            {"field": field_name, "value": value},
        )


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def _parse_bool_flag(value: str, field_name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    _validation_error(
        f"{field_name} must be true/false",
        {"field": field_name, "value": value},
    )


def _tx_to_dict(tx: CanonicalTx) -> dict[str, Any]:
    return {
        "tx_uid": tx.tx_uid,
        "owner": tx.owner,
        "source_type": tx.source_type,
        "source_file": tx.source_file,
        "source_ref": tx.source_ref,
        "event_date": tx.event_date.isoformat() if tx.event_date else None,
        "booking_date": tx.booking_date.isoformat() if tx.booking_date else None,
        "posted_date": tx.posted_date.isoformat() if tx.posted_date else None,
        "amount": str(tx.amount),
        "currency": tx.currency,
        "direction": tx.direction,
        "account_alias": tx.account_alias,
        "card_last4": tx.card_last4,
        "merchant_raw": tx.merchant_raw,
        "merchant_norm": tx.merchant_norm,
        "tx_type": tx.tx_type,
        "category_guess": tx.category_guess,
        "subcategory_guess": tx.subcategory_guess,
        "tags": tx.tags,
        "needs_review": tx.needs_review,
        "review_reason": tx.review_reason,
        "fitid_synthetic": tx.fitid_synthetic,
        "parser_name": tx.parser_name,
        "parser_version": tx.parser_version,
        "mmex_status": tx.mmex_status,
        "transfer_pair_uid": tx.transfer_pair_uid,
    }


def _run_review_list(args: argparse.Namespace) -> NoReturn:
    repo = StagingRepo(args.db)
    txs = repo.list_txs(
        owner=args.owner,
        account_alias=args.account_alias,
        mmex_status=args.status,
        needs_review_only=args.needs_review_only,
        since=args.since,
        until=args.until,
        limit=args.limit,
    )
    items = [_tx_to_dict(tx) for tx in txs]
    _emit(
        True,
        data={
            "items": items,
            "count": len(items),
            "filters": {
                "owner": args.owner,
                "account_alias": args.account_alias,
                "status": args.status,
                "needs_review_only": args.needs_review_only,
                "since": args.since,
                "until": args.until,
                "limit": args.limit,
            },
        },
    )


def _run_review_update(args: argparse.Namespace) -> NoReturn:
    fields: dict[str, object] = {}
    if args.owner is not None:
        if args.owner not in VALID_OWNERS:
            _validation_error(
                "owner must be one of ricardo|laura|joint",
                {"field": "owner", "value": args.owner},
            )
        fields["owner"] = args.owner
    if args.category_guess is not None:
        fields["category_guess"] = args.category_guess
    if args.subcategory_guess is not None:
        fields["subcategory_guess"] = args.subcategory_guess
    if args.merchant_norm is not None:
        fields["merchant_norm"] = args.merchant_norm
    if args.tags is not None:
        fields["tags_json"] = json.dumps(_parse_tags(args.tags))
    if args.needs_review is not None:
        fields["needs_review"] = (
            1 if _parse_bool_flag(args.needs_review, "--needs-review") else 0
        )
    if args.review_reason is not None:
        fields["review_reason"] = args.review_reason

    if not fields:
        _validation_error(
            "At least one updatable field must be provided",
            {"tx_uid": args.tx_uid},
        )

    repo = StagingRepo(args.db)
    if repo.get_tx(args.tx_uid) is None:
        _emit(
            False,
            errors=[
                {
                    "code": "VALIDATION_ERROR",
                    "message": "Transaction not found",
                    "details": {"tx_uid": args.tx_uid},
                }
            ],
            exit_code=2,
        )

    repo.update_tx_fields(args.tx_uid, fields)
    updated_tx = repo.get_tx(args.tx_uid)
    assert updated_tx is not None  # we just confirmed it exists
    _emit(
        True,
        data={
            "tx_uid": args.tx_uid,
            "updated_fields": sorted(fields.keys()),
            "tx": _tx_to_dict(updated_tx),
        },
    )


def _run_review_resolve(args: argparse.Namespace) -> NoReturn:
    if args.status not in RESOLVE_STATUSES:
        _validation_error(
            "status must be one of exported|inserted|rejected",
            {"field": "--status", "value": args.status},
        )
    repo = StagingRepo(args.db)
    if repo.get_tx(args.tx_uid) is None:
        _emit(
            False,
            errors=[
                {
                    "code": "VALIDATION_ERROR",
                    "message": "Transaction not found",
                    "details": {"tx_uid": args.tx_uid},
                }
            ],
            exit_code=2,
        )
    repo.update_mmex_status(args.tx_uid, args.status)
    _emit(
        True,
        data={
            "tx_uid": args.tx_uid,
            "mmex_status": args.status,
        },
    )


def _run_quickadd_create(args: argparse.Namespace) -> NoReturn:
    if args.owner not in VALID_OWNERS:
        _validation_error(
            "owner must be one of ricardo|laura|joint",
            {"field": "--owner", "value": args.owner},
        )
    if args.direction not in VALID_DIRECTIONS:
        _validation_error(
            "direction must be debit|credit",
            {"field": "--direction", "value": args.direction},
        )
    if args.tx_type not in VALID_TX_TYPES:
        _validation_error(
            "tx-type invalid",
            {"field": "--tx-type", "value": args.tx_type},
        )

    event_date = _parse_iso_date(args.date, "--date")

    try:
        if args.currency.upper() == "CLP":
            amount = parse_clp_amount(args.amount)
        else:
            amount = Decimal(args.amount).quantize(Decimal("0.00"))
            if amount <= 0:
                raise ValueError("amount must be greater than zero")
    except (InvalidOperation, ValueError) as exc:
        _validation_error(
            f"Invalid amount: {exc}",
            {"field": "--amount", "value": args.amount},
        )

    tx = CanonicalTx(
        owner=args.owner,
        source_type="manual",
        source_file=None,
        source_ref=args.source_ref,
        raw_text="",
        content_sha256="",
        event_date=event_date,
        posted_date=event_date,
        amount=amount,
        currency=args.currency.upper(),
        direction=args.direction,
        account_alias=args.account_alias,
        merchant_raw=args.merchant_raw,
        tx_type=args.tx_type,
        category_guess=args.category_guess,
        subcategory_guess=args.subcategory_guess,
        tags=_parse_tags(args.tags),
        parser_name="manual",
        parser_version="1.0",
        needs_review=False,
    )
    tx = ensure_fitid(tx)
    assert tx.fitid_synthetic is not None  # ensure_fitid always sets it

    repo = StagingRepo(args.db)
    existing = repo.get_tx_by_fitid(tx.fitid_synthetic)
    if existing is not None:
        _emit(
            True,
            data={
                "created": False,
                "tx_uid": existing.tx_uid,
                "fitid_synthetic": existing.fitid_synthetic,
                "tx": _tx_to_dict(existing),
            },
            warnings=["Transaction already exists for this fitid; no insert performed"],
        )

    repo.upsert_tx(tx)
    _emit(
        True,
        data={
            "created": True,
            "tx_uid": tx.tx_uid,
            "fitid_synthetic": tx.fitid_synthetic,
            "tx": _tx_to_dict(tx),
        },
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

    # review command (list/update/resolve)
    review_parser = subparsers.add_parser(
        "review",
        help="Inspect and update transactions in the staging review queue",
    )
    review_sub = review_parser.add_subparsers(
        dest="review_action",
        required=True,
        parser_class=ContractArgumentParser,
    )

    review_list_parser = review_sub.add_parser(
        "list", help="List transactions matching the given filters"
    )
    review_list_parser.add_argument(
        "--db", default="staging.db", help="Path to staging.db"
    )
    review_list_parser.add_argument(
        "--owner",
        choices=sorted(VALID_OWNERS),
        help="Filter by owner",
    )
    review_list_parser.add_argument(
        "--account-alias", help="Filter by account alias", default=None
    )
    review_list_parser.add_argument(
        "--status",
        choices=sorted(VALID_REVIEW_STATUSES),
        default=None,
        help="Filter by mmex_status (default: no filter)",
    )
    review_list_parser.add_argument(
        "--needs-review-only",
        action="store_true",
        help="Restrict to transactions flagged needs_review=true",
    )
    review_list_parser.add_argument(
        "--since", help="ISO date YYYY-MM-DD lower bound (inclusive)"
    )
    review_list_parser.add_argument(
        "--until", help="ISO date YYYY-MM-DD upper bound (inclusive)"
    )
    review_list_parser.add_argument(
        "--limit", type=int, default=200, help="Max rows to return (default 200)"
    )

    review_update_parser = review_sub.add_parser(
        "update", help="Update reviewable fields on a transaction"
    )
    review_update_parser.add_argument("--db", default="staging.db")
    review_update_parser.add_argument("--tx-uid", required=True, help="Target tx_uid")
    review_update_parser.add_argument("--owner", default=None)
    review_update_parser.add_argument("--category-guess", default=None)
    review_update_parser.add_argument("--subcategory-guess", default=None)
    review_update_parser.add_argument("--merchant-norm", default=None)
    review_update_parser.add_argument(
        "--tags", default=None, help="Comma-separated list of tags (overwrites)"
    )
    review_update_parser.add_argument(
        "--needs-review", default=None, help="true/false"
    )
    review_update_parser.add_argument("--review-reason", default=None)

    review_resolve_parser = review_sub.add_parser(
        "resolve", help="Set the mmex_status of a transaction"
    )
    review_resolve_parser.add_argument("--db", default="staging.db")
    review_resolve_parser.add_argument("--tx-uid", required=True)
    review_resolve_parser.add_argument(
        "--status",
        required=True,
        choices=sorted(RESOLVE_STATUSES),
        help="Target mmex_status",
    )

    # quickadd command (create)
    quickadd_parser = subparsers.add_parser(
        "quickadd",
        help="Create transactions manually via the canonical pipeline",
    )
    quickadd_sub = quickadd_parser.add_subparsers(
        dest="quickadd_action",
        required=True,
        parser_class=ContractArgumentParser,
    )

    quickadd_create_parser = quickadd_sub.add_parser(
        "create", help="Insert a manual transaction in the staging DB"
    )
    quickadd_create_parser.add_argument("--db", default="staging.db")
    quickadd_create_parser.add_argument(
        "--owner", required=True, choices=sorted(VALID_OWNERS)
    )
    quickadd_create_parser.add_argument("--account-alias", required=True)
    quickadd_create_parser.add_argument(
        "--amount", required=True, help="Positive amount"
    )
    quickadd_create_parser.add_argument("--currency", default="CLP")
    quickadd_create_parser.add_argument(
        "--direction", required=True, choices=sorted(VALID_DIRECTIONS)
    )
    quickadd_create_parser.add_argument(
        "--date", required=True, help="ISO date YYYY-MM-DD"
    )
    quickadd_create_parser.add_argument("--merchant-raw", required=True)
    quickadd_create_parser.add_argument("--category-guess", default=None)
    quickadd_create_parser.add_argument("--subcategory-guess", default=None)
    quickadd_create_parser.add_argument(
        "--tx-type",
        default="purchase",
        choices=sorted(VALID_TX_TYPES),
    )
    quickadd_create_parser.add_argument(
        "--tags", default=None, help="Comma-separated tags"
    )
    quickadd_create_parser.add_argument("--source-ref", default=None)

    help_parsers = {
        "init": init_parser,
        "run": run_parser,
        "login": login_parser,
        "review": review_parser,
        "quickadd": quickadd_parser,
    }
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
        elif args.command == "review":
            if args.review_action == "list":
                _run_review_list(args)
            elif args.review_action == "update":
                _run_review_update(args)
            elif args.review_action == "resolve":
                _run_review_resolve(args)
        elif args.command == "quickadd":
            if args.quickadd_action == "create":
                _run_quickadd_create(args)
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
