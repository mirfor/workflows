# WORKFLOW_RULES.md

Reglamentacja kodu generowanego dla Temporal Workflow. Dokument służy jako referencja dla deweloperów oraz system prompt dla LLM/codegen. Reguły egzekwowane przez: generator (emisja tylko bezpiecznych konstrukcji), walidator IR (kategoria E — polityki Temporala), CI (replay test, idempotency check), review.

## 1. Sandbox Temporala

- Temporal Python SDK uruchamia workflow code w `workflow.unsafe`-restricted sandboxie (moduł `temporalio.worker.workflow_sandbox`).
- Sandbox wymusza deterministyczny re-execution: każda decyzja workflow musi być reprodukowalna z historii.
- Replay = ponowne wykonanie kodu workflow na zapisanej historii zdarzeń; każde odejście od poprzedniego wyniku → `NondeterminismError`.
- Sandbox blokuje import modułów z efektami ubocznymi (`http`, `socket`, `subprocess`, `requests`, `aiohttp`, `urllib3`) na poziomie workflow.
- Bezpośrednie I/O (sieć, dysk, czas systemowy, RNG, threading) w workflow code jest zakazane — wszystko musi przejść przez Temporal API.
- State workflow trzymany jako lokalne zmienne instancji klasy `@workflow.defn`; mutacja tylko w odpowiedzi na deterministyczne zdarzenia (start, signal, activity result).

## 2. Zakazane konstrukcje

| Zakazane | Powód | Zamiennik Temporal |
|---|---|---|
| `time.sleep(s)` | blocking, niedeterministyczne | `await workflow.sleep(s)` |
| `asyncio.sleep(s)` | blokuje event loop sandboxu | `await workflow.sleep(s)` |
| `datetime.now()`, `datetime.utcnow()` | wall clock | `workflow.now()` |
| `time.time()`, `time.monotonic()` | wall clock | `workflow.time()` |
| `random.random()`, `random.randint()` | non-deterministic seed | `workflow.random().random()` |
| `uuid.uuid4()` | non-deterministic | `workflow.uuid4()` |
| `requests.*`, `httpx.*`, `aiohttp.*` | network I/O | activity z HTTP klientem |
| `open()`, `pathlib.read_text()` | file I/O | activity |
| `os.environ` (read at runtime) | non-determinism po restarcie | parametry workflow / activity |
| `threading.*`, `multiprocessing.*` | shared state, race | nie używać |
| `subprocess.*` | I/O | activity |
| `print()`, `logging` na poziomie workflow | I/O side-effect | `workflow.logger` |
| `asyncio.create_task` na zewnątrz API | bypassuje scheduler | `workflow.start_activity`, `asyncio.gather` z `workflow.*` futures |
| globalne mutowalne zmienne | non-determinism między replay | atrybuty instancji `@workflow.defn` |
| `try/except Exception:` zagłuszające `CancelledError` | breaks cancellation | re-raise `asyncio.CancelledError` |

## 3. Dozwolone i wymagane wzorce

| API | Zastosowanie |
|---|---|
| `workflow.now()` | bieżący czas (deterministyczny, z historii) |
| `workflow.time()` | timestamp float |
| `workflow.random()` | seeded RNG |
| `workflow.uuid4()` | deterministyczny UUID |
| `workflow.sleep(td)` | timer |
| `workflow.execute_activity(fn, args, **opts)` | wszystkie efekty uboczne |
| `workflow.execute_local_activity(...)` | krótkie, bezpieczne aktywności w procesie workera |
| `workflow.execute_child_workflow(...)` | wywołanie sub-workflow |
| `workflow.wait_condition(lambda: ...)` | oczekiwanie na predykat (zmiany state przez signals) |
| `@workflow.signal` | input asynchroniczny |
| `@workflow.query` | read-only inspekcja state |
| `@workflow.update` | input synchroniczny z walidacją |
| `workflow.continue_as_new(...)` | rotacja długiej historii |
| `workflow.logger` | logowanie (filtrowane przy replay) |

