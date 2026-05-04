# Internal Transfers SQL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable the SQL writer to insert internal transfer pairs as a single MMEX `Transfer` row with correct `ACCOUNTID`/`TOACCOUNTID`, using `to_account_alias` on `CanonicalTx` to expose the destination account without querying staging at write time.

**Architecture:** Add `to_account_alias: str | None` to `CanonicalTx` and `canonical_tx` staging table (schema v2). ETL `_apply_pair` populates it symmetrically on both legs. Writer pre-pass builds `credit_skip` (tx_uids of credit legs to absorb) and `pair_to_credit_uid` (for recording both legs as inserted). Main loop dispatches complete transfer pairs to `_insert_transfer_tx`; incomplete pairs and legacy `transfer_in`/`transfer_out` remain rejected.

**Tech Stack:** Python 3.11, SQLite, pytest, dataclasses (frozen), `dataclasses.replace`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/finanzasmmex/models.py` | Modify | Add `to_account_alias` field |
| `src/finanzasmmex/staging/schema.sql` | Modify | Add column, bump to v2 |
| `src/finanzasmmex/staging/repo.py` | Modify | Add field to `upsert_tx` + `_row_to_tx` |
| `src/finanzasmmex/etl/transfers.py` | Modify | Populate `to_account_alias` in `_apply_pair` |
| `src/finanzasmmex/writer/mmex_sql.py` | Modify | Pre-pass, `_insert_transfer_tx`, updated loop |
| `tests/test_etl_transfers.py` | Modify | 2 new tests for `to_account_alias` |
| `tests/test_mmex_sql_writer.py` | Modify | 5 new tests + updated fixture |

---

### Task 1: CanonicalTx model field

**Files:**
- Modify: `src/finanzasmmex/models.py`
- Test: `tests/test_etl_transfers.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_etl_transfers.py`:

```python
def test_canonical_tx_default_to_account_alias_is_none() -> None:
    tx = _tx(direction="debit", account="BE_R")
    assert tx.to_account_alias is None
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_etl_transfers.py::test_canonical_tx_default_to_account_alias_is_none -v
```
Expected: `AttributeError: 'CanonicalTx' object has no attribute 'to_account_alias'`

- [ ] **Step 3: Add field to CanonicalTx**

In `src/finanzasmmex/models.py`, after line 71 (`transfer_pair_uid: str | None = None`):

```python
    # Destination account alias for internal transfers (populated by ETL)
    to_account_alias: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_etl_transfers.py::test_canonical_tx_default_to_account_alias_is_none -v
```
Expected: PASS

- [ ] **Step 5: Run full suite to check for regressions**

```
pytest --tb=short -q
```
Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/finanzasmmex/models.py tests/test_etl_transfers.py
git commit -m "feat(model): add to_account_alias field to CanonicalTx"
```

---

### Task 2: Staging schema v2 + repo

**Files:**
- Modify: `src/finanzasmmex/staging/schema.sql`
- Modify: `src/finanzasmmex/staging/repo.py`
- Test: `tests/test_staging.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_staging.py` (imports are already present: `CanonicalTx`, `StagingRepo`, `tmp_path`):

```python
def test_upsert_and_retrieve_to_account_alias(tmp_path) -> None:
    repo = StagingRepo(str(tmp_path / "staging.db"))
    schema = Path(__file__).parent.parent / "src/finanzasmmex/staging/schema.sql"
    repo.init_db(str(schema))

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
```

Check existing imports at the top of `tests/test_staging.py`; add `from pathlib import Path` and `from decimal import Decimal` if missing.

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_staging.py::test_upsert_and_retrieve_to_account_alias -v
```
Expected: `OperationalError: table canonical_tx has no column named to_account_alias`

- [ ] **Step 3: Update schema.sql**

In `src/finanzasmmex/staging/schema.sql`:

Change the first comment line:
```sql
-- staging.db schema v1
```
to:
```sql
-- staging.db schema v2
```

Add `to_account_alias TEXT` after `transfer_pair_uid TEXT,` (line ~46):
```sql
    transfer_pair_uid TEXT,
    to_account_alias TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
