import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finanzasmmex.adapters.scraping_base import ScrapingResult
from finanzasmmex.models import CanonicalTx
from finanzasmmex.orchestrator.jobs import run_scraping_be, run_scraping_cmr

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"


def _tx(
    *,
    tx_uid: str,
    account_alias: str,
    amount: Decimal,
    direction: str,
) -> CanonicalTx:
    return CanonicalTx(
        tx_uid=tx_uid,
        owner="ricardo",
        source_type="scraping",
        source_ref=tx_uid,
        raw_text=f"{tx_uid}|COMERCIO DEMO|{amount}",
        content_sha256=(tx_uid[-1] * 64),
        event_date=date(2026, 5, 2),
        posted_date=date(2026, 5, 2),
        amount=amount,
        currency="CLP",
        direction=direction,  # type: ignore[arg-type]
        account_alias=account_alias,
        merchant_raw="COMERCIO DEMO",
        tx_type="purchase" if direction == "debit" else "refund",
        parser_name="be_scraping_v1",
        parser_version="1.0",
    )


def _reconcile_rows(db_path: Path) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return conn.execute(
            """
            SELECT account_alias, period_start, period_end, sum_credits,
                   sum_debits, expected_final, status, delta
            FROM reconcile_log
            ORDER BY account_alias
            """
        ).fetchall()


def test_scraping_be_records_ok_reconcile_log(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "staging.db"
    ofx_path = tmp_path / "out" / "be.ofx"
    tx = _tx(
        tx_uid="scraped-ok-1",
        account_alias="BE_Ricardo_RUT",
        amount=Decimal("1000.00"),
        direction="debit",
    )
    result = ScrapingResult(
        transactions=[tx],
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        balances={"BE_Ricardo_RUT": (Decimal("10000.00"), Decimal("9000.00"))},
    )
    monkeypatch.setattr(
        "finanzasmmex.adapters.be_scraping.BancoEstadoScraper.scrape",
        lambda _self, _since: result,
    )

    summary = run_scraping_be(
        db_path=str(db_path),
        schema_path=str(SCHEMA),
        ofx_output_path=str(ofx_path),
        report_output_path=str(tmp_path / "reports" / "be.html"),
    )

    assert summary.reconcile_status == "ok"
    assert ofx_path.is_file()
    assert _reconcile_rows(db_path) == [
        (
            "BE_Ricardo_RUT",
            "2026-05-01",
            "2026-05-31",
            0.0,
            1000.0,
            9000.0,
            "ok",
            0.0,
        )
    ]


def test_scraping_be_records_off_and_blocks_ofx(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "staging.db"
    ofx_path = tmp_path / "out" / "be.ofx"
    tx = _tx(
        tx_uid="scraped-off-1",
        account_alias="BE_Ricardo_RUT",
        amount=Decimal("1000.00"),
        direction="debit",
    )
    result = ScrapingResult(
        transactions=[tx],
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        balances={"BE_Ricardo_RUT": (Decimal("10000.00"), Decimal("8700.00"))},
    )
    monkeypatch.setattr(
        "finanzasmmex.adapters.be_scraping.BancoEstadoScraper.scrape",
        lambda _self, _since: result,
    )

    with pytest.raises(ValueError, match="reconcile status is off"):
        run_scraping_be(
            db_path=str(db_path),
            schema_path=str(SCHEMA),
            ofx_output_path=str(ofx_path),
            report_output_path=str(tmp_path / "reports" / "be.html"),
        )

    assert not ofx_path.exists()
    assert _reconcile_rows(db_path)[0][6:] == ("off", -300.0)


def test_scraping_cmr_without_balances_records_manual_review(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "staging.db"
    ofx_path = tmp_path / "out" / "cmr.ofx"
    tx = _tx(
        tx_uid="scraped-manual-1",
        account_alias="CMR_Ricardo",
        amount=Decimal("5000.00"),
        direction="debit",
    )
    result = ScrapingResult(
        transactions=[tx],
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        balances={},
    )
    monkeypatch.setattr(
        "finanzasmmex.adapters.cmr_scraping.CMRScraper.scrape",
        lambda _self, _since: result,
    )

    summary = run_scraping_cmr(
        db_path=str(db_path),
        schema_path=str(SCHEMA),
        ofx_output_path=str(ofx_path),
        report_output_path=str(tmp_path / "reports" / "cmr.html"),
    )

    assert summary.reconcile_status == "manual_review"
    assert ofx_path.is_file()
    assert _reconcile_rows(db_path)[0][6:] == ("manual_review", 0.0)
