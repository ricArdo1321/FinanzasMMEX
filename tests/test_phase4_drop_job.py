import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"
FIXTURES = ROOT / "tests" / "fixtures" / "drop"


def test_drop_directory_processes_files_by_state_and_is_idempotent(
    tmp_path: Path,
) -> None:
    drop_dir = tmp_path / "drop"
    db = tmp_path / "staging.db"
    drop_dir.mkdir()
    shutil.copy2(FIXTURES / "sample.csv", drop_dir / "sample.csv")
    shutil.copy2(FIXTURES / "sample.qif", drop_dir / "sample.qif")

    first = _run_cli_drop(db, drop_dir)
    second = _run_cli_drop(db, drop_dir)

    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first.returncode == 0, first.stdout
    assert second.returncode == 0, second.stdout
    assert first_payload["data"]["files_seen"] == 2
    assert first_payload["data"]["files_processed"] == 2
    assert first_payload["data"]["files_error"] == 0
    assert second_payload["data"]["files_seen"] == 0
    assert sorted(path.name for path in (drop_dir / "processed").iterdir()) == [
        "sample.csv",
        "sample.qif",
    ]
    assert list((drop_dir / "processing").iterdir()) == []

    with sqlite3.connect(db) as conn:
        tx_count = conn.execute("SELECT COUNT(*) FROM canonical_tx").fetchone()[0]
        raw_count = conn.execute("SELECT COUNT(*) FROM raw_artifacts").fetchone()[0]
    assert tx_count == 4
    assert raw_count == 2


def test_drop_directory_quarantines_bad_file_with_json_error(tmp_path: Path) -> None:
    drop_dir = tmp_path / "drop"
    db = tmp_path / "staging.db"
    drop_dir.mkdir()
    (drop_dir / "bad.dat").write_text("no soportado", encoding="utf-8")

    result = _run_cli_drop(db, drop_dir)

    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "FILE_LOADER_UNSUPPORTED"
    assert payload["data"]["files_error"] == 1
    assert (drop_dir / "error" / "bad.dat").is_file()
    assert list((drop_dir / "processing").iterdir()) == []
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT status, error_message FROM job_runs WHERE job_name = 'drop'"
        ).fetchone()
    assert row == ("error", "Unsupported drop file extension: .dat")


def test_drop_directory_mixed_success_keeps_valid_json_warning(tmp_path: Path) -> None:
    drop_dir = tmp_path / "drop"
    db = tmp_path / "staging.db"
    drop_dir.mkdir()
    shutil.copy2(FIXTURES / "sample.csv", drop_dir / "sample.csv")
    (drop_dir / "bad.dat").write_text("no soportado", encoding="utf-8")

    result = _run_cli_drop(db, drop_dir)

    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["warnings"] == ["1 drop file(s) moved to error"]
    assert payload["data"]["files_processed"] == 1
    assert payload["data"]["files_error"] == 1
    assert (drop_dir / "processed" / "sample.csv").is_file()
    assert (drop_dir / "error" / "bad.dat").is_file()


def _run_cli_drop(db: Path, input_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "finanzasmmex.cli",
            "run",
            "--source",
            "drop",
            "--input",
            str(input_path),
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
