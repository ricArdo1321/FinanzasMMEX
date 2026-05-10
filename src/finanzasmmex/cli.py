import argparse
import getpass
import json
import os
import shutil
import sqlite3
import sys
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, NoReturn, cast

from .adapters.file_loaders import FileLoaderError, load_drop_file_for_staging
from .adapters.mp_api import MercadoPagoCredentialsError, MercadoPagoTemporaryError
from .adapters.scraping_base import ScrapingError, ScrapingLoginError
from .etl.fitid import ensure_fitid
from .etl.normalize import parse_clp_amount
from .models import CanonicalTx
from .notifications import notify_needs_review
from .orchestrator.jobs import (
    RunSummary,
    run_gmail_all_to_ofx,
    run_gmail_bancoestado_to_ofx,
    run_gmail_cmr_to_ofx,
    run_gmail_mach_to_ofx,
    run_mp_online,
    run_mp_to_ofx,
    run_pending_to_sql,
    run_scraping_be,
    run_scraping_cmr,
)
from .reports import (
    generate_monthly_dashboard,
    latest_monthly_dashboard,
    list_monthly_dashboards,
)
from .secrets.vault import Vault
from .staging.repo import JobRunStatus, StagingRepo
from .writer.mmex_sql import (
    MmexBackupError,
    MmexLockedError,
    MmexMappingError,
    MmexSafetyError,
    MmexSchemaError,
)

VALID_EXIT_CODES = {0, 2, 3, 4, 5}
MP_VAULT_KEY = "mp_access_token"
MP_TOKEN_ENV = "MP_ACCESS_TOKEN"
DISABLE_VAULT_ENV = "FINANZASMMEX_DISABLE_VAULT"
DEFAULT_DATA_DIR = r"C:\Finanzas"
DEFAULT_STAGING_DB = rf"{DEFAULT_DATA_DIR}\staging.db"
DEFAULT_REPORTS_DIR = rf"{DEFAULT_DATA_DIR}\reports"
DEFAULT_REPORT_OUTPUT = rf"{DEFAULT_REPORTS_DIR}\review.html"
DEFAULT_OFX_OUTPUT = rf"{DEFAULT_REPORTS_DIR}\finanzasmmex.ofx"
DEFAULT_BACKUP_DIR = rf"{DEFAULT_DATA_DIR}\backups"
DEFAULT_DROP_DIR = rf"{DEFAULT_DATA_DIR}\drop"

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
                        "available_mode": "offline_input_only",
                    },
                }
            ],
            exit_code=3,
        )

    source_label: str
    from collections.abc import Callable
    runner: Callable[..., RunSummary]
    if args.gmail_source == "cmr":
        source_label = "CMR"
        runner = run_gmail_cmr_to_ofx
    elif args.gmail_source == "mach":
        source_label = "Mach"
        runner = run_gmail_mach_to_ofx
    else:
        source_label = "BancoEstado"
        runner = run_gmail_bancoestado_to_ofx

    result = runner(
        input_path=args.input,
        db_path=args.db,
        schema_path=args.schema,
        ofx_output_path=args.ofx_output,
        report_output_path=args.report_output,
    )
    _emit(
        True,
        data={
            "message": f"Gmail {source_label} ingestion completed",
            "source": args.source,
            "writer": args.writer,
            **result.as_dict(),
        },
    )


