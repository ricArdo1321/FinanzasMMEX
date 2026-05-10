# Phase 2 Shadow Mode - Week 1

Estado: bloqueado para ejecucion real. Preflight 2026-05-10 18:21 -04:00
sin `finanza_test.mmb` operativo ni lote staging.

Este documento existe para cerrar la brecha de auditoria, no como evidencia
retroactiva. Phase 2 solo puede declararse cerrada cuando esta tabla tenga al
menos 7 dias calendario de corridas reales contra `finanza_test.mmb`.

## Requisitos de cada corrida

- Fecha y hora local.
- Comando ejecutado.
- Hash o ruta del `staging.db` usado.
- Ruta exacta de `finanza_test.mmb`.
- Conteo de transacciones consideradas, insertadas, duplicadas y rechazadas.
- Estado de `reconcile_log` por cuenta.
- Rutas de backup pre y post.
- Resultado de segunda corrida idempotente.
- Firma del responsable.

## Registro

| Dia | Fecha | Comando | Items | Duplicados | Reconcile | Backups | Idempotencia | Responsable |
|---|---|---|---:|---:|---|---|---|---|
| 1 | Pendiente | Pendiente | 0 | 0 | Pendiente | Pendiente | Pendiente | Pendiente |
| 2 | Pendiente | Pendiente | 0 | 0 | Pendiente | Pendiente | Pendiente | Pendiente |
| 3 | Pendiente | Pendiente | 0 | 0 | Pendiente | Pendiente | Pendiente | Pendiente |
| 4 | Pendiente | Pendiente | 0 | 0 | Pendiente | Pendiente | Pendiente | Pendiente |
| 5 | Pendiente | Pendiente | 0 | 0 | Pendiente | Pendiente | Pendiente | Pendiente |
| 6 | Pendiente | Pendiente | 0 | 0 | Pendiente | Pendiente | Pendiente | Pendiente |
| 7 | Pendiente | Pendiente | 0 | 0 | Pendiente | Pendiente | Pendiente | Pendiente |

## Preflight 2026-05-10

Resultado: no ejecutado.

- `C:\Finanzas` no expuso un `finanza_test.mmb` operativo durante la busqueda.
- El unico `staging.db` localizado fue el del repo:
  `C:\Users\sqsri\Desktop\Ricardo\una app para mis cuentas\staging.db`.
- Ese `staging.db` contiene `canonical_tx=0`, `reconcile_log=0` y
  `job_runs=0`, por lo que no hay lote real para medir.
- Los `.mmb` encontrados durante busquedas previas pertenecen a carpetas
  temporales `.pytest-*`; no califican como evidencia operacional.

Comando objetivo cuando existan insumos reales:

```powershell
finanzasmmex run --writer sql `
  --db "C:\Finanzas\staging.db" `
  --mmex-db "C:\Finanzas\finanza_test.mmb" `
  --backup-dir "C:\Finanzas\backups" `
  --allow-shadow-write
```

El mismo lote debe correrse una segunda vez para documentar idempotencia.

## Criterio de cierre

Phase 2 queda operativamente cerrable solo si los 7 dias muestran:

- Cero escrituras a `finanza.mmb` productivo.
- Cero duplicados al repetir el mismo lote.
- `reconcile_log.status` distinto de `off` para cada cuenta escrita.
- Backup pre y post existente en cada corrida con inserciones.
- Errores de lock como `MMEX_LOCKED` y `job_runs.status='deferred'`.
