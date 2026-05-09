# Plan implementacji V2 — compliance-first

Restart po pierwszym MVP: implementacja **per task wymaga passing compliance test** (`tests/test_compliance.py`). Mapowanie decyzja → test w `docs/COMPLIANCE.md`.

**Ostatnia aktualizacja:** 2026-05-09 (po F6 — wszystkie fazy zamknięte)

## Status (live)

| Faza | Compliance | Status |
|---|---|---|
| F0 — scaffold + compliance baseline | 0 → 30 (3 xpassed vacuously) | ✅ |
| F1 — multi-tenant layout + bulk ops | egzekwowane przez F3.E.2 | ✅ |
| F2 — Pydantic IR | 15 passed (#3, #4, #5, #7, #8, #11, #13, #19, #20, #22, #23, #24, #27, #29, #30) | ✅ |
| F3.A — mapper RF→IR | +5 passed (#1, #2, #9, #10, #25) → 20 | ✅ |
| F3.B — walidator | +2 passed (#16, #21) → 22 | ✅ |
| F3.C — generator | +6 passed (#6, #12, #14, #15, #17, #26) → 28 | ✅ |
| F3.D + F4 — manifest builder + activities + worker | +2 passed (#18, #28) → 30 | ✅ |
| F3.E.2 — multi-tenant restructure | #4, #19 realnie egzekwowane (były vacuous) | ✅ |
| F3.E.1 — switch flow naprawiony | +2 nowe testy → 32 | ✅ |
| F3.E.3 — wszystkie 12 task types (no placeholder) | #6 strict | ✅ |
| F5 — multi-blueprint suite + cross-tenant isolation | +2 nowe testy → 34 | ✅ |
| F6 — updates dokumentów | — | ✅ |

**Compliance: 34/34 passing** (`uv run pytest tests/test_compliance.py`).

E2E zweryfikowane na żywym Temporal Server: 6 scenariuszy + cross-tenant isolation.

## Reguły procesu

1. Task `[~]` w trakcie → compliance test może pozostać `xfail` (z `reason=#X`).
2. Task `[x]` → **wymaga** compliance test passing **bez** `xfail` markeru.
3. Każda implementacja modułu — **najpierw** zdejmij `xfail` z odpowiedniego compliance testu, **potem** doprowadź assertion do passing.
4. PR review — pierwsze pytanie: który compliance test się zmienił z `xfail` → `pass`?
5. CI job `compliance` blokuje merge gdy test fail bez `xfail`.

## Aktualny status compliance

```bash
uv run pytest tests/test_compliance.py -v
# Baseline: 27 xfailed, 3 xpassed
```

## Mapa zależności (V2)

```
F0 (scaffold + compliance baseline) ✅
  └── F1 (multi-tenant layout + bulk ops) ← startujemy tutaj
        └── F2 (Pydantic IR — wszystkie 12 task types pokryte)
              └── F3 (mapper + walidator + generator + manifest builder; multi-tenant)
                    └── F4 (activities + worker per Tenant)
                          └── F5 (multi-blueprint test suite — wszystkie 12 task types
                                  + error handling + multi-catch + retry profiles, każdy
                                  uruchomiony E2E na Temporal Server)
                                └── F6 (operacje, dokumenty)
```

**Critical change:** F5 = "multi-blueprint test suite" zamiast pojedynczego happy-path. **Każdy** z 12 task types pokryty co najmniej jednym Blueprintem uruchamianym na żywym Temporal Server.

## Faza F1 — multi-tenant layout + bulk ops

| ID | Task | Compliance | Acceptance |
|----|------|------------|------------|
| F1.1 | Layout: `blueprints/<tenant>/<bp>/v<n>/`, `generated/<tenant>/{manifest.json,workflows/}` | `test_decision_04_tenant_isolation_layout` | xfail → pass |
| F1.2 | `scripts/regenerate_workflow.py` z `--tenant` arg + bulk wariant `regenerate_all.py` | `test_decision_19_three_forms_persisted` | xfail → pass |
| F1.3 | `scripts/validate_all.py` — bulk walidacja per Tenant | nowy compliance: `test_bulk_validate_iterates_all_tenants` (do dodania) | passing |
| F1.4 | `worker.py` z `--tenant` (loaduje tylko `generated/<tenant>/manifest.json`) | `test_decision_18_activity_registry_layout` | passing |

## Faza F2 — Pydantic IR (compliance #5–#13, #20–#28)

| ID | Task | Compliance |
|----|------|------------|
| F2.1 | `ir/_base.py` — StrictModel, IsoDuration, JqExpression | — |
| F2.2 | `ir/policies.py` — RetryPolicy, TimeoutPolicy + Temporal extensions | #20, #21, #22, #24, #28 |
| F2.3 | `ir/errors.py` — BaseErrorType, ErrorSpec, ErrorReference | #23 |
| F2.4 | `ir/triggers.py` — Manual/Webhook/Schedule/Event | #10 |
| F2.5 | `ir/functions.py` — ToolFunction, SpecializedAgentFunction | #7, #13 |
| F2.6 | `ir/tasks.py` — wszystkie 12 task types | #6, #8, #11, #12 |
| F2.7 | `ir/document.py` — Workflow, Document, Use, WorkflowMetadata | #5, #19, #27 |
| F2.8 | `schemas/ir.schema.json` auto-generated + `scripts/export_ir_schema.py` | #13 |

## Faza F3 — pipeline (compliance #1, #2, #9, #14–#17, #21, #23, #25, #26, #28)

| ID | Task | Compliance |
|----|------|------------|
| F3.A | `mapper/reactflow_to_cncfsw.py` — RF→IR z multi-tenant context | #1, #2, #9, #10, #19, #25 |
| F3.B | `validator/` — 6 kategorii reguł, ERROR codes A001..F999 | #16, #21, #23 |
| F3.C | `generator/codegen.py` — Python AST, **wszystkie 12 task types** (NIE placeholder) | #6, #12, #14, #15, #17, #26, #27 |
| F3.D | `generator/manifest.py` — per-Tenant manifest, build_id_lineage, deprecated_versions | #17 |
| F3.E | **NAPRAWA SWITCH FLOW** — case z `do[]` jako branch body, mapper rebuilduje branches z reachability analysis | nowy: `test_switch_branches_inline_no_dead_paths` |
| F3.F | `scripts/build_manifest.py` — Tool introspection + OpenAPI pull + cascade | #18, #28 |

## Faza F4 — activities + worker

| ID | Task | Compliance |
|----|------|------------|
| F4.1 | `activities/tools/<integration>.py` × 4+ (sample + http_get + log_message + fail_simulator) | #18 |
| F4.2 | `activities/specialized_agents.py` — dispatcher z error mapping na base types | #18, #23 |
| F4.3 | `worker.py` — `--tenant`, sandbox passthrough, manifest-driven loading | #4, #18 |

## Faza F5 — **multi-blueprint test suite**

Pokrycie wszystkich 12 task types + scenariusze error handling, multi-catch, retry. **Każdy Blueprint uruchamiany E2E na Temporal Server.**

| ID | Blueprint | Pokrywa task types | Scenariusz |
|----|-----------|--------------------|-----------| 
| F5.1 | `demo/sequence_call/v1` | `call`, `set`, `emit` | Linear sequence: log → process → emit |
| F5.2 | `demo/branching/v1` | `switch`, `set` | Switch z 3 cases + default; tylko właściwa gałąź wykonana |
| F5.3 | `demo/error_handling/v1` | `try`, `raise`, `catch`, `set` | Try wokół call; raise w pewnym przypadku; multi-catch (Validation/Auth) |
| F5.4 | `demo/retry_demo/v1` | `call` z retry profile, `wait` | Retryable Tool + custom retry policy; verify retry count |
| F5.5 | `demo/parallel/v1` | `fork`, `call`, `set` | Fork 3 branches; join (wait-all) |
| F5.6 | `demo/iteration/v1` | `for`, `call`, `set` | For loop nad listą; per-iteration call |
| F5.7 | `demo/signals/v1` | `listen`, `emit`, `wait` | Listen na external signal; timeout via wait |
| F5.8 | `demo/external_run/v1` | `run` (workflow), `set` | Child workflow execution |
| F5.9 | `acme/multi_tenant_isolation/v1` | (cross-cut) | Drugi Tenant — verify że Workers per Tenant nie widzą cudzych Blueprintów |

| ID | Task | Compliance |
|----|------|------------|
| F5.A | Stwórz 9 Blueprintów (RF JSON + regenerate) | #6, #19 |
| F5.B | E2E test runner per Blueprint na Temporal Server | nowy: `test_e2e_<blueprint>` (każdy passing) |
| F5.C | Cross-tenant isolation test | #4 (passing) |
| F5.D | Replay test dla wszystkich Blueprintów (deterministic) | nowy: `test_replay_all_blueprints` |

## Faza F6 — operacje (poprawione + uzupełnione)

Aktualne dokumenty z poprzedniej iteracji **zachowane** (ARCHITECTURE, PIPELINE, IR_SPEC, WORKFLOW_RULES, ACTIVITY_CATALOG, SECURITY, OBSERVABILITY, DEV_SETUP, CONTRIBUTING, runbooks). Updates per implementacja:

| ID | Update |
|----|--------|
| F6.1 | Update `ARCHITECTURE.md` — diagram pipeline z multi-tenant routing |
| F6.2 | Update `PIPELINE.md` — bulk publish flow |
| F6.3 | Update `DEV_SETUP.md` — multi-tenant local dev |
| F6.4 | Update `CONTRIBUTING.md` — compliance-first workflow |
| F6.5 | Nowy `docs/MULTI_TENANT.md` — operacyjny guide |

## Następny krok

Faza F1 — sequencyjnie:
1. F1.1 layout: `blueprints/<tenant>/<bp>/v<n>/`
2. F1.2 `regenerate_workflow.py` + `regenerate_all.py`
3. F1.3 `validate_all.py`
4. F1.4 `worker.py --tenant`

Każdy task: zdejmij `xfail` z odpowiedniego compliance testu, doprowadź do passing.
