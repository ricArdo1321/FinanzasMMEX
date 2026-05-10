from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from finanzasmmex.models import CanonicalTx
from finanzasmmex.orchestrator.jobs import run_gmail_all_to_ofx
from finanzasmmex.staging.repo import StagingRepo

ROOT = Path(__file__).resolve().parents[1]


def _mock_be_parser(raw_text: str, **kwargs: Any) -> CanonicalTx:
    return CanonicalTx(
        owner="ricardo",
        source_type="email",
        source_ref="BE-1",
        content_sha256="hash1",
        posted_date=date(2026, 5, 2),
        amount=Decimal("15000.00"),
        direction="debit",
        account_alias="BE_Ricardo_1234",
        merchant_raw="Transferencia a Mach",
        tx_type="transfer_out",
        parser_name="mock_be",
        parser_version="1.0",
        **kwargs
    )


def _mock_mach_parser(raw_text: str, **kwargs: Any) -> CanonicalTx:
    return CanonicalTx(
        owner="ricardo",
        source_type="email",
        source_ref="MACH-1",
        content_sha256="hash2",
        posted_date=date(2026, 5, 2),
        amount=Decimal("15000.00"),
        direction="credit",
        account_alias="MACH_Ricardo",
        merchant_raw="Transferencia desde BE",
        tx_type="transfer_in",
        parser_name="mock_mach",
        parser_version="1.0",
        **kwargs
    )


def test_gmail_all_links_transfers_cross_source(tmp_path, monkeypatch) -> None:
    # Setup files
    input_dir = tmp_path / "emails"
    input_dir.mkdir()
    (input_dir / "be_trf.txt").write_text("be", encoding="utf-8")

    mach_dir = input_dir / "mach"
    mach_dir.mkdir()
    (mach_dir / "mach_trf.txt").write_text("mach", encoding="utf-8")

    db_path = tmp_path / "staging.db"
    schema_path = ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"

    # Mock parsers in orchestrator.jobs
    # We need to mock where they are imported: run_gmail_all_to_ofx imports them locally
    import finanzasmmex.adapters.be_email
    import finanzasmmex.adapters.mach_email

    monkeypatch.setattr(
        finanzasmmex.adapters.be_email,
        "parse_purchase_email",
        _mock_be_parser,
    )
    monkeypatch.setattr(
        finanzasmmex.adapters.mach_email,
        "parse_purchase_email",
        _mock_mach_parser,
    )

    # Run job
    run_gmail_all_to_ofx(
        input_path=str(input_dir),
        db_path=str(db_path),
        schema_path=str(schema_path),
        ofx_output_path=str(tmp_path / "out.ofx"),
        report_output_path=str(tmp_path / "report.html"),
    )

    # Verify staging.db
    repo = StagingRepo(str(db_path))
    txs = repo.list_txs(limit=10)
    assert len(txs) == 2

    by_alias = {tx.account_alias: tx for tx in txs}
    be_tx = by_alias["BE_Ricardo_1234"]
    mach_tx = by_alias["MACH_Ricardo"]

    assert be_tx.tx_type == "internal_transfer"
    assert mach_tx.tx_type == "internal_transfer"
    assert be_tx.transfer_pair_uid == mach_tx.tx_uid
    assert mach_tx.transfer_pair_uid == be_tx.tx_uid
    assert be_tx.to_account_alias == "MACH_Ricardo"
    assert mach_tx.to_account_alias == "BE_Ricardo_1234"
