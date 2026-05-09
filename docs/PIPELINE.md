# Pipeline edycja → produkcja

Drzewo zdarzeń od edycji w designerze do uruchomienia Engagement na Workerze. Gates, idempotencja, SLO.

## Stany Blueprintu

| Stan | Mutowalność | Trigger przejścia | Artefakty |
|---|---|---|---|
| Draft | mutowalny | utworzenie / edycja w UI | DB designera: `reactflow.json`, `cncf-sw.json` |
| Validated | mutowalny | walidator IR przeszedł bez `error` | dodaje raport walidatora w DB |
| Published | immutable | gate **Publish** | git: `blueprints/<id>/v<n>/{reactflow.json,cncf-sw.json}`; trigger codegen |
| Built | immutable | gate **CI build** | git: `generated/workflows/<snake_id>__v<n>.py`; Worker image z Build ID |
| Active | immutable | gate **Rolling deploy** | manifest aktualizacja: `active_version = v<n>` |
| Deprecated | immutable | gate **Activation v<n+1>** | manifest: `deprecated_versions += v<n>` (running executions kompletują) |
| Retired | immutable | housekeeping (0 running executions) | manifest cleanup; Worker image cleanup; pliki zostają w git |

## Drzewo zdarzeń

```
[Designer UI: edit RF]
        │
        ▼
   (1) Save Draft  ─────────► DB.draft = (rf_json, ir_json, validator_report)
        │
        ▼
   (2) Validate (auto on save)
        │ — walidator IR (6 kategorii reguł, ADR-004)
        │ — błędy `error` blokują (3); warningi nie blokują
        ▼
   ┌────────────────────────────────────┐
   │ Designer: "Publish v<n>"           │
   └────────────────┬───────────────────┘
                    ▼
   (3) Gate: Publish
        │ — Blueprint-level lock
        │ — walidator IR `error` count == 0
        │ — source hash check (idempotency: czy v<n> już istnieje z tym hashem?)
        │     ├─ tak → no-op (zwróć istniejący Build ID)
        │     └─ nie → kontynuuj
        ▼
   (4) Generator IR → .py
        │ — Python `ast` builder
        │ — emisja typed locals + steps_output dict + _eval() z compiled JQ cache
        │ — header (Generated from Blueprint X v<n> at <ts>; Source hash: <sha>; DO NOT EDIT)
        │ — black formatter (fixed config)
        ▼
   (5) Git commit
        │ — `blueprints/<id>/v<n>/{reactflow.json, cncf-sw.json}`
        │ — `generated/workflows/<snake_id>__v<n>.py`
        │ — `generated/manifest.json` (dodanie wpisu blueprints[<id>].versions[<n>])
        ▼
   (6) CI build
        │ — uv sync, lint, type, test
        │ — codegen idempotency check (regenerate → diff == empty)
        │ — Docker build Worker image z Build ID = sha krótki(commit)
        │ — push image do registry
        ▼
   (7) Rolling deploy
        │ — Worker image z nowym Build ID dołącza do Tenant namespace
        │ — Temporal kieruje *nowe* Engagementy na nowy Build ID
        │ — *running* Engagementy na poprzednim Build ID kompletują na starym Workerze
        │ — manifest: blueprints[<id>].active_version = v<n>; deprecated_versions += poprzednia
        ▼
   (8) Activation
        │ — UI pokazuje v<n> jako Active
        │ — można uruchamiać Engagementy nowej wersji
        ▼
   (9) Housekeeping (asynchronicznie)
        │ — co interwał: query Temporal o running executions per Build ID
        │ — gdy 0 running na deprecated Build ID → cleanup Worker image; manifest: status = retired
        ▼
       [Retired]
```

## Preview path (przed Publish)

