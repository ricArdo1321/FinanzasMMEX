# Issue #3 - Fase 2 Writer SQL Directo

## Checklist

- [x] Leer `AGENTS.md`, `CLAUDE.md`, `PLAN2.md` y roster de agentes.
- [x] Verificar estado GitHub de issue #3.
- [x] Crear subissues de Fase 2 si faltan para separar cortes verificables.
- [x] Implementar writer SQL directo seguro.
- [x] Ejecutar agentes especialistas requeridos por gate Phase 2.
- [x] Ejecutar pruebas y checks locales.
- [x] Actualizar GitHub con evidencia y estado final.

## Revision

Implementado writer SQL de shadow/test con `BEGIN IMMEDIATE`, rollback,
backups pre/post, dedupe por `CUSTOMFIELDDATA_V1.sync_hash`, CLI
`run --writer sql`, exit code 4 para `MMEX_LOCKED`, hardening de parsers y
rutas de datos fuera del repo. **Consolidado segundo pase de agentes
(writer-guard y schema-validator) con correcciones aplicadas para
mapeo de cuentas y sincronización de hashes en transferencias.** 42 tests
verdes. Listo para Phase 3.

---

# Plan - Mejora trabajo registrado en linux.md

Plan detallado: `docs/superpowers/plans/2026-05-07-linux-work-hardening.md`.

## Checklist

- [x] Corregir contrato Gmail: no recomendar `login --source gmail` hasta que exista.
- [x] Mapear errores MP 401/403 a `CREDENTIALS_REQUIRED` exit 3.
- [x] Mapear errores temporales MP a `TEMPORARY_FAILURE` exit 5 sin filtrar tokens.
- [x] Evitar drops silenciosos en MP online: parsear todo antes de upsert/OFX.
- [x] Rechazar montos MP negativos en vez de convertirlos a creditos positivos.
- [x] Cerrar limpieza writer transfer: tests verdes actuales + ruff limpio.
- [x] Actualizar `linux.md` y `contracts/CHANGELOG.md` con la verdad operativa.
- [x] Ejecutar gates: `ruff`, `mypy`, `pytest`, `detect-secrets` y especialistas aplicables.

## Revision

Implementado y verificado. Corregidos contrato Gmail, mapeo de errores MP,
parseo fail-fast de MP online, rechazo de montos negativos y limpieza del
writer de transferencias. Evidencia: `ruff check src/ tests/`, `mypy src/`,
`pytest --basetemp C:\tmp\pytest-finanzasmmex-full-final` con 149 passed,
`detect_secrets scan --baseline .secrets.baseline`, `dotnet build
FinanzasMMEX.slnx` y checklist local de especialistas sin blockers.

---

# Auditoria independiente - Cierre real Phase 2

## Checklist

- [x] Leer `CLAUDE.md`, `PLAN2.md`, roster de agentes e informe local en `tareas/a-hacer.md`.
- [x] Aplicar checklists locales de especialistas requeridos por gate Phase 2.
- [x] Ejecutar pruebas de integridad Python, contrato CLI, writer SQL y staging.
- [x] Ejecutar pruebas/build .NET relevantes.
- [x] Verificar evidencia documental de shadow-mode 1 semana contra `finanza_test.mmb`.
- [x] Emitir veredicto final con blockers y pruebas ejecutadas.

## Revision

Veredicto: **Phase 2 no esta terminada**.

Evidencia ejecutada:
- `ruff check src tests` fallo con 22 errores.
- `mypy src` fallo con 4 errores en `src/finanzasmmex/writer/mmex_sql.py`.
- `pytest --basetemp .pytest-phase2-audit -p no:cacheprovider`: 150 passed.
- `detect_secrets scan --baseline .secrets.baseline`: sin nuevos hallazgos.
- Schema staging en SQLite `:memory:` ejecuto OK, version 2.
- `dotnet build FinanzasMMEX.slnx`: OK, 0 errores, 0 warnings.
- `dotnet test desktop/FinanzasMMEX.App.Tests/FinanzasMMEX.App.Tests.csproj --no-restore`: 19 passed.

Bloqueos de gate detectados en checklist local:
- `parser-reviewer`: blocker en `mp_api.py` por inferencia de direction/tx_type.
- `secrets-pii-auditor`: blockers por uso de `MP_ACCESS_TOKEN` como bypass/env bootstrap.
- `mmex-writer-guard`: writer gate bloqueado por politica de target `.mmb`,
  ausencia de shadow-mode 1 semana, post-backup no obligatorio, backup_dir
  dentro del repo, dedupe parcial en transferencias y bypass de reconcile guard.
