# Compliance — mapowanie decyzji projektowych na testy

Każda decyzja z `docs/SESSION_STATE.md` (#1–#30) musi mieć assertion w `tests/test_compliance.py`. CI gate `compliance` blokuje merge gdy któryś test fail.

Decyzja `[x]` w `IMPLEMENTATION_PLAN_V2.md` wymaga **passing** compliance test.

## Tabela mapowania

| # | Decyzja (skrót) | Test (compliance) | Co sprawdza |
|---|---|---|---|
| 1 | Source of truth UI = React Flow | `test_decision_01_reactflow_source_of_truth` | Mapper RF→IR istnieje; brak modułu BPMN→IR |
| 2 | UI primitivy strukturalne (N8N-style) | `test_decision_02_structural_primitives_only` | Mapper rejects raw edges między atomic tasks (musi być Sequence/Branch/...) |
| 3 | Dwuwarstwowy model: control flow + Tools/Agents registry | `test_decision_03_two_layer_model` | `Use.functions` oddzielone od task types; closed set 12 task types |
| 4 | Tenancy: fizyczna per Tenant + logiczna per Client Org | `test_decision_04_tenant_isolation_layout` | `blueprints/<tenant>/<bp>/v<n>/`; `generated/<tenant>/...`; manifest per Tenant |
| 5 | CNCF SW 1.0 JSON + Pydantic models | `test_decision_05_cncfsw_pydantic_models` | `Workflow.document.dsl == "1.0.0"`; round-trip JSON parse |
| 6 | Wszystkie 12 task types CNCF SW w MVP | `test_decision_06_all_12_task_types_supported` | Pydantic ma 12 klas; mapper wspiera 12 typów; generator emituje 12 |
| 7 | Tools/Agents jako CNCF SW `functions` z custom `type` | `test_decision_07_tools_agents_as_functions` | `ToolFunction.type == "weaver_tool"`, `SpecializedAgentFunction.type == "weaver_specialized_agent"` |
| 8 | Atrybuty task = pola spec + extensions | `test_decision_08_task_extensions_in_metadata` | Każdy task ma `metadata: dict | None`; ekstensje w `metadata.weaver.*` / `metadata.temporal.*` |
| 9 | Mapping krawędzi RF → CNCF SW | `test_decision_09_edge_handles_mapping` | `case_<id>` / `default` / `branch_<n>` / `main` / `catch_<err>` rozpoznawane |
| 10 | Trigger jako pierwszy node | `test_decision_10_trigger_as_first_node` | Mapper przenosi trigger do `metadata.weaver.trigger`; walidator wymusza ≤1 trigger |
| 11 | Warunki strukturalne w UI → JQ | `test_decision_11_jq_compiled_from_ui` | Walidator akceptuje JQ; brak LLM-NL w MVP |
| 12 | Auto-export `steps.<id>.output` + opcjonalne `export.as` | `test_decision_12_auto_export_steps_output` | Generator emituje `steps_output["<id>"] = ...` po każdym task |
| 13 | Pydantic source of truth dla schemy I/O | `test_decision_13_pydantic_io_schemas` | `model_json_schema()` eksport dla Tool input/output; OpenAPI dla Specialized Agents |
| 14 | Output `<snake_id>__v<n>.py` per Tenant | `test_decision_14_generated_py_layout` | `generated/<tenant>/workflows/<snake>__v<n>.py`; header (Generated, Source hash, DO NOT EDIT); `black` formatter |
| 15 | Generator AST + libjq + JQ→Python NIE w MVP | `test_decision_15_ast_generator_jq_libjq` | Generator używa `ast`; `_eval()` z compiled JQ cache; brak transpile |
| 16 | Walidator IR — 6 kategorii reguł | `test_decision_16_validator_six_categories` | Walidator emituje codes w schemacie `<A-F><NNN>`; `error` blokuje publish |
| 17 | Lifecycle: Draft→Publish→CI→deploy + manifest z Build ID | `test_decision_17_versioning_lifecycle_manifest` | Manifest entry ma `active_version`, `deprecated_versions`, `build_id_lineage`; Blueprint-level lock |
| 18 | Activity registry: tools/<integration>.py + dispatcher Specialized Agents | `test_decision_18_activity_registry_layout` | `ALL_ACTIVITIES` discovery; `call_specialized_agent` dispatcher |
| 19 | Trzy formy Blueprintu (RF, IR, .py) — wszystkie persystowane | `test_decision_19_three_forms_persisted` | Po Publish: `blueprints/<t>/<id>/v<n>/{reactflow.json, cncf-sw.json}` + `generated/<t>/workflows/<id>__v<n>.py` |
| 20 | Profile retry/timeout w `Use.retries`/`Use.timeouts` | `test_decision_20_profile_based_policies` | `Use.retries[name]` i `Use.timeouts[name]`; refowane przez nazwę z task |
| 21 | Retry mapping CNCF SW → Temporal; pola bez mapping blokowane | `test_decision_21_retry_unsupported_fields_blocked` | Walidator emituje `E101..E105` dla `jitter`/`when`/`exceptWhen`/`limit.duration`/`limit.attempt.duration` |
| 22 | Timeout: `after` (start_to_close) + `metadata.temporal.{heartbeat,schedule_to_close}` | `test_decision_22_timeout_three_fields` | Pydantic `TimeoutPolicy.after` wymagane; `schedule_to_start_timeout` brak w MVP |
| 23 | Error taxonomy: 7 base + per-Tool extensions | `test_decision_23_error_taxonomy` | 7 base errors w manifest; `BaseErrorType` enum; walidator `C003` blokuje unknown type |
| 24 | Non-retryable: manifest default + profile override | `test_decision_24_non_retryable_merge` | Generator merguje manifest `retryable=False` ∪ `profile.nonRetryableTypes` → `Temporal.non_retryable_error_types` |
| 25 | Multi-catch UI → switch w `catch.do` (mapper) | `test_decision_25_multi_catch_compilation` | Mapper przy >1 catch UI emituje single `catch.do` z `switch` task wewnątrz |
| 26 | Uncaught = fail-fast; brak workflow-level handler/retry | `test_decision_26_fail_fast_uncaught` | Generator nie emituje workflow-level catch; brak `WorkflowRetryPolicy` |
| 27 | Workflow timeout w `metadata.temporal.workflow_run_timeout` | `test_decision_27_workflow_run_timeout_only` | Generator emituje `workflow_run_timeout` jako `start_workflow` parameter; brak `execution_timeout`/`task_timeout` |
| 28 | Cascade defaults Tenant → Client Org → Blueprint | `test_decision_28_cascade_defaults_resolution` | `cascade_resolve(tenant, client_org, blueprint)` → final values; brak hardcoded |
| 29 | Compensation: pattern user-implemented, brak native | `test_decision_29_no_native_saga` | Brak `metadata.weaver.compensation` extension; saga = explicit try-catch |
| 30 | Model wykonania = compiled `.py` (B); interpreter odrzucony | `test_decision_30_compiled_only_no_interpreter` | Brak `interpreter/` modułu; każdy Blueprint ma `.py` w `generated/<tenant>/workflows/` |

## Process

1. **Każdy task w `IMPLEMENTATION_PLAN_V2.md` → Acceptance Criteria** z linkiem do compliance test (lub kilku).
2. Task `[~]` → in progress; compliance test może być `xfail`.
3. Task `[x]` → **wymaga** compliance test passing (CI gate).
4. CI job `compliance` w `.github/workflows/ci.yml` — odrzuca PR gdy compliance test fail.
5. Code review pierwsze pytanie: który compliance test się zmienił?

## Stan compliance (live)

Aktualny status — patrz `tests/test_compliance.py` (każdy test ma marker `xfail` z `reason=#X`, lub passing).

```bash
uv run pytest tests/test_compliance.py -v
```