```

Change `INSERT INTO schema_version (version) VALUES (1)` to:
```sql
INSERT INTO schema_version (version) VALUES (2);
```

> **Note for existing staging.db:** Run this migration manually before using a pre-existing staging.db:
> ```sql
> ALTER TABLE canonical_tx ADD COLUMN to_account_alias TEXT;
> INSERT INTO schema_version (version) VALUES (2);
> ```

- [ ] **Step 4: Update `upsert_tx` in repo.py**

In `src/finanzasmmex/staging/repo.py`, update the INSERT in `upsert_tx`. Change the column list to include `to_account_alias` as the last column:

```python
    sql = """
    INSERT INTO canonical_tx (
        tx_uid, owner, source_type, source_file, source_ref,
        content_sha256, raw_text,
        event_date, booking_date, posted_date, amount, currency, direction,
        account_alias, card_last4, merchant_raw, merchant_norm, tx_type,
        category_guess, subcategory_guess, tags_json, fitid_synthetic,
        parser_name, parser_version, needs_review, review_reason,
        mmex_account_id, mmex_tx_id, mmex_status, transfer_pair_uid,
        to_account_alias
    ) VALUES (
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
    )
    ON CONFLICT(fitid_synthetic) DO UPDATE SET
        mmex_status = excluded.mmex_status,
        updated_at = datetime('now')
    """
    params = (
        tx.tx_uid,
        tx.owner,
        tx.source_type,
        tx.source_file,
        tx.source_ref,
        tx.content_sha256,
        tx.raw_text,
        tx.event_date.isoformat() if tx.event_date else None,
        tx.booking_date.isoformat() if tx.booking_date else None,
        tx.posted_date.isoformat() if tx.posted_date else None,
        float(tx.amount),
        tx.currency,
        tx.direction,
        tx.account_alias,
        tx.card_last4,
        tx.merchant_raw,
        tx.merchant_norm,
        tx.tx_type,
        tx.category_guess,
        tx.subcategory_guess,
        json.dumps(tx.tags),
        tx.fitid_synthetic,
        tx.parser_name,
        tx.parser_version,
        1 if tx.needs_review else 0,
        tx.review_reason,
        tx.mmex_account_id,
        tx.mmex_tx_id,
        tx.mmex_status,
        tx.transfer_pair_uid,
        tx.to_account_alias,
    )
```

- [ ] **Step 5: Update `_row_to_tx` in repo.py**

At the end of the `_row_to_tx` method, add `to_account_alias` after `transfer_pair_uid`:

```python
            transfer_pair_uid=row["transfer_pair_uid"],
            to_account_alias=row["to_account_alias"],
```

- [ ] **Step 6: Run test to verify it passes**

```
pytest tests/test_staging.py::test_upsert_and_retrieve_to_account_alias -v
```
Expected: PASS

- [ ] **Step 7: Run full suite**

```
pytest --tb=short -q
```
Expected: all previously passing tests still pass.

- [ ] **Step 8: Commit**

```bash
git add src/finanzasmmex/staging/schema.sql src/finanzasmmex/staging/repo.py tests/test_staging.py
git commit -m "feat(staging): add to_account_alias column, schema v2"
```

---

### Task 3: ETL transfers — populate to_account_alias

**Files:**
- Modify: `src/finanzasmmex/etl/transfers.py`
- Test: `tests/test_etl_transfers.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_etl_transfers.py`:

```python
def test_link_populates_to_account_alias_symmetrically() -> None:
    a = _tx(direction="debit", account="BE_R", tx_type="transfer_out", tx_uid="a")
    b = _tx(direction="credit", account="MACH_R", tx_type="transfer_in", tx_uid="b")
    out = link_internal_transfers([a, b])
    by_uid = {tx.tx_uid: tx for tx in out}
    assert by_uid["a"].to_account_alias == "MACH_R"
    assert by_uid["b"].to_account_alias == "BE_R"


