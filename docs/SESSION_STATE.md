# Stan sesji

Snapshot kontekstu i decyzji. Czytaj na początku nowej sesji, żeby kontynuować pracę.

**Ostatnia aktualizacja:** 2026-05-09 (sesja kontynuowana — L14 w toku)

## Cel projektu

Pipeline: **React Flow JSON → działający `.py` Temporal**.

Cel sesji: ustalić wszystkie decyzje projektowe **przed** budową.

Projekt jest częścią ekosystemu **Weaver** (AI Agent Orchestrator, NIE workflow system) — szczegóły w pamięci `project_weaver_vocabulary.md` i `~/Desktop/weaver-root/docs/content/architecture/vocabulary/index.md`.

## Decyzje zamknięte (sesja 2026-05-09)

| # | Decyzja | Status |
|---|---|---|
| 1 | Source of truth UI = **React Flow** | ✅ |
| 2 | UI primitivy ograniczone strukturalnie (jak N8N — Sequence/Branch/Loop/Parallel/WaitSignal, brak surowych krawędzi) | ✅ |
| 3 | **Dwuwarstwowy model** typów: zamknięty zestaw control flow primitivów + otwarty rejestr Tools/Specialized Agents (zgodne z istniejącą architekturą Weaver) | ✅ |
| 4 | Tenancy — **fizyczna izolacja per Tenant** (osobny Temporal namespace + DB), **logiczna izolacja per Client Org** (row-level filter, Search Attribute), opcjonalna fizyczna opt-in per Client Org dla regulowanych klientów | ✅ |
| 5 | **Reprezentacja workflow** = CNCF Serverless Workflow 1.0 JSON (wire format) + Pydantic models matchujące spec (runtime, walidacja, codegen) | ✅ |
| 6 | **Wszystkie 12 task types CNCF SW 1.0** (`call`, `do`, `for`, `fork`, `switch`, `try`, `wait`, `listen`, `emit`, `raise`, `run`, `set`) są w MVP | ✅ |
| 7 | **Rejestracja Tools/Specialized Agents** jako CNCF SW `functions` z custom `type` (`weaver_tool` / `weaver_specialized_agent`); pola: `name`, `type`, `operation`, `input` schema ref, `output` schema ref; generator dispatchuje per `type` (Tool → lokalna activity, Specialized Agent → generyczna activity HTTP) | ✅ |
| 8 | **Atrybuty task types** = wszystkie pola spec CNCF SW 1.0 + extensions Weaver/Temporal (przez `metadata` lub custom keys); konkretna lista extensions definiowana iteracyjnie (Temporal: retry policy, start_to_close_timeout, heartbeat_timeout; Weaver: assignee_group, audience_type, visibility_scope, ...) | ✅ |
| 9 | **Mapping krawędzi React Flow → CNCF SW**: flat edges z multi-handle dla `switch`/`fork`/`listen`/sekwencji/atomowych; container/subflow (React Flow `parentNode`) dla `for` i `try`. Konwencja handles: `case_<id>`/`default`, `branch_<n>`, `main`/`catch_<err>`, defaulty `out`/`in` | ✅ |
| 10 | **Trigger jako pierwszy node w grafie** (bez incoming edges); typy: `manual_trigger`, `webhook_trigger`, `schedule_trigger`, `event_trigger` | ✅ |
| 11 | **Warunki w MVP** = strukturalny builder w UI (field/op/value, AND/OR przyciski). UI kompiluje do JQ pod spodem. Brak ręcznego pisania JQ, brak LLM-NL w MVP — odłożone do późniejszych faz | ✅ |
| 12 | **Przepływ danych** = hybryda: auto-export wyniku każdego task pod `.steps.<node_id>.output` (default, bez deklaracji); opcjonalne `export.as` per task gdy user chce nazwać/przekształcić wynik. Kontekst workflow jest globalny, akumulujący się | ✅ |
| 13 | **Schemy I/O = Pydantic w kodzie jako source of truth.** Tools (in-process w `weaver-workers`) → JSON Schema auto-eksportowany z Pydantic do manifestu. Specialized Agents (osobne FastAPI serwisy) → OpenAPI auto-generowany przez FastAPI z ich własnych Pydantic modeli, manifest pulluje z `/openapi.json`. Walidator IR i UI palette używają JSON Schema. Generator Pythona importuje Pydantic typy. Wszystko code-first | ✅ |
| 14 | **Output format** = layout #3 (jeden plik per Blueprint × wersja, all-inclusive: typy Pydantic + `@workflow.defn` class). Ścieżka: `generated/workflows/<snake_id>__v<n>.py`. Temporal workflow `name` = bez wersji (Worker Versioning Build ID pinuje), Python class name = `<PascalCaseId>_v<n>`. Top-level manifest w `generated/manifest.json`. Activities w ręcznie pisanym `activities/registry.py`. Header: `# Generated from Blueprint <id> v<n> at <ts>\n# Source hash: <sha>\n# DO NOT EDIT`. Formatter: `black` fixed config | ✅ |
| 15 | **Mapping CNCF SW → Python Temporal** zgodnie z tabelą L10 dla wszystkich 12 task types. **Generator używa Python `ast` module** (nie string templating) — branżowy standard. **Emituje typowane zmienne lokalne równolegle z `steps_output` dict** (typed direct refs + JQ runtime access). Helper `_eval()` z compiled JQ programs cached w module. **JQ engine** = biblioteka `jq` Python (libjq wrapper) w runtime; **JQ→Python transpilacja NIE w MVP** (custom optimization, marginalne korzyści). **Action item:** zweryfikować w fazie implementacji czy libjq przechodzi przez Workflow Sandbox; fallback: expression eval w activity | ✅ |
| 16 | **Walidator IR** egzekwuje reguły z 6 kategorii: A (struktura grafu — single trigger, reachability, brak cykli poza for/try, unique IDs, container body non-empty, fork/join match), B (handles/edges — switch.default, declared handles, no duplicates, valid catch error types), C (registry funkcji — exists, type ∈ closed set, schema resolvable), D (schemy/typy — workflow Input/Output declared, call.with type-compatible, export.as compat, JQ refs best-effort), E (polityki Temporal — timeout, retry bounds, valid ISO 8601 duration, for.while terminates), F (CNCF SW spec compliance — document.dsl, JSON Schema validation, task type ∈ 12). Severity: error (blokuje generację) vs warning. Implementacja: Pydantic walidatory + osobny `validator.py` z semantycznymi regułami C/D/E/F | ✅ |
| 17 | **Lifecycle wersji**: Draft → Publish → generator (source hash check, idempotent) → CI build z Worker Versioning Build ID → rolling deploy → housekeeping (cleanup starych workerów gdy 0 running executions). **Worker image zawiera tylko latest version** każdego Blueprintu (`_v<n>` suffix na klasie kosmetyczny). **Stare `_v<n>.py` w git history forever** dla audytu/replay/rollback. **Manifest** w `generated/manifest.json` z aktywnymi/deprecated wersjami + Build ID lineage. Concurrent publish: Blueprint-level lock + atomowy CI workflow | ✅ |
| 18 | **Activity registry**: katalog `activities/` z modułami `tools/<integration>.py` (jeden plik per Tool integration, każdy `@activity.defn`), centralnym `registry.py` (re-export `ALL_ACTIVITIES`), generycznym dispatcher-em `specialized_agents.py` z jedną activity `call_specialized_agent(AgentCall) -> AgentResult`. Manifest `activities/manifest.json` auto-generowany przez `scripts/build_manifest.py`: introspekcja Pydantic dla Tools + pull `/openapi.json` dla Specialized Agents. Manifest konsumowany przez UI palette / walidator IR / generator. Worker startuje z `Worker(activities=ALL_ACTIVITIES, workflows=load_all_from(generated/workflows/))` | ✅ |
| 19 | **Trzy formy Blueprintu** (uzupełnienie #14/#17): (1) **React Flow JSON** — UI layer (positions, styling, handles); (2) **CNCF SW IR JSON** — semantyka, source of truth dla source hash + walidator + generator; (3) **Generated `.py`** — runtime. DB designerze: Draft + Published wersje form (1) i (2). Git (immutable artifacts po Publish): `blueprints/<id>/v<n>/{reactflow.json, cncf-sw.json}` + `generated/workflows/<id>__v<n>.py`. Mapper React Flow → CNCF SW jest deterministyczny. Z `.py` nie da się odtworzyć (1) ani (2); persystencja wszystkich trzech form jest obowiązkowa | ✅ |
| 20 | **Error handling — model konfiguracji**: reusable profile `use.retries.<name>` / `use.timeouts.<name>` w CNCF SW (zgodne ze spec); taski referują przez nazwę, inline jako fallback. UI = dropdown "Retry profile" / "Timeout profile" | ✅ |
| 21 | **Error handling — mapping retry CNCF SW → Temporal RetryPolicy**: pełen CNCF SW retry model + Temporal-specific extensions w `metadata.temporal.*` (`non_retryable_error_types`, `maximum_interval`). Walidator IR (kategoria E) **blokuje publish** jeśli profile używa pól bez mapping na Temporal: `jitter`, `when`/`exceptWhen`, `limit.duration`, `limit.attempt.duration`. UI palette pokazuje tylko obsługiwane pola | ✅ |
| 22 | **Error handling — mapping timeout CNCF SW → Temporal**: profile `use.timeouts.<name>` zawiera `after` (= Temporal `start_to_close_timeout`, **wymagane**) + `metadata.temporal.heartbeat` (long-running) + `metadata.temporal.schedule_to_close` (globalny deadline włącznie z retries). `schedule_to_start_timeout` **odłożone** (rzadko poprawnie używane) | ✅ |
| 23 | **Error handling — error taxonomy (catch semantics)**: hybryda. **Base error types** (zamknięte): `ValidationError`, `AuthError`, `RateLimitError`, `TimeoutError`, `NotFoundError`, `IntegrationError`, `InternalError`. Tool/Specialized Agent **deklaruje custom errors w manifest** (Pydantic subclasses `ApplicationError`; per error: `type`, `description`, `retryable: bool`, `output_schema_ref`). `build_manifest.py` eksportuje sekcję `errors` per Tool. UI palette: dropdown `catch.with.type` filtrowany do errors deklarowanych przez konkretny task. Walidator IR (kategorie C/D) blokuje publish jeśli `catch.with.type ∉ (base ∪ tool.errors)` | ✅ |
| 24 | **Error handling — non-retryable source of truth**: manifest deklaruje default `retryable: bool` per error type (decyzja #23). Profile `use.retries.<name>` może rozszerzyć `nonRetryableTypes: [list]` nadpisując manifest dla wszystkich tasków używających tego profilu. Generator emituje merged list (manifest non-retryable ∪ profile.nonRetryableTypes) do `RetryPolicy.non_retryable_error_types` | ✅ |
| 25 | **Error handling — multi-catch**: spec-literal + UI helper. CNCF SW 1.0 `try.catch` jest singular (jeden catch per try). UI prezentuje multi-catch tabelę dla UX; mapper React Flow → CNCF SW IR kompiluje multi-catch UI do **pojedynczego `catch` z `switch` task wewnątrz `catch.do`** matchującego po `error.type` (kolejność branches = priorytet UI). 100% spec-compliant; IR pozostaje deterministycznie generowane | ✅ |
| 26 | **Error handling — uncaught exceptions**: fail-fast. Niezłapany error propaguje do top-level workflow → status `Failed`. **Brak workflow-level error handler** (`document.onError`) w MVP. **Brak workflow retry policy** w MVP (idempotency concerns). User opakowuje workflow body w explicit top-level `try` task jeśli potrzebuje cleanup/notification (decyzja #6 — `emit`/`raise` dostępne). Observability poprzez natywne Temporal failure events / metryki. Po MVP można dodać `document.onError` extension | ✅ |
| 27 | **Workflow-level timeout**: pojedyncze pole `document.metadata.temporal.workflow_run_timeout` (opcjonalne, ISO 8601 duration). Generator emituje do `@workflow.defn` przez `start_workflow(..., run_timeout=...)`. **Brak `workflow_execution_timeout`** (redundantne wobec #26 — brak workflow retry policy w MVP). **Brak `workflow_task_timeout`** (Temporal default 10s wystarczy). UI pokazuje jedno pole "Workflow timeout" na Blueprint settings | ✅ |
| 28 | **Defaulty profile**: built-in profile `default_timeout` auto-aplikowany dla tasków `call`/`run` bez explicit `use.timeouts.<ref>` ani inline timeout. **Wartości konfigurowalne 3-poziomowo (cascade)**: **Tenant** (system-wide defaults dla całego namespace) → **Client Org** override → **Blueprint** override. Brak hardcoded values w kodzie. Pola konfigurowane: `default_start_to_close` (= `after`), `default_heartbeat`, `default_schedule_to_close`. Generator wykonuje cascade resolution w momencie publish i emituje finalne wartości do `document.use.timeouts.default_timeout`. UI: Settings panel per Tenant, per Client Org, per Blueprint (każdy pokazuje aktualne wartości + dziedziczone, oznacza override-y). **Brak default retry** — task bez `use.retries.<ref>` = no retry, fail-fast (świadoma decyzja). Walidator IR (kategoria E): jeśli brak timeout → auto-przypisz `default_timeout` (warning, nie error). UI palette pokazuje "Using default_timeout (inherited from <Tenant\|Client Org\|Blueprint>)" placeholder | ✅ |
| 29 | **Compensation / saga pattern**: **NIE w MVP** jako native construct. Saga = user-implemented pattern przez explicit `try.catch.do` z compensation tasks definiowanymi ręcznie. Spójne z decyzjami #6 (zamknięte 12 task types CNCF SW) i #19 (CNCF SW IR jako source of truth). Po MVP rozważyć convention przez extension `metadata.weaver.compensation: <task_ref>` z auto-rollback wrapper-em w generatorze | ✅ |
| 30 | **Model wykonania**: **B (kompilacja `.py`) — jedyny model**. CNCF SW IR → codegen → `.py` plik per Blueprint × wersja, Worker importuje na startup. Wszystkie decyzje #14, #15, #17, #18, #19 są na tym oparte. **Opcja A (interpreter)** i **Opcja C (hybryda z interpreter-em)** **odrzucone** — interpreter to powrót do DSL-a, który cały projekt porzuca (cel projektu = migracja z DSL na Temporal-native codegen). Skala long-tail (tysiące Blueprintów per tenant) rozwiązywana per-tenant Worker partitioning lub Worker Versioning, **nie przez interpreter** | ✅ |

## Lista do zamknięcia (kolejność)

| # | Decyzja | Status |
|---|---|---|
| L1 | Input format (React Flow JSON schema) | (rozwiązane przez #5: CNCF SW jako kanoniczny IR; React Flow → mapper → CNCF SW) |
| L2 | Lista task types CNCF SW wspieranych w MVP + jak rejestrowane są Tools/Specialized Agents (callable via `call`) | ✅ (decyzje #6, #7) |
| L3 | Atrybuty każdego task type (jakie pola CNCF SW + ewentualne extensions) | ✅ (decyzja #8) |
| L4 | Reprezentacja krawędzi React Flow → CNCF SW (sourceHandle/targetHandle dla switch then/else, dla fork/join) | ✅ (decyzja #9) |
| L5 | Trigger (jak zaczyna się workflow — webhook, schedule, manual) | ✅ (decyzja #10) |
| L6 | Reprezentacja warunków (CNCF SW używa runtime expressions — JQ lub Workflow Expression Language) | ✅ (decyzja #11) |
| L7 | Reprezentacja przepływu danych (CNCF SW ma `input`/`output`/`export` per task) | ✅ (decyzja #12) |
| L8 | Schemy I/O Tools/Specialized Agents (jak walidator wie, że output A pasuje do input B) | ✅ (decyzja #13) |
| L9 | Output format (jak wygląda generowany `.py` — struktura, importy, nazwa klasy) | ✅ (decyzja #14) |
| L10 | Mapping: dla każdego CNCF SW task → konkretna konstrukcja Python Temporal | ✅ (decyzja #15) |
| L11 | Walidator (lista reguł strukturalnych) | ✅ (decyzja #16) |
| L12 | Wersjonowanie pliku `.py` (nazwa, gdzie leży, jak deployowany) | ✅ (decyzja #17) |
| L13 | Activity registry (skąd Python wie, że "send_email" to konkretna funkcja) | ✅ (decyzja #18) |
| L14 | Error handling (retry, timeout — gdzie w IR, jak emitowane do Pythona) | ✅ (decyzje #20–#29) |

## Decyzje dyskutowane, ale otwarte

(brak — wszystkie wcześniej dyskutowane zostały sformalizowane: model wykonania → #30, język ekspresji warunków → #11)

## Decyzje odłożone (sprzed sesji)

6. Target deployment (Cloud Run / GKE / self-hosted; Temporal Cloud czy własny)
7. Skala docelowa (liczba Blueprintów, Engagement/dzień)
8. Wielkość zespołu
9. Audience UI (dev / analityk / nietechniczny user)
10. Język UI / dokumentacji user-facing

## Stan plików w repo

```
workflows/
├── CLAUDE.md
└── docs/
    ├── DOCS_PLAN.md
    └── SESSION_STATE.md   ← ten plik
```

## Następny krok

**Sesja zamknięta — pipeline React Flow JSON → Temporal `.py` w pełni wyspecyfikowany. 30 decyzji projektowych. Build-ready.**

Tematy spoza scope tej sesji (do osobnych sesji, **nie** do rozwijania automatycznie):
- Audience UI / RBAC / multi-role / permissions / per-role UI surface — kompleksowy temat produktowy
- Język UI / dokumentacji user-facing
- Target deployment (Cloud Run / GKE / self-hosted; Temporal Cloud vs własny)
- Skala docelowa (liczba Blueprintów, Engagements/dzień)
- Wielkość zespołu

## Referencje

- `~/Desktop/weaver-root/docs/content/architecture/vocabulary/index.md` — słownik Weaver (Agent / Blueprint / Engagement / Skill / Tool / Specialized Agent)
- `~/Desktop/weaver-root/docs/content/architecture/b2b-client-model.md` — Tenant / Client Org / Branch hierarchia
- `~/Desktop/weaver/N8N/n8n-toolset.md` — referencja kategorii i typów kroków
- CNCF Serverless Workflow 1.0 spec — kanoniczna reprezentacja workflow

## Reguły komunikacji ustalone w sesji

- Jedno pytanie naraz (feedback memory: `feedback_one_question_at_a_time.md`)
- Terse responses, bullets/tabele, max info density (`feedback_terse_responses.md`)
- Zamykaj jeden temat zanim otworzysz następny (`feedback_close_topics_sequentially.md`)