- `cli-contract-checker`: sin breaking-change blocker, pero majors por `replay`
  ausente, validacion DB insuficiente y `category-rules` no documentado.
- `staging-schema-validator`: sin findings; schema y upsert policy OK.

No se encontro documento de shadow-mode >= 1 semana contra `finanza_test.mmb`.

---

# Implementacion - Remediar blockers Phase 2

## Checklist

- [x] Corregir MP API: inferir `direction`/`tx_type` por `operation_type` y
  marcar revision ante operaciones desconocidas.
- [x] Corregir MP API: soportar hash de `raw_text` completo cuando viene de
  archivo/API cruda.
- [x] Eliminar uso normal de `MP_ACCESS_TOKEN` para ejecucion online y login.
- [x] Endurecer CLI: validar `staging.db`, ayuda anidada y registrar lock en
  `job_runs.status='deferred'`.
- [x] Endurecer writer SQL: solo `finanza_test.mmb`, `staging_repo`
  obligatorio, backup post obligatorio, backups fuera del repo y dedupe de
  ambas patas de transferencias.
- [x] Documentar `category-rules`, diferir `replay` fuera de Fase 2 y crear
  runbook de shadow-mode.
- [x] Ejecutar verificacion completa.

## Revision

Implementado el cierre tecnico de blockers de codigo/contrato detectados en la
auditoria. Evidencia final:
- `ruff check src tests`: OK.
- `mypy src`: OK.
- `pytest --basetemp C:\tmp\pytest-finanzasmmex-phase2-final -p no:cacheprovider`: 162 passed.
- `detect_secrets scan --baseline .secrets.baseline`: OK; se actualizo baseline
  por falso positivo de hash en `skills-lock.json`.
- `dotnet build FinanzasMMEX.slnx`: OK, 0 errores, 0 warnings.
- `dotnet test desktop/FinanzasMMEX.App.Tests/FinanzasMMEX.App.Tests.csproj --no-restore`: 19 passed.
- `git diff --check`: OK.

Nota operativa: Phase 2 queda lista a nivel tecnico para iniciar/correr el gate,
pero **no debe declararse cerrada productivamente** hasta completar 7 dias reales
de shadow-mode en `docs/shadow-mode/phase2-week-1.md`.

Modo de revision: checklist local Codex sobre los especialistas requeridos; no se
declaro ejecucion de subagentes delegados.

---

# Issue #4 - Fase 3 Scraping Headful

Estado: tecnicamente lista por checks locales; cierre remoto pendiente por bloqueo de `gh`.
Orden critico:
1. #25 Pipeline scraping -> staging: FITID, dedupe, tests de job.
2. #27 Abortos seguros: CAPTCHA/login/cambios estructurales + stdout JSON-only.
3. #26 Conciliacion matematica: registrar `reconcile_log` y bloquear `off`.
4. #28 Gate final: fixtures HTML, changelog, ruff/mypy/pytest/detect-secrets y checklists especialistas.

No cerrar #4 hasta que #25-#28 esten cerrados y los gates pasen.

## Revision #25

Pipeline scraping -> staging verificado para BancoEstado/CMR: los jobs pasan
por `prepare_batch_for_staging`, calculan FITID, hacen merge con movimientos
existentes y mantienen idempotencia al reejecutar. Evidencia:
`tests/test_phase3_scraping_jobs.py` incluido en full pytest con 210 passed.

## Revision #27

Abortos seguros de scraping verificados: login incompleto devuelve
`CREDENTIALS_REQUIRED` exit 3, CAPTCHA/challenge usa `SCRAPING_CHALLENGE`,
cambio estructural usa `SCRAPING_STRUCTURE_CHANGED` exit 5 y stdout mantiene
envelope JSON-only. Evidencia: `tests/test_phase3_scraping_errors.py` incluido
en full pytest con 210 passed.

## Revision #26

Conciliacion matematica verificada: scraping registra `reconcile_log`,
calcula status `ok|off|manual_review`, bloquea OFX ante `off` y deja CMR sin
balances como `manual_review`. Evidencia: `tests/test_phase3_reconcile.py`
incluido en full pytest con 210 passed.

## Revision #28

