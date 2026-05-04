# CLI Contract Changelog

Registra cambios al contrato JSON `{ok, data, errors, warnings, run_id}` consumido por la UI WPF. La forma del envelope se valida contra `contracts/envelope.schema.json`.

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
