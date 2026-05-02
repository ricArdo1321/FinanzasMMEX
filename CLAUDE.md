# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

FinanzasMMEX — local-first desktop app to consolidate Chilean banking transactions (BancoEstado, CMR, Mach, Mercado Pago) from Gmail, headful scraping, MP API, and dropped files into Money Manager Ex (`finanza.mmb`). Hybrid stack: Python motor + C# WPF UI.

## Stack

- **Python 3.11+** engine: ingestion, ETL, staging SQLite, dedup, scraping, OFX/SQL writers, jobs. Source: `src/finanzasmmex/`.
- **C# WPF .NET 10** desktop UI for review queue + quick-add. Source: `desktop/FinanzasMMEX.App/`. Invokes Python CLI via subprocess + JSON contract. **WPF never writes `staging.db` or `finanza.mmb` directly** — Python is sole writer.
- **SQLite** staging DB (`staging.db`, WAL mode) → MMEX `finanza.mmb` (later).
- Secrets via `keyring` → Windows Credential Manager only. Never repo/logs/files.

## Common Commands

```bash
# Install (editable + dev tools)
pip install -e .[dev]

# CLI entrypoint (defined in pyproject.toml [project.scripts])
finanzasmmex init                          # init staging.db
finanzasmmex run --source gmail|mp|all     # phase 1+; currently stub

# Lint / type / test
ruff check src/
mypy src/                                   # strict mode (per pyproject.toml)
pytest                                      # tests dir not yet present
detect-secrets scan

# WPF build (when implemented)
dotnet build FinanzasMMEX.slnx
dotnet run --project desktop/FinanzasMMEX.App
```

Note: `pyproject.toml` declares `pytest`, `ruff`, `mypy`, `detect-secrets` under `[project.optional-dependencies].dev`. There is **no `tests/` dir yet** — Phase 0 work in progress.

## Architecture (big picture)

Pipeline shape: **Sources → Adapters → ETL → `staging.db` (canonical_tx) → Writer → MMEX**.

- `models.py` — `CanonicalTx` frozen dataclass is the **single canonical interface** between every adapter, ETL step, and writer. Amount is **always positive**; sign carried in `direction` ('debit'|'credit'). Must remain immutable.
- `staging/schema.sql` — versioned schema (see `schema_version` table). Tables: `canonical_tx`, `raw_artifacts`, `category_rules`, `merge_log`, `reconcile_log`, `job_runs`. Dedup happens via `UNIQUE INDEX uq_canonical_fitid` on `fitid_synthetic` — a SHA-256 hash of `(owner, account, date, amount, merchant_norm)` computed in ETL (not in adapters).
- `staging/repo.py` — only path to `staging.db`. `upsert_tx` uses `ON CONFLICT(fitid_synthetic)` for idempotency; current upsert only updates `mmex_status` + `updated_at` on conflict (intentional — adapters must not silently overwrite canonical fields).
- `secrets/vault.py` — wraps `keyring` under service name `"FinanzasMMEX"`. All OAuth tokens, Playwright `storage_state`, bank credentials go through this. Never read secrets from disk or env.
- `cli.py` — argparse entrypoint. Phase-1 `run` is currently a stub. Future commands per PLAN2: `login`, `review list|update|resolve`, `quickadd create`, `replay --since`.

### C#/Python contract

Every CLI command must return JSON `{ok, data, errors, warnings, run_id}`. Errors carry `{code, message, details}`. Exit codes distinguish: success / validation / credentials / MMEX lock / temporary failure. WPF parses these — keep stable.

### Writer modes (planned)

- **Phase 1 (current):** OFX export → manual import into `finanza_test.mmb`.
- **Phase 2:** Direct SQL writer to MMEX (`BEGIN IMMEDIATE / COMMIT / ROLLBACK`, lock detect with timeout=0, dedup via `CUSTOMFIELDDATA_V1.sync_hash`, backup pre/post). Dual mode `--writer ofx|sql`.
- **Never touch productive `finanza.mmb` until 1 week shadow-mode against `finanza_test.mmb`.**

## Project conventions

- **Owner field** (`owner`): `'ricardo' | 'laura' | 'joint'`. Don't assume single user.
- **CLP amounts**: parse via `etl/normalize.parse_clp_amount` (planned). CLP has no decimals natively but model uses `Decimal('0.00')`.
- **Internal transfers**: detected as pairs in ETL, linked via `transfer_pair_uid`, exported as MMEX `Transfer` with `TOACCOUNTID` (not two separate txs).
- **Fuzzy merchant matching**: RapidFuzz against `category_rules` (priority order: `substr` → `regex` → `fuzzy`, default threshold 85). Falls back to local Ollama `qwen3:8b` JSON-only mode for ambiguous emails. **No remote LLM ever.**
- **Scraping**: Playwright **headful only** (BancoEstado, CMR). Headless forbidden. Abort on CAPTCHA. Mach is email/manual only.
- **Code locations**:
  - Productive data lives outside repo at `C:\Finanzas\` (mmb, backups, logs, drop, reports). Repo holds code only.
  - `.mmb` operates inside BitLocker-encrypted folder.

## Reference docs in repo

- `PLAN2.md` — **definitive plan** (hybrid stack). Supersedes PLAN.md and implementation_plan.md on stack questions.
- `PLAN.md` — original full-phase plan (still authoritative for phase scope/criteria).
- `implementation_plan.md` — older Phase 0/1 detail; partial.
- `investigación/iteracion #3/FinanzasMMEX_PlanArquitectura.pdf` — source-of-truth architecture PDF (referenced for Apéndice B schema, Apéndice C regex).

## Phase status

Phase 0 partial: `pyproject.toml`, `models.py`, `staging/schema.sql`, `staging/repo.py`, `secrets/vault.py`, `cli.py` skeleton, WPF project shell. **Pending Phase 0**: `etl/`, `adapters/`, `orchestrator/`, `writer/ofx_export.py`, contracts/, tests/, fixtures, JSONL structlog setup, OAuth bootstrap, Ollama install, detect-secrets baseline.
