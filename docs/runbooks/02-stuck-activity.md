# Runbook 02: Stuck activity

## Symptom

- Activity bez `ActivityTaskCompleted` event przez > 2× `start_to_close_timeout`.
- `weaver_tool_invocation_total{status="pending"}` rośnie monotonicznie.
- Alert: `weaver_activity_schedule_to_start_latency_seconds` p99 > próg.
- Worker logs: brak `ActivityTaskStarted` dla `activity_id`.
- `tctl workflow describe` pokazuje `pendingActivities` z `attempt > 1` lub `lastHeartbeatTime` stale.

## Diagnoza

1. Stack trace workflow: `tctl --namespace <tenant> workflow query -w <id> -qt __stack_trace`.
2. Inspekcja pending activity:
   - `tctl ... workflow describe -w <id>` → sekcja `pendingActivities`.
   - Pola: `activityId`, `attempt`, `lastHeartbeatTime`, `lastFailure`.
3. Klasyfikacja:
   - `heartbeat_timeout` ustawiony, brak heartbeat → bug w Tool (nie wywołuje `heartbeat()`).
   - Brak `ActivityTaskStarted` → Worker nie zassał z task queue.
   - `attempt` rośnie z `lastFailure` → pętla retry, sprawdź `non_retryable_error_types`.
4. Worker side:
   - `kubectl logs <worker-pod> | grep <activity_id>`.
   - Sprawdź pollery: `tctl ... task-queue describe --task-queue <tq>` → kolumna `LastAccessTime` per Build ID.
5. Tool-wide impact: `sum by (tool_id) (weaver_tool_invocation_total{status="pending"})` — czy stuck dotyczy wszystkich invocation tego Tool.

## Mitigation

1. Cancel pojedynczej activity: `tctl ... activity-cancel -w <id> --activity_id <activity_id>`.
2. Worker nie odbiera tasków:
   - Restart pod: `kubectl rollout restart deployment/<worker>`.
   - Sprawdź `task_queue` rate limit i sticky cache.
3. Systemic stuck (cały Tool):
   - Włącz fallback Tool jeśli zdefiniowany w Blueprint (`tools.<id>.fallback`).
   - Circuit breaker: skaluj down workery konsumujące dany Tool task queue.
   - Komunikat do Tenant Owners zależnych od Tool.
4. Po unblock: `tctl ... workflow signal -w <id> --name retry_activity` (jeśli workflow obsługuje signal).

## Permanent fix

- Long-running Tool bez heartbeat → dodaj `activity.heartbeat()` co < `heartbeat_timeout/2`.
- Niewłaściwy timeout profile → popraw `use.timeouts.{start_to_close,heartbeat,schedule_to_start}` w Blueprint.
- Worker capacity → zwiększ `max_concurrent_activity_task_pollers`.
- ADR jeśli zmiana modelu retry/timeout cross-tenant.

## Escalation

| Warunek | Eskalacja |
|---|---|
| Stuck > 1h pojedyncza activity | Tool maintainer |
| Cross-tenant (wiele namespace) | Platform on-call |
| Worker poolers down | Platform Infra |
| SLA breach Tenant | Tenant Owner |

## Powiązane

- `01-failed-workflow-rollback.md` — gdy stuck eskaluje do workflow failure.
- `docs/ACTIVITY_CATALOG.md` — definicje Tool i timeouts.
- `docs/OBSERVABILITY.md` — metryki activity.
