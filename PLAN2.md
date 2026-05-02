# Plan Definitivo FinanzasMMEX: Stack Híbrido Python + C# WPF

## Resumen
El plan definitivo toma `PLAN.md` como base principal y rescata de `implementation_plan.md` el detalle operativo inicial de Fase 0/Fase 1. La diferencia clave queda fijada: el stack será híbrido.

Python será el motor financiero: ingesta, ETL, staging SQLite, deduplicación, scraping, OFX, escritura MMEX, backups, logs y jobs. C# WPF .NET 8 será la app desktop local para Review + Quick-add, invocando al motor Python mediante subprocesos con entrada/salida JSON. C# no escribirá directamente en `staging.db` ni en `finanza.mmb`.

## Arquitectura E Interfaces
- Estructura principal: `src/finanzasmmex` para Python, `desktop/FinanzasMMEX.App` para WPF, `contracts/` para esquemas JSON compartidos y `tests/` para motor + contratos.
- CLI Python estable: `finanzasmmex init`, `run --source gmail|mp|scraping-be|scraping-cmr|drop|manual|all --writer ofx|sql`, `login --source gmail|mp|be|cmr`, `review list|update|resolve`, `quickadd create`, `replay --since YYYY-MM-DD`.
- Contrato JSON C# ↔ Python: cada comando devuelve `{ ok, data, errors, warnings, run_id }`; errores con `code`, `message`, `details`; exit codes claros para éxito, validación, credenciales, lock MMEX y fallo temporal.
- Modelo central: `CanonicalTx` inmutable en Python; DTOs equivalentes en C# solo para UI. La fuente de verdad sigue siendo `staging.db`.
- C# WPF: ventana de revisión, edición de categoría/payee/tags, quick-add manual, estado resumido del último job y apertura de reportes HTML locales.
- Seguridad: tokens OAuth, `storage_state` y credenciales solo vía Windows Credential Manager/keyring desde Python. La UI C# nunca muestra secretos completos ni los guarda.

## Fases De Implementación
- Fase 0, base híbrida: crear repo en esta carpeta, `pyproject.toml`, solución `.sln`, proyecto WPF, logging JSONL, config local, `staging/schema.sql`, `repo.py`, `vault.py`, contratos JSON, fixtures anonimizadas, `ruff`, `black`, `mypy`, `pytest`, pruebas C# y `detect-secrets`.
- Fase 1, MVP seguro: implementar Gmail BancoEstado primero hasta cerrar `Gmail -> staging.db -> OFX -> finanza_test.mmb`; luego CMR, Mach y Mercado Pago API; normalización CLP, RapidFuzz, `fitid_synthetic`, transferencias internas, fallback Ollama, reporte HTML y Task Scheduler. UI WPF solo lee pendientes y permite quick-add vía CLI JSON.
- Fase 2, writer SQL: crear `sync_hash` en MMEX, resolver cuentas/payees/categorías/tags, lock detection, backup pre/post, `BEGIN IMMEDIATE / COMMIT / ROLLBACK`, dedupe por `CUSTOMFIELDDATA_V1`, modo dual `--writer ofx|sql`, validación contra `finanza_test.mmb`.
- Fase 3, scraping headful: Playwright headful para BancoEstado/CMR, login semi-asistido, storage_state vía vault, solo lectura, dedupe con sliding window ±14 días, conciliación matemática y abortar ante CAPTCHA. Mach queda email/manual.
- Fase 4, archivos y reportes: loaders OFX/QIF/CSV/PDF/XLSX, watcher drop folder, dashboards HTML mensuales, mejoras de UI para filtros/revisión masiva y notificaciones n8n/Telegram solo para `needs_review`.
- Fase 5, Laura: acuerdo firmado, cuentas separadas en MMEX, tags `Conjunto`, `Personal-R`, `Personal-L`, `Reembolsable`, parsers/fuentes de Laura, sesión inicial headful y flujo de revocación.

## Pruebas Y Aceptación
- Python unitario: parsers, `parse_clp_amount`, FITID estable, fuzzy, transferencias internas, vault mock, reconciliación, writer rollback/idempotencia.
- C# unitario: parseo de respuestas JSON, estados de error, validaciones quick-add, edición de pendientes y manejo de timeouts del subproceso.
- Integración híbrida: WPF invoca CLI Python en ambiente de prueba; crea quick-add; lista pendientes; resuelve una transacción; verifica cambios en `staging.db`.
- E2E financiero: correr mismo lote dos veces sin duplicados; MMEX bloqueado difiere escritura; lote descuadrado no inserta; backup + replay restauran.
- Smoke real: Gmail 24h, Gmail 30 días BancoEstado con extracción >= 95%, MP 30 días, OFX sin duplicados, OAuth revocado con error claro, Ollama apagado manda a revisión.
- Seguridad: sin secretos en repo/logs; storage protegido; tráfico limitado a Gmail API, Mercado Pago API y portales bancarios durante scraping.

## Supuestos Definitivos
- `PLAN.md` es la base correcta, pero debe enriquecerse con el stack híbrido Python + C# WPF.
- `implementation_plan.md` queda como antecedente parcial: útil para detalle de Fase 0/Fase 1, pero insuficiente como plan final.
- Se parte limpio, sin absorber `gmail-to-MMEX` salvo que aparezca después como fuente de fixtures/regex.
- El código vive en esta carpeta; `C:\Finanzas\` queda para datos productivos, backups, logs, drop, staging y reportes.
- La operación productiva usa `.mmb` en carpeta cifrada por BitLocker; `.emb`, LLM remoto, agregadores comerciales, scraping móvil y reverse engineering quedan fuera de v1.
