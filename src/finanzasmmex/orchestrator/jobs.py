from dataclasses import dataclass
from html import escape
from pathlib import Path

from ..adapters.be_email import parse_purchase_email
from ..artifacts import safe_output_path
from ..etl.pipeline import prepare_for_staging
from ..models import CanonicalTx
from ..staging.repo import StagingRepo
from ..writer.ofx_export import write_ofx


@dataclass(frozen=True)
class RunSummary:
    items_processed: int
    items_inserted: int
    items_review: int
    db_path: str
    ofx_path: str
    report_path: str

    def as_dict(self) -> dict[str, int | str]:
        return {
            "items_processed": self.items_processed,
            "items_inserted": self.items_inserted,
            "items_review": self.items_review,
            "db_path": self.db_path,
            "ofx_path": self.ofx_path,
            "report_path": self.report_path,
        }


def run_gmail_bancoestado_to_ofx(
    *,
    input_path: str,
    db_path: str,
    schema_path: str,
    ofx_output_path: str,
    report_output_path: str,
) -> RunSummary:
    files = _collect_email_files(Path(input_path))
    if not files:
        raise ValueError("No BancoEstado email input files found")

    repo = StagingRepo(db_path)
    _ensure_db(repo, Path(db_path), schema_path)

    transactions: list[CanonicalTx] = []
    for file_path in files:
        raw_text = file_path.read_text(encoding="utf-8")
        parsed = parse_purchase_email(raw_text, source_file=str(file_path))
        tx = prepare_for_staging(parsed)
        repo.upsert_tx(tx)
        transactions.append(tx)

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
