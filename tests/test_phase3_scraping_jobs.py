import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

from finanzasmmex.etl.fitid import ensure_fitid
from finanzasmmex.models import CanonicalTx
from finanzasmmex.orchestrator.jobs import run_scraping_be
from finanzasmmex.staging.repo import StagingRepo

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"


def _scraped_tx(
    *,
    tx_uid: str = "scraped-001",
    merchant_raw: str = "SUPERMERCADO DEMO",
    posted_date: date = date(2026, 5, 2),
    amount: Decimal = Decimal("12990.00"),
) -> CanonicalTx:
    return CanonicalTx(
        tx_uid=tx_uid,
        owner="ricardo",
        source_type="scraping",
        source_ref="be-scrape-row-001",
        raw_text="02/05/2026|SUPERMERCADO DEMO|-$12.990",
        content_sha256="a" * 64,
        event_date=posted_date,
        posted_date=posted_date,
        amount=amount,
        currency="CLP",
        direction="debit",
        account_alias="BE_Ricardo_RUT",
        merchant_raw=merchant_raw,
        tx_type="purchase",
        parser_name="be_scraping_v1",
        parser_version="1.0",
    )


def test_scraping_be_job_computes_fitid_and_is_idempotent(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "staging.db"
    ofx_path = tmp_path / "out" / "scraping-be.ofx"
    report_path = tmp_path / "reports" / "scraping-be.html"

    monkeypatch.setattr(
        "finanzasmmex.adapters.be_scraping.BancoEstadoScraper.scrape",
        lambda _self, _since: [_scraped_tx()],
    )

    kwargs = {
        "db_path": str(db_path),
        "schema_path": str(SCHEMA),
        "ofx_output_path": str(ofx_path),
        "report_output_path": str(report_path),
    }

    first = run_scraping_be(**kwargs)
    second = run_scraping_be(**kwargs)

    assert first.items_processed == 1
    assert second.items_processed == 1
    assert ofx_path.is_file()
    assert report_path.is_file()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT COUNT(*), COUNT(DISTINCT fitid_synthetic),
                   MIN(fitid_synthetic)
            FROM canonical_tx
            """
        ).fetchone()

    assert row == (1, 1, row[2])
    assert row[2] is not None


def test_scraping_be_job_keeps_existing_identity_when_merged(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "staging.db"
    repo = StagingRepo(str(db_path))
    repo.init_db(str(SCHEMA))

    existing = ensure_fitid(
        CanonicalTx(
            tx_uid="email-001",
            owner="ricardo",
            source_type="email",
            source_ref="gmail-msg-001",
            raw_text="email",
            content_sha256="b" * 64,
            event_date=date(2026, 5, 1),
            posted_date=date(2026, 5, 1),
            amount=Decimal("12990.00"),
            currency="CLP",
            direction="debit",
            account_alias="BE_Ricardo_RUT",
            merchant_raw="SUPERMERCADO DEMO",
            merchant_norm="SUPERMERCADO DEMO",
            tx_type="purchase",
            parser_name="be_email_v1",
            parser_version="1.0",
        )
    )
    repo.upsert_tx(existing)

    monkeypatch.setattr(
        "finanzasmmex.adapters.be_scraping.BancoEstadoScraper.scrape",
        lambda _self, _since: [
            _scraped_tx(
                tx_uid="scraped-001",
                posted_date=date(2026, 5, 1),
            )
        ],
    )

    run_scraping_be(
        db_path=str(db_path),
        schema_path=str(SCHEMA),
        ofx_output_path=str(tmp_path / "out" / "scraping-be.ofx"),
        report_output_path=str(tmp_path / "reports" / "scraping-be.html"),
    )

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT tx_uid, fitid_synthetic FROM canonical_tx"
        ).fetchall()

    assert rows == [("email-001", existing.fitid_synthetic)]
