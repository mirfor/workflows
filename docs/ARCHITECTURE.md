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
                                  │   (3) generated/workflows/<id>__v<n>.py
                                  ▼
                       ┌─────────────────────┐
                       │  CI build           │  Worker image z Build ID
                       └──────────┬──────────┘
                                  │
                            (rolling deploy)
                                  ▼
                       ┌─────────────────────┐
                       │  Temporal Worker    │  importuje `generated/workflows/`
                       │  + activities/      │  + `activities/registry.py`
                       └─────────────────────┘
```

## Trzy formy Blueprintu

| Forma | Zawartość | Persystencja | Mutowalność |
|---|---|---|---|
| 1. React Flow JSON | UI layer (positions, styling, handles) | DB (Draft + Published); git po Publish: `blueprints/<id>/v<n>/reactflow.json` | Draft mutowalny; Published immutable |
| 2. CNCF SW IR JSON | Semantyka — source of truth dla source hash, walidatora, generatora | DB (Draft + Published); git po Publish: `blueprints/<id>/v<n>/cncf-sw.json` | jak (1) |
| 3. Generated `.py` | Runtime artefakt | git (immutable): `generated/workflows/<snake_id>__v<n>.py` | immutable, regenerowalny idempotentnie |

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
| Plik `.py` | `generated/workflows/<snake_id>__v<n>.py` |
| Python class | `<PascalCaseId>_v<n>` (suffix kosmetyczny) |
| Temporal workflow `name` | bez suffixu `_v<n>` (Build ID pinuje) |
| Pinning runtime | **Worker Versioning Build ID** (ADR-005) |
| Manifest aktualnych wersji | `generated/manifest.json` (active / deprecated / build_id_lineage) |
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

## Profile retry / timeout (cascade)

Defaulty `default_timeout` (i potencjalnie `default_retry`) konfigurowalne 3-poziomowo: **Tenant → Client Org → Blueprint**. Generator wykonuje cascade resolution w momencie publish i emituje finalne wartości do `document.use.timeouts.default_timeout`. Brak hardcoded values w kodzie.

## Error handling

Hybryda: zamknięte base error types (`ValidationError`, `AuthError`, `RateLimitError`, `TimeoutError`, `NotFoundError`, `IntegrationError`, `InternalError`) + per-Tool custom errors deklarowane w manifest. Walidator IR blokuje publish jeśli `catch.with.type` nieznany lub niezgodny z Tool.

Niezłapany error → status `Failed` (fail-fast). Brak workflow-level handler i workflow retry policy w MVP.

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
