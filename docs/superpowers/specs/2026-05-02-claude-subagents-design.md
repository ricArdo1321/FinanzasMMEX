# Diseño: Subagentes Claude Code para FinanzasMMEX

**Fecha:** 2026-05-02
**Estado:** Aprobado para plan de implementación
**Scope:** 7 subagentes dev-workflow (`.claude/agents/*.md`) que cubren motor Python + UI WPF + transversal seguridad/datos.

## 1. Objetivo

Acelerar y blindar el desarrollo de FinanzasMMEX con un roster fijo de subagentes Claude Code que automaticen revisiones de alto valor en los puntos críticos del PLAN2: parsers de email, writer MMEX, contrato JSON Python↔C#, schema staging, UI WPF, secretos/PII, y generación de fixtures anonimizadas.

No se busca cubrir todo. Se busca cubrir **lo que duele cuando falla**: leak de PII, escritura corrupta a `finanza.mmb`, regex que silenciosamente baja extracción, breaking changes en contrato CLI que rompen WPF, migraciones de schema sin versión.

## 2. Convenciones comunes

**Ubicación:** `.claude/agents/*.md`, project-scoped, versionados en repo.

**Frontmatter YAML por agente:**
- `name`: kebab-case, único.
- `description`: trigger específico (no genérico). Indica cuándo invocar proactivamente.
- `tools`: subset mínimo necesario. Read-only por default.
- `model`: `sonnet` por default; `opus` solo donde el costo de un falso negativo es alto.

**Cuerpo (system prompt) por agente:**
- Rol y mission statement.
- Reglas duras (lista de "MUST"/"NEVER").
- Checklist accionable.
- Formato de salida estructurado.

**Lectura obligatoria por agente al arrancar:**
- `CLAUDE.md` (orientación repo).
- `PLAN2.md` (plan definitivo).

**Formato de salida (todos los agentes):**
```
findings:
  - severity: blocker | major | minor | nit
    location: <file>:<line>
    rule: <short rule id>
    message: <qué está mal>
    fix: <propuesta concreta>
out-of-scope:
  - <hallazgo fuera de mi alcance> → ver <otro-agente>
summary: <1-2 líneas>
```

**Read-only por default.** Solo `fixtures-anonymizer` escribe (a `tests/fixtures/`). Ningún agente edita código productivo: solo análisis + propuestas que el desarrollador aplica.

**Sin auto-loops:** un agente no invoca a otro. Si encuentra algo fuera de scope, lo lista en `out-of-scope`.

## 3. Roster (7 agentes)

### 3.1 `parser-reviewer`

- **Modelo:** `sonnet`
- **Tools:** Read, Grep, Glob, Bash (solo `pytest` sobre fixtures)
- **Trigger:** cambios en `src/finanzasmmex/adapters/be_email.py`, `cmr_email.py`, `mach_email.py`, `mp_api.py`.
- **Checks:**
  - Regex matchea contra fixtures en `tests/fixtures/<source>/`.
  - Todos los campos no-Optional de `CanonicalTx` poblados (`tx_uid`, `owner`, `source_type`, `content_sha256`, `amount`, `currency`, `direction`, `account_alias`, `tx_type`, `parser_name`, `parser_version`).
  - `amount` siempre positivo; signo en `direction`.
  - Fechas en ISO 8601, validadas con `date.fromisoformat`.
  - `content_sha256` calculado del raw text completo (no del subset extraído).
  - `needs_review=True` cuando hay ambigüedad (monto sin moneda, fecha incierta, multi-match).
  - `parser_name` + `parser_version` seteados (no defaults vacíos).
  - Regex frágiles flagged: dependencia de whitespace literal, locale, HTML rendering específico de cliente.
- **Output extra:** tabla por adapter con `coverage% campos`, ejemplos fallidos, regex sugeridas más robustas.

### 3.2 `mmex-writer-guard`

