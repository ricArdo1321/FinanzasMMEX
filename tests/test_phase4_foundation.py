import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from finanzasmmex.adapters.file_loaders import (
    FileLoaderUnsupportedError,
    detect_source_type,
    load_drop_file_for_staging,
)
from finanzasmmex.models import CanonicalTx
from finanzasmmex.staging.repo import StagingRepo

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"


def _repo(tmp_path: Path) -> StagingRepo:
    repo = StagingRepo(str(tmp_path / "staging.db"))
    repo.init_db(str(SCHEMA))
    return repo


def test_qif_and_xlsx_source_types_round_trip_through_staging(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    for source_type in ("qif", "xlsx"):
        tx = CanonicalTx(
            tx_uid=f"tx-{source_type}",
            owner="ricardo",
            source_type=source_type,
            content_sha256=f"hash-{source_type}",
            amount=Decimal("1000.00"),
            account_alias="BE_Ricardo_1234",
            merchant_raw="Comercio Demo",
            tx_type="purchase",
            parser_name=f"{source_type}_loader",
            fitid_synthetic=f"fitid-{source_type}",
        )
        repo.upsert_tx(tx)

    qif = repo.get_tx("tx-qif")
    xlsx = repo.get_tx("tx-xlsx")
    assert qif is not None
    assert xlsx is not None
    assert qif.source_type == "qif"
    assert xlsx.source_type == "xlsx"


def test_raw_artifact_insert_is_idempotent_by_content_sha(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    payload = b"archivo anonimizado"
    content_sha256 = hashlib.sha256(payload).hexdigest()

    first_id = repo.insert_raw_artifact(
        artifact_type="qif",
        source_ref="drop/demo.qif",
        content_sha256=content_sha256,
        payload_blob=payload,
        payload_text="archivo anonimizado",
    )
    second_id = repo.insert_raw_artifact(
        artifact_type="qif",
        source_ref="drop/demo-copy.qif",
        content_sha256=content_sha256,
    )

    stored = repo.get_raw_artifact_by_sha(content_sha256)
    assert second_id == first_id
    assert stored is not None
    assert stored.artifact_id == first_id
    assert stored.payload_blob == payload
    assert stored.payload_text == "archivo anonimizado"


def test_job_run_start_finish_and_one_shot_records_metadata(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    running_id = repo.start_job_run(job_name="drop", metadata={"input": "drop"})
    assert repo.finish_job_run(
        running_id,
        status="ok",
        items_processed=2,
        items_inserted=2,
        items_review=1,
        metadata={"source_type": "qif"},
    )
    deferred_id = repo.record_job_run(
        job_name="drop",
        status="deferred",
        error_message="locked",
        metadata={"input": "drop/demo.qif"},
    )

    running = repo.get_job_run(running_id)
    deferred = repo.get_job_run(deferred_id)
    assert running is not None
    assert running.status == "ok"
    assert running.items_review == 1
    assert running.metadata == {"source_type": "qif"}
    assert deferred is not None
    assert deferred.status == "deferred"
    assert deferred.error_message == "locked"


def test_drop_loader_foundation_prepares_transactions_for_staging(
    tmp_path: Path,
) -> None:
    input_file = tmp_path / "movimientos.qif"
    input_file.write_text("fixture anonimizada", encoding="utf-8")

    def parse_demo(path: Path) -> list[CanonicalTx]:
        assert path == input_file
        return [
            CanonicalTx(
                owner="ricardo",
                amount=Decimal("1234.00"),
                account_alias="BE_Ricardo_1234",
                event_date=date(2026, 5, 10),
                merchant_raw="Cafe Demo",
                tx_type="purchase",
                parser_name="qif_loader",
            )
        ]

    result = load_drop_file_for_staging(
        input_file,
        loaders={".qif": parse_demo},
    )

    assert result.source_type == "qif"
    assert result.content_sha256 == hashlib.sha256(
        input_file.read_bytes()
    ).hexdigest()
    assert len(result.transactions) == 1
    tx = result.transactions[0]
    assert tx.source_type == "qif"
    assert tx.source_file == str(input_file)
    assert tx.source_ref == "movimientos.qif"
    assert tx.content_sha256 == result.content_sha256
    assert tx.fitid_synthetic


def test_detect_source_type_rejects_unknown_drop_extension(tmp_path: Path) -> None:
    unknown = tmp_path / "movimientos.dat"
    unknown.write_text("x", encoding="utf-8")

    try:
        detect_source_type(unknown)
    except FileLoaderUnsupportedError as exc:
        assert exc.error_code == "FILE_LOADER_UNSUPPORTED"
        assert ".csv" in exc.details["supported_extensions"]
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("unknown extension should be rejected")


def test_cli_drop_unsupported_file_returns_json_and_records_job_run(
    tmp_path: Path,
) -> None:
    input_file = tmp_path / "movimientos.dat"
    db = tmp_path / "staging.db"
    input_file.write_text("fixture anonimizada", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "finanzasmmex.cli",
            "run",
            "--source",
            "drop",
            "--input",
            str(input_file),
            "--db",
            str(db),
            "--schema",
            str(SCHEMA),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "FINANZASMMEX_DISABLE_VAULT": "1"},
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "FILE_LOADER_UNSUPPORTED"
    assert result.stdout.strip().startswith("{")
    with StagingRepo(str(db))._get_connection() as conn:
        row = conn.execute(
            "SELECT job_name, status, error_message FROM job_runs"
        ).fetchone()
    assert tuple(row) == ("drop", "error", "Unsupported drop file extension: .dat")