def test_link_unpaired_tx_leaves_to_account_alias_none() -> None:
    a = _tx(direction="debit", account="BE_R", merchant="Supermercado",
            tx_type="purchase", tx_uid="a")
    out = link_internal_transfers([a])
    assert out[0].to_account_alias is None
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_etl_transfers.py::test_link_populates_to_account_alias_symmetrically tests/test_etl_transfers.py::test_link_unpaired_tx_leaves_to_account_alias_none -v
```
Expected: `AssertionError: assert None == 'MACH_R'`

- [ ] **Step 3: Update `etl/transfers.py`**

Replace the entire file with:

```python
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable
from uuid import uuid4

from ..models import CanonicalTx

_TRANSFER_TX_TYPES = {"transfer_in", "transfer_out", "internal_transfer"}
_TRANSFER_KEYWORDS = ("TRANSFER", "TRANSF", "ABONO", "GIRO ENTRE")
_PAIR_WINDOW = timedelta(days=1)


def link_internal_transfers(txs: Iterable[CanonicalTx]) -> list[CanonicalTx]:
    items = list(txs)
    by_uid: dict[str, CanonicalTx] = {tx.tx_uid: tx for tx in items}

    paired: dict[str, str] = {}          # tx_uid → pair_uid
    to_alias: dict[str, str] = {}        # tx_uid → counterpart account_alias
    consumed: set[str] = set()

    for i, tx_a in enumerate(items):
        if tx_a.tx_uid in consumed:
            continue
        if not _is_transfer_candidate(tx_a):
            continue
        for tx_b in items[i + 1:]:
            if tx_b.tx_uid in consumed:
                continue
            if not _is_pair(tx_a, tx_b):
                continue
            pair_uid = tx_a.transfer_pair_uid or tx_b.transfer_pair_uid or str(uuid4())
            paired[tx_a.tx_uid] = pair_uid
            paired[tx_b.tx_uid] = pair_uid
            to_alias[tx_a.tx_uid] = tx_b.account_alias
            to_alias[tx_b.tx_uid] = tx_a.account_alias
            consumed.add(tx_a.tx_uid)
            consumed.add(tx_b.tx_uid)
            break

    return [
        _apply_pair(by_uid[uid], paired[uid], to_alias[uid])
        if uid in paired
        else tx
        for uid, tx in by_uid.items()
    ]


def _is_transfer_candidate(tx: CanonicalTx) -> bool:
    if tx.tx_type in _TRANSFER_TX_TYPES:
        return True
    haystack = (tx.merchant_norm or tx.merchant_raw or "").upper()
    return any(keyword in haystack for keyword in _TRANSFER_KEYWORDS)


def _is_pair(a: CanonicalTx, b: CanonicalTx) -> bool:
    if a.owner != b.owner:
        return False
    if a.account_alias == b.account_alias:
        return False
    if {a.direction, b.direction} != {"debit", "credit"}:
        return False
    if _amount(a) != _amount(b):
        return False
    if not _is_transfer_candidate(b):
        return False
    return _within_window(a, b)


def _amount(tx: CanonicalTx) -> Decimal:
    return tx.amount.quantize(Decimal("0.00"))


def _within_window(a: CanonicalTx, b: CanonicalTx) -> bool:
    da = _ref_date(a)
    db = _ref_date(b)
    if da is None or db is None:
        return False
    return abs(da - db) <= _PAIR_WINDOW


def _ref_date(tx: CanonicalTx) -> date | None:
    return tx.event_date or tx.posted_date or tx.booking_date


