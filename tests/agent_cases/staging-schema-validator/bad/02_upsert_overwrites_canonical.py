# BAD: upsert overwrites extracted canonical fields (amount, merchant_raw, etc.) on conflict.
# Re-runs would destroy reviewed/edited data downstream.

UPSERT_SQL = """
INSERT INTO canonical_tx (
    tx_uid, owner, source_type, content_sha256, amount, currency, direction,
    account_alias, tx_type, parser_name, parser_version, fitid_synthetic,
    needs_review, mmex_status, merchant_raw
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(fitid_synthetic) DO UPDATE SET
    mmex_status = excluded.mmex_status,
    amount = excluded.amount,                -- VIOLATION
    merchant_raw = excluded.merchant_raw,    -- VIOLATION
    needs_review = excluded.needs_review,    -- VIOLATION
    updated_at = datetime('now')
"""
