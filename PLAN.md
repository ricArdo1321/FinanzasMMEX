# Plan De Implementación FinanzasMMEX v1.0

## Resumen
Construir FinanzasMMEX como app desktop/local-first en Python 3.12 para consolidar Gmail, Mercado Pago, scraping headful, archivos drop y entrada manual hacia `staging.db`, y desde ahí hacia Money Manager Ex. El código vivirá en esta carpeta de trabajo; `C:\Finanzas\` será la carpeta productiva para `finanza.mmb`, backups, staging, logs, drop y reportes.

La entrega será orgánica: primero modo seguro con OFX/importación manual, luego escritura SQL directa a MMEX, después scraping y extras. No se tocará el `finanza.mmb` productivo hasta pasar una semana en `shadow mode` contra `finanza_test.mmb`.

## Interfaces Y Datos
- CLI estable: `finanzasmmex init`, `run --source gmail|mp|scraping-be|scraping-cmr|drop|manual|all --writer ofx|sql`, `login --source gmail|mp|be|cmr`, `review`, `replay --since YYYY-MM-DD`.
- Modelo central: `CanonicalTx` inmutable con origen, fechas, monto positivo, dirección, cuenta, comercio crudo/normalizado, tipo contable, categoría, tags, parser, trazabilidad, `needs_review` y `fitid_synthetic`.
- `staging.db`: `schema_version`, `canonical_tx`, `raw_artifacts`, `category_rules`, `merge_log`, `reconcile_log`, `job_runs`, usando WAL, índices de deduplicación y migraciones versionadas.
- MMEX: resolver/crear `PAYEE_V1`, `CATEGORY_V1`, `TAG_V1`, `TAGLINK_V1`; insertar en `CHECKINGACCOUNT_V1`; guardar `sync_hash` en `CUSTOMFIELDDATA_V1`; usar `STATUS='F'` para revisión; modelar transferencias internas como `Transfer` con `TOACCOUNTID`.
- Seguridad: tokens OAuth, `storage_state`, credenciales y secretos solo en Windows Credential Manager vía `keyring`; nada sensible en repo, logs ni archivos planos.
- Fuentes: Gmail label `Bancos`, Mercado Pago OAuth, Playwright headful para BancoEstado/CMR, drop folder `OFX/QIF/CSV/PDF/XLSX`, y quick-add manual.

## Fases De Implementación
- Fase 0, base: crear repo en esta carpeta, `pyproject.toml` con `uv`, `ruff`, `black`, `mypy strict`, `pytest`; generar `SPEC.md` y `ARCHITECTURE.md` desde el PDF; crear `src/finanzasmmex`; implementar config, logging JSONL, `staging/schema.sql`, `staging/repo.py`, `secrets/vault.py`; preparar OAuth Gmail/MP; instalar/probar Ollama `qwen3:8b`; crear fixtures anonimizadas y `detect-secrets`.
- Fase 1, MVP seguro: implementar adapters de email BancoEstado, CMR, Mach y Mercado Pago API; partir con BancoEstado hasta cerrar el loop `Gmail -> staging.db -> OFX -> MMEX test`; implementar normalización de fechas/montos CLP, reglas `category_rules`, RapidFuzz, `fitid_synthetic`, transferencias internas, fallback Ollama JSON-only, exporter OFX por cuenta, reporte HTML diario, jobs Gmail/MP y Task Scheduler; documentar importación manual.
- Fase 2, writer SQL directo: crear campo MMEX `sync_hash` y guardar `FIELDID` en config; mapear `account_alias` a `ACCOUNTID`; detectar locks con timeout cero; hacer backup pre/post con rotación 30 días; escribir con `BEGIN IMMEDIATE / COMMIT / ROLLBACK`; deduplicar por `CUSTOMFIELDDATA_V1`; mantener modo dual `--writer ofx|sql`; validar idempotencia contra `finanza_test.mmb`.
- Fase 3, scraping headful: implementar Playwright headful para BancoEstado y CMR, jamás headless; login semi-asistido con prompts claros; guardar estado vía vault; extraer movimientos solo lectura; fusionar contra emails con sliding window ±14 días y similitud >= 75; poblar `reconcile_log`; abortar ante CAPTCHA o señales de riesgo; Mach queda solo email/manual.
- Fase 4, archivos, UI y reportes: implementar loaders `ofx`, `qif`, `csv`, `pdf`, `xlsx`; PDFs con `pdfplumber`, Camelot y OCR como fallback; watcher de drop folder; UI PySide6 para cola de revisión, quick-add y estado; dashboards HTML mensuales por categoría/tag/comercio; notificación n8n/Telegram solo para `needs_review`.
- Fase 5, Laura: generar y archivar acuerdo de mandato firmado; crear cuentas BE/CMR Laura y tags `Conjunto`, `Personal-R`, `Personal-L`, `Reembolsable`; activar Gmail/parsers de Laura; hacer sesión inicial headful con consentimiento; refinar auto-tagging; implementar revocación: borrar storage/tokens, deshabilitar fuentes de Laura y conservar histórico salvo solicitud de borrado.
- Operación continua: revisar `reports/review_YYYY-MM-DD.html` a diario; refrescar BE/CMR semanalmente; restaurar desde backup con `replay --since`; mantener `category_rules` con prioridad `substr`, `regex`, `fuzzy`; si LLM fallback supera 5% diario, actualizar parser.

## Pruebas Y Aceptación
- Unitarias: parsers con correos reales anonimizados; `parse_clp_amount`; FITID estable; fuzzy merchant; transferencias internas positivas/negativas; vault mock; writer rollback/idempotencia.
- Integración: crear `finanza_test.mmb`, insertar 50 transacciones, correr dos veces y verificar mismo estado; simular lock SQLite; lote descuadrado bloquea writer; backup y replay restauran conteos/balances.
- Smoke manual: Gmail real 24h; Gmail 30 días BancoEstado con extracción >= 95%; MP 30 días; OFX importado sin duplicados; revocar OAuth y confirmar error claro; apagar Ollama y confirmar `needs_review`.
- Seguridad: `detect-secrets`; revisar que no haya credenciales en repo/logs; verificar `storage_state` protegido; monitorear red y permitir solo `googleapis.com`, `mercadopago.com` y portales bancarios durante scraping.
- Criterios finales: sin duplicados al reejecutar; balances cuadrados al peso cuando hay extracto completo; transferencias Ricardo/Laura como `Transfer`; MMEX abierto difiere escritura; categorías automáticas > 90% para comercios conocidos; onboarding Laura menor a 1 hora.

## Supuestos Y Guardrails
- Se parte limpio: no se absorberá `gmail-to-MMEX` porque no apareció en el workspace; se deja compatible la arquitectura para importar regex/tests si aparece después.
- El `implementation_plan.md` actual queda conceptualmente reemplazado por este plan porque solo detallaba Fase 0/1 y dejaba fuera Fase 2/5.
- La operación diaria usa `.mmb` dentro de carpeta cifrada por BitLocker; `.emb` queda fuera de v1.
- No habrá LLM remoto, agregadores comerciales, reverse engineering de MachBCI, scraping móvil ni operaciones transaccionales.
- El bloque legal no es asesoría jurídica: antes de scraping de Laura se firma consentimiento; antes de operación productiva se revalida normativa y T&C.
- Fuentes verificadas: PDF local `investigación/iteracion #3/FinanzasMMEX_PlanArquitectura.pdf`; [BCN Ley 21.459](https://www.bcn.cl/leychile/navegar?idNorma=1177743); [BCN Ley 21.719](https://www.bcn.cl/leychile/navegar?idNorma=1209272); [CMF SFA/NCG 514](https://www.cmfchile.cl/portal/prensa/615/w3-article-92449.html); [CMF consulta SFA 2025](https://www.cmfchile.cl/portal/prensa/615/w3-article-100482.html).
