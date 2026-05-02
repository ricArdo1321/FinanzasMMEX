-- GOOD: bumps schema_version to 2, keeps WAL + foreign_keys, all indexes intact,
-- adds new optional column to canonical_tx without removing constraints.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

INSERT INTO schema_version (version) VALUES (2);

ALTER TABLE canonical_tx ADD COLUMN external_ref TEXT;

-- existing indexes intentionally unchanged:
-- uq_canonical_fitid, idx_canonical_owner_date, idx_canonical_status, idx_canonical_match
