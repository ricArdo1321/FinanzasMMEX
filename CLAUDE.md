# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

FinanzasMMEX — local-first desktop app to consolidate Chilean banking transactions (BancoEstado, CMR, Mach, Mercado Pago) from Gmail, headful scraping, MP API, and dropped files into Money Manager Ex (`finanza.mmb`). Hybrid stack: Python motor + C# WPF UI.

## Stack

- **Python 3.11+** engine: ingestion, ETL, staging SQLite, dedup, scraping, OFX/SQL writers, jobs. Source: `src/finanzasmmex/`.
- **C# WPF .NET 8** desktop UI for review queue + quick-add. Source: `desktop/FinanzasMMEX.App/`. Invokes Python CLI via subprocess + JSON contract. **WPF never writes `staging.db` or `finanza.mmb` directly** — Python is sole writer.
- **SQLite** staging DB (`staging.db`, WAL mode) + MMEX `finanza.mmb`.
- Secrets via `keyring` → Windows Credential Manager only. Never repo/logs/files.

## Common Commands

```bash
# Install (editable + dev tools)
pip install -e .[dev]

# CLI entrypoint (defined in pyproject.toml [project.scripts])
finanzasmmex init                                # init staging.db
finanzasmmex run --source gmail --input <path>   # BE email → OFX
finanzasmmex run --source mp --input <path>      # MP offline → OFX
finanzasmmex run --writer sql --mmex-db <path> --allow-shadow-write  # pending → SQL
finanzasmmex login --source mp                   # store MP token in vault
finanzasmmex review list [--owner X] [--status pending] [--needs-review-only] [--limit 200]
finanzasmmex review update --tx-uid <uid> [--category-guess X] [--merchant-norm X] [--tags "a,b"]
finanzasmmex review resolve --tx-uid <uid> --status exported|inserted|rejected
finanzasmmex quickadd create --owner ricardo --account-alias BE_Ricardo_1234 \
    --amount 15000 --direction debit --date 2026-05-01 --merchant-raw "Cafeteria" \
    [--category-guess X] [--tx-type purchase] [--tags "joint"]

# Lint / type / test
ruff check src/
mypy src/
pytest                                      # all tests
pytest tests/test_be_email.py               # single test file
pytest -k "test_etl"                        # keyword filter

# WPF build
dotnet build FinanzasMMEX.slnx
dotnet test desktop/FinanzasMMEX.App.Tests/
```

## Architecture (big picture)

Pipeline shape: **Sources → Adapters → ETL → `staging.db` (canonical_tx) → Writer → MMEX**.

### Models & ETL

- `models.py` — `CanonicalTx` frozen dataclass is the **single canonical interface** between every adapter, ETL step, and writer. Amount is **always positive**; sign carried in `direction` ('debit'|'credit'). Must remain immutable.
- `etl/fitid.py` — `ensure_fitid(tx)` computes `fitid_synthetic` (SHA-256 of `owner|account|date|amount|merchant_norm`). Always call before upserting; adapters must NOT compute it themselves.
- `etl/categorize.py` — `categorize_tx(tx, rules)` matches merchant against `CategoryRule` list (priority: `substr` → `regex` → `fuzzy`, threshold 85). Winner is lowest `(type_order, priority, rule_id)`.
- `etl/pipeline.py` — `prepare_for_staging(tx, rules)` chains categorize → ensure_fitid. `prepare_batch_for_staging` adds `link_internal_transfers` before fitid.
- `etl/normalize.py` — `parse_clp_amount` (CLP-specific), `normalize_merchant`.
- `etl/transfers.py` — `link_internal_transfers` detects transfer pairs and assigns `transfer_pair_uid`.
- `etl/llm_fallback.py` — local Ollama `qwen3:8b` for ambiguous merchant extraction. **No remote LLM ever.**

### Staging DB