- **Modelo:** `opus` (costo de falso negativo: corrupción de `finanza.mmb` productivo)
- **Tools:** Read, Grep, Glob (read-only)
- **Trigger:** cambios en `src/finanzasmmex/writer/*.py`, lógica de dedup MMEX, configuración de backup.
- **Checks:**
  - Toda escritura SQL envuelta en `BEGIN IMMEDIATE` ... `COMMIT` con `ROLLBACK` explícito en error.
  - `sync_hash` escrito en `CUSTOMFIELDDATA_V1` antes/atómicamente con insert en `CHECKINGACCOUNT_V1`.
  - Dedup por `sync_hash` antes de cada insert (no confiar solo en `fitid_synthetic` del staging).
  - Lock detect con `timeout=0` → si `.mmb` está abierto en MMEX, abortar limpio (exit code 4) con `needs_review` agregado al run.
  - Backup pre-write y post-write con rotación 30 días, paths configurables, no en repo.
  - Modo dual `--writer ofx|sql` mutuamente excluyente; nunca escribe ambos en el mismo run.
  - **Bloqueador absoluto:** ninguna ruta de código toca `finanza.mmb` productivo. Solo `finanza_test.mmb` hasta validar shadow-mode 1 semana.
  - Idempotencia: ejecutar mismo lote 2x produce mismo estado de DB (verificado con test de integración).
  - Lote descuadrado (`reconcile_log.status='off'`) bloquea writer.
- **Output:** `blocker` si encuentra escritura sin transacción, sin backup, o que toque productivo. Severidad mínima `major` para todo lo demás.

### 3.3 `secrets-pii-auditor`

- **Modelo:** `opus` (costo de falso negativo: leak de credenciales/PII)
- **Tools:** Read, Grep, Glob, Bash (`detect-secrets scan`)
- **Trigger:** pre-commit, pre-PR, cambios en `vault.py`, `adapters/*`, `tests/fixtures/*`, `logs/`.
- **Checks:**
  - `detect-secrets scan` sin findings nuevos.
  - `keyring` es el único path para tokens OAuth, `storage_state` Playwright, credenciales bancarias.
  - Ningún `.env`, `secrets/*.json`, ni archivo plano contiene valores reales (placeholders OK).
  - Fixtures en `tests/fixtures/` no contienen RUTs reales (regex `\d{1,2}\.\d{3}\.\d{3}-[\dkK]`), emails reales, números de cuenta, números de tarjeta (PAN), nombres reales identificables.
  - Logs JSONL no incluyen `raw_text` con PII salvo flag explícito de debug local.
  - `vault.py` nunca expone secret completo en logs (truncar/maskear).
- **Output:** lista de leaks con severidad `blocker`, ubicación, comando concreto de rotación (ejemplo: `python -m finanzasmmex login --source gmail --revoke-then-relogin`).

### 3.4 `cli-contract-checker`

- **Modelo:** `sonnet`
- **Tools:** Read, Grep, Glob (read-only)
- **Trigger:** cambios en `src/finanzasmmex/cli.py`, comandos nuevos, exit codes, `contracts/*.json`.
- **Checks:**
  - Toda salida JSON cumple `{ok: bool, data: any, errors: ErrorObj[], warnings: string[], run_id: str}`.
  - `ErrorObj = {code: str, message: str, details: any}`.
  - Exit codes mapeados consistentemente:
    - `0` success
    - `2` validación de input
    - `3` credenciales inválidas/expiradas
    - `4` lock MMEX (`.mmb` abierto)
    - `5` fallo temporal (red, MP API down)
  - Retrocompatibilidad: campos no removidos sin bump versión del comando; campos nuevos opcionales por default.
  - `contracts/*.json` schemas alineados con la implementación (validar con muestras de salida).
  - Ningún comando emite logs/prints fuera del JSON en stdout (logs van a stderr o JSONL file).
  - Comandos planeados (PLAN2): `init`, `run`, `login`, `review list|update|resolve`, `quickadd create`, `replay --since`.
