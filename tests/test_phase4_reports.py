import json
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finanzasmmex.models import CanonicalTx
from finanzasmmex.reports import generate_monthly_dashboard
from finanzasmmex.staging.repo import StagingRepo

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"


def test_monthly_dashboard_empty_month_writes_safe_html(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    data = generate_monthly_dashboard(
        repo,
        month="2026-05",
        reports_dir=tmp_path / "reports",
    )

    report_path = Path(str(data["report_path"]))
    html = report_path.read_text(encoding="utf-8")
    assert report_path.name == "dashboard_2026-05.html"
    assert data["items_count"] == 0
    assert "Sin movimientos" in html
    assert "raw_text" not in html


def test_monthly_dashboard_aggregates_staging_without_raw_text(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    repo.upsert_batch(
        [
            _tx(
                "tx-cafe",
                amount="1000",
                posted=date(2026, 5, 2),
                merchant="Cafe Demo",
                category="Comida",
                tags=["joint", "personal"],
            ),
            _tx(
                "tx-salary",
                amount="3000",
                direction="credit",
                posted=date(2026, 5, 5),
                merchant="Empresa Demo",
                category="Sueldo",
                status="inserted",
            ),
            _tx(
                "tx-review",
                amount="500",
                posted=date(2026, 5, 8),
                merchant="Farmacia Demo",
                category="Salud",
                account="CMR_Ricardo_9999",
                needs_review=True,
                raw_text="RAW_TEXT_PRIVATE_MARKER",
            ),
            _tx(
                "tx-outside",
                amount="700",
                posted=date(2026, 4, 30),
                merchant="Fuera Demo",
                category="Otros",
            ),
        ]
    )

    data = generate_monthly_dashboard(
        repo,
        month="2026-05",
        reports_dir=tmp_path / "reports",
    )

    html = Path(str(data["report_path"])).read_text(encoding="utf-8")
    assert data["items_count"] == 3
    assert data["totals"] == {
        "debit": "1500.00",
        "credit": "3000.00",
        "net": "1500.00",
    }
    assert data["needs_review"] == {
        "count": 1,
        "debit": "500.00",
        "credit": "0.00",
    }
    assert data["mmex_status_counts"] == {"inserted": 1, "pending": 2}
    category_rows = {
        row["key"]: row for row in data["aggregations"]["category"]  # type: ignore[index]
    }
    assert category_rows["Comida"]["debit"] == "1000.00"
    assert category_rows["Sueldo"]["credit"] == "3000.00"
    assert "Cafe Demo" in html
    assert "RAW_TEXT_PRIVATE_MARKER" not in html
    assert "raw_text" not in html


def test_monthly_dashboard_rejects_mmex_output_path(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    with pytest.raises(ValueError, match="MMEX database path"):
        generate_monthly_dashboard(
            repo,
            month="2026-05",
            reports_dir=tmp_path / "reports",
            output_path="finanza.mmb",
        )


def test_reports_cli_monthly_list_latest_and_dangerous_path(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    repo.upsert_tx(
        _tx(
            "tx-cli",
            amount="1234",
            posted=date(2026, 5, 10),
            merchant="Comercio CLI",
            category="Compras",
        )
    )
    reports_dir = tmp_path / "reports"

    generated = _run_cli(
        "reports",
        "monthly",
        "--db",
        repo.db_path,
        "--month",
        "2026-05",
        "--reports-dir",
        str(reports_dir),
    )
    generated_payload = json.loads(generated.stdout)
    assert generated.returncode == 0, generated.stdout
    assert generated_payload["ok"] is True
    assert generated_payload["data"]["items_count"] == 1
    assert Path(generated_payload["data"]["report_path"]).is_file()

    listed = _run_cli("reports", "list", "--reports-dir", str(reports_dir))
    listed_payload = json.loads(listed.stdout)
    assert listed.returncode == 0, listed.stdout
    assert listed_payload["data"]["count"] == 1
    assert listed_payload["data"]["reports"][0]["month"] == "2026-05"

    latest = _run_cli("reports", "latest", "--reports-dir", str(reports_dir))
    latest_payload = json.loads(latest.stdout)
    assert latest.returncode == 0, latest.stdout
    assert latest_payload["data"]["report"]["month"] == "2026-05"

    dangerous = _run_cli(
        "reports",
        "monthly",
        "--db",
        repo.db_path,
        "--month",
        "2026-05",
        "--reports-dir",
        str(reports_dir),
        "--output",
        "finanza.mmb",
    )
    dangerous_payload = json.loads(dangerous.stdout)
    assert dangerous.returncode == 2
    assert dangerous_payload["ok"] is False
    assert dangerous_payload["errors"][0]["code"] == "VALIDATION_ERROR"


def _repo(tmp_path: Path) -> StagingRepo:
    repo = StagingRepo(str(tmp_path / "staging.db"))
    repo.init_db(str(SCHEMA))
    return repo


def _tx(
    uid: str,
    *,
    amount: str,
    posted: date,
    merchant: str,
    category: str,
    direction: str = "debit",
    status: str = "pending",
    tags: list[str] | None = None,
    account: str = "BE_Ricardo_1234",
    needs_review: bool = False,
    raw_text: str = "",
) -> CanonicalTx:
    return CanonicalTx(
        tx_uid=uid,
        owner="ricardo",
        source_type="manual",
        content_sha256=f"hash-{uid}",
        raw_text=raw_text,
        posted_date=posted,
        amount=Decimal(amount),
        direction=direction,  # type: ignore[arg-type]
        account_alias=account,
        merchant_raw=merchant,
        merchant_norm=merchant,
        tx_type="purchase",
        category_guess=category,
        tags=tags or [],
        parser_name="test",
        fitid_synthetic=f"fitid-{uid}",
        needs_review=needs_review,
        review_reason="test_review" if needs_review else None,
        mmex_status=status,  # type: ignore[arg-type]
    )


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "finanzasmmex.cli", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "FINANZASMMEX_DISABLE_VAULT": "1"},
    )