- `staging/schema.sql` — versioned schema v1. Tables: `canonical_tx`, `raw_artifacts`, `category_rules`, `merge_log`, `reconcile_log`, `job_runs`. Dedup via `UNIQUE INDEX uq_canonical_fitid` on `fitid_synthetic`.
- `staging/repo.py` — **only path** to `staging.db`. `upsert_tx` uses `ON CONFLICT(fitid_synthetic)` — on conflict only updates `mmex_status` + `updated_at` (intentional: adapters must not silently overwrite canonical fields). Query methods: `list_txs` (with filters), `get_tx`, `get_tx_by_fitid`, `get_pending_txs`, `update_tx_fields`, `update_mmex_status`, `mark_inserted`, `has_reconcile_off`.

### Adapters

All produce `CanonicalTx` with `parser_name` + `parser_version` set. Amount always positive, `direction` explicit.

- `adapters/be_email.py` — `parse_purchase_email(raw_text, ...)` → BancoEstado purchase notifications. Regex extraction of amount, merchant, account last4, date, auth code. Sets `needs_review=True` when currency implicit, account ambiguous, or auth code missing.
- `adapters/mp_api.py` — `parse_payment(payload, ...)` → Mercado Pago API payments. Also `MercadoPagoClient` class for live API (`search_payments` with pagination, `timeout=15s`).
- `adapters/cmr_email.py`, `adapters/mach_email.py` — additional email parsers.

### Writers

- `writer/ofx_export.py` — `write_ofx(transactions, output_path)` → OFX v1.0.2 SGML. Single account per file. Uses `escape()` for XML safety.
- `writer/mmex_sql.py` — `write_sql(transactions, mmex_db_path, backup_dir, ...)` → direct MMEX SQLite writes. Safety contract:
  - **Never** write productive `finanza.mmb` (path guard rejects it).
  - `BEGIN IMMEDIATE` with `timeout=0` → lock detection surfaces as `MmexLockedError` (CLI exit code 4).
  - Pre/post backups via SQLite Online Backup API, 30-day retention.
  - Dedup via `CUSTOMFIELDDATA_V1.sync_hash` (fitid_synthetic) with unique partial index.
  - Blocks if any account has `reconcile_log.status='off'`.
  - Exception hierarchy: `MmexSqlError` → `MmexSafetyError | MmexLockedError | MmexSchemaError | MmexMappingError`.
  - Transfers (`transfer_in/out/internal_transfer`) are rejected (unsupported for SQL).

### Orchestrator

- `orchestrator/jobs.py` — job functions that wire adapters → ETL → writers:
  - `run_gmail_bancoestado_to_ofx` — collect email files, parse, ETL, upsert, OFX export, HTML report.
  - `run_mp_to_ofx` — same for Mercado Pago JSON payloads.
  - `run_pending_to_sql` — list pending txs, write to MMEX via SQL, mark inserted.
  - `write_review_report` — HTML table of transactions for manual review.

### Artifacts guard

- `artifacts.py` — `safe_output_path(path, allowed_suffixes)` rejects `.mmb`/`.emb` suffixes and enforces allowlisted extensions. Used by all writers before creating files.

### CLI (Python)

- `cli.py` — argparse with `ContractArgumentParser` subclass that catches `-h`/`--help` and argparse errors, emitting them as valid JSON envelopes.
- `_emit(ok, data, errors, warnings, exit_code)` — **every** command path must exit through this. Produces JSON `{ok, data, errors, warnings, run_id}` to stdout and exits with the given code.
- Exit codes: **0** success, **2** validation error, **3** credentials required, **4** MMEX locked, **5** temporary failure.

### C#/Python contract

Defined in `contracts/envelope.schema.json`. Every CLI command returns JSON `{ok, data, errors, warnings, run_id}`. Errors carry `{code, message, details}`. On `ok=false`, `errors` must be non-empty. WPF parses these — keep stable.

### WPF (C#)