Gate final Fase 3 verificado junto con Fase 4: fixtures HTML anonimizadas de
BancoEstado/CMR poblan campos canonicos, contrato CLI documentado en
`contracts/CHANGELOG.md`, y checks completos pasan. Evidencia:
- `pytest --basetemp .pytest-phase4-final-full3 -p no:cacheprovider`: 210 passed.
- `ruff check src tests`: OK.
- `mypy src`: OK.
- `dotnet build FinanzasMMEX.slnx --no-restore` con `UseSharedCompilation=false`: OK.
- `dotnet test desktop/FinanzasMMEX.App.Tests/FinanzasMMEX.App.Tests.csproj --no-restore`: 27 passed.
- `detect_secrets scan --baseline .secrets.baseline`: OK.
- `git diff --check`: OK.

Checklists locales aplicados: `parser-reviewer`, `cli-contract-checker`,
`staging-schema-validator`, `wpf-ui-reviewer` y `secrets-pii-auditor` sin
blockers. Resultado: #4 queda listo localmente; cierre remoto pendiente por
bloqueo de GitHub CLI.

---

# Issue #5 - Fase 4 Archivos, Reportes y Notificaciones

Estado: abierta; auditoria 2026-05-09 confirma brechas. Orden critico:
1. #29 F4.1 Base loaders/drop: contrato, qif/xlsx, raw_artifacts/job_runs.
2. #30 F4.2 Loaders OFX/QIF/CSV/XLSX + fixtures.
3. #31 F4.3 PDF review-first + fixtures anonimizadas.
4. #32 F4.4 Drop watcher: processed/error, cuarentena, idempotencia.
5. #33 F4.5 Dashboards/reports HTML mensuales.
6. #34 F4.6 Alerta local needs_review sin integraciones externas.
7. #35 F4.7 Bulk review CLI.
8. #36 F4.8 WPF filtros, bulk review y reportes.
9. #37 F4.9 Gate final: changelog, especialistas y checks.

No cerrar #5 hasta cerrar subissues F4, resolver o declarar bloqueo externo #17, y pasar gates.

## Revision #29

Implementada base Fase 4.1: contrato comun para loaders de archivos, soporte
`source_type` para `qif`/`xlsx`, metodos reutilizables `raw_artifacts` y
`job_runs`, dispatch inicial `run --source drop` con errores typed y changelog
de contrato. Evidencia: `pytest tests/test_phase4_foundation.py
tests/test_staging.py --basetemp .pytest-phase4-1 -p no:cacheprovider` con 13
passed; `ruff check src/ tests/`; `mypy src/`; `detect_secrets scan --baseline
.secrets.baseline`; `git diff --check`. Nota: `tests/test_cli_contract.py`
sigue con dos fallos preexistentes del writer SQL por `backup_dir` dentro del
worktree; no se mezcla en #29.

## Revision #30

Implementados loaders deterministas OFX/QIF/CSV/XLSX para `run --source drop`,
fixtures anonimizadas para OFX/QIF/CSV y fixture XLSX generado en test. Los
loaders normalizan signo, fecha, comercio, cuenta, categoria/tags, marcan
`needs_review` ante cuenta/comercio faltante y delegan FITID al ETL. Evidencia:
`pytest tests/test_phase4_file_loaders.py tests/test_phase4_foundation.py
tests/test_staging.py --basetemp .pytest-phase4-2 -p no:cacheprovider` con 20
passed; `ruff check` focal; `mypy src/`.

## Revision #31

Implementado loader PDF review-first para `run --source drop`: usa `pdfplumber`
si esta disponible, fallback a texto embebido, marca toda transaccion PDF como
`needs_review=true`, deja `raw_text` vacio y falla claro con
`FILE_LOADER_CORRUPT` cuando no hay tabla soportada. Evidencia: `pytest
tests/test_phase4_file_loaders.py tests/test_phase4_foundation.py --basetemp
.pytest-phase4-3 -p no:cacheprovider` con 17 passed; `ruff check` focal;
`mypy src/`.

## Revision #32

Implementada ingesta de carpeta drop one-shot: default `C:\Finanzas\drop`,
estados `processing`/`processed`/`error`, validacion de archivo estable,
cuarentena de malformados y resumen JSON con archivos procesados/error.
Evidencia: `pytest tests/test_phase4_drop_job.py tests/test_phase4_file_loaders.py
tests/test_phase4_foundation.py --basetemp .pytest-phase4-4 -p no:cacheprovider`
con 20 passed; `ruff check` focal; `mypy src/`.

## Revision #33

