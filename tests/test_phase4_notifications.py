import json
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from finanzasmmex.models import CanonicalTx
from finanzasmmex.notifications import notify_needs_review
from finanzasmmex.staging.repo import StagingRepo

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"


def test_notify_needs_review_without_rows_sends_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    result = _run_cli(
        "notify",
        "needs-review",
        "--dry-run",
        "--db",
        repo.db_path,
        "--reports-dir",
        str(tmp_path / "reports"),
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 0, result.stdout
    assert payload["data"]["sent"] is False
    assert payload["data"]["delivery"] == "local_envelope"
    assert payload["data"]["needs_review_count"] == 0
    assert payload["data"]["payload"]["summary"]["count"] == 0


def test_notify_needs_review_payload_is_redacted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    report = reports_dir / "dashboard_2026-05.html"
    report.write_text("<html>ok</html>", encoding="utf-8")
    repo.upsert_tx(
        _tx(
            "tx-review",
            needs_review=True,
            raw_text="RAW_PRIVATE_MARKER",
            merchant="Farmacia Demo",
            account="BE_Ricardo_123456789",
        )
    )

    result = _run_cli(
        "notify",
        "needs-review",
        "--db",
        repo.db_path,
        "--reports-dir",
        str(reports_dir),
    )

    payload = json.loads(result.stdout)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert result.returncode == 0, result.stdout
    assert payload["data"]["sent"] is False
    assert payload["data"]["delivery"] == "local_envelope"
    assert payload["data"]["needs_review_count"] == 1
    assert payload["data"]["payload"]["summary"]["by_status"] == {"pending": 1}
    assert payload["data"]["payload"]["report_path"] == str(report.resolve())
    assert "RAW_PRIVATE_MARKER" not in serialized
    assert "Farmacia Demo" not in serialized
    assert "123456789" not in serialized


def test_notify_module_never_sends_network() -> None:
    result = notify_needs_review([_tx("tx-review", needs_review=True)])

    assert result.sent is False
    assert result.delivery == "local_envelope"
    assert result.needs_review_count == 1


def test_notify_rejects_external_channel_argument(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    result = _run_cli(
        "notify",
        "needs-review",
        "--db",
        repo.db_path,
        "--channel",
        "external",
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"


def test_login_does_not_accept_external_notification_sources() -> None:
    result = _run_cli("login", "--source", "external", input_text="ignored\n")

    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"


def _repo(tmp_path: Path) -> StagingRepo:
    repo = StagingRepo(str(tmp_path / "staging.db"))
    repo.init_db(str(SCHEMA))
    return repo


def _tx(
    uid: str,
    *,
    needs_review: bool,
    raw_text: str = "",
    merchant: str = "Comercio Demo",
    account: str = "BE_Ricardo_1234",
) -> CanonicalTx:
    return CanonicalTx(
        tx_uid=uid,
        owner="ricardo",
        source_type="manual",
        content_sha256=f"hash-{uid}",
        raw_text=raw_text,
        posted_date=date(2026, 5, 10),
        amount=Decimal("1000.00"),
        account_alias=account,
        merchant_raw=merchant,
        merchant_norm=merchant,
        tx_type="purchase",
        parser_name="test",
        fitid_synthetic=f"fitid-{uid}",
        needs_review=needs_review,
        review_reason="test_review" if needs_review else None,
    )


def _run_cli(
    *args: str,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "finanzasmmex.cli", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        input=input_text or "",
        env={**os.environ, "FINANZASMMEX_DISABLE_VAULT": "1"},
    )
