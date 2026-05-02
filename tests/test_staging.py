import sqlite3
from decimal import Decimal

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
    assert res[0] == 1
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
