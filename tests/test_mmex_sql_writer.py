import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from finanzasmmex.models import CanonicalTx
from finanzasmmex.writer.mmex_sql import (
    MmexLockedError,
    MmexMappingError,
    MmexSafetyError,
    write_sql,
)


def make_tx(
    *,
    fitid: str = "fitid-demo",
    account_alias: str = "BE_Ricardo_1234",
    needs_review: bool = False,
) -> CanonicalTx:
    return CanonicalTx(
        owner="ricardo",
        source_type="email",
        source_ref="AUTH-1",
        content_sha256="hash123",
        posted_date=date(2026, 5, 2),
        amount=Decimal("12340.00"),
        direction="debit",
        account_alias=account_alias,
        merchant_raw="COMERCIO DEMO",
        merchant_norm="COMERCIO DEMO",
        tx_type="purchase",
        category_guess="Compras",
        parser_name="be_email_v1",
        parser_version="1.0",
        fitid_synthetic=fitid,
        needs_review=needs_review,
    )


def create_mmex_db(path) -> None:
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


def test_write_sql_inserts_transaction_and_sync_hash(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    backups = tmp_path / "backups"
    create_mmex_db(mmex)

    summary = write_sql(
        [make_tx()],
        mmex_db_path=mmex,
        backup_dir=backups,
        allow_shadow_write=True,
    )

    assert summary.items_inserted == 1
    assert summary.items_skipped_duplicate == 0
    assert summary.mmex_tx_ids
    assert summary.mmex_account_ids == {next(iter(summary.mmex_tx_ids)): 10}
    assert summary.backup_pre_path is not None
    assert summary.backup_post_path is not None
    assert Path(summary.backup_pre_path).is_file()
    assert Path(summary.backup_post_path).is_file()

    with sqlite3.connect(mmex) as conn:
        tx_count = conn.execute("SELECT COUNT(*) FROM CHECKINGACCOUNT_V1").fetchone()[0]
        sync_hash = conn.execute("""
            SELECT d.CONTENT
            FROM CUSTOMFIELDDATA_V1 d
            JOIN CUSTOMFIELD_V1 f ON f.FIELDID = d.FIELDID
            WHERE f.DESCRIPTION = 'sync_hash'
            """).fetchone()[0]

    assert tx_count == 1
    assert sync_hash == "fitid-demo"


def test_write_sql_is_idempotent_by_customfield_sync_hash(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    backups = tmp_path / "backups"
    create_mmex_db(mmex)

    write_sql(
        [make_tx()],
        mmex_db_path=mmex,
        backup_dir=backups,
        allow_shadow_write=True,
    )
    second = write_sql(
        [make_tx()],
        mmex_db_path=mmex,
        backup_dir=backups,
        allow_shadow_write=True,
    )

    with sqlite3.connect(mmex) as conn:
        tx_count = conn.execute("SELECT COUNT(*) FROM CHECKINGACCOUNT_V1").fetchone()[0]

    assert second.items_inserted == 0
    assert second.items_skipped_duplicate == 1
    assert tx_count == 1


def test_write_sql_rolls_back_when_mapping_fails(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    create_mmex_db(mmex)

    with pytest.raises(MmexMappingError):
        write_sql(
            [make_tx(account_alias="MISSING")],
            mmex_db_path=mmex,
            backup_dir=tmp_path / "backups",
            allow_shadow_write=True,
        )

    with sqlite3.connect(mmex) as conn:
        tx_count = conn.execute("SELECT COUNT(*) FROM CHECKINGACCOUNT_V1").fetchone()[0]

    assert tx_count == 0


def test_write_sql_rejects_productive_or_unapproved_paths(tmp_path) -> None:
    productive = tmp_path / "finanza.mmb"
    productive.touch()
    test_db = tmp_path / "finanza_test.mmb"
    test_db.touch()

    with pytest.raises(MmexSafetyError, match="productive"):
        write_sql(
            [make_tx()],
            mmex_db_path=productive,
            backup_dir=tmp_path / "backups",
            allow_shadow_write=True,
        )
    with pytest.raises(MmexSafetyError, match="explicit"):
        write_sql(
            [make_tx()],
            mmex_db_path=test_db,
            backup_dir=tmp_path / "backups",
            allow_shadow_write=False,
        )


def test_write_sql_skips_needs_review_without_touching_mmex(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    create_mmex_db(mmex)

    summary = write_sql(
        [make_tx(needs_review=True)],
        mmex_db_path=mmex,
        backup_dir=tmp_path / "backups",
        allow_shadow_write=True,
    )

    with sqlite3.connect(mmex) as conn:
        tx_count = conn.execute("SELECT COUNT(*) FROM CHECKINGACCOUNT_V1").fetchone()[0]

    assert summary.items_inserted == 0
    assert summary.items_rejected_review == 1
    assert summary.backup_pre_path is None
    assert tx_count == 0


def test_write_sql_reports_locked_database(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    create_mmex_db(mmex)
    locker = sqlite3.connect(mmex, isolation_level=None)
    try:
        locker.execute("BEGIN EXCLUSIVE")
        with pytest.raises(MmexLockedError):
            write_sql(
                [make_tx()],
                mmex_db_path=mmex,
                backup_dir=tmp_path / "backups",
                allow_shadow_write=True,
            )
    finally:
        locker.rollback()
        locker.close()