Checklist:
- [x] Generar `dashboard_YYYY-MM.html` mensual desde `canonical_tx`.
- [x] Agregar agregaciones por categoria, tag, comercio y cuenta.
- [x] Resumir `needs_review` y estados MMEX sin exponer `raw_text`.
- [x] Exponer CLI `reports monthly/list/latest` con rutas HTML seguras.
- [x] Ejecutar pruebas y gates focales.

Implementado modulo de reportes HTML mensuales, comandos `reports monthly`,
`reports list` y `reports latest`, changelog de contrato y tests de dashboard
vacio, con datos, listado/latest y path peligroso.

Evidencia:
- `pytest tests/test_phase4_reports.py --basetemp .pytest-phase4-reports -p no:cacheprovider`: 4 passed.
- `pytest tests/test_phase4_foundation.py tests/test_phase4_file_loaders.py tests/test_phase4_drop_job.py tests/test_phase4_reports.py --basetemp .pytest-phase4-all -p no:cacheprovider`: 24 passed.
- `pytest tests/test_cli_contract.py -k "not run_sql_success_returns_sql_metrics_and_updates_staging and not run_sql_second_run_keeps_mmex_and_staging_state_unchanged" --basetemp .pytest-phase4-cli-contract-filtered -p no:cacheprovider`: 21 passed, 2 deselected.
- `ruff check src tests/test_phase4_reports.py`: OK.
- `mypy src`: OK.
- `detect_secrets scan --baseline .secrets.baseline`: OK.
- `git diff --check`: OK.

Nota: `tests/test_cli_contract.py` completo mantiene 2 fallos preexistentes del
writer SQL por `backup_dir` dentro del worktree; no pertenecen al corte #33.

## Revision #34

Checklist:
- [x] Agregar `notify needs-review --dry-run`.
- [x] Mantener el flujo local-only, sin canales externos ni credenciales nuevas.
- [x] Construir payload minimo sin `raw_text`, tokens ni PII innecesaria.
- [x] No enviar nada cuando no hay `needs_review`.
- [x] Ejecutar pruebas y gates focales.

Implementado modulo de alerta local needs_review, comando `notify needs-review`,
payload resumido y tests de dry-run/local-only, no-envio y redaccion.

Evidencia:
- `pytest tests/test_phase4_notifications.py --basetemp .pytest-phase4-notifications -p no:cacheprovider`: 5 passed.
- `pytest tests/test_phase4_foundation.py tests/test_phase4_file_loaders.py tests/test_phase4_drop_job.py tests/test_phase4_reports.py tests/test_phase4_notifications.py --basetemp .pytest-phase4-with-notify -p no:cacheprovider`: 29 passed.
- `pytest tests/test_cli_contract.py -k "not run_sql_success_returns_sql_metrics_and_updates_staging and not run_sql_second_run_keeps_mmex_and_staging_state_unchanged" --basetemp .pytest-phase4-cli-contract-filtered -p no:cacheprovider`: 21 passed, 2 deselected.
- `ruff check src tests/test_phase4_notifications.py tests/test_phase4_reports.py`: OK.
- `mypy src`: OK.
- `detect_secrets scan --baseline .secrets.baseline`: OK.
- `git diff --check`: OK.

Checklist local `cli-contract-checker`: sin breaking changes, stdout solo por
`_emit`, nuevo contrato documentado. Checklist local `secrets-pii-auditor`: sin
nuevos hallazgos en `detect-secrets`; payload no incluye `raw_text`, comercio,
cuenta, hashes, tokens ni source paths, y no agrega nuevos secretos.

Nota: `tests/test_cli_contract.py` completo mantiene 2 fallos preexistentes del
writer SQL por `backup_dir` dentro del worktree; no pertenecen al corte #34.

## Revision #35

Checklist:
- [x] Agregar `review bulk-update`.
- [x] Agregar `review bulk-resolve`.
- [x] Devolver resultado por fila con `tx_uid`, `ok`, `updated_fields`, `tx` o `error`.
- [x] Reportar fallos parciales sin ocultar filas exitosas.
- [x] Documentar contrato aditivo.
- [x] Ejecutar pruebas y gates focales.

Implementado bulk review por archivo JSON, con validacion por fila y resultados
parciales en `data.results[]`.

