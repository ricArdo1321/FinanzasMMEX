import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Any, Literal, Mapping

from ..adapters.mp_api import MercadoPagoClient, MercadoPagoParseError, parse_payment
from ..adapters.scraping_base import ScrapingResult
from ..artifacts import safe_output_path
from ..etl.merge import merge_scraped_txs
from ..etl.pipeline import prepare_batch_for_staging
from ..models import CanonicalTx
from ..staging.repo import StagingRepo
from ..writer.mmex_sql import SqlWriteSummary, write_sql
from ..writer.ofx_export import write_ofx


@dataclass(frozen=True)
class RunSummary:
    items_processed: int
    items_inserted: int
    items_review: int
    db_path: str
    ofx_path: str
    report_path: str
    reconcile_status: str | None = None
    reconcile_delta: str | None = None

    def as_dict(self) -> dict[str, int | str | None]:
        return {
            "items_processed": self.items_processed,
            "items_inserted": self.items_inserted,
            "items_review": self.items_review,
            "db_path": self.db_path,
            "ofx_path": self.ofx_path,
            "report_path": self.report_path,
            "reconcile_status": self.reconcile_status,
            "reconcile_delta": self.reconcile_delta,
        }


@dataclass(frozen=True)
class SqlRunSummary:
    items_processed: int
    items_inserted: int
    items_review: int
    items_skipped_duplicate: int
    items_rejected_unsupported: int
    db_path: str
    mmex_path: str
    backup_pre_path: str | None
    backup_post_path: str | None
    mmex_tx_ids: dict[str, int]
    mmex_account_ids: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "items_processed": self.items_processed,
            "items_inserted": self.items_inserted,
            "items_review": self.items_review,
            "items_skipped_duplicate": self.items_skipped_duplicate,
            "items_rejected_unsupported": self.items_rejected_unsupported,
            "db_path": self.db_path,
            "mmex_path": self.mmex_path,
            "backup_pre_path": self.backup_pre_path,
            "backup_post_path": self.backup_post_path,
            "mmex_tx_ids": self.mmex_tx_ids,
            "mmex_account_ids": self.mmex_account_ids,
        }


def run_pending_to_sql(
    *,
    db_path: str,
    mmex_db_path: str,
    backup_dir: str,
    allow_shadow_write: bool,
) -> SqlRunSummary:
    repo = StagingRepo(db_path)
    transactions = repo.list_txs(mmex_status="pending", limit=10_000)
    summary = write_sql(
        transactions,
        mmex_db_path=mmex_db_path,
        backup_dir=backup_dir,
        allow_shadow_write=allow_shadow_write,
        # Hard rule: a batch with any account in reconcile_log.status='off'
        # must block the writer. Pass the repo so write_sql can enforce it.
        staging_repo=repo,
    )
    _mark_inserted(repo, summary)
    return SqlRunSummary(
        items_processed=summary.items_considered,
        items_inserted=summary.items_inserted,
        items_review=summary.items_rejected_review,
        items_skipped_duplicate=summary.items_skipped_duplicate,
        items_rejected_unsupported=summary.items_rejected_unsupported,
        db_path=db_path,
        mmex_path=summary.mmex_path,
        backup_pre_path=summary.backup_pre_path,
        backup_post_path=summary.backup_post_path,
        mmex_tx_ids=summary.mmex_tx_ids,
        mmex_account_ids=summary.mmex_account_ids,
    )


def run_scraping_be(
    *,
    db_path: str,
    schema_path: str,
    ofx_output_path: str,
    report_output_path: str,
    since_days: int = 7,
) -> RunSummary:
    from ..adapters.be_scraping import BancoEstadoScraper

    repo = StagingRepo(db_path)
    _ensure_db(repo, Path(db_path), schema_path)

    scraper = BancoEstadoScraper()
    since_date = date.today() - timedelta(days=since_days)
    scrape_result = _coerce_scraping_result(scraper.scrape(since_date), since_date)
    scraped_txs = scrape_result.transactions

    if not scraped_txs:
        return RunSummary(0, 0, 0, db_path, ofx_output_path, report_output_path)

    rules = repo.list_rules(active_only=True)
    prepared_txs = prepare_batch_for_staging(scraped_txs, rules=rules)
    merged_txs = merge_scraped_txs(repo, prepared_txs)

    # Upsert results
    repo.upsert_batch(merged_txs)
    reconcile_status, reconcile_delta = _record_scraping_reconcile(
        repo, merged_txs, scrape_result
    )
    if reconcile_status == "off":
        raise ValueError("Cannot export OFX while reconcile status is off")

    ofx_path = write_ofx(merged_txs, ofx_output_path)
    report_path = write_review_report(merged_txs, report_output_path)

    return RunSummary(
        items_processed=len(scraped_txs),
        items_inserted=len(merged_txs),
        items_review=sum(1 for tx in merged_txs if tx.needs_review),
        db_path=db_path,
        ofx_path=str(ofx_path),
        report_path=str(report_path),
        reconcile_status=reconcile_status,
        reconcile_delta=str(reconcile_delta) if reconcile_delta is not None else None,
    )