def _apply_pair(tx: CanonicalTx, pair_uid: str, to_account_alias: str) -> CanonicalTx:
    return replace(
        tx,
        transfer_pair_uid=pair_uid,
        tx_type="internal_transfer",
        to_account_alias=to_account_alias,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/test_etl_transfers.py -v
```
Expected: all 9 tests PASS (7 existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/finanzasmmex/etl/transfers.py tests/test_etl_transfers.py
git commit -m "feat(etl): populate to_account_alias symmetrically on transfer pairs"
```

---

### Task 4: Writer — transfer pre-pass and _insert_transfer_tx

**Files:**
- Modify: `src/finanzasmmex/writer/mmex_sql.py`
- Test: `tests/test_mmex_sql_writer.py`

- [ ] **Step 1: Update fixture and add helper in test file**

In `tests/test_mmex_sql_writer.py`, add `BE_Laura_1234` account to `create_mmex_db`. Replace the final INSERT line:

```python
            INSERT INTO ACCOUNTLIST_V1 (ACCOUNTID, ACCOUNTNAME)
            VALUES (10, 'BE_Ricardo_1234');
            INSERT INTO ACCOUNTLIST_V1 (ACCOUNTID, ACCOUNTNAME)
            VALUES (20, 'BE_Laura_1234');
```

Then add `make_transfer_pair` helper after `make_tx`:

```python
def make_transfer_pair(
    *, pair_uid: str = "pair-001"
) -> tuple[CanonicalTx, CanonicalTx]:
    debit = CanonicalTx(
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
        transfer_pair_uid=pair_uid,
    )
    credit = CanonicalTx(
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
        transfer_pair_uid=pair_uid,
    )
    return debit, credit
```

- [ ] **Step 2: Write the 5 failing tests**

Add to `tests/test_mmex_sql_writer.py`:

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

```
pytest tests/test_mmex_sql_writer.py::test_transfer_inserts_one_mmex_row tests/test_mmex_sql_writer.py::test_transfer_idempotent tests/test_mmex_sql_writer.py::test_transfer_incomplete_pair_rejected tests/test_mmex_sql_writer.py::test_transfer_rollback_on_mapping_error tests/test_mmex_sql_writer.py::test_transfer_both_staging_tx_uids_in_summary -v
```
Expected: all FAIL (AssertionError or items_rejected_unsupported mismatch).

- [ ] **Step 4: Update `_unsupported_for_sql` in mmex_sql.py**

Replace:
```python
def _unsupported_for_sql(tx: CanonicalTx) -> bool:
    return tx.tx_type in {"transfer_in", "transfer_out", "internal_transfer"}
```
With:
```python
def _unsupported_for_sql(tx: CanonicalTx) -> bool:
    return tx.tx_type in {"transfer_in", "transfer_out"}
```

- [ ] **Step 5: Add `_build_transfer_index` function in mmex_sql.py**

Add after `_unsupported_for_sql`:

```python
def _build_transfer_index(
    eligible: list[CanonicalTx],
) -> tuple[set[str], dict[str, str]]:
    """Pre-pass over eligible batch to identify complete transfer pairs.

    Returns:
    - credit_skip: tx_uids of credit legs whose debit counterpart is in this batch
    - pair_to_credit_uid: transfer_pair_uid → credit leg tx_uid (complete pairs only)
    """
    debit_by_pair: dict[str, CanonicalTx] = {}
    credit_by_pair: dict[str, CanonicalTx] = {}
    for tx in eligible:
        if tx.tx_type != "internal_transfer" or not tx.transfer_pair_uid:
            continue
        if tx.direction == "debit" and tx.to_account_alias:
            debit_by_pair[tx.transfer_pair_uid] = tx
        elif tx.direction == "credit":
            credit_by_pair[tx.transfer_pair_uid] = tx
    complete = set(debit_by_pair) & set(credit_by_pair)
    credit_skip = {credit_by_pair[uid].tx_uid for uid in complete}
    pair_to_credit_uid = {uid: credit_by_pair[uid].tx_uid for uid in complete}
    return credit_skip, pair_to_credit_uid
```

- [ ] **Step 6: Add `_insert_transfer_tx` function in mmex_sql.py**

Add after `_insert_checking_tx`:

```python
def _insert_transfer_tx(
    conn: sqlite3.Connection,
    tx: CanonicalTx,
) -> int:
    """Insert CHECKINGACCOUNT_V1 Transfer row. Caller handles sync_hash."""
    columns = _columns(conn, "CHECKINGACCOUNT_V1")
    trans_id_col = _first_present(columns, ("TRANSID",))
    tx_date = tx.posted_date or tx.event_date or tx.booking_date
    if tx_date is None:
        raise MmexMappingError("Transaction date is required for SQL writer")
    assert tx.to_account_alias, "to_account_alias must be set before calling _insert_transfer_tx"
    account_id = _resolve_account_id(conn, tx.account_alias, card_last4=tx.card_last4)
    to_account_id = _resolve_account_id(conn, tx.to_account_alias)
    amount_str = _amount_value(tx.amount)
    values: dict[str, object] = {
        "ACCOUNTID": account_id,
        "TOACCOUNTID": to_account_id,
        "PAYEEID": 0,
        "TRANSCODE": "Transfer",
        "TRANSAMOUNT": amount_str,
        "TOTRANSAMOUNT": amount_str,
        "STATUS": "N",
        "TRANSACTIONNUMBER": tx.source_ref or "",
        "NOTES": _notes(tx),
        "CATEGID": -1,
        "SUBCATEGID": -1,
        "TRANSDATE": tx_date.isoformat(),
        "FOLLOWUPID": -1,
        "COLOR": "",
        "DELETEDTIME": "",
    }
    filtered = {key: value for key, value in values.items() if key in columns}
    required = {"ACCOUNTID", "TOACCOUNTID", "TRANSCODE", "TRANSAMOUNT", "TRANSDATE"}
    missing = required - set(filtered)
    if missing:
        raise MmexSchemaError(
            f"CHECKINGACCOUNT_V1 missing required columns for Transfer: {sorted(missing)}"
        )
    return _insert_row_returning_id(conn, "CHECKINGACCOUNT_V1", filtered, trans_id_col)
```

- [ ] **Step 7: Update the main loop in `write_sql`**

In `write_sql`, replace the section from `pre_backup_path` through the end of the `for tx in eligible` loop (inside the `try` block). The updated block:

```python
    pre_backup_path: Path | None = _safe_backup(mmex_path, backup_dir, "pre")
    inserted: dict[str, int] = {}
    inserted_accounts: dict[str, int] = {}
    duplicates = 0
    inserted_count = 0

    conn = _connect(mmex_path)
    try:
        _begin_immediate(conn)
        _ensure_required_schema(conn)
        sync_field_id = _ensure_sync_hash_field(conn)

        credit_skip, pair_to_credit_uid = _build_transfer_index(eligible)

        for tx in eligible:
            if not tx.fitid_synthetic:
                raise MmexMappingError("fitid_synthetic is required for SQL writer")

            # Credit leg of a complete pair — absorbed into the Transfer row
            if tx.tx_uid in credit_skip:
                continue

            if _sync_hash_exists(conn, sync_field_id, tx.fitid_synthetic):
                duplicates += 1
                continue

            if tx.tx_type == "internal_transfer":
                if (
                    tx.direction != "debit"
                    or not tx.to_account_alias
                    or tx.transfer_pair_uid not in pair_to_credit_uid
                ):
                    rejected_unsupported += 1
                    continue
                mmex_tx_id = _insert_transfer_tx(conn, tx)
                _insert_sync_hash(conn, sync_field_id, mmex_tx_id, tx.fitid_synthetic)
                inserted[tx.tx_uid] = mmex_tx_id
                credit_uid = pair_to_credit_uid[tx.transfer_pair_uid]
                inserted[credit_uid] = mmex_tx_id
                inserted_accounts[tx.tx_uid] = -1
                inserted_count += 1
                continue

            account_id = _resolve_account_id(
                conn, tx.account_alias, card_last4=tx.card_last4
            )
            category_id, subcategory_id = _resolve_category(
                conn,
                tx.category_guess,
                tx.subcategory_guess,
            )
            payee_id = _resolve_payee_id(
                conn,
                _payee_name(tx),
                category_id,
                subcategory_id,
            )
            mmex_tx_id = _insert_checking_tx(
                conn,
                tx,
                account_id=account_id,
                payee_id=payee_id,
                category_id=category_id,
                subcategory_id=subcategory_id,
            )
            _insert_sync_hash(conn, sync_field_id, mmex_tx_id, tx.fitid_synthetic)
            _apply_tags(conn, tx.tags, mmex_tx_id)
            inserted[tx.tx_uid] = mmex_tx_id
            inserted_accounts[tx.tx_uid] = account_id
            inserted_count += 1

        conn.commit()
```

Also update the `SqlWriteSummary` construction at the end of `write_sql` to use `inserted_count` instead of `len(inserted)`:

```python
    return SqlWriteSummary(
        items_considered=len(txs),
        items_inserted=inserted_count,
        items_skipped_duplicate=duplicates,
        items_rejected_review=rejected_review,
        items_rejected_unsupported=rejected_unsupported,
        mmex_path=str(mmex_path),
        backup_pre_path=str(pre_backup_path) if pre_backup_path else None,
        backup_post_path=str(post_backup_path) if post_backup_path else None,
        mmex_tx_ids=inserted,
        mmex_account_ids=inserted_accounts,
    )
```

Find and update BOTH `SqlWriteSummary` calls in `write_sql` (the early-return one when `not eligible`, and the final one). The early-return already has `items_inserted=0` so no change needed there — only the final return needs `inserted_count`.

- [ ] **Step 8: Run the 5 new tests**

```
pytest tests/test_mmex_sql_writer.py::test_transfer_inserts_one_mmex_row tests/test_mmex_sql_writer.py::test_transfer_idempotent tests/test_mmex_sql_writer.py::test_transfer_incomplete_pair_rejected tests/test_mmex_sql_writer.py::test_transfer_rollback_on_mapping_error tests/test_mmex_sql_writer.py::test_transfer_both_staging_tx_uids_in_summary -v
```
Expected: all 5 PASS

- [ ] **Step 9: Run full suite + type check**

```
pytest --tb=short -q
mypy src/ --strict
```
Expected: all tests pass, mypy clean.

- [ ] **Step 10: Commit**

```bash
git add src/finanzasmmex/writer/mmex_sql.py tests/test_mmex_sql_writer.py
git commit -m "feat(writer): insert internal transfers as MMEX Transfer rows (#19)"
```

---

### Task 5: Gate — specialist agents

**Files:** none (review only)

- [ ] **Step 1: Run mmex-writer-guard**

Dispatch mmex-writer-guard agent with scope: `src/finanzasmmex/writer/mmex_sql.py`. Verify:
- `_insert_transfer_tx` uses `BEGIN IMMEDIATE` (inherited from `write_sql` transaction)
- Rollback covers `_insert_transfer_tx` errors
- No path can reach `finanza.mmb`
- Dedup via sync_hash on debit leg only (correct — one MMEX row per pair)

- [ ] **Step 2: Run staging-schema-validator**

Dispatch staging-schema-validator. Verify:
- schema v2 has `to_account_alias TEXT` nullable
- version INSERT is `(2)`
- All existing indexes and constraints intact
- Dry-run passes: `python -c "import sqlite3; conn=sqlite3.connect(':memory:'); conn.executescript(open('src/finanzasmmex/staging/schema.sql').read()); print('OK')"`

- [ ] **Step 3: Open PR**

```bash
git push -u origin feat/phase-2.5-internal-transfers
gh pr create --title "feat(writer): internal transfers as MMEX Transfer rows (#19)" \
  --body "Closes #19. Implements to_account_alias on CanonicalTx, schema v2, ETL symmetric population, and writer Transfer insertion with pre-pass grouping."
```
