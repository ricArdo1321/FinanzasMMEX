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


def quickadd_basic(
    db: Path,
    *,
    merchant: str = "Cafe Lola",
    owner: str = "ricardo",
    account_alias: str = "BE_Ricardo_RUT",
    tags: str | None = None,
) -> dict:
    args = [
        "quickadd",
        "create",
        "--db",
        str(db),
        "--owner",
        owner,
        "--account-alias",
        account_alias,
        "--amount",
        "10000",
        "--direction",
        "debit",
        "--date",
        "2026-04-15",
        "--merchant-raw",
        merchant,
    ]
    if tags is not None:
        args.extend(["--tags", tags])
    result = run_cli(*args)
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


def test_review_list_filters_by_source_category_and_merchant(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    cafe = quickadd_basic(db, merchant="Cafe Lola")
    pharmacy = quickadd_basic(db, merchant="Farmacia Norte")
    run_cli(
        "review",
        "update",
        "--db",
        str(db),
        "--tx-uid",
        cafe["data"]["tx_uid"],
        "--category-guess",
        "Cafes",
    )
    run_cli(
        "review",
        "update",
        "--db",
        str(db),
        "--tx-uid",
        pharmacy["data"]["tx_uid"],
        "--category-guess",
        "Salud",
    )

    result = run_cli(
        "review",
        "list",
        "--db",
        str(db),
        "--source-type",
        "manual",
        "--category",
        "Cafes",
        "--merchant",
        "Cafe",
    )

    payload = parse(result)
    assert result.returncode == 0, result.stdout
    assert payload["data"]["count"] == 1
    assert payload["data"]["items"][0]["tx_uid"] == cafe["data"]["tx_uid"]
    assert payload["data"]["filters"]["source_type"] == "manual"
    assert payload["data"]["filters"]["category"] == "Cafes"
    assert payload["data"]["filters"]["merchant"] == "Cafe"


def test_review_list_filters_by_normalized_tag(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    ricardo = quickadd_basic(db, merchant="Cafe Ricardo", tags="personal-r,cafes")
    quickadd_basic(
        db,
        merchant="Cafe Laura",
        owner="laura",
        account_alias="BE_Laura_RUT",
        tags="Personal-L,cafes",
    )

    result = run_cli(
        "review",
        "list",
        "--db",
        str(db),
        "--tag",
        "Personal_R",
    )

    payload = parse(result)
    assert result.returncode == 0, result.stdout
    assert payload["data"]["count"] == 1
    assert payload["data"]["items"][0]["tx_uid"] == ricardo["data"]["tx_uid"]
    assert payload["data"]["items"][0]["tags"] == ["Personal-R", "cafes"]
    assert payload["data"]["filters"]["tag"] == "Personal-R"


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
        "personal-r, personal",
    )
    payload = parse(result)
    assert result.returncode == 0, result.stdout
    updated_fields = payload["data"]["updated_fields"]
    assert "category_guess" in updated_fields
    assert "needs_review" in updated_fields
    # Public field name "tags" must surface, never the internal "tags_json".
    assert "tags" in updated_fields
    assert "tags_json" not in updated_fields
    assert payload["data"]["tx"]["category_guess"] == "Cafes"
    assert payload["data"]["tx"]["needs_review"] is True
    assert payload["data"]["tx"]["tags"] == ["Personal-R", "personal"]


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


def test_review_bulk_update_applies_valid_batch(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    created = quickadd_basic(db)
    batch = tmp_path / "bulk-update.json"
    batch.write_text(
        json.dumps(
            [
                {
                    "tx_uid": created["data"]["tx_uid"],
                    "category_guess": "Cafes",
                    "tags": ["Personal-R", "personal"],
                    "needs_review": True,
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "review",
        "bulk-update",
        "--db",
        str(db),
        "--input",
        str(batch),
    )

    payload = parse(result)
    assert result.returncode == 0, result.stdout
    assert payload["ok"] is True
    assert payload["data"]["items_total"] == 1
    assert payload["data"]["items_ok"] == 1
    row = payload["data"]["results"][0]
    assert row["ok"] is True
    assert row["updated_fields"] == ["category_guess", "needs_review", "tags"]
    assert row["tx"]["category_guess"] == "Cafes"
    assert row["tx"]["tags"] == ["Personal-R", "personal"]
    assert row["tx"]["needs_review"] is True


def test_review_bulk_update_rejects_conflicting_ownership_tag(
    tmp_path: Path,
) -> None:
    db = init_db(tmp_path)
    created = quickadd_basic(db)
    batch = tmp_path / "bulk-update-conflict.json"
    batch.write_text(
        json.dumps(
            [
                {
                    "tx_uid": created["data"]["tx_uid"],
                    "tags": ["Conjunto"],
                }
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "review", "bulk-update", "--db", str(db), "--input", str(batch)
    )
    payload = parse(result)
    assert result.returncode == 2
    assert payload["data"]["results"][0]["ok"] is False
    assert "conflicts with owner ricardo" in payload["data"]["results"][0]["error"][
        "message"
    ]


def test_review_bulk_update_reports_missing_tx(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    batch = tmp_path / "bulk-update-missing.json"
    batch.write_text(
        json.dumps([{"tx_uid": "ghost", "category_guess": "Cafes"}]),
        encoding="utf-8",
    )

    result = run_cli(
        "review",
        "bulk-update",
        "--db",
        str(db),
        "--input",
        str(batch),
    )

    payload = parse(result)
    assert result.returncode == 2
    assert payload["ok"] is False
    assert payload["errors"][0]["code"] == "BULK_PARTIAL_FAILURE"
    assert payload["data"]["items_error"] == 1
    row = payload["data"]["results"][0]
    assert row["tx_uid"] == "ghost"
    assert row["ok"] is False
    assert row["error"]["message"] == "Transaction not found"


def test_review_bulk_resolve_reports_invalid_status(tmp_path: Path) -> None:
    db = init_db(tmp_path)
    created = quickadd_basic(db)
    batch = tmp_path / "bulk-resolve-invalid.json"
    batch.write_text(
        json.dumps([{"tx_uid": created["data"]["tx_uid"], "status": "pending"}]),
        encoding="utf-8",
    )

    result = run_cli(
        "review",
        "bulk-resolve",
        "--db",
        str(db),
        "--input",
        str(batch),
    )

    payload = parse(result)
    assert result.returncode == 2
    assert payload["data"]["items_error"] == 1
    row = payload["data"]["results"][0]
    assert row["ok"] is False
    assert row["error"]["details"]["field"] == "status"


def test_review_bulk_resolve_mixed_partial_applies_valid_rows(
    tmp_path: Path,
) -> None:
    db = init_db(tmp_path)
    first = quickadd_basic(db, merchant="Primera")
    second = quickadd_basic(db, merchant="Segunda")
    first_uid = first["data"]["tx_uid"]
    batch = tmp_path / "bulk-resolve-partial.json"
    batch.write_text(
        json.dumps(
            [
                {"tx_uid": first_uid, "status": "exported"},
                {"tx_uid": "ghost", "status": "rejected"},
            ]
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "review",
        "bulk-resolve",
        "--db",
        str(db),
        "--input",
        str(batch),
    )

    payload = parse(result)
    assert result.returncode == 2
    assert payload["ok"] is False
    assert payload["data"]["items_ok"] == 1
    assert payload["data"]["items_error"] == 1
    assert payload["data"]["results"][0]["tx"]["mmex_status"] == "exported"
    assert payload["data"]["results"][1]["error"]["message"] == "Transaction not found"

    exported = parse(run_cli("review", "list", "--db", str(db), "--status", "exported"))
    pending = parse(run_cli("review", "list", "--db", str(db), "--status", "pending"))
    assert exported["data"]["count"] == 1
    assert pending["data"]["count"] == 1
    assert pending["data"]["items"][0]["tx_uid"] == second["data"]["tx_uid"]