def run_scraping_cmr(
    *,
    db_path: str,
    schema_path: str,
    ofx_output_path: str,
    report_output_path: str,
    since_days: int = 7,
) -> RunSummary:
    from ..adapters.cmr_scraping import CMRScraper

    repo = StagingRepo(db_path)
    _ensure_db(repo, Path(db_path), schema_path)

    scraper = CMRScraper()
    since_date = date.today() - timedelta(days=since_days)
    scrape_result = _coerce_scraping_result(scraper.scrape(since_date), since_date)
    scraped_txs = scrape_result.transactions

    if not scraped_txs:
        return RunSummary(0, 0, 0, db_path, ofx_output_path, report_output_path)

    rules = repo.list_rules(active_only=True)
    prepared_txs = prepare_batch_for_staging(scraped_txs, rules=rules)
    merged_txs = merge_scraped_txs(repo, prepared_txs)

    # Upsert results
    repo.upsert_batch(merged_txs)
    reconcile_status, reconcile_delta = _record_scraping_reconcile(
        repo, merged_txs, scrape_result
    )
    if reconcile_status == "off":
        raise ValueError("Cannot export OFX while reconcile status is off")

    ofx_path = write_ofx(merged_txs, ofx_output_path)
    report_path = write_review_report(merged_txs, report_output_path)

    return RunSummary(
        items_processed=len(scraped_txs),
        items_inserted=len(merged_txs),
        items_review=sum(1 for tx in merged_txs if tx.needs_review),
        db_path=db_path,
        ofx_path=str(ofx_path),
        report_path=str(report_path),
        reconcile_status=reconcile_status,
        reconcile_delta=str(reconcile_delta) if reconcile_delta is not None else None,
    )


def _coerce_scraping_result(
    result: ScrapingResult | list[CanonicalTx],
    since_date: date,
) -> ScrapingResult:
    if isinstance(result, ScrapingResult):
        return result
    return ScrapingResult(
        transactions=list(result),
        period_start=since_date,
        period_end=date.today(),
        balances={},
    )


def _record_scraping_reconcile(
    repo: StagingRepo,
    transactions: list[CanonicalTx],
    result: ScrapingResult,
) -> tuple[str | None, Decimal | None]:
    if not transactions:
        return None, None

    period_start = result.period_start or min(_tx_date(tx) for tx in transactions)
    period_end = result.period_end or max(_tx_date(tx) for tx in transactions)
    statuses: list[str] = []
    deltas: list[Decimal] = []

    for account_alias in sorted({tx.account_alias for tx in transactions}):
        account_txs = [tx for tx in transactions if tx.account_alias == account_alias]
        sum_credits = sum(
            (tx.amount for tx in account_txs if tx.direction == "credit"),
            Decimal("0.00"),
        )
        sum_debits = sum(
            (tx.amount for tx in account_txs if tx.direction == "debit"),
            Decimal("0.00"),
        )

        balances = result.balances.get(account_alias)
        if balances is None:
            status = "manual_review"
            balance_initial = Decimal("0.00")
            balance_final = Decimal("0.00")
            expected_final = Decimal("0.00")
            delta = Decimal("0.00")
            notes = "Scraping source did not provide balances"
        else:
            balance_initial, balance_final = balances
            expected_final = balance_initial + sum_credits - sum_debits
            delta = balance_final - expected_final
            status = _reconcile_status(delta)
            notes = None

        repo.insert_reconcile_log(
            account_alias=account_alias,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            balance_initial=balance_initial,
            balance_final=balance_final,
            sum_credits=sum_credits,
            sum_debits=sum_debits,
            expected_final=expected_final,
            status=status,
            delta=delta,
            notes=notes,
        )
        statuses.append(status)
        deltas.append(delta)

    return _overall_reconcile_status(statuses), max(deltas, key=lambda d: abs(d))


