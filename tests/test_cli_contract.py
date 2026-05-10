import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest

from finanzasmmex import cli
from finanzasmmex.adapters.mp_api import (
    MercadoPagoCredentialsError,
    MercadoPagoTemporaryError,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def safe_backup_dir() -> Iterator[Path]:
    path = Path(tempfile.gettempdir()) / f"finanzasmmex-test-backups-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def run_cli(
    *args: str,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, "-m", "finanzasmmex.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        env=merged_env,
        input=input_text or "",
    )


def parse_stdout(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def create_mmex_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE ACCOUNTLIST_V1 (
                ACCOUNTID INTEGER PRIMARY KEY,
                ACCOUNTNAME TEXT NOT NULL UNIQUE
            );
            CREATE TABLE PAYEE_V1 (
                PAYEEID INTEGER PRIMARY KEY,
                PAYEENAME TEXT NOT NULL UNIQUE,
                CATEGID INTEGER,
                SUBCATEGID INTEGER
            );
            CREATE TABLE CATEGORY_V1 (
                CATEGID INTEGER PRIMARY KEY,
                CATEGNAME TEXT NOT NULL UNIQUE
            );
            CREATE TABLE SUBCATEGORY_V1 (
                SUBCATEGID INTEGER PRIMARY KEY,
                SUBCATEGNAME TEXT NOT NULL,
                CATEGID INTEGER NOT NULL
            );
            CREATE TABLE CHECKINGACCOUNT_V1 (
                TRANSID INTEGER PRIMARY KEY,
                ACCOUNTID INTEGER NOT NULL,
                TOACCOUNTID INTEGER,
                PAYEEID INTEGER,
                TRANSCODE TEXT NOT NULL,
                TRANSAMOUNT TEXT NOT NULL,
                STATUS TEXT,
                TRANSACTIONNUMBER TEXT,
                NOTES TEXT,
                CATEGID INTEGER,
                SUBCATEGID INTEGER,
                TRANSDATE TEXT NOT NULL,
                FOLLOWUPID INTEGER,
                TOTRANSAMOUNT TEXT,
                COLOR TEXT,
                DELETEDTIME TEXT
            );
            CREATE TABLE CUSTOMFIELD_V1 (
                FIELDID INTEGER PRIMARY KEY,
                REFTYPE TEXT,
                DESCRIPTION TEXT NOT NULL,
                TYPE TEXT,
                PROPERTIES TEXT
            );
            CREATE TABLE CUSTOMFIELDDATA_V1 (
                FIELDATADID INTEGER PRIMARY KEY,
                FIELDID INTEGER NOT NULL,
                REFID INTEGER NOT NULL,
                CONTENT TEXT NOT NULL
            );
            INSERT INTO ACCOUNTLIST_V1 (ACCOUNTID, ACCOUNTNAME)
            VALUES (10, 'BE_Ricardo_1234');
            """)


def test_missing_command_returns_json_validation_error() -> None:
    result = run_cli()

    payload = parse_stdout(result)
    assert result.returncode == 2
    assert payload["ok"] is False
    assert payload["data"] is None
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"
    assert payload["warnings"] == []
    assert payload["run_id"]


def test_root_help_returns_json_envelope() -> None:
    result = run_cli("--help")

    payload = parse_stdout(result)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert "usage:" in payload["data"]["help"]
    assert payload["errors"] == []


def test_subcommand_help_returns_json_envelope() -> None:
    result = run_cli("run", "--help")

    payload = parse_stdout(result)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert "--source" in payload["data"]["help"]
    assert payload["errors"] == []


def test_nested_subcommand_help_returns_json_envelope() -> None:
    result = run_cli("review", "list", "--help")

    payload = parse_stdout(result)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert "--needs-review-only" in payload["data"]["help"]
    assert payload["errors"] == []


def test_invalid_argument_returns_json_validation_error() -> None:
    result = run_cli("run", "--source", "bad")

    payload = parse_stdout(result)
    assert result.returncode == 2
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"


def test_run_success_returns_full_envelope(tmp_path) -> None:
    result = run_cli(
        "run",
        "--source",
        "gmail",
        "--writer",
        "ofx",
        "--input",
        str(ROOT / "tests" / "fixtures" / "gmail"),
        "--db",
        str(tmp_path / "staging.db"),
        "--ofx-output",
        str(tmp_path / "bancoestado.ofx"),
        "--report-output",
        str(tmp_path / "review.html"),
    )

    payload = parse_stdout(result)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["data"]["source"] == "gmail"
    assert payload["data"]["writer"] == "ofx"
    assert payload["data"]["items_processed"] == 1
    assert payload["data"]["items_review"] == 1
    assert Path(payload["data"]["ofx_path"]).is_file()
    assert Path(payload["data"]["report_path"]).is_file()
    assert payload["errors"] == []
    assert payload["warnings"] == []
    assert payload["run_id"]


def test_run_without_input_returns_credentials_error() -> None:
    result = run_cli("run", "--source", "gmail", "--writer", "ofx")

    payload = parse_stdout(result)
    assert result.returncode == 3
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "CREDENTIALS_REQUIRED"
    assert payload["errors"][0]["details"]["offline_flag"] == "--input"


def test_run_gmail_without_input_does_not_advertise_unsupported_login() -> None:
    result = run_cli("run", "--source", "gmail", "--writer", "ofx")

    payload = parse_stdout(result)
    details = payload["errors"][0]["details"]

    assert result.returncode == 3
    assert payload["errors"][0]["code"] == "CREDENTIALS_REQUIRED"
    assert details["offline_flag"] == "--input"
    assert "login_command" not in details


def test_run_all_without_input_does_not_advertise_unsupported_gmail_login() -> None:
    result = run_cli("run", "--source", "all", "--writer", "ofx")

    payload = parse_stdout(result)
    details = payload["errors"][0]["details"]

    assert result.returncode == 3
    assert payload["errors"][0]["code"] == "CREDENTIALS_REQUIRED"
    assert details["offline_flag"] == "--input"
    assert "login_command" not in details


def test_run_mp_offline_input_succeeds(tmp_path) -> None:
    fixture = ROOT / "tests" / "fixtures" / "mp_api" / "payment_anonymized.json"
    result = run_cli(
        "run",
        "--source",
        "mp",
        "--writer",
        "ofx",
        "--input",
        str(fixture),
        "--db",
        str(tmp_path / "staging.db"),
        "--ofx-output",
        str(tmp_path / "mp.ofx"),
        "--report-output",
        str(tmp_path / "review.html"),
    )

    payload = parse_stdout(result)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["data"]["source"] == "mp"
    assert payload["data"]["items_processed"] == 1
    assert Path(payload["data"]["ofx_path"]).is_file()
    # Token must never be echoed in any envelope field.
    assert "access_token" not in result.stdout.lower()


def test_run_mp_without_input_or_token_returns_credentials_error() -> None:
    result = run_cli(
        "run",
        "--source",
        "mp",
        "--writer",
        "ofx",
        env={"FINANZASMMEX_DISABLE_VAULT": "1"},
    )

    payload = parse_stdout(result)
    assert result.returncode == 3
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "CREDENTIALS_REQUIRED"
    assert payload["errors"][0]["details"]["login_command"].endswith("--source mp")


def _mp_online_args(tmp_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        input=None,
        source="mp",
        writer="ofx",
        db=str(tmp_path / "staging.db"),
        schema=str(ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"),
        ofx_output=str(tmp_path / "mp.ofx"),
        report_output=str(tmp_path / "review.html"),
        begin_date="2026-05-01",
        end_date="2026-05-07",
    )


def test_run_mp_online_credentials_error_maps_exit_3(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def raise_credentials(**kwargs) -> None:
        raise MercadoPagoCredentialsError("mp_credentials_invalid:http_401")

    monkeypatch.delenv("MP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("FINANZASMMEX_DISABLE_VAULT", raising=False)
    monkeypatch.setattr(cli, "_read_vault_secret", lambda key: "TEST-TOKEN")
    monkeypatch.setattr(cli, "run_mp_online", raise_credentials)

    with pytest.raises(SystemExit) as exc:
        cli._run_mp(_mp_online_args(tmp_path))

    payload = json.loads(capsys.readouterr().out)
    assert exc.value.code == 3
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "CREDENTIALS_REQUIRED"
    assert "TEST-TOKEN" not in json.dumps(payload)


def test_run_mp_online_temporary_error_maps_exit_5(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def raise_temporary(**kwargs) -> None:
        raise MercadoPagoTemporaryError("mp_server_error:http_503")

    monkeypatch.delenv("MP_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("FINANZASMMEX_DISABLE_VAULT", raising=False)
    monkeypatch.setattr(cli, "_read_vault_secret", lambda key: "TEST-TOKEN")
    monkeypatch.setattr(cli, "run_mp_online", raise_temporary)

    with pytest.raises(SystemExit) as exc:
        cli._run_mp(_mp_online_args(tmp_path))

    payload = json.loads(capsys.readouterr().out)
    assert exc.value.code == 5
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "TEMPORARY_FAILURE"
    assert "TEST-TOKEN" not in json.dumps(payload)


def test_run_mp_ignores_env_token_without_vault_secret(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    def fail_if_called(**kwargs) -> None:
        raise AssertionError("run_mp_online must not receive env tokens")

    monkeypatch.setenv("MP_ACCESS_TOKEN", "TEST-TOKEN")
    monkeypatch.delenv("FINANZASMMEX_DISABLE_VAULT", raising=False)
    monkeypatch.setattr(cli, "_read_vault_secret", lambda key: None)
    monkeypatch.setattr(cli, "run_mp_online", fail_if_called)

    with pytest.raises(SystemExit) as exc:
        cli._run_mp(_mp_online_args(tmp_path))

    payload = json.loads(capsys.readouterr().out)
    assert exc.value.code == 3
    assert payload["errors"][0]["code"] == "CREDENTIALS_REQUIRED"


def test_login_mp_requires_token_from_stdin() -> None:
    result = run_cli(
        "login",
        "--source",
        "mp",
        env={"MP_ACCESS_TOKEN": "", "FINANZASMMEX_DISABLE_VAULT": "1"},
    )

    payload = parse_stdout(result)
    assert result.returncode == 3
    assert payload["errors"][0]["code"] == "CREDENTIALS_REQUIRED"
    assert payload["errors"][0]["details"]["input"] == "stdin_or_secure_prompt"


def test_login_mp_accepts_token_from_stdin_without_echoing_it() -> None:
    sentinel = "SENTINEL-TOKEN-DO-NOT-LEAK-9b3c1e"
    result = run_cli(
        "login",
        "--source",
        "mp",
        env={"MP_ACCESS_TOKEN": "", "FINANZASMMEX_DISABLE_VAULT": "1"},
        input_text=f"{sentinel}\n",
    )

    payload = parse_stdout(result)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert sentinel not in result.stdout
    assert sentinel not in result.stderr


def test_login_mp_invalid_source_validation_error() -> None:
    result = run_cli("login", "--source", "gmail")
    payload = parse_stdout(result)
    assert result.returncode == 2
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"


def test_init_missing_schema_returns_validation_error(tmp_path) -> None:
    result = run_cli(
        "init",
        "--db",
        str(tmp_path / "staging.db"),
        "--schema",
        str(tmp_path / "missing.sql"),
    )

    payload = parse_stdout(result)
    assert result.returncode == 2
    assert payload["ok"] is False
    assert payload["data"] is None
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"
    assert payload["errors"][0]["details"]["schema_path"].endswith("missing.sql")
    assert payload["warnings"] == []


def test_review_missing_db_returns_validation_error(tmp_path) -> None:
    result = run_cli("review", "list", "--db", str(tmp_path / "missing.db"))

    payload = parse_stdout(result)
    assert result.returncode == 2
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"
    assert payload["errors"][0]["details"]["field"] == "--db"


def test_run_sql_success_returns_sql_metrics_and_updates_staging(
    tmp_path,
    safe_backup_dir: Path,
) -> None:
    db = tmp_path / "staging.db"
    mmex = tmp_path / "finanza_test.mmb"
    backups = safe_backup_dir
    create_mmex_db(mmex)

    init = run_cli(
        "init",
        "--db",
        str(db),
        "--schema",
        str(ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"),
    )
    assert init.returncode == 0, init.stdout
    created = run_cli(
        "quickadd",
        "create",
        "--db",
        str(db),
        "--owner",
        "ricardo",
        "--account-alias",
        "BE_Ricardo_1234",
        "--amount",
        "12340",
        "--direction",
        "debit",
        "--date",
        "2026-05-02",
        "--merchant-raw",
        "COMERCIO DEMO",
        "--category-guess",
        "Compras",
    )
    assert created.returncode == 0, created.stdout

    result = run_cli(
        "run",
        "--writer",
        "sql",
        "--db",
        str(db),
        "--mmex-db",
        str(mmex),
        "--backup-dir",
        str(backups),
        "--allow-shadow-write",
    )

    payload = parse_stdout(result)
    assert result.returncode == 0, result.stdout
    assert payload["ok"] is True
    assert payload["data"]["writer"] == "sql"
    assert payload["data"]["items_inserted"] == 1
    assert Path(payload["data"]["backup_pre_path"]).is_file()
    assert Path(payload["data"]["backup_post_path"]).is_file()
    assert payload["data"]["mmex_tx_ids"]

    listed = parse_stdout(
        run_cli("review", "list", "--db", str(db), "--status", "inserted")
    )
    assert listed["data"]["count"] == 1
    assert listed["data"]["items"][0]["mmex_status"] == "inserted"


def test_run_sql_second_run_keeps_mmex_and_staging_state_unchanged(
    tmp_path,
    safe_backup_dir: Path,
) -> None:
    db = tmp_path / "staging.db"
    mmex = tmp_path / "finanza_test.mmb"
    backups = safe_backup_dir
    create_mmex_db(mmex)

    assert run_cli(
        "init",
        "--db",
        str(db),
        "--schema",
        str(ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"),
    ).returncode == 0
    assert run_cli(
        "quickadd",
        "create",
        "--db",
        str(db),
        "--owner",
        "ricardo",
        "--account-alias",
        "BE_Ricardo_1234",
        "--amount",
        "12340",
        "--direction",
        "debit",
        "--date",
        "2026-05-02",
        "--merchant-raw",
        "COMERCIO DEMO",
    ).returncode == 0

    first = run_cli(
        "run",
        "--writer",
        "sql",
        "--db",
        str(db),
        "--mmex-db",
        str(mmex),
        "--backup-dir",
        str(backups),
        "--allow-shadow-write",
    )
    second = run_cli(
        "run",
        "--writer",
        "sql",
        "--db",
        str(db),
        "--mmex-db",
        str(mmex),
        "--backup-dir",
        str(backups),
        "--allow-shadow-write",
    )

    assert first.returncode == 0, first.stdout
    assert second.returncode == 0, second.stdout
    second_payload = parse_stdout(second)
    assert second_payload["data"]["items_inserted"] == 0
    with sqlite3.connect(mmex) as conn:
        tx_count = conn.execute("SELECT COUNT(*) FROM CHECKINGACCOUNT_V1").fetchone()[0]
        hash_count = conn.execute(
            "SELECT COUNT(*) FROM CUSTOMFIELDDATA_V1"
        ).fetchone()[0]
    inserted = parse_stdout(
        run_cli("review", "list", "--db", str(db), "--status", "inserted")
    )
    pending = parse_stdout(
        run_cli("review", "list", "--db", str(db), "--status", "pending")
    )
    assert tx_count == 1
    assert hash_count == 1
    assert inserted["data"]["count"] == 1
    assert pending["data"]["count"] == 0


def test_run_sql_requires_shadow_write_flag(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    mmex.touch()

    result = run_cli(
        "run",
        "--writer",
        "sql",
        "--db",
        str(tmp_path / "staging.db"),
        "--mmex-db",
        str(mmex),
        "--backup-dir",
        str(tmp_path / "backups"),
    )

    payload = parse_stdout(result)
    assert result.returncode == 2
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"
    assert "explicit" in payload["errors"][0]["message"]


def test_run_sql_locked_db_returns_exit_4(tmp_path) -> None:
    db = tmp_path / "staging.db"
    mmex = tmp_path / "finanza_test.mmb"
    create_mmex_db(mmex)
    init = run_cli(
        "init",
        "--db",
        str(db),
        "--schema",
        str(ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"),
    )
    assert init.returncode == 0, init.stdout
    created = run_cli(
        "quickadd",
        "create",
        "--db",
        str(db),
        "--owner",
        "ricardo",
        "--account-alias",
        "BE_Ricardo_1234",
        "--amount",
        "12340",
        "--direction",
        "debit",
        "--date",
        "2026-05-02",
        "--merchant-raw",
        "COMERCIO DEMO",
        "--category-guess",
        "Compras",
    )
    assert created.returncode == 0, created.stdout

    locker = sqlite3.connect(mmex, isolation_level=None)
    try:
        locker.execute("BEGIN EXCLUSIVE")
        result = run_cli(
            "run",
            "--writer",
            "sql",
            "--db",
            str(db),
            "--mmex-db",
            str(mmex),
            "--backup-dir",
            str(tmp_path / "backups"),
            "--allow-shadow-write",
        )
    finally:
        locker.rollback()
        locker.close()

    payload = parse_stdout(result)
    assert result.returncode == 4
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "MMEX_LOCKED"
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT status, error_message FROM job_runs WHERE job_name = ?",
            ("mmex_sql",),
        ).fetchone()
    assert row == ("deferred", "MMEX database is locked")
