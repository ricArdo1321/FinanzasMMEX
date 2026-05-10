import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

from finanzasmmex.adapters.file_loaders import (
    FileLoaderCorruptError,
    load_drop_file_for_staging,
    parse_csv_file,
    parse_ofx_file,
    parse_pdf_file,
    parse_qif_file,
    parse_xlsx_file,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src" / "finanzasmmex" / "staging" / "schema.sql"
FIXTURES = ROOT / "tests" / "fixtures" / "drop"


def test_parse_ofx_fixture_extracts_signed_transactions() -> None:
    txs = parse_ofx_file(FIXTURES / "sample.ofx")

    assert len(txs) == 2
    assert txs[0].source_type == "ofx"
    assert txs[0].direction == "debit"
    assert str(txs[0].amount) == "12340.00"
    assert txs[0].merchant_norm == "CAFE DEMO"
    assert txs[0].source_ref == "OFX-DEMO-001"
    assert txs[1].direction == "credit"
    assert txs[1].tx_type == "transfer_in"
    assert txs[0].fitid_synthetic is None


def test_parse_qif_fixture_extracts_categories_and_waits_for_etl_fitid() -> None:
    txs = parse_qif_file(FIXTURES / "sample.qif")

    assert len(txs) == 2
    assert txs[0].source_type == "qif"
    assert txs[0].direction == "debit"
    assert txs[0].category_guess == "Alimentacion"
    assert txs[1].direction == "credit"
    assert txs[0].fitid_synthetic is None


def test_parse_csv_fixture_extracts_account_direction_and_tags() -> None:
    txs = parse_csv_file(FIXTURES / "sample.csv")

    assert len(txs) == 2
    assert txs[0].source_type == "csv"
    assert txs[0].account_alias == "BE_Ricardo_1234"
    assert txs[0].direction == "debit"
    assert txs[0].tags == ["personal"]
    assert txs[1].direction == "credit"


def test_csv_missing_account_marks_needs_review(tmp_path: Path) -> None:
    csv_path = tmp_path / "missing_account.csv"
    csv_path.write_text(
        "fecha,monto,comercio,tipo\n10-05-2026,12340,CAFE DEMO,cargo\n",
        encoding="utf-8",
    )

    tx = parse_csv_file(csv_path)[0]

    assert tx.needs_review is True
    assert tx.review_reason == "missing_account_alias"
    assert tx.account_alias == "CSV_IMPORT"


def test_parse_xlsx_fixture_extracts_rows(tmp_path: Path) -> None:
    xlsx_path = tmp_path / "sample.xlsx"
    _write_minimal_xlsx(
        xlsx_path,
        [
            ["fecha", "monto", "comercio", "cuenta", "tipo", "categoria"],
            [
                "10-05-2026", "12340", "CAFE DEMO",
                "BE_Ricardo_1234", "cargo", "Alimentacion",
            ],
            [
                "11-05-2026", "50000", "ABONO DEMO",
                "BE_Ricardo_1234", "abono", "Ingresos",
            ],
        ],
    )

    txs = parse_xlsx_file(xlsx_path)

    assert len(txs) == 2
    assert txs[0].source_type == "xlsx"
    assert txs[0].direction == "debit"
    assert txs[1].direction == "credit"


def test_parse_pdf_fixture_marks_every_transaction_for_review() -> None:
    txs = parse_pdf_file(FIXTURES / "sample.pdf")

    assert len(txs) == 2
    assert txs[0].source_type == "pdf"
    assert txs[0].parser_name == "pdf_file"
    assert txs[0].content_sha256
    assert txs[0].raw_text == ""
    assert txs[0].needs_review is True
    assert txs[0].review_reason == "pdf_review_required"
    assert txs[0].direction == "debit"


def test_pdf_missing_account_keeps_review_reason(tmp_path: Path) -> None:
    pdf_path = tmp_path / "ambiguous.pdf"
    pdf_path.write_text(
        "%PDF-1.4\nfecha;monto;comercio;tipo\n"
        "10-05-2026;12340;CAFE DEMO;cargo\n%%EOF",
        encoding="utf-8",
    )

    tx = parse_pdf_file(pdf_path)[0]

    assert tx.needs_review is True
    assert tx.account_alias == "PDF_IMPORT"
    assert tx.review_reason == "missing_account_alias;pdf_review_required"


def test_pdf_without_supported_table_fails_clearly(tmp_path: Path) -> None:
    pdf_path = tmp_path / "corrupt.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\ncontenido ilegible\n%%EOF")

    try:
        parse_pdf_file(pdf_path)
    except FileLoaderCorruptError as exc:
        assert exc.error_code == "FILE_LOADER_CORRUPT"
        assert "transaction table" in str(exc)
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("corrupt PDF should fail clearly")


def test_drop_loader_prepares_registered_csv_with_fitid() -> None:
    result = load_drop_file_for_staging(FIXTURES / "sample.csv")

    assert result.source_type == "csv"
    assert len(result.transactions) == 2
    assert all(tx.fitid_synthetic for tx in result.transactions)
    assert {tx.source_file for tx in result.transactions} == {
        str(FIXTURES / "sample.csv")
    }


def test_drop_loader_prepares_pdf_with_fitid_and_review() -> None:
    result = load_drop_file_for_staging(FIXTURES / "sample.pdf")

    assert result.source_type == "pdf"
    assert len(result.transactions) == 2
    assert all(tx.fitid_synthetic for tx in result.transactions)
    assert all(tx.needs_review for tx in result.transactions)


def test_cli_drop_csv_is_idempotent_and_records_artifact(tmp_path: Path) -> None:
    db = tmp_path / "staging.db"
    first = _run_cli_drop(db, FIXTURES / "sample.csv")
    second = _run_cli_drop(db, FIXTURES / "sample.csv")

    first_payload = json.loads(first.stdout)
    second_payload = json.loads(second.stdout)
    assert first.returncode == 0, first.stdout
    assert second.returncode == 0, second.stdout
    assert first_payload["data"]["items_processed"] == 2
    assert first_payload["data"]["source_type"] == "csv"
    assert second_payload["data"]["artifact_id"] == first_payload["data"]["artifact_id"]

    with sqlite3.connect(db) as conn:
        tx_count = conn.execute("SELECT COUNT(*) FROM canonical_tx").fetchone()[0]
        raw_count = conn.execute("SELECT COUNT(*) FROM raw_artifacts").fetchone()[0]
        job_count = conn.execute("SELECT COUNT(*) FROM job_runs").fetchone()[0]

    assert tx_count == 2
    assert raw_count == 1
    assert job_count == 2


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


def _write_minimal_xlsx(path: Path, rows: list[list[str]]) -> None:
    strings: list[str] = []
    indexes: dict[str, int] = {}
    for row in rows:
        for value in row:
            if value not in indexes:
                indexes[value] = len(strings)
                strings.append(value)

    shared = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(f"<si><t>{value}</t></si>" for value in strings)
        + "</sst>"
    )
    sheet_rows = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row):
            ref = f"{_column_name(col_index)}{row_index}"
            cells.append(f'<c r="{ref}" t="s"><v>{indexes[value]}</v></c>')
        sheet_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def _column_name(index: int) -> str:
    name = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        name = chr(ord("A") + remainder) + name
    return name