def _run_gmail_all(args: argparse.Namespace) -> NoReturn:
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
                        "available_mode": "offline_input_only",
                    },
                }
            ],
            exit_code=3,
        )

    result = run_gmail_all_to_ofx(
        input_path=args.input,
        db_path=args.db,
        schema_path=args.schema,
        ofx_output_path=args.ofx_output,
        report_output_path=args.report_output,
    )
    _emit(
        True,
        data={
            "message": "Gmail all sources ingestion completed",
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

    token = _read_vault_secret(MP_VAULT_KEY)
    if token is None:
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

    begin_date = args.begin_date
    end_date = args.end_date
    today = date.today()
    if begin_date is None:
        begin_date = (today - timedelta(days=7)).isoformat()
    else:
        _parse_iso_date(begin_date, "--begin-date")  # validate format
    if end_date is None:
        end_date = today.isoformat()
    else:
        _parse_iso_date(end_date, "--end-date")  # validate format

    try:
        result = run_mp_online(
            access_token=token,
            begin_date=begin_date,
            end_date=end_date,
            db_path=args.db,
            schema_path=args.schema,
            ofx_output_path=args.ofx_output,
            report_output_path=args.report_output,
        )
    except MercadoPagoCredentialsError as exc:
        _emit(
            False,
            errors=[
                {
                    "code": "CREDENTIALS_REQUIRED",
                    "message": "Mercado Pago access token is invalid or expired",
                    "details": {
                        "source": args.source,
                        "login_command": "finanzasmmex login --source mp",
                        "exception_type": type(exc).__name__,
                    },
                }
            ],
            exit_code=3,
        )
    except MercadoPagoTemporaryError as exc:
        _emit(
            False,
            errors=[
                {
                    "code": "TEMPORARY_FAILURE",
                    "message": "Mercado Pago API request failed temporarily",
                    "details": {
                        "source": args.source,
                        "exception_type": type(exc).__name__,
                    },
                }
            ],
            exit_code=5,
        )
    _emit(
        True,
        data={
            "message": "Mercado Pago online ingestion completed",
            "source": args.source,
            "writer": args.writer,
            **result.as_dict(),
        },
    )


def _run_drop(args: argparse.Namespace) -> NoReturn:
    input_path = Path(args.input or DEFAULT_DROP_DIR)
    if args.input is None:
        input_path.mkdir(parents=True, exist_ok=True)
    repo = StagingRepo(args.db)
    db_path = Path(args.db)
    if not db_path.exists():
        repo.init_db(args.schema)

    if input_path.is_dir():
        _run_drop_directory(args, repo, input_path)

    try:
        data = _persist_drop_file(args, repo, input_path)
    except FileLoaderError as exc:
        _record_job_run_safely(
            repo,
            job_name="drop",
            status="error",
            error_message=str(exc),
            metadata={
                "input": str(input_path),
                "error_code": exc.error_code,
                **exc.details,
            },
        )
        raise
    _emit(True, data=data)


def _run_drop_directory(
    args: argparse.Namespace,
    repo: StagingRepo,
    drop_dir: Path,
) -> NoReturn:
    processing_dir = drop_dir / "processing"
    processed_dir = drop_dir / "processed"
    error_dir = drop_dir / "error"
    for state_dir in (processing_dir, processed_dir, error_dir):
        state_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(path for path in drop_dir.iterdir() if path.is_file())
    summary: dict[str, object] = {
        "message": "Drop folder ingestion completed",
        "source": args.source,
        "writer": args.writer,
        "db_path": args.db,
        "incoming_dir": str(drop_dir),
        "processing_dir": str(processing_dir),
        "processed_dir": str(processed_dir),
        "error_dir": str(error_dir),
        "files_seen": len(files),
        "files_processed": 0,
        "files_error": 0,
        "items_processed": 0,
        "items_inserted": 0,
        "items_review": 0,
        "processed_files": [],
        "error_files": [],
    }
    errors: list[dict[str, object]] = []

    for file_path in files:
        if not _is_stable_file(file_path):
            errors.append(
                _drop_error(
                    file_path,
                    "FILE_NOT_STABLE",
                    "Drop file is still changing",
                    error_path=None,
                )
            )
            summary["files_error"] = cast(int, summary["files_error"]) + 1
            continue

        processing_path = _move_to_state(file_path, processing_dir)
        try:
            data = _persist_drop_file(args, repo, processing_path)
        except FileLoaderError as exc:
            error_path = _move_to_state(processing_path, error_dir)
            _record_job_run_safely(
                repo,
                job_name="drop",
                status="error",
                error_message=str(exc),
                metadata={
                    "input": str(file_path),
                    "error_path": str(error_path),
                    "error_code": exc.error_code,
                    **exc.details,
                },
            )
            errors.append(
                _drop_error(
                    file_path,
                    exc.error_code,
                    str(exc),
                    error_path=error_path,
                )
            )
            summary["files_error"] = cast(int, summary["files_error"]) + 1
            cast_errors = summary["error_files"]
            assert isinstance(cast_errors, list)
            cast_errors.append(str(error_path))
            continue

        processed_path = _move_to_state(processing_path, processed_dir)
        summary["files_processed"] = cast(int, summary["files_processed"]) + 1
        summary["items_processed"] = cast(int, summary["items_processed"]) + cast(
            int, data["items_processed"]
        )
        summary["items_inserted"] = cast(int, summary["items_inserted"]) + cast(
            int, data["items_inserted"]
        )
        summary["items_review"] = cast(int, summary["items_review"]) + cast(
            int, data["items_review"]
        )
        processed_files = summary["processed_files"]
        assert isinstance(processed_files, list)
        processed_files.append(str(processed_path))

    if errors and cast(int, summary["files_processed"]) == 0:
        _emit(False, data=summary, errors=errors, exit_code=2)
    _emit(
        True,
        data=summary,
        warnings=[f"{len(errors)} drop file(s) moved to error"] if errors else [],
    )


def _persist_drop_file(
    args: argparse.Namespace,
    repo: StagingRepo,
    input_path: Path,
) -> dict[str, object]:
    result = load_drop_file_for_staging(
        input_path,
        rules=repo.list_rules(active_only=True),
    )
    artifact_id = repo.insert_raw_artifact(
        artifact_type=result.source_type,
        source_ref=result.source_path,
        content_sha256=result.content_sha256,
        payload_blob=Path(result.source_path).read_bytes(),
    )
    repo.upsert_batch(result.transactions)
    repo.record_job_run(
        job_name="drop",
        status="ok",
        items_processed=len(result.transactions),
        items_inserted=len(result.transactions),
        items_review=sum(1 for tx in result.transactions if tx.needs_review),
        metadata={
            "input": result.source_path,
            "source_type": result.source_type,
            "content_sha256": result.content_sha256,
            "artifact_id": artifact_id,
        },
    )
    return {
        "message": "Drop ingestion completed",
        "source": args.source,
        "writer": args.writer,
        "items_processed": len(result.transactions),
        "items_inserted": len(result.transactions),
        "items_review": sum(1 for tx in result.transactions if tx.needs_review),
        "db_path": args.db,
        "source_type": result.source_type,
        "artifact_id": artifact_id,
    }


def _is_stable_file(path: Path, *, wait_seconds: float = 0.05) -> bool:
    first = path.stat()
    time.sleep(wait_seconds)
    second = path.stat()
    return (
        first.st_size == second.st_size
        and first.st_mtime_ns == second.st_mtime_ns
    )


def _move_to_state(path: Path, state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    target = _unique_state_path(state_dir / path.name)
    return Path(shutil.move(str(path), str(target)))


def _unique_state_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 10_000):
        candidate = path.with_name(f"{path.stem}.{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate unique drop state path for {path}")


def _drop_error(
    input_path: Path,
    code: str,
    message: str,
    *,
    error_path: Path | None,
) -> dict[str, object]:
    details: dict[str, object] = {"input": str(input_path)}
    if error_path is not None:
        details["error_path"] = str(error_path)
    return {"code": code, "message": message, "details": details}


def _run_sql(args: argparse.Namespace) -> NoReturn:
    if not args.mmex_db:
        _validation_error(
            "--mmex-db is required when --writer sql is used",
            {"field": "--mmex-db"},
        )
    if not args.allow_shadow_write:
        _validation_error(
            "SQL writer requires explicit shadow/test write flag",
            {"field": "--allow-shadow-write"},
        )
    if not Path(args.db).is_file():
        _validation_error(
            "staging.db does not exist",
            {"field": "--db", "db_path": args.db},
        )
    _validate_staging_db(args.db)
    # Echo only the basename of the .mmb in error envelopes — the full
    # absolute path is local file-system metadata that should not surface
    # to UIs or logs.
    mmex_basename = Path(args.mmex_db).name
    try:
        result = run_pending_to_sql(
            db_path=args.db,
            mmex_db_path=args.mmex_db,
            backup_dir=args.backup_dir,
            allow_shadow_write=args.allow_shadow_write,
        )
    except MmexLockedError as exc:
        _record_deferred_job(args.db, "mmex_sql", str(exc))
        _emit(
            False,
            errors=[
                {
                    "code": "MMEX_LOCKED",
                    "message": str(exc),
                    "details": {"mmex_db": mmex_basename},
                }
            ],
            exit_code=4,
        )
    except (MmexSafetyError, MmexMappingError, MmexSchemaError) as exc:
        _validation_error(
            str(exc),
            {"exception_type": type(exc).__name__, "mmex_db": mmex_basename},
        )
    except MmexBackupError as exc:
        _emit(
            False,
            errors=[
                {
                    "code": "TEMPORARY_FAILURE",
                    "message": str(exc),
                    "details": {
                        "exception_type": type(exc).__name__,
                        "mmex_db": mmex_basename,
                    },
                }
            ],
            exit_code=5,
        )
    else:
        # Reachable only on a successful run; the except branches above
        # are NoReturn (they call sys.exit). Using else binds `result`
        # to its happy-path scope and removes any UnboundLocalError risk.
        _emit(
            True,
            data={
                "message": "MMEX SQL writer completed",
                "source": args.source,
                "writer": args.writer,
                **result.as_dict(),
            },
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


def _validate_staging_db(db_path: str) -> None:
    path = Path(db_path)
    if not path.is_file():
        _validation_error(
            "staging.db does not exist",
            {"field": "--db", "db_path": db_path},
        )
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
    except sqlite3.Error as exc:
        _validation_error(
            "staging.db is not readable",
            {"field": "--db", "exception_type": type(exc).__name__},
        )
    required = {"schema_version", "canonical_tx", "category_rules", "job_runs"}
    missing = sorted(required - tables)
    if missing:
        _validation_error(
            "staging.db schema is not initialized",
            {"field": "--db", "missing_tables": missing},
        )


def _record_deferred_job(db_path: str, job_name: str, error_message: str) -> None:
    try:
        repo = StagingRepo(db_path)
        repo.record_job_run(
            job_name=job_name,
            status="deferred",
            error_message=error_message,
        )
    except sqlite3.Error:
        return


def _record_job_run_safely(
    repo: StagingRepo,
    *,
    job_name: str,
    status: JobRunStatus,
    error_message: str,
    metadata: dict[str, object],
) -> None:
    try:
        repo.record_job_run(
            job_name=job_name,
            status=status,
            error_message=error_message,
            metadata=metadata,
        )
    except sqlite3.Error:
        return


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
    _validate_staging_db(args.db)
    repo = StagingRepo(args.db)
    txs = repo.list_txs(
        owner=args.owner,
        account_alias=args.account_alias,
        mmex_status=args.status,
        needs_review_only=args.needs_review_only,
        since=args.since,
        until=args.until,
        source_type=args.source_type,
        category_guess=args.category,
        merchant_query=args.merchant,
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
                "source_type": args.source_type,
                "category": args.category,
                "merchant": args.merchant,
                "limit": args.limit,
            },
        },
    )


def _run_review_update(args: argparse.Namespace) -> NoReturn:
    _validate_staging_db(args.db)
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
    if updated_tx is None:
        _emit(
            False,
            errors=[
                {
                    "code": "TEMPORARY_FAILURE",
                    "message": "Transaction disappeared between update and read",
                    "details": {"tx_uid": args.tx_uid},
                }
            ],
            exit_code=5,
        )
    public_fields = sorted(("tags" if name == "tags_json" else name) for name in fields)
    _emit(
        True,
        data={
            "tx_uid": args.tx_uid,
            "updated_fields": public_fields,
            "tx": _tx_to_dict(updated_tx),
        },
    )


def _run_review_resolve(args: argparse.Namespace) -> NoReturn:
    _validate_staging_db(args.db)
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


def _run_review_bulk_update(args: argparse.Namespace) -> NoReturn:
    _validate_staging_db(args.db)
    repo = StagingRepo(args.db)
    items = _load_bulk_items(args.input)
    results: list[dict[str, object]] = []

    for index, item in enumerate(items):
        tx_uid = _bulk_tx_uid(item)
        if tx_uid is None:
            results.append(
                _bulk_error(index, "tx_uid is required", {"field": "tx_uid"})
            )
            continue

        field_result = _bulk_update_fields(item)
        if "error" in field_result:
            error = field_result["error"]
            assert isinstance(error, dict)
            results.append(_bulk_error(index, str(error["message"]), error, tx_uid))
            continue

        fields = field_result["fields"]
        assert isinstance(fields, dict)
        if repo.get_tx(tx_uid) is None:
            results.append(
                _bulk_error(
                    index,
                    "Transaction not found",
                    {"tx_uid": tx_uid},
                    tx_uid,
                )
            )
            continue

        repo.update_tx_fields(tx_uid, fields)
        updated_tx = repo.get_tx(tx_uid)
        if updated_tx is None:
            results.append(
                _bulk_error(
                    index,
                    "Transaction disappeared between update and read",
                    {"tx_uid": tx_uid},
                    tx_uid,
                    code="TEMPORARY_FAILURE",
                )
            )
            continue

        public_fields = sorted(
            ("tags" if name == "tags_json" else name) for name in fields
        )
        results.append(
            {
                "index": index,
                "tx_uid": tx_uid,
                "ok": True,
                "updated_fields": public_fields,
                "tx": _tx_to_dict(updated_tx),
            }
        )

    _emit_bulk_result("bulk-update", results)


def _run_review_bulk_resolve(args: argparse.Namespace) -> NoReturn:
    _validate_staging_db(args.db)
    repo = StagingRepo(args.db)
    items = _load_bulk_items(args.input)
    results: list[dict[str, object]] = []

    for index, item in enumerate(items):
        tx_uid = _bulk_tx_uid(item)
        if tx_uid is None:
            results.append(
                _bulk_error(index, "tx_uid is required", {"field": "tx_uid"})
            )
            continue
        status = item.get("status")
        if status not in RESOLVE_STATUSES:
            results.append(
                _bulk_error(
                    index,
                    "status must be one of exported|inserted|rejected",
                    {"field": "status", "value": status},
                    tx_uid,
                )
            )
            continue
        if repo.get_tx(tx_uid) is None:
            results.append(
                _bulk_error(
                    index,
                    "Transaction not found",
                    {"tx_uid": tx_uid},
                    tx_uid,
                )
            )
            continue

        repo.update_mmex_status(tx_uid, str(status))
        tx = repo.get_tx(tx_uid)
        results.append(
            {
                "index": index,
                "tx_uid": tx_uid,
                "ok": True,
                "updated_fields": ["mmex_status"],
                "tx": _tx_to_dict(tx) if tx else None,
            }
        )

    _emit_bulk_result("bulk-resolve", results)


def _load_bulk_items(input_path: str) -> list[dict[str, object]]:
    path = Path(input_path)
    if not path.is_file():
        _validation_error("Bulk input file does not exist", {"input": input_path})
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        _validation_error(
            "Bulk input file must contain valid JSON",
            {"input": input_path, "exception_type": type(exc).__name__},
        )
    if not isinstance(raw, list):
        _validation_error("Bulk input must be a JSON array", {"input": input_path})
    if not raw:
        _validation_error(
            "Bulk input must contain at least one item",
            {"input": input_path},
        )

    items: list[dict[str, object]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            _validation_error(
                "Bulk input items must be JSON objects",
                {"input": input_path, "index": index},
            )
        items.append(cast(dict[str, object], item))
    return items


def _bulk_tx_uid(item: dict[str, object]) -> str | None:
    tx_uid = item.get("tx_uid")
    if not isinstance(tx_uid, str) or not tx_uid.strip():
        return None
    return tx_uid.strip()


def _bulk_update_fields(item: dict[str, object]) -> dict[str, object]:
    allowed = {
        "tx_uid",
        "owner",
        "category_guess",
        "subcategory_guess",
        "merchant_norm",
        "tags",
        "needs_review",
        "review_reason",
    }
    unknown = sorted(set(item) - allowed)
    if unknown:
        return {
            "error": {
                "message": "Unsupported bulk update fields",
                "unknown": unknown,
            }
        }

    fields: dict[str, object] = {}
    if "owner" in item:
        owner = item["owner"]
        if owner not in VALID_OWNERS:
            return {"error": {"message": "owner must be one of ricardo|laura|joint"}}
        fields["owner"] = owner
    for name in (
        "category_guess",
        "subcategory_guess",
        "merchant_norm",
        "review_reason",
    ):
        if name in item:
            value = item[name]
            if value is not None and not isinstance(value, str):
                return {"error": {"message": f"{name} must be string or null"}}
            fields[name] = value
    if "tags" in item:
        tags = _bulk_tags(item["tags"])
        if tags is None:
            return {"error": {"message": "tags must be string or array of strings"}}
        fields["tags_json"] = json.dumps(tags)
    if "needs_review" in item:
        needs_review = _bulk_bool(item["needs_review"])
        if needs_review is None:
            return {"error": {"message": "needs_review must be boolean"}}
        fields["needs_review"] = 1 if needs_review else 0
    if not fields:
        return {"error": {"message": "At least one updatable field must be provided"}}
    return {"fields": fields}


def _bulk_tags(value: object) -> list[str] | None:
    if isinstance(value, str):
        return _parse_tags(value)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [tag.strip() for tag in value if tag.strip()]
    return None


def _bulk_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _bulk_error(
    index: int,
    message: str,
    details: dict[str, object],
    tx_uid: str | None = None,
    *,
    code: str = "VALIDATION_ERROR",
) -> dict[str, object]:
    return {
        "index": index,
        "tx_uid": tx_uid,
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "details": {"index": index, **details},
        },
    }


def _emit_bulk_result(action: str, results: list[dict[str, object]]) -> NoReturn:
    errors = [result for result in results if result.get("ok") is False]
    data = {
        "action": action,
        "items_total": len(results),
        "items_ok": len(results) - len(errors),
        "items_error": len(errors),
        "results": results,
    }
    if errors:
        _emit(
            False,
            data=data,
            errors=[
                {
                    "code": "BULK_PARTIAL_FAILURE",
                    "message": "One or more bulk review items failed",
                    "details": {
                        "action": action,
                        "items_error": len(errors),
                    },
                }
            ],
            exit_code=2,
        )
    _emit(True, data=data)


def _run_reports_monthly(args: argparse.Namespace) -> NoReturn:
    _validate_staging_db(args.db)
    data = generate_monthly_dashboard(
        StagingRepo(args.db),
        month=args.month,
        reports_dir=args.reports_dir,
        output_path=args.output,
    )
    _emit(
        True,
        data={
            "message": "Monthly dashboard generated",
            **data,
        },
    )


def _run_reports_list(args: argparse.Namespace) -> NoReturn:
    data = list_monthly_dashboards(args.reports_dir)
    _emit(True, data=data)


def _run_reports_latest(args: argparse.Namespace) -> NoReturn:
    data = latest_monthly_dashboard(args.reports_dir)
    _emit(True, data=data)


def _run_notify_needs_review(args: argparse.Namespace) -> NoReturn:
    _validate_staging_db(args.db)
    if args.limit < 1:
        _validation_error("--limit must be greater than zero", {"field": "--limit"})
    repo = StagingRepo(args.db)
    txs = repo.list_txs(needs_review_only=True, limit=args.limit)
    report_path = _resolve_notify_report_path(
        report_path=args.report_path,
        reports_dir=args.reports_dir,
    )
    result = notify_needs_review(txs, report_path=report_path)
    _emit(
        True,
        data={
            "message": (
                "No needs_review transactions found"
                if result.needs_review_count == 0
                else "Needs-review notification prepared"
            ),
            **result.as_dict(),
        },
    )


def _resolve_notify_report_path(
    *,
    report_path: str | None,
    reports_dir: str,
) -> str | None:
    if report_path is not None:
        path = Path(report_path).expanduser().resolve(strict=False)
        return str(path) if path.is_file() else None
    latest = latest_monthly_dashboard(reports_dir)
    report = latest["report"]
    if isinstance(report, dict):
        resolved = report.get("report_path")
        return str(resolved) if resolved else None
    return None


def _run_quickadd_create(args: argparse.Namespace) -> NoReturn:
    _validate_staging_db(args.db)
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
            {"field": "--amount", "value": str(args.amount)[:30]},
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
    if tx.fitid_synthetic is None:
        _emit(
            False,
            errors=[
                {
                    "code": "TEMPORARY_FAILURE",
                    "message": "Failed to compute fitid_synthetic for the transaction",
                    "details": {},
                }
            ],
            exit_code=5,
        )

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
    if args.source == "mp":
        token = _read_secret_from_stdin_or_prompt("Mercado Pago access token: ")
        if not token:
            _emit(
                False,
                errors=[
                    {
                        "code": "CREDENTIALS_REQUIRED",
                        "message": (
                            "Mercado Pago access token must be provided via "
                            "stdin or secure prompt"
                        ),
                        "details": {
                            "source": args.source,
                            "input": "stdin_or_secure_prompt",
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
    elif args.source in {"be", "cmr"}:
        # For scrapers, login means running the headful browser to capture storage state
        from .adapters.be_scraping import BancoEstadoScraper
        from .adapters.cmr_scraping import CMRScraper

        scraper_cls = BancoEstadoScraper if args.source == "be" else CMRScraper
        scraper = scraper_cls()

        def login_action(page: Any, context: Any) -> bool:
            logged_in = scraper.wait_for_user_login(
                page, scraper.LOGIN_URL, scraper.DASHBOARD_INDICATOR
            )
            if not logged_in:
                raise ScrapingLoginError(
                    f"{args.source} login was not completed",
                    details={"source": args.source},
                )
            scraper.save_storage_state(context)
            return True

        scraper.run_headful(login_action)
        _emit(
            True,
            data={
                "message": f"Storage state captured for {args.source}",
                "source": args.source,
            },
        )
    else:
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


def _read_secret_from_stdin_or_prompt(prompt: str) -> str:
    if sys.stdin.isatty():
        return getpass.getpass(prompt).strip()
    return sys.stdin.readline().strip()


def _run_rules_list(args: argparse.Namespace) -> NoReturn:
    _validate_staging_db(args.db)
    repo = StagingRepo(args.db)
    rules = repo.list_rules(active_only=args.active_only)
    items = [
        {
            "rule_id": r.rule_id,
            "pattern": r.pattern,
            "pattern_type": r.pattern_type,
            "merchant_norm": r.merchant_norm,
            "category_name": r.category_name,
            "subcategory_name": r.subcategory_name,
            "tags": r.tags,
            "fuzzy_threshold": r.fuzzy_threshold,
            "priority": r.priority,
            "active": r.active,
        }
        for r in rules
    ]
    _emit(True, data={"items": items, "count": len(items)})


def _run_rules_add(args: argparse.Namespace) -> NoReturn:
    _validate_staging_db(args.db)
    repo = StagingRepo(args.db)
    rule_id = repo.add_rule(
        pattern=args.pattern,
        pattern_type=args.pattern_type,
        merchant_norm=args.merchant_norm,
        category_name=args.category_name,
        subcategory_name=args.subcategory_name or None,
        tags=_parse_tags(args.tags),
        fuzzy_threshold=args.fuzzy_threshold,
        priority=args.priority,
    )
    _emit(True, data={"rule_id": rule_id, "created": True})


def _run_rules_update(args: argparse.Namespace) -> NoReturn:
    _validate_staging_db(args.db)
    fields: dict[str, object] = {}
    for key, arg_key in [
        ("pattern", "pattern"),
        ("pattern_type", "pattern_type"),
        ("merchant_norm", "merchant_norm"),
        ("category_name", "category_name"),
        ("subcategory_name", "subcategory_name"),
        ("fuzzy_threshold", "fuzzy_threshold"),
        ("priority", "priority"),
    ]:
        val = getattr(args, arg_key, None)
        if val is not None:
            fields[key] = val
    if args.tags is not None:
        fields["tags_json"] = json.dumps(_parse_tags(args.tags))
    if args.active is not None:
        fields["active"] = int(args.active)
    if not fields:
        _validation_error("At least one field must be provided")
    repo = StagingRepo(args.db)
    ok = repo.update_rule(args.rule_id, **fields)
    if not ok:
        _emit(
            False,
            errors=[{
                "code": "VALIDATION_ERROR",
                "message": "Rule not found",
                "details": {"rule_id": args.rule_id},
            }],
            exit_code=2,
        )
    _emit(True, data={"rule_id": args.rule_id, "updated_fields": sorted(fields)})


def _run_rules_delete(args: argparse.Namespace) -> NoReturn:
    _validate_staging_db(args.db)
    repo = StagingRepo(args.db)
    ok = repo.delete_rule(args.rule_id)
    if not ok:
        _emit(
            False,
            errors=[{
                "code": "VALIDATION_ERROR",
                "message": "Rule not found",
                "details": {"rule_id": args.rule_id},
            }],
            exit_code=2,
        )
    _emit(True, data={"rule_id": args.rule_id, "deleted": True})


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
    init_parser.add_argument(
        "--db", default=DEFAULT_STAGING_DB, help="Path to staging.db"
    )
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
            "Path to email file or directory for offline Gmail ingestion"
        ),
    )
    run_parser.add_argument(
        "--gmail-source",
        choices=["be", "cmr", "mach"],
        default="be",
        help="Gmail sub-source: be (BancoEstado), cmr, mach (default: be)",
    )
    run_parser.add_argument(
        "--begin-date",
        default=None,
        help="ISO date YYYY-MM-DD for MP online search start (default: 7 days ago)",
    )
    run_parser.add_argument(
        "--end-date",
        default=None,
        help="ISO date YYYY-MM-DD for MP online search end (default: today)",
    )
    run_parser.add_argument(
        "--db", default=DEFAULT_STAGING_DB, help="Path to staging.db"
    )
    run_parser.add_argument(
        "--schema",
        default="src/finanzasmmex/staging/schema.sql",
        help="Path to schema.sql",
    )
    run_parser.add_argument(
        "--ofx-output",
        default=DEFAULT_OFX_OUTPUT,
        help="Path to write the OFX file",
    )
    run_parser.add_argument(
        "--report-output",
        default=DEFAULT_REPORT_OUTPUT,
        help="Path to write the HTML review report",
    )
    run_parser.add_argument(
        "--mmex-db",
        help="Path to the test/shadow .mmb database for --writer sql",
    )
    run_parser.add_argument(
        "--backup-dir",
        default=DEFAULT_BACKUP_DIR,
        help="Directory for SQL writer pre/post backups",
    )
    run_parser.add_argument(
        "--allow-shadow-write",
        action="store_true",
        help="Required to enable SQL writes to a test/shadow .mmb",
    )

    # login command
    login_parser = subparsers.add_parser(
        "login",
        help="Store credentials for a source in the Windows Credential Manager",
    )
    login_parser.add_argument(
        "--source",
        choices=["mp", "be", "cmr"],
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
        "--db", default=DEFAULT_STAGING_DB, help="Path to staging.db"
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
        "--source-type", default=None, help="Filter by source type"
    )
    review_list_parser.add_argument(
        "--category", default=None, help="Filter by category_guess"
    )
    review_list_parser.add_argument(
        "--merchant",
        default=None,
        help="Filter by merchant_norm or merchant_raw substring",
    )
    review_list_parser.add_argument(
        "--limit", type=int, default=200, help="Max rows to return (default 200)"
    )

    review_update_parser = review_sub.add_parser(
        "update", help="Update reviewable fields on a transaction"
    )
    review_update_parser.add_argument("--db", default=DEFAULT_STAGING_DB)
    review_update_parser.add_argument("--tx-uid", required=True, help="Target tx_uid")
    review_update_parser.add_argument("--owner", default=None)
    review_update_parser.add_argument("--category-guess", default=None)
    review_update_parser.add_argument("--subcategory-guess", default=None)
    review_update_parser.add_argument("--merchant-norm", default=None)
    review_update_parser.add_argument(
        "--tags", default=None, help="Comma-separated list of tags (overwrites)"
    )
    review_update_parser.add_argument("--needs-review", default=None, help="true/false")
    review_update_parser.add_argument("--review-reason", default=None)

    review_resolve_parser = review_sub.add_parser(
        "resolve", help="Set the mmex_status of a transaction"
    )
    review_resolve_parser.add_argument("--db", default=DEFAULT_STAGING_DB)
    review_resolve_parser.add_argument("--tx-uid", required=True)
    review_resolve_parser.add_argument(
        "--status",
        required=True,
        choices=sorted(RESOLVE_STATUSES),
        help="Target mmex_status",
    )

    review_bulk_update_parser = review_sub.add_parser(
        "bulk-update", help="Update reviewable fields for a JSON batch"
    )
    review_bulk_update_parser.add_argument("--db", default=DEFAULT_STAGING_DB)
    review_bulk_update_parser.add_argument(
        "--input",
        required=True,
        help="JSON file with an array of update items",
    )

    review_bulk_resolve_parser = review_sub.add_parser(
        "bulk-resolve", help="Resolve mmex_status for a JSON batch"
    )
    review_bulk_resolve_parser.add_argument("--db", default=DEFAULT_STAGING_DB)
    review_bulk_resolve_parser.add_argument(
        "--input",
        required=True,
        help="JSON file with an array of resolve items",
    )

    # reports command (monthly/list/latest)
    reports_parser = subparsers.add_parser(
        "reports",
        help="Generate and list local HTML dashboards",
    )
    reports_sub = reports_parser.add_subparsers(
        dest="reports_action",
        required=True,
        parser_class=ContractArgumentParser,
    )

    reports_monthly_parser = reports_sub.add_parser(
        "monthly", help="Generate dashboard_YYYY-MM.html from staging"
    )
    reports_monthly_parser.add_argument("--db", default=DEFAULT_STAGING_DB)
    reports_monthly_parser.add_argument(
        "--month",
        required=True,
        help="Month to report in YYYY-MM format",
    )
    reports_monthly_parser.add_argument(
        "--reports-dir",
        default=DEFAULT_REPORTS_DIR,
        help="Directory for local HTML dashboards",
    )
    reports_monthly_parser.add_argument(
        "--output",
        default=None,
        help="Optional HTML filename/path under --reports-dir",
    )

    reports_list_parser = reports_sub.add_parser(
        "list", help="List generated monthly dashboards"
    )
    reports_list_parser.add_argument(
        "--reports-dir",
        default=DEFAULT_REPORTS_DIR,
        help="Directory for local HTML dashboards",
    )

    reports_latest_parser = reports_sub.add_parser(
        "latest", help="Return the newest generated monthly dashboard"
    )
    reports_latest_parser.add_argument(
        "--reports-dir",
        default=DEFAULT_REPORTS_DIR,
        help="Directory for local HTML dashboards",
    )

    # notify command (needs-review)
    notify_parser = subparsers.add_parser(
        "notify",
        help="Send optional local notifications",
    )
    notify_sub = notify_parser.add_subparsers(
        dest="notify_action",
        required=True,
        parser_class=ContractArgumentParser,
    )

    notify_needs_review_parser = notify_sub.add_parser(
        "needs-review",
        help="Notify when staging has needs_review transactions",
    )
    notify_needs_review_parser.add_argument("--db", default=DEFAULT_STAGING_DB)
    notify_needs_review_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compatibility flag; this command is always local-only",
    )
    notify_needs_review_parser.add_argument(
        "--reports-dir",
        default=DEFAULT_REPORTS_DIR,
        help="Directory used to discover latest monthly dashboard",
    )
    notify_needs_review_parser.add_argument(
        "--report-path",
        default=None,
        help="Optional existing HTML report path to include in payload",
    )
    notify_needs_review_parser.add_argument(
        "--limit",
        type=int,
        default=10_000,
        help="Maximum needs_review rows to summarize",
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
    quickadd_create_parser.add_argument("--db", default=DEFAULT_STAGING_DB)
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

    # category-rules command
    rules_parser = subparsers.add_parser(
        "category-rules",
        help="Manage categorization rules",
    )
    rules_sub = rules_parser.add_subparsers(
        dest="rules_action",
        required=True,
        parser_class=ContractArgumentParser,
    )

    rules_list_parser = rules_sub.add_parser("list", help="List categorization rules")
    rules_list_parser.add_argument("--db", default=DEFAULT_STAGING_DB)
    rules_list_parser.add_argument(
        "--active-only", action="store_true", help="Only show active rules"
    )

    rules_add_parser = rules_sub.add_parser("add", help="Add a categorization rule")
    rules_add_parser.add_argument("--db", default=DEFAULT_STAGING_DB)
    rules_add_parser.add_argument("--pattern", required=True, help="Search pattern")
    rules_add_parser.add_argument(
        "--pattern-type",
        required=True,
        choices=["substr", "regex", "fuzzy"],
        help="Pattern matching type",
    )
    rules_add_parser.add_argument(
        "--merchant-norm", required=True, help="Normalized merchant name"
    )
    rules_add_parser.add_argument("--category-name", required=True, help="Category")
    rules_add_parser.add_argument(
        "--subcategory-name", default=None, help="Subcategory name"
    )
    rules_add_parser.add_argument("--tags", default=None, help="Comma-separated tags")
    rules_add_parser.add_argument(
        "--fuzzy-threshold", type=int, default=85, help="Fuzzy threshold 0-100"
    )
    rules_add_parser.add_argument(
        "--priority", type=int, default=100, help="Rule priority (lower = wins)"
    )

    rules_update_parser = rules_sub.add_parser(
        "update", help="Update a categorization rule"
    )
    rules_update_parser.add_argument("--db", default=DEFAULT_STAGING_DB)
    rules_update_parser.add_argument("--rule-id", type=int, required=True)
    rules_update_parser.add_argument("--pattern", default=None)
    rules_update_parser.add_argument(
        "--pattern-type", choices=["substr", "regex", "fuzzy"], default=None
    )
    rules_update_parser.add_argument("--merchant-norm", default=None)
    rules_update_parser.add_argument("--category-name", default=None)
    rules_update_parser.add_argument("--subcategory-name", default=None)
    rules_update_parser.add_argument("--tags", default=None)
    rules_update_parser.add_argument("--fuzzy-threshold", type=int, default=None)
    rules_update_parser.add_argument("--priority", type=int, default=None)
    rules_update_parser.add_argument(
        "--active",
        default=None,
        choices=["0", "1"],
        help="Set to 0 to deactivate, 1 to activate",
    )

    rules_delete_parser = rules_sub.add_parser(
        "delete", help="Delete a categorization rule"
    )
    rules_delete_parser.add_argument("--db", default=DEFAULT_STAGING_DB)
    rules_delete_parser.add_argument("--rule-id", type=int, required=True)

    help_parsers: dict[tuple[str, ...], argparse.ArgumentParser] = {
        ("init",): init_parser,
        ("run",): run_parser,
        ("login",): login_parser,
        ("review",): review_parser,
        ("review", "list"): review_list_parser,
        ("review", "update"): review_update_parser,
        ("review", "resolve"): review_resolve_parser,
        ("review", "bulk-update"): review_bulk_update_parser,
        ("review", "bulk-resolve"): review_bulk_resolve_parser,
        ("reports",): reports_parser,
        ("reports", "monthly"): reports_monthly_parser,
        ("reports", "list"): reports_list_parser,
        ("reports", "latest"): reports_latest_parser,
        ("notify",): notify_parser,
        ("notify", "needs-review"): notify_needs_review_parser,
        ("quickadd",): quickadd_parser,
        ("quickadd", "create"): quickadd_create_parser,
        ("category-rules",): rules_parser,
        ("category-rules", "list"): rules_list_parser,
        ("category-rules", "add"): rules_add_parser,
        ("category-rules", "update"): rules_update_parser,
        ("category-rules", "delete"): rules_delete_parser,
    }

    try:
        if argv in (["-h"], ["--help"]):
            _emit(True, data={"help": parser.format_help()})
        if len(argv) >= 2 and argv[-1] in ("-h", "--help"):
            key = tuple(argv[:-1])
            if key in help_parsers:
                _emit(True, data={"help": help_parsers[key].format_help()})

        args = parser.parse_args(argv)

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
                _run_sql(args)
            else:
                if args.source not in {
                    "gmail", "mp", "all", "scraping-be", "scraping-cmr", "drop"
                }:
                    _emit(
                        False,
                        errors=[
                            {
                                "code": "VALIDATION_ERROR",
                                "message": (
                                    "Only gmail, mp, all, and scraping sources "
                                    "are implemented"
                                ),
                                "details": {"source": args.source},
                            }
                        ],
                        exit_code=2,
                    )

                if args.source == "gmail":
                    _run_gmail(args)
                elif args.source == "all":
                    _run_gmail_all(args)
                elif args.source == "scraping-be":
                    result = run_scraping_be(
                        db_path=args.db,
                        schema_path=args.schema,
                        ofx_output_path=args.ofx_output,
                        report_output_path=args.report_output,
                    )
                    _emit(True, data=result.as_dict())
                elif args.source == "scraping-cmr":
                    result = run_scraping_cmr(
                        db_path=args.db,
                        schema_path=args.schema,
                        ofx_output_path=args.ofx_output,
                        report_output_path=args.report_output,
                    )
                    _emit(True, data=result.as_dict())
                elif args.source == "drop":
                    _run_drop(args)
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
            elif args.review_action == "bulk-update":
                _run_review_bulk_update(args)
            elif args.review_action == "bulk-resolve":
                _run_review_bulk_resolve(args)
        elif args.command == "reports":
            if args.reports_action == "monthly":
                _run_reports_monthly(args)
            elif args.reports_action == "list":
                _run_reports_list(args)
            elif args.reports_action == "latest":
                _run_reports_latest(args)
        elif args.command == "notify":
            if args.notify_action == "needs-review":
                _run_notify_needs_review(args)
        elif args.command == "quickadd":
            if args.quickadd_action == "create":
                _run_quickadd_create(args)
        elif args.command == "category-rules":
            if args.rules_action == "list":
                _run_rules_list(args)
            elif args.rules_action == "add":
                _run_rules_add(args)
            elif args.rules_action == "update":
                _run_rules_update(args)
            elif args.rules_action == "delete":
                _run_rules_delete(args)
    except ScrapingLoginError as e:
        _emit(
            False,
            errors=[
                {
                    "code": e.error_code,
                    "message": str(e),
                    "details": e.details,
                }
            ],
            exit_code=e.exit_code,
        )
    except ScrapingError as e:
        _emit(
            False,
            errors=[
                {
                    "code": e.error_code,
                    "message": str(e),
                    "details": e.details,
                }
            ],
            exit_code=e.exit_code,
        )
    except FileLoaderError as e:
        _emit(
            False,
            errors=[
                {
                    "code": e.error_code,
                    "message": str(e),
                    "details": e.details,
                }
            ],
            exit_code=e.exit_code,
        )
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
