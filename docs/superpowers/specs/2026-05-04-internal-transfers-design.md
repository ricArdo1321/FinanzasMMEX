# Internal Transfers SQL — Design Spec
**Issue:** #19 — Fase 2.5: Transferencias internas SQL con TOACCOUNTID  
**Date:** 2026-05-04  
**Status:** Approved

## Problem

The SQL writer rejects all `internal_transfer`, `transfer_in`, and `transfer_out` tx types. ETL already detects and links pairs via `transfer_pair_uid`, but `CanonicalTx` has no field exposing the destination account alias. Without it, the writer cannot resolve `TOACCOUNTID` in MMEX.

## Decision: Symmetric `to_account_alias`

Both legs of a pair carry `to_account_alias` pointing to the counterpart's `account_alias`. Debit leg is always primary for the MMEX Transfer row. This approach was chosen over asymmetric (only debit leg) and a new `TransferPair` type because:
- Self-documenting: each staging row carries full transfer context
- Writer rule is simple and invariant: debit = primary
- Auditable without reconstructing ETL logic

## Data Model

### `CanonicalTx` (models.py)

Add one field after `transfer_pair_uid`:
```python
to_account_alias: str | None = None
```
- Regular txs: `None`
- Complete transfer pair: both legs populated with counterpart's `account_alias`
- Incomplete pair (only one leg seen): `to_account_alias = None`, stays `pending`

### staging `canonical_tx` — Migration v2

```sql
ALTER TABLE canonical_tx ADD COLUMN to_account_alias TEXT;
INSERT INTO schema_version (version) VALUES (2);
```

Nullable. No CHECK constraint. No additional index needed.

**Invariant:** `transfer_pair_uid IS NOT NULL AND to_account_alias IS NOT NULL` → pair complete, writer-ready. `transfer_pair_uid IS NOT NULL AND to_account_alias IS NULL` → orphan leg, skip.

## ETL (`etl/transfers.py`)

`_apply_pair` currently calls `replace()` once per tx separately. New signature returns a tuple and populates `to_account_alias` symmetrically:

```python
def _apply_pair(
    tx_a: CanonicalTx, tx_b: CanonicalTx, pair_uid: str
) -> tuple[CanonicalTx, CanonicalTx]:
    return (
        replace(tx_a, transfer_pair_uid=pair_uid,
                tx_type="internal_transfer", to_account_alias=tx_b.account_alias),
        replace(tx_b, transfer_pair_uid=pair_uid,
                tx_type="internal_transfer", to_account_alias=tx_a.account_alias),
    )
```

`link_internal_transfers` adjusts the loop to unpack the tuple. Detection logic (`_is_pair`, `_is_transfer_candidate`) is unchanged.

## Writer (`writer/mmex_sql.py`)

### Pre-pass (before main loop)

Build two structures from the eligible batch:
- `transfer_pairs: dict[str, CanonicalTx]` — `transfer_pair_uid → credit leg`  
- `credit_skip: set[str]` — `tx_uid` of credit legs to skip in main loop

A pair is complete when both legs are present in the batch with `to_account_alias` populated. An incomplete pair (only one leg in batch) counts as `items_rejected_unsupported`.

### Main loop dispatch

```
tx.tx_uid in credit_skip          → skip
tx.tx_type == "internal_transfer"
  and pair complete               → _insert_transfer_tx
  else                            → items_rejected_unsupported
regular tx                        → _insert_checking_tx (unchanged)
```

### `_insert_transfer_tx(conn, tx_debit, to_account_alias)`

1. `account_id = _resolve_account_id(conn, tx_debit.account_alias, card_last4=tx_debit.card_last4)`
2. `to_account_id = _resolve_account_id(conn, to_account_alias)`
3. Insert into `CHECKINGACCOUNT_V1`:
   - `TRANSCODE = 'Transfer'`
   - `ACCOUNTID = account_id`
   - `TOACCOUNTID = to_account_id`
   - `TRANSAMOUNT = TOTRANSAMOUNT = amount` (CLP, no FX conversion)
   - `PAYEEID = 0` (MMEX convention for transfers)
4. `_insert_sync_hash` using debit leg's `fitid_synthetic` only
5. Returns `mmex_tx_id` → recorded for **both** legs in `inserted`

### `SqlWriteSummary`

`items_inserted` counts transfer pairs as 1 (one MMEX row per pair, not two).

## Error Handling

- `MmexMappingError` on either account resolution → full rollback, 0 MMEX rows
- Ambiguous `to_account_alias` (>1 MMEX account match) → `MmexMappingError`
- Missing `TOACCOUNTID` column in schema → `MmexSchemaError`

## Testing

Five new tests in `tests/test_mmex_sql_writer.py`:

| Test | Assertion |
|------|-----------|
| `test_transfer_inserts_one_mmex_row` | 1 CHECKINGACCOUNT row, TRANSCODE='Transfer', correct TOACCOUNTID, `items_inserted=1` |
| `test_transfer_idempotent` | Second run: 0 new rows, `items_skipped_duplicate=1` |
| `test_transfer_incomplete_pair_rejected` | Only debit leg in batch → 0 rows, `items_rejected_unsupported=1` |
| `test_transfer_rollback_on_error` | MmexMappingError on to_account_alias → rollback, 0 rows, no post-backup |
| `test_transfer_both_staging_rows_marked_inserted` | Both legs get `mmex_status='inserted'` with same `mmex_tx_id` |

## Gate

- `mmex-writer-guard` — no blockers
- `staging-schema-validator` — migration v2 verified
- `secrets-pii-auditor` — no new PII surface

## Out of Scope

- Cross-owner transfers (ETL `_is_pair` already requires `a.owner == b.owner`)
- FX conversion for non-CLP transfers (TOTRANSAMOUNT = TRANSAMOUNT always)
- `transfer_in` / `transfer_out` single-leg types remain rejected until ETL links them