- **Output:** diff de contrato vs versión previa, breaking changes flagged como `blocker`.

### 3.5 `staging-schema-validator`

- **Modelo:** `sonnet`
- **Tools:** Read, Grep, Glob, Bash (`sqlite3` para dry-run de schema en DB temporal)
- **Trigger:** cambios en `src/finanzasmmex/staging/schema.sql`, `repo.py`, archivos de migración.
- **Checks:**
  - `schema_version` incrementa en cada cambio; insert de versión nueva incluido.
  - `PRAGMA journal_mode=WAL` y `PRAGMA foreign_keys=ON` presentes.
  - Índices de dedup intactos: `uq_canonical_fitid`, `idx_canonical_owner_date`, `idx_canonical_status`, `idx_canonical_match`.
  - Constraints intactos: `amount > 0`, enum `direction IN ('debit','credit')`, enum `mmex_status IN ('pending','exported','inserted','rejected')`, enum `owner`.
  - Migraciones forward-only o con par up/down explícito.
  - `repo.upsert_tx` mantiene política `ON CONFLICT(fitid_synthetic) DO UPDATE` solo de `mmex_status` + `updated_at` (no sobrescribe campos canónicos extraídos).
  - Schema dry-run sobre DB temporal exitoso.
- **Output:** report con migraciones rotas, queries de verificación de integridad, tabla de constraints faltantes.

### 3.6 `wpf-ui-reviewer`

- **Modelo:** `sonnet`
- **Tools:** Read, Grep, Glob (read-only)
- **Trigger:** cambios en `desktop/FinanzasMMEX.App/**`.
- **Checks:**
  - Invocación del CLI Python vía `System.Diagnostics.Process` con `WaitForExitAsync` + `CancellationToken` + timeout configurable.
  - Parseo JSON robusto: maneja `ok=false`, `errors[]` no vacío, exit codes 2/3/4/5.
  - Sin UI freeze: operaciones largas via `await`/`Task.Run`; no `Process.WaitForExit()` síncrono en thread UI.
  - Bindings con `INotifyPropertyChanged` o equivalentes; `ObservableCollection<T>` para listas.
  - **Cero acceso directo a `staging.db` o `finanza.mmb`** — todo via subprocess CLI.
  - Secretos nunca mostrados en UI (solo metadata: "Token Gmail válido hasta YYYY-MM-DD").
  - Errores del CLI mapeados a mensajes UI legibles según `error.code`.
  - `App.xaml`/MVVM separation razonable; code-behind mínimo.
- **Output:** lista de violaciones de contrato + smells WPF, con file:line.

### 3.7 `fixtures-anonymizer`

- **Modelo:** `sonnet`
- **Tools:** Read, Write (solo `tests/fixtures/**`), Grep
- **Trigger:** invocación explícita con email/HTML/PDF/CSV de entrada.
- **Acciones:**
  - Reemplaza RUTs reales por `11.111.111-1` (manteniendo formato y dígito verificador válido).
  - Nombres reales → placeholders consistentes (mismo nombre real → mismo placeholder dentro de un archivo).
  - Cuentas/tarjetas: mantiene últimos 4 si necesarios para parser, resto `****`.
  - Emails reales → `user-XX@example.com` (XX consistente por persona).
  - Montos: opcional aleatorización con flag `--randomize-amounts`; default mantener para no romper tests deterministas.
  - Fechas: opcional shift relativo con flag `--date-shift`; default mantener.
  - Preserva estructura HTML, headers de email, encoding, line endings — los regex de adapters deben seguir matcheando.
- **Garantía:** corre internamente la lógica de `secrets-pii-auditor` sobre el output antes de devolverlo. Si quedan PII residual: falla y reporta.
- **Output:**
  - Archivo escrito en `tests/fixtures/<source>/<case>.txt` (o `.html`/`.pdf` según input).
  - Reporte de reemplazos: tabla `original-pattern → replacement` (sin valores originales en el reporte).

