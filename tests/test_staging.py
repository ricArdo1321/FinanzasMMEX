import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from finanzasmmex.models import CanonicalTx
from finanzasmmex.staging.repo import StagingRepo


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_staging.db"
    return str(db_path)


@pytest.fixture
def repo(temp_db):
    r = StagingRepo(temp_db)
    schema_path = "src/finanzasmmex/staging/schema.sql"
    r.init_db(schema_path)
    return r


def test_db_initialization(temp_db):
    repo = StagingRepo(temp_db)
    schema_path = "src/finanzasmmex/staging/schema.sql"
    repo.init_db(schema_path)

    conn = sqlite3.connect(temp_db)
    res = conn.execute("SELECT version FROM schema_version").fetchone()
    assert res[0] == 2
    conn.close()


def test_upsert_and_get_pending(repo):
    tx = CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="hash123",
        amount=Decimal("100.50"),
        account_alias="BE_Main",
        tx_type="purchase",
        parser_name="test_parser",
        fitid_synthetic="fitid_1",
    )

    repo.upsert_tx(tx)
    pending = repo.get_pending_txs()

    assert len(pending) == 1
    assert pending[0].fitid_synthetic == "fitid_1"
    assert pending[0].amount == Decimal("100.50")


def test_upsert_idempotency(repo):
    tx = CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="hash123",
        amount=Decimal("100.50"),
        account_alias="BE_Main",
        tx_type="purchase",
        parser_name="test_parser",
        fitid_synthetic="fitid_1",
    )

    repo.upsert_tx(tx)
    # Re-upsert should not create new record
    repo.upsert_tx(tx)

    with repo._get_connection() as conn:
        count = conn.execute("SELECT COUNT(*) FROM canonical_tx").fetchone()[0]
    assert count == 1


def test_upsert_conflict_preserves_reviewed_canonical_fields(repo):
    tx = CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="hash123",
        amount=Decimal("100.50"),
        account_alias="BE_Main",
        merchant_raw="Original",
        category_guess="Cafe",
        tx_type="purchase",
        parser_name="test_parser",
        fitid_synthetic="fitid_1",
        needs_review=True,
        mmex_status="pending",
    )
    changed = CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="hash999",
        amount=Decimal("999.99"),
        account_alias="BE_Other",
        merchant_raw="Changed",
        category_guess="Changed",
        tx_type="purchase",
        parser_name="test_parser",
        fitid_synthetic="fitid_1",
        needs_review=False,
        mmex_status="exported",
    )

    repo.upsert_tx(tx)
    repo.upsert_tx(changed)

    stored = repo.get_tx_by_fitid("fitid_1")
    assert stored is not None
    assert stored.amount == Decimal("100.5")
    assert stored.account_alias == "BE_Main"
    assert stored.merchant_raw == "Original"
    assert stored.category_guess == "Cafe"
    assert stored.needs_review is True
    assert stored.mmex_status == "exported"


def test_mark_inserted_updates_only_mmex_handoff_fields(repo):
    tx = CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="hash123",
        amount=Decimal("100.50"),
        account_alias="BE_Main",
        merchant_raw="Original",
        category_guess="Cafe",
        tx_type="purchase",
        parser_name="test_parser",
        fitid_synthetic="fitid_1",
    )

    repo.upsert_tx(tx)
    assert repo.mark_inserted(tx.tx_uid, mmex_account_id=10, mmex_tx_id=99)

    stored = repo.get_tx(tx.tx_uid)
    assert stored is not None
    assert stored.account_alias == "BE_Main"
    assert stored.mmex_status == "inserted"
    assert stored.mmex_account_id == 10
    assert stored.mmex_tx_id == 99


def test_foreign_keys_enabled_for_repo_connections(repo):
    tx = CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="hash123",
        amount=Decimal("100.50"),
        account_alias="BE_Main",
        tx_type="purchase",
        parser_name="test_parser",
        fitid_synthetic="fitid_1",
        transfer_pair_uid="missing-parent",
    )

    with pytest.raises(sqlite3.IntegrityError):
        repo.upsert_tx(tx)


def test_upsert_and_retrieve_to_account_alias(tmp_path) -> None:
    repo = StagingRepo(str(tmp_path / "staging.db"))
    schema = Path(__file__).parent.parent / "src/finanzasmmex/staging/schema.sql"
    repo.init_db(str(schema))

    # Create the parent transaction to satisfy FK constraint
    parent_tx = CanonicalTx(
        tx_uid="pair-001",
        owner="ricardo",
        source_type="email",
        content_sha256="parent123",
        amount=Decimal("50000.00"),
        direction="credit",
        account_alias="MACH_R",
        merchant_raw="Transferencia",
        tx_type="internal_transfer",
        parser_name="be_email_v1",
        fitid_synthetic="fitid-transfer-pair",
    )
    repo.upsert_tx(parent_tx)

    # Create the linked transaction with to_account_alias
    tx = CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="abc123",
        amount=Decimal("50000.00"),
        direction="debit",
        account_alias="BE_R",
        merchant_raw="Transferencia",
        tx_type="internal_transfer",
        parser_name="be_email_v1",
        fitid_synthetic="fitid-transfer-1",
        transfer_pair_uid="pair-001",
        to_account_alias="MACH_R",
    )
    repo.upsert_tx(tx)
    retrieved = repo.get_tx_by_fitid("fitid-transfer-1")
    assert retrieved is not None
    assert retrieved.to_account_alias == "MACH_R"


def test_list_txs_filters_by_exact_tag(repo) -> None:
    ricardo = CanonicalTx(
        owner="ricardo",
        source_type="email",
        content_sha256="hash-ricardo",
        amount=Decimal("100.50"),
        account_alias="BE_Main",
        tx_type="purchase",
        parser_name="test_parser",
        fitid_synthetic="fitid_ricardo",
        tags=["Personal-R", "cafes"],
    )
    laura = CanonicalTx(
        owner="laura",
        source_type="email",
        content_sha256="hash-laura",
        amount=Decimal("200.50"),
        account_alias="BE_Laura",
        tx_type="purchase",
        parser_name="test_parser",
        fitid_synthetic="fitid_laura",
        tags=["Personal-L", "cafes"],
    )

    repo.upsert_batch([ricardo, laura])

    personal_r = repo.list_txs(tag="Personal-R")
    assert [tx.fitid_synthetic for tx in personal_r] == ["fitid_ricardo"]

    cafes = repo.list_txs(tag="cafes")
    assert {tx.fitid_synthetic for tx in cafes} == {"fitid_ricardo", "fitid_laura"}
