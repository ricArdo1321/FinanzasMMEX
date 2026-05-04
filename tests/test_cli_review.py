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
    assert result.returncode == 0, result.stdout
    return db


def quickadd_basic(db: Path, *, merchant: str = "Cafe Lola") -> dict:
    result = run_cli(
        "quickadd",
        "create",
        "--db",
        str(db),
        "--owner",
        "ricardo",
        "--account-alias",
        "BE_Ricardo_RUT",
        "--amount",
        "10000",
        "--direction",
        "debit",
        "--date",
        "2026-04-15",
        "--merchant-raw",
        merchant,
    )
    assert result.returncode == 0, result.stdout
    return parse(result)


def test_review_list_returns_envelope(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    result = run_cli("review", "list", "--db", str(db))

    payload = parse(result)
    assert result.returncode == 0
    assert payload["ok"] is True
    assert payload["data"]["count"] == 0
    assert payload["data"]["items"] == []
    assert payload["errors"] == []
    assert payload["run_id"]


def test_review_list_filters_by_status_and_owner(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    quickadd_basic(db, merchant="Tx One")

    result = run_cli(
        "review",
        "list",
        "--db",
        str(db),
        "--status",
        "pending",
        "--owner",
        "ricardo",
    )
    payload = parse(result)
    assert result.returncode == 0
    assert payload["data"]["count"] == 1
    assert payload["data"]["items"][0]["owner"] == "ricardo"
    assert payload["data"]["items"][0]["mmex_status"] == "pending"


def test_review_list_invalid_status_returns_validation(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    result = run_cli("review", "list", "--db", str(db), "--status", "bogus")

    payload = parse(result)
    assert result.returncode == 2
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"


def test_review_update_applies_fields(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    created = quickadd_basic(db)
    tx_uid = created["data"]["tx_uid"]

    result = run_cli(
        "review",
        "update",
        "--db",
        str(db),
        "--tx-uid",
        tx_uid,
        "--category-guess",
        "Cafes",
        "--needs-review",
        "true",
        "--tags",
        "joint, personal",
    )
    payload = parse(result)
    assert result.returncode == 0, result.stdout
    assert "category_guess" in payload["data"]["updated_fields"]
    assert "needs_review" in payload["data"]["updated_fields"]
    assert payload["data"]["tx"]["category_guess"] == "Cafes"
    assert payload["data"]["tx"]["needs_review"] is True
    assert payload["data"]["tx"]["tags"] == ["joint", "personal"]


def test_review_update_unknown_tx_returns_validation(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    result = run_cli(
        "review",
        "update",
        "--db",
        str(db),
        "--tx-uid",
        "ghost",
        "--category-guess",
        "X",
    )
    payload = parse(result)
    assert result.returncode == 2
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"
    assert payload["errors"][0]["details"]["tx_uid"] == "ghost"


def test_review_update_without_fields_returns_validation(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    created = quickadd_basic(db)
    tx_uid = created["data"]["tx_uid"]

    result = run_cli("review", "update", "--db", str(db), "--tx-uid", tx_uid)
    payload = parse(result)
    assert result.returncode == 2
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"


def test_review_resolve_changes_status(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    created = quickadd_basic(db)
    tx_uid = created["data"]["tx_uid"]

    result = run_cli(
        "review",
        "resolve",
        "--db",
        str(db),
        "--tx-uid",
        tx_uid,
        "--status",
        "exported",
    )
    payload = parse(result)
    assert result.returncode == 0
    assert payload["data"]["mmex_status"] == "exported"

    # subsequent list filtered by 'exported' returns the row
    listing = parse(
        run_cli("review", "list", "--db", str(db), "--status", "exported")
    )
    assert listing["data"]["count"] == 1


def test_review_resolve_invalid_status_returns_validation(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    created = quickadd_basic(db)
    tx_uid = created["data"]["tx_uid"]

    result = run_cli(
        "review",
        "resolve",
        "--db",
        str(db),
        "--tx-uid",
        tx_uid,
        "--status",
        "pending",  # not in RESOLVE_STATUSES
    )
    payload = parse(result)
    assert result.returncode == 2
    assert payload["errors"][0]["code"] == "VALIDATION_ERROR"