```
[Designer: "Preview"]
        │
        ▼
   (P1) Validator IR (warning + error obojętne — preview pozwala na error dla diagnostyki)
        │
        ▼
   (P2) Generator IR → .py (ephemeral, w preview-only namespace)
        │
        ▼
   (P3) Worker preview-only namespace per Tenant
        │ — ephemeral Build ID (czas życia ~ TTL)
        │ — wykonanie z preview input
        │
        ▼
   (P4) UI pokazuje wynik / log / replay
```

Preview używa tego samego pipeline'u, ale Worker w izolowanym namespace. Brak wpływu na production.

## Gates

| Gate | Wejście | Reguły | Wyjście przy fail |
|---|---|---|---|
| Validate | RF JSON + IR JSON | walidator IR (6 kategorii) | błędy `error` → blokada Publish; warningi → notyfikacja |
| Publish | IR JSON + walidator OK | Blueprint-level lock; source hash check | lock contention → retry; existing hash → no-op (idempotency) |
| CI build | git commit z `generated/workflows/<id>__v<n>.py` | uv sync; lint; type; test; codegen idempotency | failed step → blokada deploy; Blueprint stays Published not Built |
| Rolling deploy | Worker image w registry | health check nowego Workera; smoke test | rollback do poprzedniego Build ID |
| Activation | nowy Build ID accepting nowe Engagementy | manifest spójny | manual rollback |
| Housekeeping | 0 running executions na deprecated Build ID | retencja w git history forever | — |

## Idempotency

| Operacja | Mechanizm idempotency |
|---|---|
| Generator | source hash CNCF SW IR; ten sam hash → pomiń regenerację |
| Publish | Blueprint-level lock + source hash check |
| CI build codegen check | regenerate all → `git diff generated/` = empty → pass |
| Manifest update | atomowy zapis (write to temp + rename) |

## SLO (cele)

| Metryka | Cel | Notatka |
|---|---|---|
| Czas Publish (gate 3 → 5) | < 10s p95 | walidator + generator + git commit |
| Czas CI build (gate 6) | < 5 min p95 | docker build dominuje; cache uv |
| Czas Rolling deploy (gate 7) | < 2 min p95 | per Tenant namespace |
| Czas Preview (P1 → P4 start) | < 30s p95 | ephemeral worker boot |
| Czas Housekeeping cycle | 1× / godz. | kontroluje accumulation deprecated Build IDs |
| Częstotliwość failed CI build na Publish | < 1% | walidator IR powinien wcześniej wyłapać |
| Idempotency violation (regenerate produces diff) | 0 | hard constraint, blokuje merge |

## Search Attributes (każdy workflow execution)

| SA | Wartość | Cel |
|---|---|---|
| `tenant_id` | UUID Tenanta | scoping audit/observability |
| `client_org_id` | UUID Client Org | filtering per klient |
| `blueprint_id` | snake_id Blueprintu | tracking per definition |
| `version` | numer wersji `<n>` | tracking per wersja |
| `engagement_id` | UUID konkretnego uruchomienia | korelacja end-to-end |

## Concurrent publish

| Scenariusz | Zachowanie |
|---|---|
| Dwóch designerów Publish na różnych Blueprintach równocześnie | Niezależne lock-i; równoległy CI workflow per Blueprint |
| Dwóch designerów Publish na tym samym Blueprincie równocześnie | Blueprint-level lock; drugi czeka lub dostaje 409; przy tym samym source hash → drugi widzi no-op |

## Powiązane dokumenty

- `ARCHITECTURE.md` — wysokopoziomowa architektura pipeline'u
- `adr/ADR-003-compiled-py-per-blueprint.md` — layout `.py`, lifecycle wersji, manifest
- `adr/ADR-005-worker-versioning-build-id.md` — Worker Versioning, Build ID lineage
- `adr/ADR-006-tenancy-isolation.md` — namespace per Tenant
- `IR_SPEC.md` — schema IR konsumowanego przez walidator i generator
- `WORKFLOW_RULES.md` — sandbox constraints sprawdzane w CI build
- `DEPLOYMENT.md` — szczegóły docelowej infrastruktury (out of scope sesji projektowej)
