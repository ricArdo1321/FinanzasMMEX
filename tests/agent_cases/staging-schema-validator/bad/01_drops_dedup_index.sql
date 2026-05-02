-- BAD: drops uq_canonical_fitid (dedup correctness destroyed),
-- removes amount > 0 CHECK, no schema_version bump, missing WAL pragma in migration.

DROP INDEX uq_canonical_fitid;  -- VIOLATION: required dedup index removed

ALTER TABLE canonical_tx DROP CONSTRAINT IF EXISTS amount_positive;
-- VIOLATION: amount > 0 invariant destroyed

-- VIOLATION: no INSERT INTO schema_version (version) VALUES (N+1);
-- VIOLATION: no PRAGMA journal_mode = WAL re-asserted in migration

CREATE TABLE temp_dedup_workaround (
    fitid TEXT  -- non-unique fallback
);
