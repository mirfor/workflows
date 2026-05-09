# ADR-005: Temporal Worker Versioning (Build ID) dla wersjonowania Blueprintów

**Status:** Accepted
**Data:** 2026-05-09
**Decyzje źródłowe:** #17 (`docs/SESSION_STATE.md`)

## Kontekst
- Publish nowej wersji Blueprintu nie może łamać Engagementów uruchomionych na poprzednich wersjach.
- Determinism check Temporala wymaga, by konkretna execution wykonywała się stale na tej samej definicji workflow.
- Wymagane: równoczesne istnienie running executions na `_v<n-1>` i nowych na `_v<n>`.
- Opcje Temporala:
  - Patching (`workflow.patched`) — kontrola rozgałęzień wewnątrz tej samej klasy.
  - Worker Versioning (Build ID) — przypisanie executions do konkretnej wersji Workera.
  - Osobna nazwa workflow per wersja — manualny routing po stronie startera.

## Decyzja
- Worker Versioning z Build ID jako mechanizm pinningu workflow definition do wersji Workera.
- Każdy Publish generuje nowy Build ID; Task Queue ma multi-version compatibility set.
- Klasa workflow rejestrowana pod stabilną nazwą (bez wersji w `name`).

## Lifecycle wersji
1. **Draft** — edycja w UI; nie zmienia żadnego artefaktu w git.
2. **Publish** — generator z source hash check (idempotent); commit `reactflow.json` + `cncf-sw.json` + `<id>__v<n>.py` do git.
3. **CI build** — Worker image z nowym Build ID; włącza nowy `_v<n>.py`.
4. **Rolling deploy** — nowe Engagements → nowy Worker; running Engagements → stary Worker (kompletują).
5. **Housekeeping** — cleanup starych Workerów gdy 0 running executions.

## Manifest (`generated/manifest.json`)
| Pole | Znaczenie |
|---|---|
| `blueprints[].id` | Identyfikator Blueprintu |
| `blueprints[].active_version` | Aktualna wersja `_v<n>` |
| `blueprints[].deprecated_versions` | Wersje z running executions (do cleanup) |
| `blueprints[].build_id_lineage` | Mapowanie wersja → Build ID (Worker image) |

## Konwencje nazewnictwa
| Element | Konwencja |
|---|---|
| Plik | `generated/workflows/<snake_id>__v<n>.py` |
| Python class | `<PascalCaseId>_v<n>` |
| Temporal workflow `name` | Bez wersji (Worker Versioning Build ID pinuje) |
| `_v<n>` suffix na klasie | Kosmetyczny — pinning w runtime jest po Build ID |

## Concurrent publish
- Blueprint-level lock (np. row lock w DB designerze) wokół sekwencji generate → commit → trigger CI.
- Atomowy CI workflow per Publish: jeden bieg = jeden nowy Build ID.
- Lock zwalniany dopiero po push commitu wersji.

## Rozważone alternatywy
| Opcja | Opis | Dlaczego nie |
|---|---|---|
| `workflow.patched` | Rozgałęzienia wersji w jednej klasie | Akumulacja `if patched(...)` rośnie liniowo z liczbą wersji; nieczytelny diff vs. ReactFlow source |
| Osobna nazwa workflow per wersja (`bp_v1`, `bp_v2`) | Routing po `workflow_type` w starterze | Eksponuje wersję w API; wymaga ręcznego mapowania w starterze; brak natywnego compatibility set |
| Single Worker, hot-reload modułu | Dynamiczne podmiany klas w runtime | Łamie determinism guarantees Temporala; brak izolacji running executions |
| Brak wersjonowania, blokada nowych Publish do 0 running | Drain running przed deploy | Niedopuszczalny czas oczekiwania dla Engagementów long-running (dni/tygodnie) |

## Konsekwencje

### Pozytywne
- Zero-downtime publish niezależny od długości running executions.
- Deterministyczny replay: każda execution wraca do swojego Build ID.
- Audit/rollback przez git history `_v<n>.py` (immutable).
- Worker image zawiera tylko latest `_v<n>` każdego Blueprintu — mniejszy image, prosty build.

### Trade-offs
- Operacyjny narzut: równoległe Workery dla deprecated wersji do czasu drain.
- Manifest musi być spójny z Build ID lineage — dryf prowadzi do mis-routingu.
- Cleanup wymaga monitoringu running count per (Blueprint, version).
- CI build per Publish — koszt vs. częstotliwość edycji.

### Follow-up
- Mechanizm wykrywania 0 running executions per Build ID (query Temporal Visibility).
- Polityka retencji deprecated Workerów (max wiek, max liczba równoległych wersji).
- Telemetria: alert gdy deprecated Worker żyje > N dni.
- Procedura rollback: oznaczenie `_v<n>` jako wycofanej w manifeście + redirect nowych startów na `_v<n-1>`.

## Referencje
- `docs/SESSION_STATE.md` #17
- ADR-003 (compiled .py per Blueprint) — powiązane
- Temporal Worker Versioning: https://docs.temporal.io/workers#worker-versioning
