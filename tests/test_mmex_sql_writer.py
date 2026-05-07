import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from finanzasmmex.models import CanonicalTx
from finanzasmmex.writer.mmex_sql import (
    MmexLockedError,
    MmexMappingError,
    MmexSafetyError,
    MmexSchemaError,
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


def make_transfer_pair() -> tuple[CanonicalTx, CanonicalTx]:
    debit_uid = str(uuid4())
    credit_uid = str(uuid4())
    debit = CanonicalTx(
        tx_uid=debit_uid,
        owner="ricardo",
        source_type="email",
        source_ref="TRF-1",
        content_sha256="hash-debit",
        posted_date=date(2026, 5, 2),
        amount=Decimal("50000.00"),
        direction="debit",
        account_alias="BE_Ricardo_1234",
        to_account_alias="BE_Laura_1234",
        merchant_raw="Transferencia",
        merchant_norm="TRANSFERENCIA",
        tx_type="internal_transfer",
        parser_name="be_email_v1",
        parser_version="1.0",
        fitid_synthetic="fitid-debit-001",
        transfer_pair_uid=credit_uid,
    )
    credit = CanonicalTx(
        tx_uid=credit_uid,
        owner="ricardo",
        source_type="email",
        source_ref="TRF-2",
        content_sha256="hash-credit",
        posted_date=date(2026, 5, 2),
        amount=Decimal("50000.00"),
        direction="credit",
        account_alias="BE_Laura_1234",
        to_account_alias="BE_Ricardo_1234",
        merchant_raw="Transferencia",
        merchant_norm="TRANSFERENCIA",
        tx_type="internal_transfer",
        parser_name="be_email_v1",
        parser_version="1.0",
        fitid_synthetic="fitid-credit-001",
        transfer_pair_uid=debit_uid,
    )
    return debit, credit


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
            CREATE TABLE TAG_V1 (
                TAGID INTEGER PRIMARY KEY,
                TAGNAME TEXT NOT NULL UNIQUE,
                ACTIVE INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE TAGLINK_V1 (
                TAGLINKID INTEGER PRIMARY KEY,
                REFTYPE TEXT NOT NULL,
                REFID INTEGER NOT NULL,
                TAGID INTEGER NOT NULL
            );
            INSERT INTO ACCOUNTLIST_V1 (ACCOUNTID, ACCOUNTNAME)
            VALUES (10, 'BE_Ricardo_1234');
            INSERT INTO ACCOUNTLIST_V1 (ACCOUNTID, ACCOUNTNAME)
            VALUES (20, 'BE_Laura_1234');
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


@pytest.mark.parametrize(
    "name",
    [
        "Finanza.mmb",
        "FINANZA.MMB",
        "finanza_backup.mmb",
        "Finanza_2026.mmb",
        "finanza.MMB",
    ],
)
def test_write_sql_rejects_disguised_productive_names(tmp_path, name) -> None:
    target = tmp_path / name
    target.touch()
    with pytest.raises(MmexSafetyError, match="productive"):
        write_sql(
            [make_tx()],
            mmex_db_path=target,
            backup_dir=tmp_path / "backups",
            allow_shadow_write=True,
        )


def test_write_sql_blocks_when_reconcile_off(tmp_path) -> None:
    from finanzasmmex.staging.repo import StagingRepo

    schema = Path("src/finanzasmmex/staging/schema.sql")
    staging_db = tmp_path / "staging.db"
    repo = StagingRepo(str(staging_db))
    repo.init_db(str(schema))
    with sqlite3.connect(staging_db) as sconn:
        sconn.execute(
            """
            INSERT INTO reconcile_log (
                account_alias, period_start, period_end,
                balance_initial, balance_final,
                sum_credits, sum_debits, expected_final,
                status, delta
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "BE_Ricardo_1234",
                "2026-04-01",
                "2026-04-30",
                0.0,
                100.0,
                100.0,
                0.0,
                100.0,
                "off",
                0.0,
            ),
        )
        sconn.commit()

    mmex = tmp_path / "finanza_test.mmb"
    create_mmex_db(mmex)
    with pytest.raises(MmexSafetyError, match="reconcile_log"):
        write_sql(
            [make_tx()],
            mmex_db_path=mmex,
            backup_dir=tmp_path / "backups",
            allow_shadow_write=True,
            staging_repo=repo,
        )

    with sqlite3.connect(mmex) as conn:
        tx_count = conn.execute(
            "SELECT COUNT(*) FROM CHECKINGACCOUNT_V1"
        ).fetchone()[0]
    assert tx_count == 0
    backup_dir = tmp_path / "backups"
    assert (
        not backup_dir.exists() or not list(backup_dir.iterdir())
    ), "Refused write must not create backup files"


def test_resolve_account_falls_back_to_card_last4(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    create_mmex_db(mmex)
    # MMEX has the account under a different name; staging alias does not match.
    with sqlite3.connect(mmex) as conn:
        conn.execute("DELETE FROM ACCOUNTLIST_V1")
        conn.execute(
            "INSERT INTO ACCOUNTLIST_V1 (ACCOUNTID, ACCOUNTNAME) VALUES (?, ?)",
            (20, "BE Ricardo Cuenta_1234"),
        )
        conn.commit()

    tx = CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="hash-card",
        posted_date=date(2026, 5, 2),
        amount=Decimal("12340.00"),
        direction="debit",
        account_alias="BE_Ricardo_1234",  # exact lookup will miss
        card_last4="1234",
        merchant_raw="COMERCIO DEMO",
        merchant_norm="COMERCIO DEMO",
        tx_type="purchase",
        category_guess="Compras",
        parser_name="be_email_v1",
        parser_version="1.0",
        fitid_synthetic="fitid-card",
    )
    summary = write_sql(
        [tx],
        mmex_db_path=mmex,
        backup_dir=tmp_path / "backups",
        allow_shadow_write=True,
    )
    assert summary.items_inserted == 1
    assert summary.mmex_account_ids[tx.tx_uid] == 20


def test_resolve_account_ambiguous_last4_raises(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    create_mmex_db(mmex)
    with sqlite3.connect(mmex) as conn:
        conn.execute("DELETE FROM ACCOUNTLIST_V1")
        conn.executemany(
            "INSERT INTO ACCOUNTLIST_V1 (ACCOUNTID, ACCOUNTNAME) VALUES (?, ?)",
            [(20, "BE_Ricardo_1234"), (21, "BE_Laura_1234")],
        )
        conn.commit()

    tx = CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="hash-amb",
        posted_date=date(2026, 5, 2),
        amount=Decimal("12340.00"),
        direction="debit",
        account_alias="BE_Joint_1234",  # exact miss
        card_last4="1234",
        merchant_raw="COMERCIO DEMO",
        merchant_norm="COMERCIO DEMO",
        tx_type="purchase",
        parser_name="be_email_v1",
        parser_version="1.0",
        fitid_synthetic="fitid-amb",
    )
    with pytest.raises(MmexMappingError, match="ambiguous by last4"):
        write_sql(
            [tx],
            mmex_db_path=mmex,
            backup_dir=tmp_path / "backups",
            allow_shadow_write=True,
        )


def test_sync_hash_field_collision_raises_schema_error(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    create_mmex_db(mmex)
    # Pre-existing customfield with case-variant name should block the run
    # rather than silently create a second sync_hash field.
    with sqlite3.connect(mmex) as conn:
        conn.execute(
            "INSERT INTO CUSTOMFIELD_V1 (FIELDID, REFTYPE, DESCRIPTION) "
            "VALUES (?, ?, ?)",
            (50, "Transaction", "Sync_Hash"),
        )
        conn.commit()

    with pytest.raises(MmexSchemaError, match="different casing"):
        write_sql(
            [make_tx()],
            mmex_db_path=mmex,
            backup_dir=tmp_path / "backups",
            allow_shadow_write=True,
        )


def test_sync_hash_unique_index_enforces_dedup(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    create_mmex_db(mmex)
    write_sql(
        [make_tx(fitid="dup-1")],
        mmex_db_path=mmex,
        backup_dir=tmp_path / "backups",
        allow_shadow_write=True,
    )
    # The partial UNIQUE INDEX on (FIELDID, CONTENT) must exist and block
    # any out-of-band manual duplicate insertion of the same sync_hash.
    with sqlite3.connect(mmex) as conn:
        field_id = conn.execute(
            "SELECT FIELDID FROM CUSTOMFIELD_V1 WHERE DESCRIPTION = 'sync_hash'"
        ).fetchone()[0]
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert f"uq_finanzasmmex_sync_hash_{field_id}" in indexes
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO CUSTOMFIELDDATA_V1 (FIELDID, REFID, CONTENT) "
                "VALUES (?, ?, ?)",
                (field_id, 99, "dup-1"),
            )


def test_apply_tags_links_unique_tags(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    create_mmex_db(mmex)

    tx = CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="hash-tags",
        posted_date=date(2026, 5, 2),
        amount=Decimal("12340.00"),
        direction="debit",
        account_alias="BE_Ricardo_1234",
        merchant_raw="COMERCIO DEMO",
        merchant_norm="COMERCIO DEMO",
        tx_type="purchase",
        parser_name="be_email_v1",
        parser_version="1.0",
        fitid_synthetic="fitid-tags",
        tags=["joint", "personal", "joint", " "],  # duplicates + blanks
    )
    summary = write_sql(
        [tx],
        mmex_db_path=mmex,
        backup_dir=tmp_path / "backups",
        allow_shadow_write=True,
    )
    assert summary.items_inserted == 1
    mmex_tx_id = summary.mmex_tx_ids[tx.tx_uid]

    with sqlite3.connect(mmex) as conn:
        tags = sorted(
            row[0]
            for row in conn.execute(
                "SELECT TAGNAME FROM TAG_V1 ORDER BY TAGNAME"
            ).fetchall()
        )
        links = conn.execute(
            "SELECT COUNT(*) FROM TAGLINK_V1 WHERE REFID = ? AND REFTYPE = ?",
            (mmex_tx_id, "Transaction"),
        ).fetchone()[0]
    assert tags == ["joint", "personal"]
    assert links == 2


def test_resolve_account_last4_does_not_match_via_wildcard_underscore(tmp_path) -> None:
    """LIKE '%_1234' must treat '_' as literal, not as the SQL single-char wildcard.

    Without ESCAPE, an account named 'Productive_finanza_X1234' would match
    last4='1234' and silently route a tx to the wrong account.
    """
    mmex = tmp_path / "finanza_test.mmb"
    create_mmex_db(mmex)
    with sqlite3.connect(mmex) as conn:
        conn.execute("DELETE FROM ACCOUNTLIST_V1")
        conn.execute(
            "INSERT INTO ACCOUNTLIST_V1 (ACCOUNTID, ACCOUNTNAME) VALUES (?, ?)",
            (30, "DecoyX1234"),
        )
        conn.commit()

    tx = CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="hash-wild",
        posted_date=date(2026, 5, 2),
        amount=Decimal("12340.00"),
        direction="debit",
        account_alias="BE_Ricardo_1234",
        card_last4="1234",
        merchant_raw="COMERCIO DEMO",
        merchant_norm="COMERCIO DEMO",
        tx_type="purchase",
        parser_name="be_email_v1",
        parser_version="1.0",
        fitid_synthetic="fitid-wild",
    )
    with pytest.raises(MmexMappingError, match="not found"):
        write_sql(
            [tx],
            mmex_db_path=mmex,
            backup_dir=tmp_path / "backups",
            allow_shadow_write=True,
        )


def test_partial_unique_index_recreated_after_field_recreation(tmp_path) -> None:
    """If MMEX deletes and recreates the sync_hash field, the next run must
    drop the stale partial index and create a fresh one for the new id.
    """
    mmex = tmp_path / "finanza_test.mmb"
    create_mmex_db(mmex)
    write_sql(
        [make_tx(fitid="run-1")],
        mmex_db_path=mmex,
        backup_dir=tmp_path / "backups",
        allow_shadow_write=True,
    )

    with sqlite3.connect(mmex) as conn:
        old_id = conn.execute(
            "SELECT FIELDID FROM CUSTOMFIELD_V1 WHERE DESCRIPTION = 'sync_hash'"
        ).fetchone()[0]
        # Simulate user deleting the sync_hash field in MMEX (along with
        # any rows that referenced it) and recreating it with a new id.
        conn.execute("DELETE FROM CUSTOMFIELDDATA_V1 WHERE FIELDID = ?", (old_id,))
        conn.execute("DELETE FROM CUSTOMFIELD_V1 WHERE FIELDID = ?", (old_id,))
        conn.commit()

    write_sql(
        [make_tx(fitid="run-2")],
        mmex_db_path=mmex,
        backup_dir=tmp_path / "backups",
        allow_shadow_write=True,
    )

    with sqlite3.connect(mmex) as conn:
        new_id = conn.execute(
            "SELECT FIELDID FROM CUSTOMFIELD_V1 WHERE DESCRIPTION = 'sync_hash'"
        ).fetchone()[0]
        indexes = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name LIKE 'uq_finanzasmmex_sync_hash%'"
            ).fetchall()
        ]
    # Old per-field index dropped, new one created for new field id.
    assert f"uq_finanzasmmex_sync_hash_{new_id}" in indexes
    assert all(name == f"uq_finanzasmmex_sync_hash_{new_id}" for name in indexes), (
        f"Stale per-field indexes survived: {indexes}"
    )


def test_transfer_inserts_one_mmex_row(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    backups = tmp_path / "backups"
    create_mmex_db(mmex)
    debit, credit = make_transfer_pair()

    summary = write_sql(
        [debit, credit],
        mmex_db_path=mmex,
        backup_dir=backups,
        allow_shadow_write=True,
    )

    assert summary.items_inserted == 1
    assert summary.items_rejected_unsupported == 0

    with sqlite3.connect(mmex) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM CHECKINGACCOUNT_V1").fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["TRANSCODE"] == "Transfer"
    assert row["ACCOUNTID"] == 10    # BE_Ricardo_1234
    assert row["TOACCOUNTID"] == 20  # BE_Laura_1234
    assert row["TRANSAMOUNT"] == "50000.00"
    assert row["TOTRANSAMOUNT"] == "50000.00"


def test_transfer_idempotent(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    backups = tmp_path / "backups"
    create_mmex_db(mmex)
    debit, credit = make_transfer_pair()

    first = write_sql(
        [debit, credit],
        mmex_db_path=mmex,
        backup_dir=backups,
        allow_shadow_write=True,
    )
    second = write_sql(
        [debit, credit],
        mmex_db_path=mmex,
        backup_dir=backups,
        allow_shadow_write=True,
    )

    assert first.items_inserted == 1
    assert second.items_inserted == 0
    assert second.items_skipped_duplicate == 1

    with sqlite3.connect(mmex) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM CHECKINGACCOUNT_V1"
        ).fetchone()[0]
    assert count == 1


def test_transfer_incomplete_pair_rejected(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    backups = tmp_path / "backups"
    create_mmex_db(mmex)
    debit, _ = make_transfer_pair()  # credit leg absent from batch

    summary = write_sql(
        [debit],
        mmex_db_path=mmex,
        backup_dir=backups,
        allow_shadow_write=True,
    )

    assert summary.items_inserted == 0
    assert summary.items_rejected_unsupported == 1

    with sqlite3.connect(mmex) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM CHECKINGACCOUNT_V1"
        ).fetchone()[0]
    assert count == 0


def test_transfer_rollback_on_mapping_error(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    backups = tmp_path / "backups"
    create_mmex_db(mmex)
    debit, credit = make_transfer_pair()
    # to_account_alias points to an account that doesn't exist in this MMEX
    from dataclasses import replace as dc_replace
    debit_bad = dc_replace(debit, to_account_alias="NONEXISTENT_ACCOUNT")
    credit_bad = dc_replace(credit, to_account_alias="BE_Ricardo_1234")

    with pytest.raises(MmexMappingError):
        write_sql(
            [debit_bad, credit_bad],
            mmex_db_path=mmex,
            backup_dir=backups,
            allow_shadow_write=True,
        )

    with sqlite3.connect(mmex) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM CHECKINGACCOUNT_V1"
        ).fetchone()[0]
    assert count == 0


def test_transfer_both_staging_tx_uids_in_summary(tmp_path) -> None:
    mmex = tmp_path / "finanza_test.mmb"
    backups = tmp_path / "backups"
    create_mmex_db(mmex)
    debit, credit = make_transfer_pair()

    summary = write_sql(
        [debit, credit],
        mmex_db_path=mmex,
        backup_dir=backups,
        allow_shadow_write=True,
    )

    # Both staging tx_uids must appear in mmex_tx_ids, mapped to the same MMEX row
    assert debit.tx_uid in summary.mmex_tx_ids
    assert credit.tx_uid in summary.mmex_tx_ids
    assert summary.mmex_tx_ids[debit.tx_uid] == summary.mmex_tx_ids[credit.tx_uid]