## 4. Workflow + Phase gates

**Matriz disparo:**

| Evento | Agentes |
|---|---|
| Edit `adapters/*` | parser-reviewer, secrets-pii-auditor |
| Edit `writer/*` | mmex-writer-guard, staging-schema-validator |
| Edit `staging/schema.sql` o `repo.py` | staging-schema-validator |
| Edit `cli.py` o `contracts/*` | cli-contract-checker |
| Edit `desktop/**` | wpf-ui-reviewer, cli-contract-checker |
| Pre-commit / pre-PR | secrets-pii-auditor |
| Necesito fixture nueva | fixtures-anonymizer (invocación explícita) |

**Phase gates:**
- **Phase 1 merge:** `parser-reviewer` + `cli-contract-checker` + `secrets-pii-auditor` → todos sin findings `blocker`.
- **Phase 2 merge (writer SQL):** suma `mmex-writer-guard` + `staging-schema-validator` → blocker-free, **y** validación shadow-mode 1 semana contra `finanza_test.mmb` documentada.
- **Phase 4 merge (UI):** suma `wpf-ui-reviewer`.

**Anti-overlap:**
- `parser-reviewer` NO chequea secretos.
- `mmex-writer-guard` NO valida schema staging.
- `cli-contract-checker` NO revisa lógica WPF.
- Cada agente lista hallazgos fuera de scope en `out-of-scope` y delega.

## 5. Validación de los propios agentes

**Fixture-set por agente:** `tests/agent_cases/<agent-name>/{good,bad}/`
- `good/` — ejemplos donde el agente NO debe levantar findings (o solo `nit`).
- `bad/` — ejemplos con violaciones plantadas; el agente debe levantarlas con severidad correcta.

**Tuning loop:** si un agente da falsos positivos sobre `good/`, ajustar prompt. Si falla detección en `bad/`, reforzar reglas.

**Catálogo:** `.claude/agents/README.md` con tabla:
| Nombre | Modelo | Trigger | Severidad típica | Phase gate |

## 6. Entregables del plan de implementación

1. `.claude/agents/parser-reviewer.md`
2. `.claude/agents/mmex-writer-guard.md`
3. `.claude/agents/secrets-pii-auditor.md`
4. `.claude/agents/cli-contract-checker.md`
5. `.claude/agents/staging-schema-validator.md`
6. `.claude/agents/wpf-ui-reviewer.md`
7. `.claude/agents/fixtures-anonymizer.md`
8. `.claude/agents/README.md` (catálogo)
9. `tests/agent_cases/<agent>/{good,bad}/` (fixture-sets, mínimo 2 casos por bucket)
10. Sección agregada a `CLAUDE.md`: "Subagentes disponibles" con tabla de triggers.

## 7. Fuera de alcance (explícito)

- Agentes runtime del motor Python (clasificador comercios, conciliador, LLM-fallback) — esos son módulos productivos, no subagentes Claude Code. PLAN2 ya los cubre.
- Agentes para Phase 3 (scraping headful), Phase 5 (Laura), reportes HTML — agregar cuando esas fases arranquen.
- Auto-loops, multi-agent orchestration, agentes que escriban código productivo.

## 8. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Agentes ruidosos → desarrollador los ignora | Fixture-sets `good/bad`, tuning iterativo, severidades estrictas. |
| Solapamiento entre agentes | Reglas anti-overlap explícitas en prompts; sección `out-of-scope` obligatoria. |
| Costo `opus` × 2 agentes | Solo dos agentes opus; resto sonnet. Falsos negativos en writer/secrets son catastróficos, justifica costo. |
| Drift entre `CLAUDE.md`/`PLAN2.md` y prompts | Cada agente lee ambos al arrancar; revisión trimestral del catálogo. |
| `fixtures-anonymizer` deja PII residual | Auto-corre `secrets-pii-auditor` sobre su output; falla si encuentra. |
