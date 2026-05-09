# Runbook 04: Version cleanup (deprecated)

## Symptom

- `manifest.blueprints.<id>.deprecated_versions` rośnie monotonicznie.
- Worker image size > próg (np. > 2 GB).
- Worker startup time > 60s (registracja wszystkich workflow types).
- Storage cost alert (S3/GCS bucket `generated/`).
- `tctl task-queue describe` zwraca > 20 Build IDs per task queue.

## Diagnoza

1. Per-blueprint inventory:
   - `jq '.blueprints[].deprecated_versions | length' generated/manifest.json`.
   - Lista: `jq '.blueprints | to_entries[] | {id: .key, deprecated: .value.deprecated_versions}' generated/manifest.json`.
2. Per Build ID running count:
   ```
   tctl --namespace <tenant> task-queue describe --task-queue <tq> --task-queue-type workflow
   ```
   - Tabela: Build ID → `pollers`, `backlog`.
   - Cross-reference z `tctl workflow list --query "BuildIds = '<build_id>'"`.
3. Kandydaci do retire: `deprecated AND running_count == 0 AND age > retention_window`.
4. Image audit: `docker history <worker-image> | grep generated/workflows`.

## Mitigation (housekeeping)

1. Dry-run cleanup:
   ```
   uv run python -m scripts.cleanup_versions --dry-run
   ```
   - TODO: skrypt zgodnie z `docs/PIPELINE.md` gate 9.
   - Output: lista (blueprint_id, version, build_id) do retire.
2. Per Build ID z 0 running:
   - Usuń wpis z `manifest.blueprints.<id>.versions.<v>` (przenieś do `retired_versions` z timestamp).
   - Wyłącz Build ID z Worker registration (`worker.versioning.compatible_versions`).
3. Rebuild Worker image:
   - `.dockerignore` skip `generated/workflows/<id>/<retired_version>.py`.
   - `docker build -t <worker>:<tag>` + push + rollout.
4. Audit retention:
   - NIE usuwaj `.py` z git history (decyzja #17 — forever for audit).
   - Pliki pozostają w git, są jedynie wykluczone z runtime image.

## Permanent fix

- Cron housekeeping 1×/godz. zgodnie z `docs/PIPELINE.md` SLO.
- Trigger: `cleanup_versions --apply` po przejściu kryteriów.
- Metryka: `weaver_versions_retired_total`, alert na brak progresji.
- Polityka retention per tenant w `manifest.tenants.<id>.retention_policy`.

## Escalation

| Warunek | Eskalacja |
|---|---|
| Storage > threshold | Platform Infra |
| Worker image > 5 GB | Platform Lead |
| Retention policy violation | Compliance |
| Housekeeping cron down > 24h | Platform on-call |

## Powiązane

- `03-manifest-mismatch.md` — manifest spójność po cleanup.
- `docs/PIPELINE.md` — gate 9 housekeeping.
- `docs/ARCHITECTURE.md` — Worker Versioning, Build IDs.
- ADR #17 — retention generated artifacts.
