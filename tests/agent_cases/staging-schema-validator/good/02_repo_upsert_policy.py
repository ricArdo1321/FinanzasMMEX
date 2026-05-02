# GOOD: ON CONFLICT clause only updates mmex_status + updated_at.
# Canonical extracted fields are preserved across re-runs.

UPSERT_SQL = """
INSERT INTO canonical_tx (
    tx_uid, owner, source_type, content_sha256, amount, currency, direction,
    account_alias, tx_type, parser_name, parser_version, fitid_synthetic,
    needs_review, mmex_status
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(fitid_synthetic) DO UPDATE SET
    mmex_status = excluded.mmex_status,
    updated_at = datetime('now')
"""
