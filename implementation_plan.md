# FinanzasMMEX - Plan de Implementación

Este plan de implementación se basa estrictamente en el documento `FinanzasMMEX_PlanArquitectura.pdf` (v1.0). El objetivo es construir una aplicación de escritorio en Python que consolide transacciones financieras (BancoEstado, CMR, MachBCI, Mercado Pago) mediante una **arquitectura de dos capas** (SQLite de staging y sincronización posterior con `finanza.mmb`).

## User Review Required

> [!IMPORTANT]
> **Aprobación de Fases y Alcance**
> El documento original divide el trabajo en 6 fases (Fase 0 a Fase 5). Para mantener el proceso orgánico e implementable sin saltarnos nada, iniciaremos con la **Fase 0 (Setup)** y la **Fase 1 (MVP - Ingesta de Emails + MP API + Exportación OFX)**. La escritura directa a SQLite en MMEX (`Fase 2`) y el scraping web asistido (`Fase 3`) se construirán progresivamente sobre la base estable del MVP.
> ¿Estás de acuerdo con avanzar iterativamente y enfocarnos primero en dejar completas las Fases 0 y 1 antes de tocar el archivo real de MMEX?

> [!WARNING]
> **Compatibilidad y dependencias locales**
> El proyecto requiere que configuremos credenciales (Google Cloud OAuth para Gmail API y Mercado Pago Developer App) en tu entorno local y que instalemos Ollama (`qwen3:8b`) para el fallback semántico. Requeriremos tu interacción manual esporádica para autorizar tokens y guardarlos en el Windows Credential Manager.

## Open Questions

> [!NOTE]
> 1. **Proyecto previo:** El plan menciona que `FinanzasMMEX` absorberá el proyecto previo `gmail-to-MMEX`. ¿Deseas que creemos un nuevo repositorio / carpeta para `FinanzasMMEX` o trabajamos directamente sobre la base del proyecto anterior si lo tienes accesible en este workspace?
> 2. **Configuración de Google y Mercado Pago:** ¿Ya tienes configuradas las credenciales en Google Cloud (para Gmail API) y Mercado Pago, o te gustaría que te guíe paso a paso cuando lleguemos a la implementación del Setup (Fase 0)?

## Proposed Changes

El proyecto se estructurará modularmente en la carpeta de trabajo (p. ej., `C:\Finanzas\code\`). A continuación se describe la creación de los componentes iniciales.

### Estructura Base y Setup (Fase 0)

Creación del esqueleto del proyecto, base de datos de staging y gestor de credenciales.

#### [NEW] `pyproject.toml`
- Configuración de dependencias (p. ej., `uv` package manager, `pydantic`, `structlog`, `keyring`, `google-api-python-client`, `mercadopago`, `rapidfuzz`, `ollama`, `pytest`).
- Configuración de linters (`ruff`, `mypy`).

#### [NEW] `src/finanzasmmex/staging/schema.sql`
- Script SQL original del Apéndice B con las tablas `canonical_tx`, `raw_artifacts`, `category_rules`, `merge_log`, `reconcile_log` y `job_runs`.

#### [NEW] `src/finanzasmmex/staging/repo.py`
- Abstracción de conexión SQLite con la base de datos `staging.db`. Operaciones CRUD para el modelo de datos.

#### [NEW] `src/finanzasmmex/secrets/vault.py`
- Wrapper para Windows Credential Manager (usando `keyring`) para almacenar de forma segura los refresh tokens de OAuth (Gmail, Mercado Pago) y el estado de Playwright.

### Core Interface y CLI

#### [NEW] `src/finanzasmmex/models.py`
- Definición de la `@dataclass(frozen=True)` `CanonicalTx` como el contrato de interfaz central.

#### [NEW] `src/finanzasmmex/cli.py`
- Entrypoint de línea de comandos para orquestar la ejecución (e.g., `finanzasmmex run --source all`).

### Motor ETL y Normalización (Fase 1)

Componentes encargados de transformar y limpiar la información.

#### [NEW] `src/finanzasmmex/etl/normalize.py`
- Funciones para normalizar fechas y montos (`parse_clp_amount`).

#### [NEW] `src/finanzasmmex/etl/fuzzy.py`
- Lógica de matching de comercios (`RapidFuzz`) contra el historial y `category_rules`.

#### [NEW] `src/finanzasmmex/etl/fitid.py`
- Generador de `fitid_synthetic` mediante hash SHA-256 (owner, account, date, amount, merchant_norm) para deduplicación.

#### [NEW] `src/finanzasmmex/etl/transfers.py`
- Detección en ventana móvil (sliding window) de transferencias internas entre cuentas familiares.

#### [NEW] `src/finanzasmmex/etl/llm_fallback.py`
- Interfaz con `ollama` local (modelo Qwen3 8B) para parsear emails que fallen la extracción por Regex.

### Adapters / Ingestión (Fase 1)

Lectura de datos desde distintas fuentes.

#### [NEW] `src/finanzasmmex/adapters/be_email.py`
- Extracción vía Regex (Apéndice C) para correos de BancoEstado.

#### [NEW] `src/finanzasmmex/adapters/cmr_email.py`
- Extracción vía Regex para correos de Falabella / CMR.

#### [NEW] `src/finanzasmmex/adapters/mach_email.py`
- Extracción vía Regex para notificaciones de MachBCI.

#### [NEW] `src/finanzasmmex/adapters/mp_api.py`
- Integración con API oficial de Mercado Pago usando OAuth.

### Orquestación y Reportes (Fase 1)

#### [NEW] `src/finanzasmmex/orchestrator/jobs.py`
- Lógica de sincronización general: extraer (Adapters) -> transformar (ETL) -> cargar en Staging.

#### [NEW] `src/finanzasmmex/orchestrator/alerts.py`
- Generación de reportes HTML diarios (`reports/review_YYYY-MM-DD.html`) detallando `needs_review` e incongruencias.

### Writer a MMEX (Fase 1 MVP)

#### [NEW] `src/finanzasmmex/writer/ofx_export.py`
- Genera archivos OFX desde `canonical_tx` para la Fase 1, permitiendo a Ricardo importarlos manualmente a MMEX.

---
*(Nota: Los componentes de Fases posteriores (Fase 2: SQL Directo a MMEX y Fase 3: Scraping Headful) se definirán y construirán detalladamente tras estabilizar la Fase 0 y 1, asegurando así un avance robusto).*

## Verification Plan

### Automated Tests
Implementaremos `pytest` para alcanzar una cobertura del 70%+ en ETL y parsing.
- **Unit Tests:**
  - `tests/test_adapters.py`: Ejecutar los parsers de Regex sobre strings anónimos predefinidos (fixtures) para garantizar extracción 100% precisa.
  - `tests/test_fitid.py`: Verificar que campos idénticos generen el mismo hash SHA-256, garantizando idempotencia.
  - `tests/test_fuzzy.py`: Validar la deduplicación de textos usando RapidFuzz.

### Manual Verification
- **Prueba de Ingesta Gmail:** Ejecutar el `job_gmail` de forma local autorizando la cuenta de Ricardo. Validar que la extracción en staging.db sea precisa.
- **Prueba de Ingesta MP:** Autorizar la cuenta de Mercado Pago y validar que los registros caigan a staging.db.
- **Exportación OFX (Fase 1):** Generaremos un archivo `.ofx` para BancoEstado. Deberás importarlo manualmente en un archivo de prueba `finanza_test.mmb` para comprobar que los campos de MMEX (inclusive el CUSTOMFIELDDATA_V1 si existe o se procesa nativamente mediante deduplicación de OFX) se pueblen correctamente.