def _tx_date(tx: CanonicalTx) -> date:
    tx_date = tx.posted_date or tx.booking_date or tx.event_date
    if tx_date is None:
        raise ValueError("Cannot reconcile scraping transaction without a date")
    return tx_date


def _reconcile_status(delta: Decimal) -> str:
    if delta == Decimal("0.00"):
        return "ok"
    if abs(delta) <= Decimal("100.00"):
        return "minor"
    return "off"


def _overall_reconcile_status(statuses: list[str]) -> str:
    for status in ("off", "manual_review", "minor", "ok"):
        if status in statuses:
            return status
    return "manual_review"


def run_gmail_bancoestado_to_ofx(
    *,
    input_path: str,
    db_path: str,
    schema_path: str,
    ofx_output_path: str,
    report_output_path: str,
) -> RunSummary:
    from ..adapters.be_email import parse_purchase_email

    return _run_email_job(
        input_path=input_path,
        db_path=db_path,
        schema_path=schema_path,
        ofx_output_path=ofx_output_path,
        report_output_path=report_output_path,
        parser_fn=parse_purchase_email,
        parser_source_name="BancoEstado",
    )


def run_gmail_cmr_to_ofx(
    *,
    input_path: str,
    db_path: str,
    schema_path: str,
    ofx_output_path: str,
    report_output_path: str,
) -> RunSummary:
    from ..adapters.cmr_email import parse_purchase_email as parse_cmr

    return _run_email_job(
        input_path=input_path,
        db_path=db_path,
        schema_path=schema_path,
        ofx_output_path=ofx_output_path,
        report_output_path=report_output_path,
        parser_fn=parse_cmr,
        parser_source_name="CMR",
    )


def run_gmail_mach_to_ofx(
    *,
    input_path: str,
    db_path: str,
    schema_path: str,
    ofx_output_path: str,
    report_output_path: str,
) -> RunSummary:
    from ..adapters.mach_email import parse_purchase_email as parse_mach

    return _run_email_job(
        input_path=input_path,
        db_path=db_path,
        schema_path=schema_path,
        ofx_output_path=ofx_output_path,
        report_output_path=report_output_path,
        parser_fn=parse_mach,
        parser_source_name="Mach",
    )


def run_gmail_all_to_ofx(
    *,
    input_path: str,
    db_path: str,
    schema_path: str,
    ofx_output_path: str,
    report_output_path: str,
) -> RunSummary:
    from ..adapters.be_email import parse_purchase_email as parse_be
    from ..adapters.cmr_email import parse_purchase_email as parse_cmr
    from ..adapters.mach_email import parse_purchase_email as parse_mach
    from ..etl.pipeline import prepare_batch_for_staging

    repo = StagingRepo(db_path)
    _ensure_db(repo, Path(db_path), schema_path)

    base = Path(input_path)
    sources: list[tuple[Callable[..., CanonicalTx], str, Path]] = [
        (parse_be, "BancoEstado", base),
        (parse_cmr, "CMR", base / "cmr"),
        (parse_mach, "Mach", base / "mach"),
    ]

    parsed_items: list[CanonicalTx] = []
    for parser_fn, _name, source_path in sources:
        if not source_path.is_dir():
            continue
        files = _collect_email_files(source_path)
        if not files:
            continue
        for file_path in files:
            raw_text = file_path.read_text(encoding="utf-8")
            try:
                parsed = parser_fn(raw_text, source_file=str(file_path))
                parsed_items.append(parsed)
            except ValueError:
                continue

    if not parsed_items:
        raise ValueError("No email input files found for any Gmail source")

    # Load rules from DB
    rules = repo.list_rules(active_only=True)
    all_transactions = prepare_batch_for_staging(parsed_items, rules=rules)

    repo.upsert_batch(all_transactions)

    if repo.has_reconcile_off({tx.account_alias for tx in all_transactions}):
        raise ValueError("Cannot export OFX while reconcile status is off")

    ofx_path = write_ofx(all_transactions, ofx_output_path)
    report_path = write_review_report(all_transactions, report_output_path)

    return RunSummary(
        items_processed=len(all_transactions),
        items_inserted=len(all_transactions),
        items_review=sum(1 for tx in all_transactions if tx.needs_review),
        db_path=db_path,
        ofx_path=str(ofx_path),
        report_path=str(report_path),
    )


