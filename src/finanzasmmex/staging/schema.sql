-- staging.db schema v2
-- 2026-05-02

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO schema_version (version) VALUES (2);

-- ===== canonical_tx =====
CREATE TABLE canonical_tx (
    tx_uid TEXT PRIMARY KEY,
    owner TEXT NOT NULL CHECK (owner IN ('ricardo','laura','joint')),
    source_type TEXT NOT NULL,
    source_file TEXT,
    source_ref TEXT,
    content_sha256 TEXT NOT NULL,
    raw_text TEXT,
    event_date TEXT,
    booking_date TEXT,
    posted_date TEXT,
    amount REAL NOT NULL CHECK (amount > 0),
    currency TEXT NOT NULL DEFAULT 'CLP',
    direction TEXT NOT NULL CHECK (direction IN ('debit','credit')),
    account_alias TEXT NOT NULL,
    card_last4 TEXT,
    merchant_raw TEXT,
    merchant_norm TEXT,
    tx_type TEXT NOT NULL,
    category_guess TEXT,
    subcategory_guess TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    fitid_synthetic TEXT NOT NULL,
    parser_name TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    needs_review INTEGER NOT NULL DEFAULT 0,
    review_reason TEXT,
    mmex_account_id INTEGER,
    mmex_tx_id INTEGER,
    mmex_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (mmex_status IN ('pending','exported','inserted','rejected')),
    transfer_pair_uid TEXT,
    to_account_alias TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (transfer_pair_uid) REFERENCES canonical_tx(tx_uid)
);

CREATE UNIQUE INDEX uq_canonical_fitid ON canonical_tx(fitid_synthetic);
CREATE INDEX idx_canonical_owner_date ON canonical_tx(owner, posted_date);
CREATE INDEX idx_canonical_status ON canonical_tx(mmex_status);
CREATE INDEX idx_canonical_match ON canonical_tx(
    owner, account_alias, amount, posted_date, merchant_norm);

-- ===== raw_artifacts =====
CREATE TABLE raw_artifacts (
    artifact_id TEXT PRIMARY KEY, -- UUID4
    artifact_type TEXT NOT NULL, -- 'email','mp_response','html','pdf'
    source_ref TEXT NOT NULL, -- gmail msg-id, run_id, file path
    content_sha256 TEXT NOT NULL,
    payload_blob BLOB, -- contenido binario crudo
    payload_text TEXT, -- contenido textual extraído
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX uq_raw_sha ON raw_artifacts(content_sha256);

-- ===== category_rules =====
CREATE TABLE category_rules (
    rule_id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL, -- substring o regex
    pattern_type TEXT NOT NULL CHECK (pattern_type IN ('substr','regex','fuzzy')),
    merchant_norm TEXT NOT NULL, -- 'Amazon'
    payee_id_mmex INTEGER, -- PAYEEID en MMEX (si ya existe)
    category_name TEXT NOT NULL, -- 'Compras Online'
    subcategory_name TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    fuzzy_threshold INTEGER DEFAULT 85, -- 0-100, solo si type=fuzzy
    priority INTEGER NOT NULL DEFAULT 100,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_rules_active_priority ON category_rules(active, priority);

-- ===== merge_log =====
CREATE TABLE merge_log (
    merge_id INTEGER PRIMARY KEY,
    fitid_synthetic TEXT NOT NULL,
    sources_json TEXT NOT NULL, -- ['email#abc', 'ofx#xyz']
    chosen_source TEXT NOT NULL, -- cuál ganó cada campo
    merged_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_merge_fitid ON merge_log(fitid_synthetic);

-- ===== reconcile_log =====
CREATE TABLE reconcile_log (
    reconcile_id INTEGER PRIMARY KEY,
    account_alias TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    balance_initial REAL NOT NULL,
    balance_final REAL NOT NULL,
    sum_credits REAL NOT NULL,
    sum_debits REAL NOT NULL,
    expected_final REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok','minor','off','manual_review')),
    delta REAL NOT NULL, -- balance_final - expected_final
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ===== job_runs =====
CREATE TABLE job_runs (
    run_id TEXT PRIMARY KEY,
    job_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running','ok','error','deferred')),
    items_processed INTEGER NOT NULL DEFAULT 0,
    items_inserted INTEGER NOT NULL DEFAULT 0,
    items_review INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    metadata_json TEXT
);

CREATE INDEX idx_job_runs_started ON job_runs(started_at DESC);
