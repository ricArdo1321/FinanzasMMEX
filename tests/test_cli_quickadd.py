import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "FINANZASMMEX_DISABLE_VAULT": "1"}
    return subprocess.run(
        [sys.executable, "-m", "finanzasmmex.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def parse(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def init_db(tmp_path: Path) -> Path:
    db = tmp_path / "staging.db"
    result = run_cli("init", "--db", str(db), "--schema", str(SCHEMA))
    assert result.returncode == 0
    return db


BASE_ARGS = (
    "--owner",
    "ricardo",
    "--account-alias",
    "BE_Ricardo_RUT",
    "--amount",
    "5500",
    "--direction",
    "debit",
    "--date",
    "2026-04-15",
    "--merchant-raw",
    "Cafe Lola",
)


def test_quickadd_create_inserts_canonical_tx(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    result = run_cli(
        "quickadd",
        "create",
        "--db",
        str(db),
        *BASE_ARGS,
        "--tags",
        "personal-r,cafe",
    )

    payload = parse(result)
    assert result.returncode == 0, result.stdout
    assert payload["ok"] is True
    assert payload["data"]["created"] is True
    assert payload["data"]["fitid_synthetic"]
    assert payload["data"]["tx"]["source_type"] == "manual"
    assert payload["data"]["tx"]["parser_name"] not in {"", None}  # parser metadata
    assert payload["data"]["tx"]["amount"] == "5500.00"
    assert payload["data"]["tx"]["mmex_status"] == "pending"
    assert payload["data"]["tx"]["tags"] == ["Personal-R", "cafe"]


def test_quickadd_create_dedup_returns_existing(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    first = parse(run_cli("quickadd", "create", "--db", str(db), *BASE_ARGS))
    second_result = run_cli("quickadd", "create", "--db", str(db), *BASE_ARGS)
    second = parse(second_result)

    assert second_result.returncode == 0
    assert second["ok"] is True
    assert second["data"]["created"] is False
    assert second["data"]["tx_uid"] == first["data"]["tx_uid"]
    assert second["warnings"], "Dedup must surface a warning"


def test_quickadd_invalid_owner_returns_validation(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    args = list(BASE_ARGS)
    args[args.index("--owner") + 1] = "stranger"
    result = run_cli("quickadd", "create", "--db", str(db), *args)

    payload = parse(result)
    assert result.returncode == 2
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"


def test_quickadd_conflicting_ownership_tag_returns_validation(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    result = run_cli(
        "quickadd",
        "create",
        "--db",
        str(db),
        *BASE_ARGS,
        "--tags",
        "Conjunto",
    )

    payload = parse(result)
    assert result.returncode == 2
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"
    assert "conflicts with owner ricardo" in payload["errors"][0]["message"]


def test_quickadd_invalid_date_returns_validation(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    args = list(BASE_ARGS)
    args[args.index("--date") + 1] = "15/04/2026"
    result = run_cli("quickadd", "create", "--db", str(db), *args)

    payload = parse(result)
    assert result.returncode == 2
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"
    assert payload["errors"][0]["details"]["field"] == "--date"


def test_quickadd_invalid_amount_returns_validation(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    args = list(BASE_ARGS)
    args[args.index("--amount") + 1] = "0"
    result = run_cli("quickadd", "create", "--db", str(db), *args)

    payload = parse(result)
    assert result.returncode == 2
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"


def test_quickadd_help_emits_envelope() -> None:
    result = run_cli("quickadd", "--help")
    payload = parse(result)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert "create" in payload["data"]["help"]
