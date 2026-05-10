# Phase 2 Shadow Mode - Week 1

Estado: pendiente de ejecucion real.

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

## Criterio de cierre

Phase 2 queda operativamente cerrable solo si los 7 dias muestran:

- Cero escrituras a `finanza.mmb` productivo.
- Cero duplicados al repetir el mismo lote.
- `reconcile_log.status` distinto de `off` para cada cuenta escrita.
- Backup pre y post existente en cada corrida con inserciones.
- Errores de lock como `MMEX_LOCKED` y `job_runs.status='deferred'`.