Evidencia:
- `pytest tests/test_cli_review.py --basetemp .pytest-bulk-review -p no:cacheprovider`: 12 passed.
- `pytest tests/test_cli_review.py tests/test_phase4_foundation.py tests/test_phase4_file_loaders.py tests/test_phase4_drop_job.py tests/test_phase4_reports.py tests/test_phase4_notifications.py --basetemp .pytest-phase4-bulk-review -p no:cacheprovider`: 41 passed.
- `pytest tests/test_cli_contract.py -k "not run_sql_success_returns_sql_metrics_and_updates_staging and not run_sql_second_run_keeps_mmex_and_staging_state_unchanged" --basetemp .pytest-phase4-cli-contract-filtered -p no:cacheprovider`: 21 passed, 2 deselected.
- `ruff check src tests/test_cli_review.py tests/test_phase4_notifications.py tests/test_phase4_reports.py`: OK.
- `mypy src`: OK.
- `detect_secrets scan --baseline .secrets.baseline`: OK.
- staging schema dry-run SQLite `:memory:`: OK, version 2.
- `git diff --check`: OK.

Checklist local `cli-contract-checker`: sin breaking changes, stdout solo por
`_emit`, nuevo contrato documentado. Checklist local
`staging-schema-validator`: sin cambios de schema/repo, indices requeridos y
upsert policy intactos, dry-run OK. Checklist local `secrets-pii-auditor`: sin
nuevos hallazgos en `detect-secrets`.

Nota: `tests/test_cli_contract.py` completo mantiene 2 fallos preexistentes del
writer SQL por `backup_dir` dentro del worktree; no pertenecen al corte #35.

## Revision #36

Checklist:
- [x] Agregar filtros WPF: desde/hasta, limite, fuente, categoria y comercio.
- [x] Completar DTO C# de `review list` con trazabilidad del contrato CLI.
- [x] Habilitar edicion individual via `review update`.
- [x] Habilitar operaciones masivas via `review bulk-update` y
  `review bulk-resolve`.
- [x] Abrir reportes HTML generados via `reports latest` y servicio seguro.
- [x] Mantener WPF sin acceso directo a SQLite/MMEX.
- [x] Ejecutar pruebas, build y checklists locales requeridos.

Implementada ampliacion WPF Fase 4: filtros avanzados, panel de edicion de la
transaccion seleccionada, lote sobre filas visibles, apertura segura del ultimo
dashboard HTML y parser C# para review/bulk/reportes. El contrato `review list`
agrega filtros opcionales `--source-type`, `--category` y `--merchant`.

Evidencia:
- `pytest tests/test_cli_review.py --basetemp .pytest-phase4-wpf-cli -p no:cacheprovider`: 13 passed.
- `pytest tests/test_cli_review.py tests/test_phase4_foundation.py tests/test_phase4_file_loaders.py tests/test_phase4_drop_job.py tests/test_phase4_reports.py tests/test_phase4_notifications.py --basetemp .pytest-phase4-wpf -p no:cacheprovider`: 42 passed.
- `pytest tests/test_cli_contract.py -k "not run_sql_success_returns_sql_metrics_and_updates_staging and not run_sql_second_run_keeps_mmex_and_staging_state_unchanged" --basetemp .pytest-phase4-wpf-cli-contract-filtered -p no:cacheprovider`: 21 passed, 2 deselected.
- `ruff check src tests/test_cli_review.py tests/test_phase4_reports.py tests/test_phase4_notifications.py`: OK.
- `mypy src`: OK.
- `dotnet test desktop/FinanzasMMEX.App.Tests/FinanzasMMEX.App.Tests.csproj --no-restore`: 27 passed.
- `dotnet build FinanzasMMEX.slnx --no-restore` con `UseSharedCompilation=false`: OK.
- `detect_secrets scan --baseline .secrets.baseline`: OK.
- staging schema dry-run SQLite `:memory:`: OK, version 2.
- `git diff --check`: OK.

Checklist local `wpf-ui-reviewer`: sin acceso directo C# a SQLite/MMEX; UI usa
`ICliRunner`, DTOs tipados, `ObservableCollection`, comandos async, code-behind
sin logica de negocio y exit codes 2/3/4/5 siguen mapeados por
`CliErrorMapper`. La apertura HTML usa un servicio separado con validacion de
extension/existencia antes de shell-open. Checklist local
`cli-contract-checker`: cambio aditivo, flags opcionales, `_emit` preservado,
stdout JSON-only y changelog actualizado. Checklist local
`staging-schema-validator`: sin cambio de schema, version 2 intacta, indices y
constraints requeridos presentes, upsert policy intacta. Checklist local
`secrets-pii-auditor`: baseline presente, sin nuevos hallazgos; fixtures solo
contienen emails `example.com`.

Nota: `tests/test_cli_contract.py` completo mantiene 2 fallos preexistentes del
writer SQL por `backup_dir` dentro del worktree; no pertenecen al corte #36.

