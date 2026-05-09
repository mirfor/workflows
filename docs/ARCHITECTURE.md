# Architektura

Pipeline: **React Flow JSON → CNCF Serverless Workflow 1.0 IR → generated `.py` → Temporal Worker**.

Element ekosystemu **Weaver** (AI Agent Orchestrator). Słownik (Agent / Blueprint / Engagement / Skill / Tool / Specialized Agent) — patrz `~/Desktop/weaver-root/docs/content/architecture/vocabulary/index.md`.

## Diagram pipeline'u

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              DESIGNER (UI)                                    │
│  React Flow canvas (primitivy strukturalne: Sequence/Branch/Loop/Parallel/   │
│  WaitSignal; structural condition builder; multi-catch tabela UX)             │
└─────────────────────────────────┬────────────────────────────────────────────┘
                                  │   (1) React Flow JSON
                                  ▼
                       ┌─────────────────────┐
                       │  Mapper RF → IR     │  deterministyczny, jednokierunkowy
                       │                     │  tenant_id ← layout blueprints/<tenant>/<bp>/v<n>/
                       └──────────┬──────────┘
                                  │   (2) CNCF SW 1.0 IR JSON
                                  ▼
                       ┌─────────────────────┐
                       │  Walidator IR       │  6 kategorii reguł (#16)
                       └──────────┬──────────┘
                                  │
                          (Publish — gate)
                                  │
                                  ▼
                       ┌─────────────────────┐
                       │  Generator IR → Py  │  Python `ast`, idempotentny (source hash)
                       └──────────┬──────────┘
                                  │   (3) generated/<tenant>/workflows/<snake>__v<n>.py
                                  │       generated/<tenant>/manifest.json (per Tenant)
                                  ▼
                       ┌─────────────────────┐
                       │  CI build           │  Worker image z Build ID
                       └──────────┬──────────┘
                                  │
                            (rolling deploy per Tenant)
                                  ▼
                       ┌─────────────────────┐
                       │  Temporal Worker    │  namespace = tenant_id
                       │  per Tenant         │  task queue = weaver-<tenant>
                       │  + activities/      │  importuje generated/<tenant>/workflows/
                       └─────────────────────┘
```

## Trzy formy Blueprintu

| Forma | Zawartość | Persystencja | Mutowalność |
|---|---|---|---|
| 1. React Flow JSON | UI layer (positions, styling, handles) | DB (Draft + Published); git po Publish: `blueprints/<tenant_id>/<bp_id>/v<n>/reactflow.json` | Draft mutowalny; Published immutable |
| 2. CNCF SW IR JSON | Semantyka — source of truth dla source hash, walidatora, generatora | DB (Draft + Published); git po Publish: `blueprints/<tenant_id>/<bp_id>/v<n>/cncf-sw.json` | jak (1) |
| 3. Generated `.py` | Runtime artefakt | git (immutable): `generated/<tenant_id>/workflows/<snake>__v<n>.py` | immutable, regenerowalny idempotentnie |

Mapper RF → IR jest deterministyczny. Z (3) nie da się odtworzyć (1) ani (2) — persystencja wszystkich trzech form jest obowiązkowa.

## Granica: platforma vs definicje workflow

| Warstwa | Mutowalność | Cykl wydawania | Wersjonowane przez |
|---|---|---|---|
| **Platforma** (mapper, walidator, generator, runtime infrastructure, activities/registry, Worker base image) | Mutowalna | release platformy (ciągły) | git tag platformy |
| **Definicje workflow** (Blueprinty, generated `.py` per wersja, manifest) | Immutable po Publish | release per Blueprint × wersja | Worker Versioning Build ID |

Granica wymusza, że zmiana platformy nie wymaga regeneracji wszystkich Blueprintów; zmiana Blueprintu nie wymaga release'u platformy.

## Model wersjonowania

| Element | Konwencja |
|---|---|
| Plik `.py` | `generated/<tenant_id>/workflows/<snake_id>__v<n>.py` |
| Python class | `<PascalCaseId>_v<n>` (suffix kosmetyczny) |
| Temporal workflow `name` | bez suffixu `_v<n>` (Build ID pinuje) |
| Pinning runtime | **Worker Versioning Build ID** (ADR-005) |
| Manifest aktualnych wersji | `generated/<tenant_id>/manifest.json` per Tenant (active / deprecated / build_id_lineage) |
| Stare wersje `.py` | git history forever — audyt / replay / rollback |

Concurrent publish: Blueprint-level lock (np. row lock) + atomowy CI workflow.

## Preview vs production

| Środowisko | Cel | Worker namespace | Build ID |
|---|---|---|---|
| **Preview** | weryfikacja Blueprintu w sandboxie przed Publish | preview-only namespace per Tenant | ephemeral Build ID |
| **Production** | produkcyjny Worker po CI build | Tenant production namespace | persistent Build ID, deploy rolling |

Preview wykorzystuje ten sam pipeline (mapper → walidator → generator), ale Worker działa w izolowanym namespace; brak wpływu na Engagementy produkcyjne.

## Tenancy

| Poziom | Izolacja | Mechanizm |
|---|---|---|
| Tenant | fizyczna | osobny Temporal namespace + osobna DB |
| Client Org (default) | logiczna | row-level filter + Search Attribute |
| Client Org regulowany | fizyczna opt-in | dedykowany namespace |

Search Attributes wymagane na każdym workflow execution: `tenant_id`, `client_org_id`, `blueprint_id`, `version`, `engagement_id`.

Szczegóły: ADR-006.

## Multi-tenant routing

| Skrypt | Argument | Zakres |
|---|---|---|
| `worker.py` | `--tenant <id>` | uruchamia Worker w namespace `<id>` na task queue `weaver-<id>` |
| `scripts/regenerate_workflow.py` | `--tenant <id> --blueprint <bp>` | pojedynczy Blueprint |
| `scripts/regenerate_all.py` | `[--tenant <id> [--blueprint <bp>]]` | bulk: cały repo / Tenant / Blueprint |
| `scripts/validate_all.py` | `[--tenant <id>]` | bulk validate |

- Worker per Tenant: namespace = `tenant_id` (decyzja #4); task queue = `weaver-<tenant_id>`.
- Manifesty per Tenant są disjoint w `blueprint_ids` — brak cross-tenant overlap.
- Workflow execution wybiera Workera przez task queue routing po tenant_id w Search Attribute.

## Kluczowe komponenty kodowe

| Moduł | Rola | Główne ADR |
|---|---|---|
| `mapper/` | RF JSON → CNCF SW IR (multi-catch UI → switch w catch.do) | ADR-002, ADR-004 |
| `validator/` | 6 kategorii reguł (struktura grafu, handles, registry, schemy/typy, polityki Temporala, spec compliance) | ADR-004 |
| `generator/` | CNCF SW IR → Python AST → `.py` + black formatter | ADR-001, ADR-003 |
| `activities/tools/<integration>.py` | Activity definitions per Tool integration | — |
| `activities/registry.py` | `ALL_ACTIVITIES` re-export | — |
| `activities/specialized_agents.py` | Generic dispatcher dla Specialized Agents (HTTP) | — |
| `scripts/build_manifest.py` | Pydantic introspection (Tools) + OpenAPI pull (Specialized Agents) → `activities/manifest.json` | — |
| `scripts/regenerate_workflow.py` | Pojedynczy Blueprint: mapper → walidator → generator | — |
| `scripts/regenerate_all.py` | Bulk regeneracja: cały repo / per Tenant / per Blueprint | — |
| `scripts/validate_all.py` | Bulk walidacja IR per Tenant lub cały repo | — |
| `worker.py` | Temporal Worker per Tenant (`--tenant <id>`) | ADR-005, ADR-006 |

## Profile retry / timeout (cascade)

Defaulty `default_timeout` (i potencjalnie `default_retry`) konfigurowalne 3-poziomowo: **Tenant → Client Org → Blueprint**. Generator wykonuje cascade resolution w momencie publish i emituje finalne wartości do `document.use.timeouts.default_timeout`. Brak hardcoded values w kodzie.

## Error handling

Hybryda: zamknięte base error types (`ValidationError`, `AuthError`, `RateLimitError`, `TimeoutError`, `NotFoundError`, `IntegrationError`, `InternalError`) + per-Tool custom errors deklarowane w manifest. Walidator IR blokuje publish jeśli `catch.with.type` nieznany lub niezgodny z Tool.

Niezłapany error → status `Failed` (fail-fast). Brak workflow-level handler i workflow retry policy w MVP.

## Switch flow

- Mapper (F3.E.1) rebuilduje branche do `_SwitchCase.do` jako extension IR; każdy case ma owned nodes wyznaczone przez BFS reachability analysis.
- Generator emituje `if/elif/else` z body inline każdej gałęzi — brak dead paths, brak fallthrough.
- `default` case wymagany przez walidator; routowanie poza zadeklarowane warunki nie jest reachable.

## Compliance gate

- `tests/test_compliance.py`: 34 passing testów, każdy mapuje 1:1 na decyzję projektową.
- Mapowanie decyzja #X → test: `docs/COMPLIANCE.md`.
- CI blokuje merge przy compliance fail.

## Status implementacji

| Faza | Zakres | Stan |
|---|---|---|
| F1 + F2 | Pydantic IR, schemy, IR_SPEC autogen | done |
| F3 | mapper, walidator, generator, manifest | done |
| F3.E | multi-tenant restructure, switch fix (E.1), 12 task types (E.2) | done |
| F4 | activities, Worker `--tenant` | done |
| F5 | multi-blueprint E2E, cross-tenant isolation | done |

## ADR-y

| ID | Tytuł |
|---|---|
| [ADR-001](adr/ADR-001-python-codegen-over-dsl.md) | Python codegen zamiast własnego DSL / interpretera |
| [ADR-002](adr/ADR-002-reactflow-source-of-truth.md) | React Flow jako source of truth UI |
| [ADR-003](adr/ADR-003-compiled-py-per-blueprint.md) | Skompilowany `.py` per Blueprint × wersja |
| [ADR-004](adr/ADR-004-cncf-sw-ir-as-contract.md) | CNCF Serverless Workflow 1.0 IR jako kontrakt UI ↔ codegen |
| [ADR-005](adr/ADR-005-worker-versioning-build-id.md) | Temporal Worker Versioning (Build ID) |
| [ADR-006](adr/ADR-006-tenancy-isolation.md) | Model izolacji Tenant / Client Org |

## Powiązane dokumenty

- `IR_SPEC.md` — CNCF SW IR specyfikacja (auto-generowana z Pydantic models)
- `PIPELINE.md` — drzewo zdarzeń edycja → produkcja, gates, SLO
- `WORKFLOW_RULES.md` — Temporal sandbox restrictions
- `ACTIVITY_CATALOG.md` — manifest Tools / Specialized Agents
- `SESSION_STATE.md` — historyczny snapshot 30 decyzji projektowych
