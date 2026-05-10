# CLI Contract Changelog

Registra cambios al contrato JSON `{ok, data, errors, warnings, run_id}` consumido por la UI WPF. La forma del envelope se valida contra `contracts/envelope.schema.json`.

## 2026-05-10 - Phase 4.1 loader foundation

### Added

- `run --source drop` entra al dispatch publico del CLI. En este corte aun no
  implementa parsers concretos; archivos no soportados o loaders pendientes
  devuelven envelope JSON con `FILE_LOADER_UNSUPPORTED` y exit `2`.
- Base de loaders de archivos para `ofx`, `qif`, `csv`, `xlsx` y `pdf`.
  Cualquier loader registrado pasa sus transacciones por
  `prepare_batch_for_staging(...)` antes de insertar en staging.
- `CanonicalTx.source_type` acepta `qif` y `xlsx` ademas de los tipos previos.
- `StagingRepo` expone metodos reutilizables para `raw_artifacts` y
  `job_runs`, incluyendo corridas `running`, `ok`, `error` y `deferred`.
- Errores typed de loaders:
  - `FILE_LOADER_UNSUPPORTED`, `FILE_LOADER_AMBIGUOUS` y
    `FILE_LOADER_CORRUPT` -> exit `2`.
  - `FILE_LOADER_TEMPORARY` -> exit `5`.

### Breaking changes

Ninguno. El envelope no cambia; los comandos existentes mantienen su forma.

## 2026-05-09 - Phase 3 scraping headful

### Added

- `run --source scraping-be|scraping-cmr` queda como superficie publica del
  CLI para scraping headful asistido.
  - `data` mantiene los campos historicos de `RunSummary` y agrega
    `reconcile_status` y `reconcile_delta`.
- `login --source be|cmr` captura `storage_state` en vault/keyring solo cuando
  el login semi-asistido fue confirmado.
- Errores typed de scraping:
  - Login no completado -> `CREDENTIALS_REQUIRED`, exit `3`.
  - CAPTCHA/challenge -> `SCRAPING_CHALLENGE`, exit `5`.
  - Cambio estructural/selector roto -> `SCRAPING_STRUCTURE_CHANGED`, exit `5`.
- Los jobs de scraping registran `reconcile_log` por cuenta/periodo. Estado
  `off` bloquea OFX y SQL; falta de balances queda como `manual_review`.

### Breaking changes

Ninguno. Los campos nuevos de `data` son aditivos y los comandos existentes
mantienen el envelope.

## 2026-05-08 - Phase 2 gate hardening

### Added

- `category-rules list|add|update|delete` queda documentado como superficie
  publica del CLI:
  - `list`: `data.items[]` contiene `rule_id`, `pattern`, `pattern_type`,
    `merchant_norm`, `category_name`, `subcategory_name`, `tags[]`,
    `fuzzy_threshold`, `priority`, `active`; `data.count`.
  - `add`: `data.rule_id`, `data.created`.
  - `update`: `data.rule_id`, `data.updated_fields[]`.
  - `delete`: `data.rule_id`, `data.deleted`.
- `review`, `quickadd`, `category-rules` y `run --writer sql` validan que
  `--db` exista y tenga schema staging antes de ejecutar operaciones.
- `run --writer sql` registra `job_runs.status='deferred'` cuando MMEX esta
  bloqueado y emite `MMEX_LOCKED` con exit code `4`.

### Changed

- `run --source mp` online lee tokens solo desde vault/keyring; ya no usa
  `MP_ACCESS_TOKEN` como fallback de ejecucion normal.
- `login --source mp` recibe el token por stdin o prompt seguro y lo guarda
  en vault/keyring; no usa variables de entorno como transporte de secreto.
- `run --writer sql` restringe el destino Phase 2 a `finanza_test.mmb`,
  exige `staging_repo` para validar `reconcile_log`, bloquea backups dentro
  del repo, exige backup post-write y deduplica ambas patas de transferencias.
- `replay --since YYYY-MM-DD` queda diferido fuera del contrato estable de
  Fase 2 hasta implementar la restauracion operativa completa.

### Breaking changes

Ninguno para consumidores documentados. Los cambios endurecen entradas
inseguras o no documentadas.

## 2026-05-04 - Issue #3 - Fase 2 SQL writer

### Added

- `run --writer sql` escribe transacciones pendientes desde `staging.db` hacia
  un `.mmb` de test/shadow mediante contrato JSON.
  - Flags nuevos: `--mmex-db`, `--backup-dir`, `--allow-shadow-write`.
  - `--allow-shadow-write` es obligatorio y el destino debe ser `.mmb` de
    test/shadow; `finanza.mmb` productivo y `.emb` se rechazan.
  - `data.mmex_path`, `data.backup_pre_path`, `data.backup_post_path`.
  - `data.items_skipped_duplicate`, `data.items_rejected_unsupported`,
    `data.mmex_tx_ids`, `data.mmex_account_ids`.
