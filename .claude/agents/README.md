# Subagentes Claude Code — FinanzasMMEX

Roster fijo de 7 subagentes dev-workflow. Cubren los puntos críticos del PLAN2 sin solaparse. Cada agente lee `CLAUDE.md` y `PLAN2.md` al arrancar.

## Catálogo

| Nombre | Modelo | Trigger principal | Severidad típica | Phase gate |
|---|---|---|---|---|
| `parser-reviewer` | sonnet | Edit en `src/finanzasmmex/adapters/*` | major | Phase 1 merge |
| `mmex-writer-guard` | opus | Edit en `src/finanzasmmex/writer/*` o lógica MMEX | blocker | Phase 2 merge |
| `secrets-pii-auditor` | opus | Pre-commit / pre-PR / `vault.py` / fixtures / logs | blocker | Phase 1 merge |
| `cli-contract-checker` | sonnet | Edit en `cli.py` o `contracts/*` | major | Phase 1 merge |
| `staging-schema-validator` | sonnet | Edit en `staging/schema.sql` o `repo.py` | major | Phase 2 merge |
| `wpf-ui-reviewer` | sonnet | Edit en `desktop/**` | major | Phase 4 merge |
| `fixtures-anonymizer` | sonnet | Invocación explícita con archivo fuente | n/a (writer agent) | continuo |

## Anti-overlap

- `parser-reviewer` no chequea secretos → `secrets-pii-auditor`.
- `mmex-writer-guard` no valida schema staging → `staging-schema-validator`.
- `cli-contract-checker` no revisa lógica WPF → `wpf-ui-reviewer`.
- Cada agente lista hallazgos fuera de scope en `out-of-scope:` y delega.

## Cuándo invocarlos

**Proactivos** (Claude Code los considera por su `description`):
- parser-reviewer al editar adapters.
- mmex-writer-guard al editar writer.
- staging-schema-validator al editar schema.sql / repo.py.
- cli-contract-checker al editar cli.py.
- wpf-ui-reviewer al editar desktop/.
- secrets-pii-auditor antes de commits/PRs y al tocar archivos sensibles.

**Explícitos** (invocación manual):
- fixtures-anonymizer — siempre. Pasarle path del archivo fuente real.
- Cualquier otro cuando se quiera ejecutar como auditoría puntual.

## Phase gates

| Phase | Gates obligatorios (sin findings `blocker`) |
|---|---|
| Phase 1 (MVP seguro: Gmail → staging → OFX) | parser-reviewer, cli-contract-checker, secrets-pii-auditor |
| Phase 2 (writer SQL directo a MMEX) | + mmex-writer-guard, staging-schema-validator, **shadow-mode 1 semana documentado** |
| Phase 4 (UI + reportes) | + wpf-ui-reviewer |

Phases 3 (scraping headful) y 5 (Laura) heredan los gates de Phase 2 + 4. Si se necesitan agentes específicos para esas fases, agregar al catálogo.

## Validación de los propios agentes

`tests/agent_cases/<agent-name>/{good,bad}/`:
- `good/` — casos donde el agente NO debe levantar findings (o solo `nit`).
- `bad/` — casos con violaciones plantadas; el agente debe levantarlas.

Tuning loop: si hay falsos positivos en `good/`, ajustar el prompt; si hay falsos negativos en `bad/`, reforzar reglas.

## Convenciones de salida

Todos los agentes producen:

```
findings:
  - severity: blocker|major|minor|nit
    location: <file>:<line>
    rule: <id>
    message: <issue>
    fix: <propuesta>
out-of-scope:
  - <observación> → ver <otro-agente>
summary: <1-2 líneas>
```

Algunos agentes agregan secciones específicas (coverage_table, schema_check, contract_diff, boundary_check, postflight_audit). Ver el `.md` de cada uno.

## Modelos

- `opus`: `mmex-writer-guard`, `secrets-pii-auditor`. Costo de falso negativo catastrófico.
- `sonnet`: el resto.

## Modificar el roster

1. Editar el `.md` del agente.
2. Si cambia trigger o severidad, actualizar el catálogo aquí.
3. Si es nuevo agente, agregar fila en catálogo, casos en `tests/agent_cases/`, y mencionar en `CLAUDE.md`.
4. Revisión trimestral del catálogo: alinear con cambios en PLAN2 / CLAUDE.md.