Wymagania na wywołanie activity:
- `start_to_close_timeout` lub `schedule_to_close_timeout` — obowiązkowe.
- `retry_policy: RetryPolicy(...)` — z profilu `use.retries` (ADR-004).
- `heartbeat_timeout` — dla aktywności > 60 s.

## 4. Workflow → Activities

- Reguła: cokolwiek nie-deterministycznego ⇒ activity. Workflow jest czystą funkcją state machine.
- Activity może: I/O, RNG, czas systemowy, biblioteki zewnętrzne, side effects.
- Każda activity emitowana przez generator otrzymuje:
  - `RetryPolicy` z profilu `use.retries` (decyzja #20).
  - `timeouts` z profilu `use.timeouts` (decyzja #21).
  - `task_queue` z profilu `use.task_queue` (decyzja #22).
- Profile rezolwowane na etapie codegen z `blueprint.use.*`; brak profilu ⇒ błąd walidatora (kategoria E).
- Activity stub (`activities/<name>.py`) generowany niezależnie od workflow; rejestrowany w workerze.
- Idempotencja activity wymagana — retry musi być bezpieczny (`Idempotency-Key`, dedup w activity, lub natura operacji).

## 5. `workflow.patched()` i wersjonowanie

- W tym projekcie `workflow.patched()` / `deprecate_patch()` **nie są używane**.
- Strategia wersjonowania (ADR-005): Worker Versioning + Build ID.
  - Każda nowa wersja Blueprintu ⇒ nowy plik `.py` ⇒ nowy Build ID.
  - Stare execution kończone na starym Build ID; nowe startują na nowym.
  - Brak migracji w obrębie pliku ⇒ kod workflow pozostaje liniowy, bez gałęzi `if patched(...)`.
- Wyjątek (rozważyć ad-hoc, wymaga ADR): hot-fix bug w kodzie który nie zmienia semantyki Blueprintu i nie może czekać na rotację Build ID — wówczas `patched("fix-XYZ-2026-05")` z planem usunięcia po wygaszeniu execution.
- Generator domyślnie nie emituje `patched()`; emisja wymaga jawnej flagi w IR (`__hotfix_patch`).

## 6. JQ w workflow code

- Decyzja #15: libjq w runtime workera; transpilacja JQ → Python AST poza zakresem MVP.
- **Status: DO VERIFY.** Wymaga weryfikacji że `pyjq` / `jq.py` (binding do libjq) przechodzi Workflow Sandbox import-restrictions.
- Ryzyka:
  - libjq to natywne C — sandbox może zablokować ładowanie .so na poziomie workflow.
  - Wewnętrzne buforowanie / RNG w libjq → potencjalny non-determinism.
- Decyzja interim: wyrażenia JQ ewaluowane w activity `eval_jq(expr, input) -> output`, nie w workflow code.
- Po pozytywnej weryfikacji sandbox: dozwolona ewaluacja inline w workflow dla wyrażeń czysto deterministycznych (filtry, projekcje); operacje z `now`, `env`, `$ENV` zawsze w activity.
- Action item w SESSION_STATE.md (decyzja #15).

## 7. Imports / nondeterminism risks

Bezpieczne (generator może emitować w workflow):
- `temporalio.workflow`, `temporalio.common`, `temporalio.exceptions`.
- `dataclasses`, `typing`, `enum`, `collections`, `itertools`, `functools`, `math`, `decimal`, `fractions`.
- `json` (pure), `re` (deterministic), `base64`, `hashlib`.
- Lokalne moduły z `activities/` — tylko jako referencje (przez `workflow.execute_activity`), nigdy import wykonujący kod.

Zakazane (generator nie może emitować w workflow):
- `requests`, `httpx`, `urllib`, `socket`, `aiohttp`.
- `os` (poza `os.path` static utils), `pathlib` z I/O, `tempfile`.
- `random`, `secrets`, `uuid` (zastąpione `workflow.*`).
- `datetime` z `now/utcnow` (dozwolone klasy `datetime`/`timedelta` jako wartości).
- `threading`, `multiprocessing`, `concurrent.futures`.
- Biblioteki ML/NumPy/Pandas — duże, RNG, native code; do activity.
- Globalne `import *`.

Ryzyka non-determinism (review bramka):
- Iteracja po `dict` / `set` w starszym Pythonie — w 3.7+ dict jest insertion-ordered, set nie; generator wymusza `sorted(...)` przy iteracji po set.
- `hash()` randomized — bez `PYTHONHASHSEED`; nie używać `hash()` do identyfikacji.
- Zmienne klas (`ClassVar`) nie mogą być mutowane w workflow.

## 8. Code style

- Formatter: `black`, line length 100 (`pyproject.toml` → `[tool.black] line-length = 100`).
- Import sort: `isort` profil `black`.
- Linter: `ruff` z regułami `E,F,I,UP,B,SIM`; reguły custom: zakaz importów z listy w sekcji 7.
- Type hints: pełne adnotacje, `from __future__ import annotations`, mypy `strict = true` dla `generated/`.
- Header obowiązkowy każdego wygenerowanego `.py` (ADR-003):

```
# ============================================================
# Generated from Blueprint: <blueprint_id> v<version>
# Source hash: <sha256-of-ir>
# Generator: workflow-codegen <gen_version>
# Generated at: <iso8601>
# DO NOT EDIT — regenerate via `make codegen`
# ============================================================
```

- Nazewnictwo: klasa workflow `<BlueprintId>Workflow`, plik `generated/<blueprint_id>/v<version>/workflow.py`.
- Zero komentarzy odautorskich; tylko docstring z `description` z Blueprintu.
- Determinizm porządku: pola dataclass, kolejność `@workflow.signal`/`@workflow.query` — wg porządku z IR.

## 9. Test strategy

| Test | Zakres | CI gate |
|---|---|---|
| Replay test | Każdy wygenerowany Blueprint × wersja; historia z `tests/fixtures/histories/<bp>/` | blocking |
| Idempotency (codegen) | `codegen(IR) == codegen(IR)` (byte-identical po `black`) | blocking |
| Sandbox import test | `WorkflowEnvironment.start_local()` ładuje moduł bez błędów sandbox | blocking |
| Determinism replay | Random scheduling na pełnej historii, brak `NondeterminismError` | blocking |
| Snapshot AST | Diff drzewa AST vs zatwierdzony snapshot per Blueprint | warning |
| Validator IR (kat. E) | Zakazane konstrukcje wykryte na IR przed codegen | blocking |

- Replay tests uruchamiane via `temporalio.testing.WorkflowEnvironment` z historią z prod (sanityzowaną) i z fixture'ów.
- Idempotency check w `pipeline.py` (PIPELINE.md sekcja 4): regeneracja wszystkich Blueprintów, `git diff` musi być pusty.
- Każda zmiana w generatorze wymaga regeneracji wszystkich Blueprintów (Build ID bump).

## 10. Referencje

- Temporal Python SDK — Workflow Sandbox: https://docs.temporal.io/develop/python/python-sdk-sandbox
- Temporal — Versioning: https://docs.temporal.io/workers#worker-versioning
- ADR-001 — wybór Temporal jako runtime (`docs/adr/ADR-001-*.md`).
- ADR-003 — format wygenerowanego pliku, header, lokalizacja (`docs/adr/ADR-003-*.md`).
- ADR-004 — profile `use.*` (retries, timeouts, task_queue).
- ADR-005 — Worker Versioning Build ID, brak `patched()`.
- `docs/SESSION_STATE.md` — decyzje #14 (mapowanie SW IR → Temporal API), #15 (JQ runtime, DO VERIFY), #17 (zakres MVP codegen), #20–#22 (profile `use.*`).
- `docs/PIPELINE.md` — kroki pipeline'u, gates CI.
- `docs/ARCHITECTURE.md` — przepływ React Flow JSON → CNCF SW IR → Python AST → `.py`.
