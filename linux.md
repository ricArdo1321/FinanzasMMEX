# Linux.md

Registro de trabajo desde Linux (no Windows). Este archivo documenta adaptaciones, decisiones y
actividades realizadas fuera del entorno Windows productivo.

---

## 2026-05-05 — Sesión inicial Linux + wire CMR/Mach + login gmail

**Entorno**: Linux 6.17.0-23-generic, Python 3.11+, sin `gh` CLI, sin Windows Credential Manager.

**Adaptaciones**:
- `keyring` no tiene backend Windows en Linux. Para desarrollo local, usar
  `FINANZASMMEX_DISABLE_VAULT=1` o `MP_ACCESS_TOKEN=<token>` env vars.
- `C:\Finanzas\` no existe. Los paths defaults del CLI apuntan a `C:\Finanzas\...` y
  fallarán si no se sobreescriben con flags explícitos (`--db`, `--ofx-output`, etc.).
  Para tests esto no es problema porque usan paths temporales.
- `detect-secrets` no está instalado; `pytest` tampoco (pendiente `pip install -e .[dev]`).

**Issue implementado**: Wire CMR + Mach email parsers en CLI/orchestrator + fix login --source gmail.

## 2026-05-05 — MP online ingestion

**Issue implementado**: `run_mp_online()` en `orchestrator/jobs.py` + wiring en
`cli.py._run_mp()`. Ahora `finanzasmmex run --source mp` sin `--input` utiliza
`MercadoPagoClient.search_payments()` para traer pagos aprobados vía API,
hacer ETL, upsert a staging, y escribir OFX + reporte HTML. Soporta
`--begin-date`/`--end-date` (default: últimos 7 días). All 129 tests passing.

**Próximo issue candidato**: Scraping BE/CMR (Playwright headful, tricky sin
display en Linux), o alguno de los issues de Phase 2 del plan.

## 2026-05-06 — Wire CMR + Mach email parsers (completo)

**Issue**: CMR y Mach parsers existían pero no estaban conectados al CLI ni al
orchestrator. Solo `--source gmail` funcionaba y solo manejaba BancoEstado.

**Implementación**:
- `orchestrator/jobs.py`: se extrajo `_run_email_job()` como helper genérico,
  y `run_gmail_bancoestado_to_ofx` pasó a ser wrapper que inyecta su parser.
- Se agregaron `run_gmail_cmr_to_ofx()` y `run_gmail_mach_to_ofx()` con el
  mismo patrón, cada una con import lazy de su adapter.
- `cli.py`: nuevo flag `--gmail-source {be,cmr,mach}` (default: `be` para
  backward compat). `_run_gmail()` ahora dispatches según el flag.
- `tests/test_phase1_job.py`: tests de idempotencia para CMR y Mach.

**Resultado**: 131 tests passing, ruff/mypy clean. Agentes de revisión
(cli-contract-checker, secrets-pii-auditor) lanzados en background.