## Revision #37

Checklist:
- [x] Ejecutar gate final Python completo.
- [x] Ejecutar gate final WPF/.NET.
- [x] Confirmar contrato CLI completo sin filtros excepcionales.
- [x] Confirmar writer SQL tests alineados con regla de backups fuera del repo.
- [x] Confirmar changelog y registro operativo de Fase 4.
- [x] Aplicar checklists locales de especialistas relevantes.

Gate final Fase 4 ejecutado. Se corrigieron tests heredados para que el writer
SQL use `backup_dir` fuera del worktree, tal como exige el guard actual, y se
agrego `.pytest-*/` al `.gitignore` para que los basetemp locales no entren al
estado de Git.

Evidencia:
- `pytest --basetemp .pytest-phase4-final-full3 -p no:cacheprovider`: 210 passed.
- `pytest tests/test_cli_contract.py --basetemp .pytest-phase4-final-cli-contract-full -p no:cacheprovider`: 23 passed.
- `pytest tests/test_mmex_sql_writer.py --basetemp .pytest-mmex-writer-final -p no:cacheprovider`: 29 passed.
- `ruff check src tests`: OK.
- `mypy src`: OK.
- `dotnet build FinanzasMMEX.slnx --no-restore` con `UseSharedCompilation=false`: OK.
- `dotnet test desktop/FinanzasMMEX.App.Tests/FinanzasMMEX.App.Tests.csproj --no-restore`: 27 passed.
- `detect_secrets scan --baseline .secrets.baseline`: OK.
- staging schema dry-run SQLite `:memory:`: OK, version 2.
- `git diff --check`: OK.

Checklists locales:
- `parser-reviewer`: fixtures y parsers cubiertos por full pytest; `CanonicalTx`
  conserva amount positivo, direction explicito, parser metadata y review flags.
- `cli-contract-checker`: 23/23 contrato completo, `_emit` preservado, stdout
  JSON-only, cambios documentados en `contracts/CHANGELOG.md`.
- `staging-schema-validator`: schema version 2, pragmas, indices,
  constraints y upsert policy intactos; dry-run OK.
- `wpf-ui-reviewer`: UI no toca SQLite/MMEX directo, usa `ICliRunner`,
  DTOs tipados, async commands y code-behind minimo; `WaitForExit` sincrono fue
  eliminado del runner.
- `secrets-pii-auditor`: baseline presente, `detect_secrets` sin nuevos
  hallazgos, fixtures con dominios `example.com` solamente.

Resultado: Fase 4 queda tecnicamente lista por checks locales. Commit
`156072b9d90ff7d8b4f732b79de3b482464bdf34` fue empujado a
`feat/phase-2.5-internal-transfers` y se cerraron en GitHub #36, #37 y el padre
#5. #17 permanece abierto como gate operativo de Phase 2, no como bloqueo de
codigo de Phase 4.

---

# Issue #17 - Fase 2.4 Shadow-mode 1 semana contra finanza_test.mmb

## Checklist

- [x] Confirmar que #17 es el siguiente issue abierto accionable de Phase 2.
- [x] Revisar runbook `docs/shadow-mode/phase2-week-1.md`.
- [x] Buscar `finanza_test.mmb` operativo fuera de artefactos `.pytest-*`.
- [x] Revisar si el `staging.db` local tiene lote real para shadow-mode.
- [x] Documentar bloqueo sin fabricar evidencia.
- [ ] Ejecutar 7 dias calendario reales contra `finanza_test.mmb`.
- [ ] Registrar segunda corrida idempotente por dia.
- [ ] Comentar/cerrar #17 solo con evidencia real completa.

## Revision

Preflight ejecutado el 2026-05-10 18:21 -04:00. No se puede iniciar el dia 1
de shadow-mode todavia:

- No se encontro `C:\Finanzas\finanza_test.mmb` operativo.
- El `staging.db` del repo existe, pero contiene `canonical_tx=0`,
  `reconcile_log=0` y `job_runs=0`.
- Los `.mmb` visibles corresponden a carpetas temporales `.pytest-*`; no son
  evidencia operacional aceptable.

Resultado: #17 queda abierto y bloqueado por insumos reales. El proximo paso es
proveer o generar fuera del repo `C:\Finanzas\staging.db` con lote real y
`C:\Finanzas\finanza_test.mmb`, luego ejecutar el comando documentado en
`docs/shadow-mode/phase2-week-1.md` durante 7 dias.
