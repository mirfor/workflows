# Workflow Platform Temporal

Pipeline: **React Flow JSON → CNCF Serverless Workflow 1.0 IR → generated `.py` → Temporal Worker**.

Część ekosystemu **Weaver** (AI Agent Orchestrator).

## Stan

Pre-build. 30 decyzji projektowych zamkniętych — patrz `docs/SESSION_STATE.md`. Plan implementacji w `docs/IMPLEMENTATION_PLAN.md`.

## Struktura

| Katalog | Zawartość |
|---|---|
| `blueprints/<id>/v<n>/` | Immutable artefakty po Publish: `reactflow.json`, `cncf-sw.json` |
| `generated/workflows/` | `<snake_id>__v<n>.py` — codegen output (DO NOT EDIT) |
| `generated/manifest.json` | Top-level Blueprint manifest |
| `activities/tools/` | Activity definitions per Tool integration |
| `activities/registry.py` | `ALL_ACTIVITIES` re-export |
| `activities/specialized_agents.py` | Generic dispatcher dla Specialized Agents |
| `activities/manifest.json` | Tools / Specialized Agents / errors manifest (auto-generated) |
| `mapper/` | React Flow → CNCF SW IR mapper |
| `validator/` | IR walidator (6 kategorii reguł) |
| `generator/` | CNCF SW IR → Python AST codegen |
| `scripts/` | Build / publish utilities |
| `tests/` | Test suite |
| `docs/` | Dokumentacja architektoniczna i ADR-y |

## Setup

```bash
uv sync
```

## Kluczowe dokumenty

- `docs/ARCHITECTURE.md` — overview pipeline'u
- `docs/IR_SPEC.md` — CNCF SW IR specyfikacja
- `docs/PIPELINE.md` — drzewo zdarzeń edycja → produkcja
- `docs/adr/` — Architecture Decision Records
- `docs/SESSION_STATE.md` — historyczny snapshot decyzji projektowych

## Powiązane repo

- `~/Desktop/weaver-root/` — Weaver vocabulary, B2B model, architektura