- `desktop/FinanzasMMEX.Core/` — shared library: `CliRunner` (subprocess invocation), `CliEnvelope` (JSON parsing), `CliExitCode` (enum), `CliErrorMapper`, `PendingTx` model.
- `desktop/FinanzasMMEX.App/` — WPF UI: `MainViewModel`, `PendingsViewModel`, `QuickAddViewModel`, corresponding XAML views, `AsyncRelayCommand`.
- `desktop/FinanzasMMEX.App.Tests/` — C# tests for envelope parsing, exit codes, error mapping.

## Project conventions

- **Owner field** (`owner`): `'ricardo' | 'laura' | 'joint'`. Don't assume single user.
- **CLP amounts**: parse via `etl/normalize.parse_clp_amount`. CLP has no decimals natively but model uses `Decimal('0.00')`.
- **Internal transfers**: detected as pairs in ETL, linked via `transfer_pair_uid`. Rejected by SQL writer (OFX only for now).
- **Fuzzy merchant matching**: RapidFuzz against `category_rules` (priority: `substr` → `regex` → `fuzzy`, default threshold 85). Falls back to local Ollama `qwen3:8b` JSON-only mode for ambiguous emails. **No remote LLM ever.**
- **Scraping**: Playwright **headful only** (BancoEstado, CMR). Headless forbidden. Abort on CAPTCHA. Mach is email/manual only.
- **Code locations**: Productive data lives outside repo at `C:\Finanzas\` (mmb, backups, logs, drop, reports). Repo holds code only. `.mmb` operates inside BitLocker-encrypted folder.
- **Vault bypass**: set `FINANZASMMEX_DISABLE_VAULT=1` to skip keyring (tests/CI). MP token can also come from `MP_ACCESS_TOKEN` env var.

## Subagentes disponibles

Roster en `.claude/agents/` (catálogo: `.claude/agents/README.md`). Triggers y especialidades:

| Agente | Modelo | Cuándo dispara / Especialidad |
|---|---|---|
| `agent-orchestrator` | sonnet | Coordina especialistas con `Task`; usar en cambios multi-area, phase gates, pre-merge/pre-PR, o para decidir que agentes corresponden. |
| `parser-reviewer` | sonnet | Edit en `src/finanzasmmex/adapters/*` |
| `mmex-writer-guard` | opus | Edit en `src/finanzasmmex/writer/*` o lógica MMEX |
| `secrets-pii-auditor` | opus | Pre-commit/PR, `vault.py`, fixtures, logs |
| `cli-contract-checker` | sonnet | Edit en `cli.py` o `contracts/*` |
| `staging-schema-validator` | sonnet | Edit en `staging/schema.sql` o `repo.py` |
| `wpf-ui-reviewer` | sonnet | Edit en `desktop/**` |
| `fixtures-anonymizer` | sonnet | Invocación explícita con archivo fuente |

Phase gates: `agent-orchestrator` coordina, gates se cumplen por especialistas. Phase 1 merge → parser-reviewer + cli-contract-checker + secrets-pii-auditor sin `blocker`. Phase 2 → suma writer-guard + schema-validator + shadow-mode 1 semana. Phase 4 → suma wpf-ui-reviewer.

Casos de validación en `tests/agent_cases/<agent>/{good,bad}/`. Spec completo: `docs/superpowers/specs/2026-05-02-claude-subagents-design.md`.

## Reference docs in repo

- `PLAN2.md` — **definitive plan** (hybrid stack). Supersedes PLAN.md and implementation_plan.md on stack questions.
- `PLAN.md` — original full-phase plan (still authoritative for phase scope/criteria).
- `implementation_plan.md` — older Phase 0/1 detail; partial.
- `investigación/iteracion #3/FinanzasMMEX_PlanArquitectura.pdf` — source-of-truth architecture PDF (Apéndice B schema, Apéndice C regex).
- `contracts/CHANGELOG.md` — CLI/WPF contract version history.