- Error `MMEX_LOCKED` usa exit code `4` cuando SQLite/MMEX no permite
  `BEGIN IMMEDIATE`.

### Changed

- Defaults de datos/artefactos salen de la raiz del repo hacia `C:\Finanzas\`:
  `staging.db`, reportes, OFX y backups.

### Breaking changes

Ninguno para el envelope. `run --writer ofx`, `review`, `quickadd` y `login`
mantienen sus campos existentes cuando se pasan rutas explicitas.

## 2026-05-03 — PR #13 (issue #12) — Fase 1.6

### Added

- `review list` — lista transacciones del staging.
  - `data.items[]`: cada item incluye `tx_uid`, `owner`, `source_type`,
    `source_file`, `source_ref`, `event_date`, `booking_date`, `posted_date`,
    `amount` (string Decimal), `currency`, `direction`, `account_alias`,
    `card_last4`, `merchant_raw`, `merchant_norm`, `tx_type`,
    `category_guess`, `subcategory_guess`, `tags[]`, `needs_review` (bool),
    `review_reason`, `fitid_synthetic`, `parser_name`, `parser_version`,
    `mmex_status`, `transfer_pair_uid`.
  - `data.count`: int.
  - `data.filters`: eco de filtros aplicados (`owner`, `account_alias`,
    `status`, `needs_review_only`, `since`, `until`, `limit`).
- `review update` — actualiza campos reviewables en una transacción.
  - `data.tx_uid`: string.
  - `data.updated_fields[]`: nombres **públicos** de los campos modificados
    (la columna interna `tags_json` se expone como `"tags"`).
  - `data.tx`: objeto con la forma de un item de `review list` post-update.
- `review resolve` — fija `mmex_status` a `exported|inserted|rejected`.
  - `data.tx_uid`, `data.mmex_status`.
- `quickadd create` — inserta una transacción manual canónica.
  - `data.created` (bool): `false` si el `fitid_synthetic` ya existía.
  - `data.tx_uid`, `data.fitid_synthetic`.
  - `data.tx`: objeto con la forma de un item de `review list`.
  - Cuando `created=false`, `warnings[]` incluye un aviso de dedup.

### Exit codes

- `0` Success — sin cambios.
- `2` `VALIDATION_ERROR` — sin cambios.
- `3` `CREDENTIALS_REQUIRED` — sin cambios.
- `4` `MMEX_LOCKED` — **reservado** para el writer SQL (Phase 2). Phase 1.6
  no lo emite todavía, pero la UI ya mapea el caso.
- `5` `TEMPORARY_FAILURE` — sin cambios. La UI puede recibir además un
  exit code crudo distinto si el proceso CLI termina con código no
  documentado (1, 137, etc.); `CliErrorMapper` lo refleja en el mensaje.

### Breaking changes

Ninguno. `init`, `run`, `login` mantienen su contrato exacto.

## 2026-05-06 — CMR + Mach email parsers

### Added

- `run --source gmail` ahora acepta `--gmail-source {be,cmr,mach}` (default: `be`).
  - `be`: BancoEstado (comportamiento histórico, sin cambios).
  - `cmr`: CMR email parser (`run_gmail_cmr_to_ofx`).
  - `mach`: Mach email parser (`run_gmail_mach_to_ofx`).
- `data.message` varía según `--gmail-source`: `"Gmail BancoEstado ingestion completed"`,
  `"Gmail CMR ingestion completed"`, `"Gmail Mach ingestion completed"`.

### Breaking changes

Ninguno. `--gmail-source` es opcional con default `be`, completamente
backward-compatible. El contrato del envelope no cambia.

## 2026-05-07 - Gmail and Mercado Pago online hardening

### Changed

- `run --source gmail` y `run --source all` ya no anuncian
  `finanzasmmex login --source gmail`, porque Gmail OAuth login aun no esta
  implementado. Mantienen `CREDENTIALS_REQUIRED` exit `3` y
  `offline_flag: "--input"`.
- MP 401/403 online errors se mapean a `CREDENTIALS_REQUIRED` exit `3`.
- MP temporary/network/server errors se mapean a `TEMPORARY_FAILURE` exit `5`.
- MP online ingestion aborta antes de staging/OFX si un pago aprobado no puede
  parsearse.
- MP negative `transaction_amount` values se rechazan en vez de convertirse a
  creditos positivos.

### Breaking changes

None. The envelope schema is unchanged. MP online behavior is stricter for
unsafe source data.
