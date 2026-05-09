# Runbook 01: Failed workflow rollback

## Symptom

- Engagement w stanie `Failed` wkrótce po Publish wersji `v<n+1>`.
- Alert: `weaver_workflow_failed_total{blueprint_id,version="v<n+1>"}` skacze powyżej baseline.
- Logs Worker: `WorkflowFailedError` z `version=v<n+1>` w Search Attributes.
- Wzrost p95 `weaver_workflow_latency_seconds` dla `version="v<n+1>"`.

## Diagnoza

1. Pobierz historię: `tctl --namespace <tenant> workflow show -w <engagement_id>`.
2. Klasyfikuj `error.type`:
   - `ApplicationError` z `non_retryable=true` → bug w generowanym workflow.
   - `ActivityError` → problem w Tool, patrz Runbook 02.
3. Odczytaj Search Attributes `version`, `build_id`, `blueprint_id`: `tctl ... workflow describe -w <engagement_id>`.
4. Porównaj metryki przed/po Publish:
   - `rate(weaver_workflow_failed_total{blueprint_id,version="v<n>"}[1h])` vs `version="v<n+1>"`.
   - Failure rate `v<n+1>` > 5× `v<n>` → potwierdzony regres.
5. Sprawdź delta: `git diff generated/workflows/<id>/v<n>.py generated/workflows/<id>/v<n+1>.py`.

## Mitigation

1. Stop nowych Engagement na `v<n+1>`:
   - `tctl ... task-queue describe --task-queue <tq>` — odczytaj Build IDs.
   - Worker scale-down dla nowego Build ID (deployment replica → 0).
2. Re-route nowych Engagement do `v<n>`: edytuj `generated/manifest.json` (`active_version: v<n>`), commit, redeploy Router.
3. Running Engagement na `v<n+1>`:
   - Decyzja `terminate`: `tctl ... workflow terminate -w <id> --reason "rollback v<n+1>"` (utrata postępu).
   - Decyzja `reset`: `tctl ... workflow reset -w <id> --event-id <checkpoint_event_id> --reason "rollback"`.
   - Kryterium: jeśli Engagement przetworzył dane krytyczne dla audytu → `reset` do ostatniego checkpoint.
4. Monitoruj `weaver_workflow_failed_total{version="v<n>"}` przez 30 min po rollback.

## Permanent fix

- Architektoniczna zmiana → ADR w `docs/adr/`.
- Bug w generatorze/walidatorze → PR fix + test regresyjny w `tests/codegen/`.
- Publish `v<n+2>` z poprawką; pozostaw `v<n+1>` w `deprecated_versions` z tagiem `failed_rollback`.
- Issue tracker: link do incident report.

## Escalation

| Warunek | Eskalacja |
|---|---|
| > 30 min bez mitigation | Platform on-call |
| Utrata danych Engagement | Tenant Owner + Compliance |
| Cross-tenant impact | Platform Lead |
| Naruszenie SLA | Tenant Owner |

## Powiązane

- `02-stuck-activity.md` — gdy failure pochodzi z Tool.
- `03-manifest-mismatch.md` — gdy rollback ujawnia desync manifestu.
- `docs/PIPELINE.md` — gate Publish.
- `docs/ARCHITECTURE.md` — wersjonowanie i Build ID.