def _run_email_job(
    *,
    input_path: str,
    db_path: str,
    schema_path: str,
    ofx_output_path: str,
    report_output_path: str,
    parser_fn: Callable[..., CanonicalTx],
    parser_source_name: str,
) -> RunSummary:
    from ..etl.pipeline import prepare_batch_for_staging

    files = _collect_email_files(Path(input_path))
    if not files:
        raise ValueError(f"No {parser_source_name} email input files found")

    repo = StagingRepo(db_path)
    _ensure_db(repo, Path(db_path), schema_path)

    parsed_items: list[CanonicalTx] = []
    for file_path in files:
        raw_text = file_path.read_text(encoding="utf-8")
        try:
            parsed = parser_fn(raw_text, source_file=str(file_path))
            parsed_items.append(parsed)
        except ValueError:
            continue

    if not parsed_items:
        raise ValueError(f"No valid {parser_source_name} email input files found")

    # Load rules from DB
    rules = repo.list_rules(active_only=True)
    transactions = prepare_batch_for_staging(parsed_items, rules=rules)

    repo.upsert_batch(transactions)

    if repo.has_reconcile_off({tx.account_alias for tx in transactions}):
        raise ValueError("Cannot export OFX while reconcile status is off")

    ofx_path = write_ofx(transactions, ofx_output_path)
    report_path = write_review_report(transactions, report_output_path)

    return RunSummary(
        items_processed=len(transactions),
        items_inserted=len(transactions),
        items_review=sum(1 for tx in transactions if tx.needs_review),
        db_path=db_path,
        ofx_path=str(ofx_path),
        report_path=str(report_path),
    )


def run_mp_online(
    *,
    access_token: str,
    begin_date: str,
    end_date: str,
    db_path: str,
    schema_path: str,
    ofx_output_path: str,
    report_output_path: str,
    owner: Literal["ricardo", "laura", "joint"] = "ricardo",
    page_size: int = 50,
) -> RunSummary:
    from ..etl.pipeline import prepare_batch_for_staging

    repo = StagingRepo(db_path)
    _ensure_db(repo, Path(db_path), schema_path)

    payments: list[Mapping[str, Any]]
    with MercadoPagoClient(access_token=access_token) as client:
        payments = list(
            client.search_payments(
                begin_date=begin_date,
                end_date=end_date,
                status="approved",
                page_size=page_size,
            )
        )

    parsed_items: list[CanonicalTx] = []
    for payment in payments:
        try:
            parsed = parse_payment(payment, owner=owner)
            parsed_items.append(parsed)
        except ValueError as exc:
            ref = str(
                payment.get("id")
                or payment.get("external_reference")
                or "<unknown>"
            )
            raise MercadoPagoParseError(
                f"Approved Mercado Pago payment could not be parsed: {ref}"
            ) from exc

    if not parsed_items:
        raise ValueError("No approved Mercado Pago payments found in date range")

    # Load rules from DB
    rules = repo.list_rules(active_only=True)
    transactions = prepare_batch_for_staging(parsed_items, rules=rules)

    if repo.has_reconcile_off({tx.account_alias for tx in transactions}):
        raise ValueError("Cannot export OFX while reconcile status is off")

    for tx in transactions:
        repo.upsert_tx(tx)

    ofx_path = write_ofx(transactions, ofx_output_path)
    report_path = write_review_report(transactions, report_output_path)

    return RunSummary(
        items_processed=len(transactions),
        items_inserted=len(transactions),
        items_review=sum(1 for tx in transactions if tx.needs_review),
        db_path=db_path,
        ofx_path=str(ofx_path),
        report_path=str(report_path),
    )


