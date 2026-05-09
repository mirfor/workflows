# Plan implementacji — Workflow Platform Temporal

Pipeline: **React Flow JSON → CNCF SW IR → codegen `.py` → Temporal Worker**.

Plan oparty o 30 decyzji z `SESSION_STATE.md`. Tracking aktualizowany live po każdym taskcie.

**Ostatnia aktualizacja:** 2026-05-09

---

## Legenda

**Status:**
- `[ ]` todo
- `[~]` in progress
- `[x]` done
- `[?]` blocked (czeka na decyzję spoza scope sesji)

**Delegate:**
- `M` = main (Claude w głównej pętli, wymaga trzymania całości w kontekście)
- `S` = subagent (delegowane równolegle, isolated context, leaf document)

**Format wpisu:**
- `Started: <YYYY-MM-DD HH:MM>` ustawiane przy zmianie na `[~]`
- `Completed: <YYYY-MM-DD HH:MM>` ustawiane przy zmianie na `[x]`
- `By:` `M` lub `S-<id>` (np. `S-1` = subagent #1)

---

## Mapa zależności (high-level)

```
F0 (scaffold)
  └── F1 (ADR-y + ARCHITECTURE + PIPELINE)         [F1.1–F1.6 równolegle S; F1.7–F1.8 sekw. M]
        └── F2 (kontrakty: Pydantic + IR_SPEC + WORKFLOW_RULES + ACTIVITY_CATALOG)
              └── F3 (pipeline impl) ┬─── F3.A Mapper RF→IR
                                     ├─── F3.B Walidator IR
                                     ├─── F3.C Generator IR→Py
                                     └─── F3.D Manifest builder
                                              └── F4 (activity registry + worker)
                                                     └── F5 (E2E + tooling)
                                                           ├── F6 (operacje, równol. z F5)
                                                           └── F7 (user-facing)
```

**Critical path:** F0 → F1.7 → F2.1 → F3.C (generator) → F4 → F5.3 (E2E test).

**Parallel opportunities:**
- F1.1–F1.6 (6 ADR-ów) — wszystkie niezależne, jeden subagent na ADR
- F3.A / F3.B / F3.C / F3.D — 4 strumienie po F2.1; każdy subdivide na (impl=M, doc=S)
- F6 ⊥ F5 — dokumenty operacyjne równolegle z E2E
- F2.4, F2.5 — ⊥ F2.1 (no Pydantic dependency)

---

## Faza 0 — Repo scaffold

Sekwencyjnie. Setup repo + dependency lock + CI stub.

| ID | Task | Delegate | Deps | Status | Started | Completed |
|----|------|----------|------|--------|---------|-----------|
| F0.1 | Struktura katalogów (`blueprints/`, `generated/workflows/`, `activities/{tools,}`, `scripts/`, `mapper/`, `validator/`, `generator/`, `tests/`) | M | — | `[x]` | 2026-05-09 15:13 | 2026-05-09 15:14 |
| F0.2 | `pyproject.toml` + `uv.lock` (`temporalio`, `pydantic>=2`, `jq` (libjq), `black`, `fastapi`, `pytest`, `ruff`, `mypy`); package manager: `uv` | M | F0.1 | `[x]` | 2026-05-09 15:14 | 2026-05-09 15:18 |
| F0.3 | `.gitignore`, `.editorconfig`, `README.md` stub | M | F0.1 | `[x]` | 2026-05-09 15:18 | 2026-05-09 15:20 |
| F0.4 | `git init` + first commit | M | F0.1, F0.2, F0.3 | `[x]` | 2026-05-09 15:20 | 2026-05-09 15:22 |
| F0.5 | CI skeleton (`.github/workflows/ci.yml`) — lint, type, test, codegen idempotency check | M | F0.4 | `[x]` | 2026-05-09 15:22 | 2026-05-09 15:24 |

---

## Faza 1 — Fundament dokumentacyjny (ADR-y + ARCHITECTURE + PIPELINE)

ADR-y równolegle (subagenci). ARCHITECTURE.md i PIPELINE.md po ADR-ach (M).

| ID | Task | Delegate | Deps | Decyzja | Status | Started | Completed |
|----|------|----------|------|---------|--------|---------|-----------|
| F1.1 | `adr/ADR-001-python-codegen-over-dsl.md` | S | F0.4 | #30 | `[x]` | 2026-05-09 15:24 | 2026-05-09 15:25 |
| F1.2 | `adr/ADR-002-reactflow-source-of-truth.md` | S | F0.4 | #1, #2, #19 | `[x]` | 2026-05-09 15:24 | 2026-05-09 15:26 |
| F1.3 | `adr/ADR-003-compiled-py-per-blueprint.md` | S | F0.4 | #14, #17, #30 | `[x]` | 2026-05-09 15:24 | 2026-05-09 15:26 |
| F1.4 | `adr/ADR-004-cncf-sw-ir-as-contract.md` | S | F0.4 | #5, #6, #19 | `[x]` | 2026-05-09 15:24 | 2026-05-09 15:26 |
| F1.5 | `adr/ADR-005-worker-versioning-build-id.md` | S | F0.4 | #17 | `[x]` | 2026-05-09 15:24 | 2026-05-09 15:26 |
| F1.6 | `adr/ADR-006-tenancy-isolation.md` | S | F0.4 | #4 | `[x]` | 2026-05-09 15:24 | 2026-05-09 15:26 |
| F1.7 | `ARCHITECTURE.md` (overview, diagram, granica platforma vs definicje, preview vs prod, wersjonowanie) | M | F1.1–F1.6 | wszystkie | `[x]` | 2026-05-09 15:26 | 2026-05-09 15:30 |
| F1.8 | `PIPELINE.md` (drzewo zdarzeń edycja → produkcja, gates, SLO) | M | F1.7 | #14, #17 | `[x]` | 2026-05-09 15:30 | 2026-05-09 15:33 |

---

## Faza 2 — Kontrakty i schemy

Pydantic models są fundamentem (code-first, decyzja #13). IR_SPEC i ir.schema.json auto-generowane.

| ID | Task | Delegate | Deps | Decyzja | Status | Started | Completed |
|----|------|----------|------|---------|--------|---------|-----------|
| F2.1 | Pydantic models CNCF SW 1.0 — 12 task types, `use.retries`, `use.timeouts`, base error types, `document.metadata.temporal.*` extensions | M | F1.7 | #5, #6, #7, #8, #20, #21, #22, #23 | `[x]` | 2026-05-09 15:34 | 2026-05-09 15:48 |
| F2.2 | `IR_SPEC.md` — code-first dump z Pydantic + przykłady | M | F2.1 | #5, #19 | `[x]` | 2026-05-09 15:48 | 2026-05-09 15:54 |
| F2.3 | `schemas/ir.schema.json` auto-generated z Pydantic (`model_json_schema()`) | M | F2.1 | #13 | `[x]` | 2026-05-09 15:48 | 2026-05-09 15:50 |
| F2.4 | `WORKFLOW_RULES.md` — Temporal sandbox restrictions, dozwolone wzorce, libjq sandbox check | S | F1.7 | #15 | `[x]` | 2026-05-09 15:34 | 2026-05-09 15:36 |
| F2.5 | `ACTIVITY_CATALOG.md` — format manifestu (Tools / Specialized Agents / errors), kontrakty I/O | S | F1.7 | #7, #13, #18, #23 | `[x]` | 2026-05-09 15:34 | 2026-05-09 15:35 |

---

## Faza 3 — Pipeline implementacja

Cztery strumienie równolegle po F2.1. Każdy strumień: impl (M) + dokument (S, równolegle z impl).

### F3.A — Mapper React Flow → CNCF SW IR

| ID | Task | Delegate | Deps | Decyzja | Status | Started | Completed |
|----|------|----------|------|---------|--------|---------|-----------|
| F3.A.1 | Mapper impl (`mapper/reactflow_to_cncfsw.py`) — flat edges + container nodes | M | F2.1 | #9, #19 | `[x]` | 2026-05-09 15:42 | 2026-05-09 16:00 |
| F3.A.2 | Multi-catch UI → `switch` w `catch.do` compilation | M | F3.A.1 | #25 | `[x]` | 2026-05-09 16:00 | 2026-05-09 16:00 |
| F3.A.3 | `codegen/REACTFLOW_TO_IR.md` | S | F3.A.1 | #9, #25 | `[x]` | 2026-05-09 15:42 | 2026-05-09 15:43 |
| F3.A.4 | Tests (golden files RF JSON → CNCF SW JSON) | M | F3.A.1, F3.A.2 | — | `[x]` | 2026-05-09 16:00 | 2026-05-09 16:01 |

### F3.B — Walidator IR

| ID | Task | Delegate | Deps | Decyzja | Status | Started | Completed |
|----|------|----------|------|---------|--------|---------|-----------|
| F3.B.1 | Walidator impl (`validator/`) — 6 kategorii A–F | M | F2.1 | #16 | `[x]` | 2026-05-09 16:01 | 2026-05-09 16:08 |
| F3.B.2 | Reguły kategoria E: retry policy non-supported fields blokowane (`jitter`, `when`, `limit.duration`, `limit.attempt.duration`) | M | F3.B.1 | #21 | `[x]` | 2026-05-09 16:01 | 2026-05-09 16:08 |
| F3.B.3 | Reguły kategoria C/D: error taxonomy match (base ∪ tool.errors) | M | F3.B.1 | #23 | `[x]` | 2026-05-09 16:01 | 2026-05-09 16:08 |
| F3.B.4 | Auto-przypisanie `default_timeout` (cascade Tenant → Client Org → Blueprint) | M | F3.B.1 | #28 | `[x]` | 2026-05-09 16:01 | 2026-05-09 16:08 |
| F3.B.5 | Tests | M | F3.B.1–F3.B.4 | — | `[x]` | 2026-05-09 16:08 | 2026-05-09 16:09 |

### F3.C — Generator IR → Python (krytyczna ścieżka)

| ID | Task | Delegate | Deps | Decyzja | Status | Started | Completed |
|----|------|----------|------|---------|--------|---------|-----------|
| F3.C.1 | Generator skeleton (Python `ast` module) — `generator/ast_builder.py` | M | F2.1 | #15 | `[x]` | 2026-05-09 16:09 | 2026-05-09 16:18 |
| F3.C.2 | Mapping dla 12 task types CNCF SW → Temporal Python (tabela L10) | M | F3.C.1 | #15 | `[x]` (MVP: 8/12 wspierane; for/fork/listen/run jako placeholder) | 2026-05-09 16:09 | 2026-05-09 16:18 |
| F3.C.3 | Typed locals + `steps_output` dict + `_eval()` helper z compiled JQ cache | M | F3.C.1 | #15 | `[x]` | 2026-05-09 16:09 | 2026-05-09 16:18 |
| F3.C.4 | Source hash check + idempotency | M | F3.C.1 | #17 | `[x]` | 2026-05-09 16:09 | 2026-05-09 16:18 |
| F3.C.5 | Header emission (Generated from Blueprint, source hash, DO NOT EDIT) + `black` formatter | M | F3.C.1 | #14 | `[x]` | 2026-05-09 16:09 | 2026-05-09 16:18 |
| F3.C.6 | Worker Versioning Build ID assignment (`<PascalCaseId>_v<n>`, manifest update) | M | F3.C.1 | #14, #17 | `[x]` | 2026-05-09 16:09 | 2026-05-09 16:18 |
| F3.C.7 | Action item: weryfikacja libjq w Workflow Sandbox; fallback expression eval w activity | M | F3.C.3 | #15 | `[?]` (TODO w F5 E2E z lokalnym Temporal Workerem) | — | — |
| F3.C.8 | `codegen/IR_TO_PYTHON.md` | S | F3.C.1 | #14, #15 | `[x]` | 2026-05-09 15:42 | 2026-05-09 15:44 |
| F3.C.9 | Tests (golden files CNCF SW JSON → `.py` + replay test) | M | F3.C.1–F3.C.6 | — | `[x]` (MVP: 11 unit testów; replay test w F5) | 2026-05-09 16:18 | 2026-05-09 16:20 |

### F3.D — Manifest builder

| ID | Task | Delegate | Deps | Decyzja | Status | Started | Completed |
|----|------|----------|------|---------|--------|---------|-----------|
| F3.D.1 | Pydantic introspection dla Tools (in-process) → JSON Schema export | M | F2.1 | #13, #18 | `[x]` (przez `TOOL_MANIFEST` per moduł) | 2026-05-09 16:20 | 2026-05-09 16:25 |
| F3.D.2 | OpenAPI pull dla Specialized Agents (`/openapi.json` fetch + parse) | M | F2.1 | #13, #18 | `[x]` (httpx + best-effort schema extraction) | 2026-05-09 16:20 | 2026-05-09 16:25 |
| F3.D.3 | Error spec extraction (Pydantic subclasses `ApplicationError` → manifest `errors[]`) | M | F3.D.1 | #23 | `[x]` (errors[] w `TOOL_MANIFEST`; `base_errors()` z 7 typami) | 2026-05-09 16:20 | 2026-05-09 16:25 |
| F3.D.4 | Cascade resolution dla `default_timeout` (Tenant → Client Org → Blueprint) | M | F3.D.1 | #28 | `[x]` (`cascade_resolve()`) | 2026-05-09 16:20 | 2026-05-09 16:25 |
| F3.D.5 | `scripts/build_manifest.py` — produkuje `activities/manifest.json` | M | F3.D.1–F3.D.4 | #18 | `[x]` | 2026-05-09 16:20 | 2026-05-09 16:25 |
| F3.D.6 | Tests | M | F3.D.5 | — | `[x]` (7 testów: base_errors, cascade, build, write atomic) | 2026-05-09 16:25 | 2026-05-09 16:26 |

---

## Faza 4 — Activity registry + worker

| ID | Task | Delegate | Deps | Decyzja | Status | Started | Completed |
|----|------|----------|------|---------|--------|---------|-----------|
| F4.1 | `activities/tools/<integration>.py` template + 1–2 sample integrations | M | F3.D.5 | #18 | `[x]` (`log_message`, `http_get`) | 2026-05-09 16:30 | 2026-05-09 16:35 |
| F4.2 | `activities/registry.py` — `ALL_ACTIVITIES` re-export | M | F4.1 | #18 | `[x]` (auto-discovery z `activities/tools/`) | 2026-05-09 16:35 | 2026-05-09 16:36 |
| F4.3 | `activities/specialized_agents.py` — generic dispatcher `call_specialized_agent(AgentCall) -> AgentResult` | M | F4.1 | #18 | `[x]` (HTTP dispatcher z error mapping na base types #23) | 2026-05-09 16:30 | 2026-05-09 16:36 |
| F4.4 | Worker startup (`worker.py`) — load workflows from `generated/workflows/`, activities from registry | M | F4.2, F4.3, F3.C.6 | #18 | `[x]` (manifest-driven; tylko `active_version`) | 2026-05-09 16:36 | 2026-05-09 16:38 |

---

## Faza 5 — E2E + tooling

| ID | Task | Delegate | Deps | Status | Started | Completed |
|----|------|----------|------|--------|---------|-----------|
| F5.1 | Sample Blueprint: prosty workflow `manual_trigger → call (Tool) → switch → emit/raise` (RF JSON + CNCF SW JSON + generated `.py`) | M | F3.A.4, F3.B.5, F3.C.9, F4.4 | `[x]` | 2026-05-09 16:38 | 2026-05-09 16:50 |
| F5.2 | `DEV_SETUP.md` — lokalny Temporal (Docker), worker run, sample Blueprint deploy | S | F4.4 | `[x]` | 2026-05-09 16:38 | 2026-05-09 16:39 |
| F5.3 | E2E test: start workflow → execution → expected result; replay test | M | F5.1, F5.2 | `[x]` (offline pipeline E2E; replay z Temporal Server odłożone — wymaga Docker) | 2026-05-09 16:50 | 2026-05-09 16:55 |
| F5.4 | `CONTRIBUTING.md` | S | F4.4 | `[x]` | 2026-05-09 16:38 | 2026-05-09 16:39 |
| F5.5 | `README.md` (entry point) | S | F4.4 | `[x]` (stub z F0 wystarczający dla MVP) | — | — |

---

## Faza 6 — Operacje (równolegle z F5)

| ID | Task | Delegate | Deps | Status | Started | Completed |
|----|------|----------|------|--------|---------|-----------|
| F6.1 | `DEPLOYMENT.md` | S | F1.7 | `[?]` blokowane: target deployment poza scope sesji | — | — |
| F6.2 | `OBSERVABILITY.md` — Search Attributes (`tenant_id`, `client_org_id`, `blueprint_id`, `version`, `engagement_id`), metryki, dashboardy, logi | S | F1.7 | `[x]` | 2026-05-09 16:38 | 2026-05-09 16:39 |
| F6.3 | `SECURITY.md` — threat model (sandbox, tenant isolation, LLM safety w przyszłości) | S | F1.7 | `[x]` | 2026-05-09 16:38 | 2026-05-09 16:39 |
| F6.4 | `runbooks/` — 4 runbooki (rollback, stuck activity, manifest mismatch, version cleanup) | S | F4.4 | `[x]` | 2026-05-09 16:38 | 2026-05-09 16:40 |

---

## Faza 7 — User-facing (po F5)

| ID | Task | Delegate | Deps | Status | Started | Completed |
|----|------|----------|------|--------|---------|-----------|
| F7.1 | `USER_GUIDE.md` | S | F5.3 | `[?]` blokowane: audience UI poza scope sesji | — | — |
| F7.2 | `USER_ERROR_CATALOG.md` — mapping technicznych errors (#23) na user-facing komunikaty | S | F2.5 | `[?]` blokowane: język UI poza scope sesji | — | — |
| F7.3 | `prompts/*` (LLM repair / IR generation) | — | — | `[?]` poza MVP — decyzja #11 (LLM-NL odłożone) | — | — |

---

## Następny krok

Faza 0 (`F0.1` — `F0.5`) sekwencyjnie. Po `F0.4` (init commit) odpalić Fazę 1 — 6 ADR-ów równolegle przez subagentów.
