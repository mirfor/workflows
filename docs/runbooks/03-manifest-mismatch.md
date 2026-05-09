# Runbook 03: Manifest mismatch

## Symptom

- Worker startup error: `Workflow class <X> not found in <file>`.
- CI job `codegen-idempotency` fail: diff w `generated/`.
- Worker registration error: `unknown workflow type <blueprint_id>:v<n>`.
- `weaver_worker_registration_failed_total` > 0.
- Engagement start error: `WorkflowNotFound` z Router.

## Diagnoza

1. Diff stanu generated:
   - `git diff generated/manifest.json generated/workflows/`.
   - `git status generated/` — niecommitowane pliki.
2. Verify ostatni Publish:
   - `git log --oneline -- generated/manifest.json | head -5`.
   - Sprawdź czy commit zawiera komplet: manifest + `generated/workflows/<id>/v<n>.py` + `generated/activities/`.
3. Source hash check:
   ```
   uv run python -c "
   from generator import compute_source_hash
   from ir import Workflow
   import json
   ir = Workflow.parse_file('blueprints/<id>/v<n>/ir.json')
   print(compute_source_hash(ir))
   "
   ```
   - Compare z `manifest.blueprints.<id>.versions.v<n>.source_hash`.
4. Worker image: `kubectl exec <worker-pod> -- ls /app/generated/workflows/<id>/`.
5. CI logs: pipeline step `codegen-idempotency` — pełen diff output.

## Mitigation

1. Regenerate z IR:
   ```
   uv run python -m scripts.regenerate_workflow blueprints/<id>/v<n>/
   ```
2. Commit i redeploy:
   - `git add generated/ && git commit -m "fix: regenerate v<n>"`.
   - Trigger Worker image rebuild + rollout.
3. Manifest hot-fix (gdy regen niemożliwy):
   - Edytuj `generated/manifest.json`: `active_version: v<n-1>` (poprzednia stabilna).
   - Skip nowy Build ID w Worker Versioning.
   - Commit + deploy.
4. Running executions na zepsutej wersji: zastosuj Runbook 01 (rollback).

## Permanent fix

- Race condition w Publish flow → Issue #17: Blueprint-level lock + atomic CI commit.
- Wymaganie: Publish musi być transakcyjny (manifest + generated + git tag w jednym commit).
- Pre-commit hook: walidacja `source_hash` zgodności.
- ADR `docs/adr/` jeśli zmiana modelu Publish.

## Escalation

| Warunek | Eskalacja |
|---|---|
| Running executions failing | Platform on-call (P1) |
| Tylko CI fail, brak runtime impact | Platform (P3) |
| Powtarzający się race | Platform Lead + ADR review |

## Powiązane

- `01-failed-workflow-rollback.md` — gdy mismatch powoduje failure.
- `04-version-cleanup.md` — housekeeping vs aktywne wersje.
- `docs/PIPELINE.md` — Publish flow.
- `docs/codegen/` — generator i source hash.
