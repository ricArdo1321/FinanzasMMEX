# Agent test cases

Fixture-set para validar los subagentes Claude Code definidos en `.claude/agents/`. Sirven para tuning iterativo: si un agente da falsos positivos sobre `good/`, ajustar prompt; si pierde detecciones en `bad/`, reforzar reglas.

## Estructura

```
tests/agent_cases/
  <agent-name>/
    good/   # casos donde el agente NO debe levantar findings (o solo `nit`)
    bad/    # casos con violaciones plantadas; el agente DEBE levantarlas
```

## Cómo usar

Manualmente, contra un agente:

1. Invocar el agente con el contenido del caso como input.
2. Para `good/*`: el output esperado es `findings: []` o solo severidad `nit`.
3. Para `bad/*`: el output esperado es ≥1 finding con la severidad indicada en el comentario del archivo.
4. Si el resultado no coincide, ajustar el prompt del agente en `.claude/agents/<agent-name>.md` y reiterar.

No hay corredor automático todavía. Cuando exista, irá en `tests/test_agents.py`.

## Mínimos por agente

Cada agente tiene al menos 2 casos `good/` y 2 `bad/`. Agregar más cuando se descubran nuevos vectores de falla en producción.

## Convenciones de los archivos de caso

- Comentario inicial `# GOOD:` o `# BAD:` con qué se está testeando.
- Para `bad/`, marcar cada violación con comentario `# VIOLATION: ...`.
- Mantener tamaño mínimo viable — un caso por concepto, no mezclar.
