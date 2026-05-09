# ADR-003: Skompilowany `.py` per Blueprint × wersja

**Status:** Accepted
**Data:** 2026-05-09
**Decyzje źródłowe:** #14, #17, #30 (`docs/SESSION_STATE.md`)

## Kontekst
- CNCF Serverless Workflow IR wymaga mostka do Temporal Python SDK.
- Kandydaci wykonania: A — interpreter IR w runtime, B — kompilacja IR → `.py`, C — hybryda.
- Temporal Python SDK wymaga `@workflow.defn` jako klasy Pythona zarejestrowanej w workerze przed startem.
- Worker Versioning Build ID pinuje konkretne rewizje workflow do executions.
- Wersjonowanie Blueprintów (Draft/Publish) generuje N immutable wersji per Blueprint.
- Audyt i replay wymagają deterministycznego dostępu do historycznego kodu workflow.

## Decyzja
Model B (kompilacja `.py`) jako jedyny model wykonania. Generator emituje jeden samowystarczalny plik per `Blueprint × wersja`, importowany przez worker na startupie.

## Layout pliku
- Ścieżka: `generated/workflows/<snake_id>__v<n>.py`.
- Zawartość: typy Pydantic (input/output/state) + klasa `@workflow.defn`, all-inclusive, bez importów cross-blueprint.
- Temporal `name` workflow: bez sufiksu wersji (Build ID pinuje wersję).
- Python class name: `<PascalCaseId>_v<n>` (sufiks kosmetyczny, dla introspekcji/debug).
- Activities: poza generacją, ręcznie pisane w `activities/registry.py`.
- Manifest top-level: `generated/manifest.json`.
- Header pliku:
  ```
  # Generated from Blueprint <id> v<n> at <ts>
  # Source hash: <sha>
  # DO NOT EDIT
  ```
- Formatter: `black` z fixed config (deterministyczny output dla source hash).

## Lifecycle wersji
1. Draft — edycja Blueprintu w UI, brak generacji.
2. Publish — zamrożenie wersji `v<n>`, trigger generatora.
3. Generator — sprawdzenie source hash (idempotent: skip jeśli plik istnieje z tym samym hash), emisja `.py`, format `black`, update `manifest.json`.
4. CI build — budowa worker image z Worker Versioning Build ID powiązanym z wersją.
5. Rolling deploy — nowi workerzy z nowym Build ID, starzy obsługują existing executions do końca.
6. Housekeeping — cleanup starych workerów po osiągnięciu 0 running executions na ich Build ID.

## Manifest
- Lokalizacja: `generated/manifest.json`.
- Zawartość:
  - lista wersji per Blueprint (active, deprecated),
  - mapping `<blueprint_id, version>` → `<file_path, source_hash, build_id>`,
  - Build ID lineage (kolejność deploymentów, redirects),
  - timestamp publish.
- Rola: source of truth dla worker startup loadera i CI.

## Rozważone alternatywy
| Opcja | Opis | Dlaczego nie |
|---|---|---|
| A — Interpreter IR | Runtime walker po IR wewnątrz generycznego `@workflow.defn` | Brak statycznej analizy, trudny debug w Temporal UI, narzut interpretacji w sandboxie workflow, problem z determinizmem przy ewolucji interpretera |
| C — Hybryda | Część kompilowana, część interpretowana | Łączy wady obu, dwa source-of-truth dla semantyki, większa powierzchnia testów |
| Layout #1 — split (types/, workflows/, shared/) | Pliki dzielone między wersjami | Cross-version coupling, trudniejszy rollback, source hash niestabilny |
| Layout #2 — jeden plik per Blueprint, wszystkie wersje | Klasy `_v1`, `_v2`, ... w jednym pliku | Plik rośnie nieograniczenie, diff publishu obejmuje cały plik, churn w git |

## Konsekwencje
### Pozytywne
- Statyczna analiza (mypy, ruff, IDE) działa na wygenerowanym kodzie.
- Stack trace w Temporal UI wskazuje konkretną wersję Blueprintu.
- Replay historycznych executions: import pliku `_v<n>.py` z git history, deterministycznie.
- Idempotentny generator (source hash) — bezpieczny re-run w CI.
- Worker image zawiera tylko latest version per Blueprint — minimalna powierzchnia runtime.
- Atomowy unit deploymentu = `(file, build_id)`.

### Trade-offs
- Każda zmiana semantyki generatora wymaga regeneracji wszystkich aktywnych wersji lub akceptacji driftu.
- Duża liczba Blueprintów × wersji = duża liczba plików w `generated/` (mitigacja: ścieżka per blueprint, manifest jako index).
- Concurrent publish wymaga Blueprint-level lock + atomowy CI workflow.
- Stare `_v<n>.py` zostają w git history forever (audyt/replay/rollback) — koszt repo size.

### Follow-up
- ADR-005: definicja schematu Worker Versioning Build ID i polityki redirectów.
- Spec generatora: deterministyczny porządek pól, importów, formatowania (test: regen → identical hash).
- Polityka deprecation wersji: kryterium 0 running executions + retention dla replay.
- Tooling: CLI do inspekcji `manifest.json` (active/deprecated/build_id lineage).

## Referencje
- `docs/SESSION_STATE.md` #14, #17, #30
- ADR-001 (Python codegen vs DSL), ADR-005 (Worker Versioning Build ID) — powiązane
