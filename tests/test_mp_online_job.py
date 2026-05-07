import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from finanzasmmex.adapters import mp_api
from finanzasmmex.adapters.mp_api import MercadoPagoParseError
from finanzasmmex.orchestrator import jobs
from finanzasmmex.orchestrator.jobs import run_mp_online

ROOT = Path(__file__).resolve().parents[1]


class FakeMercadoPagoClient:
    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    def __enter__(self) -> "FakeMercadoPagoClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: Any,
    ) -> None:
        return None

    def search_payments(self, **kwargs: Any) -> list[dict[str, Any]]:
        fixture = json.loads(
            (ROOT / "tests" / "fixtures" / "mp_api" / "payment_anonymized.json")
            .read_text(encoding="utf-8")
        )
        malformed = dict(fixture)
        malformed["id"] = "bad-approved-payment"
        malformed["currency_id"] = "USD"
        return [fixture, malformed]


def test_run_mp_online_parse_failure_aborts_before_staging(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(mp_api, "MercadoPagoClient", FakeMercadoPagoClient)
    monkeypatch.setattr(jobs, "MercadoPagoClient", FakeMercadoPagoClient, raising=False)

    db_path = tmp_path / "staging.db"
    ofx_path = tmp_path / "mp.ofx"
    report_path = tmp_path / "review.html"

    with pytest.raises(MercadoPagoParseError, match="bad-approved-payment"):
        run_mp_online(
            access_token="TEST-TOKEN",
            begin_date="2026-05-01",
            end_date="2026-05-07",
            db_path=str(db_path),
            schema_path=str(ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"),
            ofx_output_path=str(ofx_path),
            report_output_path=str(report_path),
        )

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM canonical_tx").fetchone()[0]
    assert count == 0
    assert not ofx_path.exists()
    assert not report_path.exists()