def run_mp_to_ofx(
    *,
    input_path: str,
    db_path: str,
    schema_path: str,
    ofx_output_path: str,
    report_output_path: str,
    owner: Literal["ricardo", "laura", "joint"] = "ricardo",
) -> RunSummary:
    from ..etl.pipeline import prepare_batch_for_staging

    payloads = _load_mp_payloads(Path(input_path))
    if not payloads:
        raise ValueError("No Mercado Pago payments found in input")

    repo = StagingRepo(db_path)
    _ensure_db(repo, Path(db_path), schema_path)

    parsed_items: list[CanonicalTx] = []
    for payload, raw_text in payloads:
        parsed = parse_payment(
            payload,
            source_file=str(input_path),
            raw_text=raw_text,
            owner=owner,
        )
        parsed_items.append(parsed)

    # Load rules from DB
    rules = repo.list_rules(active_only=True)
    transactions = prepare_batch_for_staging(parsed_items, rules=rules)

    repo.upsert_batch(transactions)

    if repo.has_reconcile_off({tx.account_alias for tx in transactions}):
        raise ValueError("Cannot export OFX while reconcile status is off")

    ofx_path = write_ofx(transactions, ofx_output_path)
    report_path = write_review_report(transactions, report_output_path)

    return RunSummary(
        items_processed=len(transactions),
        items_inserted=len(transactions),
        items_review=sum(1 for tx in transactions if tx.needs_review),
        db_path=db_path,
        ofx_path=str(ofx_path),
        report_path=str(report_path),
    )


def _load_mp_payloads(input_path: Path) -> list[tuple[Mapping[str, Any], str]]:
    if input_path.is_file():
        return _payloads_from_file(input_path)
    if input_path.is_dir():
        files = sorted(
            p for p in input_path.iterdir() if p.is_file() and p.suffix == ".json"
        )
        out: list[tuple[Mapping[str, Any], str]] = []
        for f in files:
            out.extend(_payloads_from_file(f))
        return out
    raise ValueError(f"Input path does not exist: {input_path}")


def _payloads_from_file(file_path: Path) -> list[tuple[Mapping[str, Any], str]]:
    raw = file_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if isinstance(data, list):
        return [(_require_mapping(item, file_path), raw) for item in data]
    if isinstance(data, dict):
        if isinstance(data.get("results"), list):
            return [
                (_require_mapping(item, file_path), raw)
                for item in data["results"]
            ]
        return [(data, raw)]
    raise ValueError(f"Unexpected MP payload shape in {file_path}")


def _require_mapping(item: Any, file_path: Path) -> Mapping[str, Any]:
    if not isinstance(item, Mapping):
        raise ValueError(f"Expected MP payload to be an object in {file_path}")
    return item


def write_review_report(
    transactions: list[CanonicalTx],
    output_path: str | Path,
) -> Path:
    path = safe_output_path(output_path, allowed_suffixes={".html", ".htm"})
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = "\n".join(_report_row(tx) for tx in transactions)
    html = f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>FinanzasMMEX Review</title>
</head>
<body>
  <h1>FinanzasMMEX Review</h1>
  <table>
    <thead>
      <tr>
        <th>Fecha</th>
        <th>Cuenta</th>
        <th>Comercio</th>
        <th>Monto</th>
        <th>Estado</th>
      </tr>
    </thead>
    <tbody>
{rows}
    </tbody>
  </table>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")
    return path


def _collect_email_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        candidates = [
            path
            for path in input_path.iterdir()
            if path.is_file() and path.suffix.lower() in {".txt", ".eml"}
        ]
        return sorted(candidates)
    raise ValueError(f"Input path does not exist: {input_path}")


def _ensure_db(repo: StagingRepo, db_path: Path, schema_path: str) -> None:
    if db_path.exists():
        return
    repo.init_db(schema_path)


def _mark_inserted(
    repo: StagingRepo,
    summary: SqlWriteSummary,
) -> None:
    for tx_uid, mmex_tx_id in summary.mmex_tx_ids.items():
        mmex_account_id = summary.mmex_account_ids[tx_uid]
        repo.mark_inserted(
            tx_uid,
            mmex_account_id=mmex_account_id,
            mmex_tx_id=mmex_tx_id,
        )


def _report_row(tx: CanonicalTx) -> str:
    tx_date = tx.posted_date or tx.event_date or tx.booking_date
    status = "needs_review" if tx.needs_review else tx.mmex_status
    merchant = tx.merchant_norm or tx.merchant_raw
    return (
        "      <tr>"
        f"<td>{escape(tx_date.isoformat() if tx_date else '')}</td>"
        f"<td>{escape(tx.account_alias)}</td>"
        f"<td>{escape(merchant)}</td>"
        f"<td>{escape(str(tx.amount))}</td>"
        f"<td>{escape(status)}</td>"
        "</tr>"
    )
