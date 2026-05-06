import sqlite3
from pathlib import Path

import pytest

from finanzasmmex.orchestrator.jobs import (
    run_gmail_bancoestado_to_ofx,
    run_gmail_cmr_to_ofx,
    run_gmail_mach_to_ofx,
    write_review_report,
)
from finanzasmmex.staging.repo import StagingRepo

ROOT = Path(__file__).resolve().parents[1]


def test_gmail_bancoestado_to_ofx_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "staging.db"
    ofx_path = tmp_path / "out" / "bancoestado.ofx"
    report_path = tmp_path / "reports" / "review.html"

    kwargs = {
        "input_path": str(ROOT / "tests" / "fixtures" / "gmail"),
        "db_path": str(db_path),
        "schema_path": str(ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"),
        "ofx_output_path": str(ofx_path),
        "report_output_path": str(report_path),
    }

    first = run_gmail_bancoestado_to_ofx(**kwargs)
    second = run_gmail_bancoestado_to_ofx(**kwargs)

    assert first.items_processed == 1
    assert second.items_processed == 1
    assert ofx_path.is_file()
    assert report_path.is_file()
    report_text = report_path.read_text(encoding="utf-8")
    assert "COMERCIO DEMO" in report_text
    assert "raw_text" not in report_text
    assert "needs_review" in report_text

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM canonical_tx").fetchone()[0]
        fitid_count = conn.execute(
            "SELECT COUNT(DISTINCT fitid_synthetic) FROM canonical_tx"
        ).fetchone()[0]

    assert count == 1
    assert fitid_count == 1


def test_gmail_cmr_to_ofx_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "staging.db"
    ofx_path = tmp_path / "out" / "cmr.ofx"
    report_path = tmp_path / "reports" / "review.html"

    kwargs = {
        "input_path": str(ROOT / "tests" / "fixtures" / "gmail" / "cmr"),
        "db_path": str(db_path),
        "schema_path": str(ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"),
        "ofx_output_path": str(ofx_path),
        "report_output_path": str(report_path),
    }

    first = run_gmail_cmr_to_ofx(**kwargs)
    second = run_gmail_cmr_to_ofx(**kwargs)

    assert first.items_processed == 1
    assert second.items_processed == 1
    assert ofx_path.is_file()
    assert report_path.is_file()
    report_text = report_path.read_text(encoding="utf-8")
    assert "TIENDA DEMO" in report_text
    assert "raw_text" not in report_text
    assert "pending" in report_text

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM canonical_tx").fetchone()[0]
        fitid_count = conn.execute(
            "SELECT COUNT(DISTINCT fitid_synthetic) FROM canonical_tx"
        ).fetchone()[0]

    assert count == 1
    assert fitid_count == 1


def test_gmail_mach_to_ofx_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "staging.db"
    ofx_path = tmp_path / "out" / "mach.ofx"
    report_path = tmp_path / "reports" / "review.html"

    kwargs = {
        "input_path": str(ROOT / "tests" / "fixtures" / "gmail" / "mach"),
        "db_path": str(db_path),
        "schema_path": str(ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"),
        "ofx_output_path": str(ofx_path),
        "report_output_path": str(report_path),
    }

    first = run_gmail_mach_to_ofx(**kwargs)
    second = run_gmail_mach_to_ofx(**kwargs)

    assert first.items_processed == 1
    assert second.items_processed == 1
    assert ofx_path.is_file()
    assert report_path.is_file()
    report_text = report_path.read_text(encoding="utf-8")
    assert "MACH" in report_text
    assert "raw_text" not in report_text
    assert "pending" in report_text

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM canonical_tx").fetchone()[0]
        fitid_count = conn.execute(
            "SELECT COUNT(DISTINCT fitid_synthetic) FROM canonical_tx"
        ).fetchone()[0]

    assert count == 1
    assert fitid_count == 1


def test_review_report_rejects_mmex_database_paths(tmp_path) -> None:
    with pytest.raises(ValueError, match="MMEX database"):
        write_review_report([], tmp_path / "finanza.mmb")


def test_gmail_bancoestado_to_ofx_blocks_reconcile_off(tmp_path) -> None:
    db_path = tmp_path / "staging.db"
    repo = StagingRepo(str(db_path))
    repo.init_db(str(ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO reconcile_log (
                account_alias, period_start, period_end, balance_initial,
                balance_final, sum_credits, sum_debits, expected_final,
                status, delta
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "BE_Ricardo_1234",
                "2026-05-01",
                "2026-05-31",
                0,
                0,
                0,
                12340,
                -12340,
                "off",
                12340,
            ),
        )

    with pytest.raises(ValueError, match="reconcile status is off"):
        run_gmail_bancoestado_to_ofx(
            input_path=str(ROOT / "tests" / "fixtures" / "gmail"),
            db_path=str(db_path),
            schema_path=str(ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"),
            ofx_output_path=str(tmp_path / "bancoestado.ofx"),
            report_output_path=str(tmp_path / "review.html"),
        )

    assert not (tmp_path / "bancoestado.ofx").exists()
