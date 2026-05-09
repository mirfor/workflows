# IR_TO_PYTHON

Specyfikacja transformacji CNCF Serverless Workflow IR (JSON) na Python `.py` dla Temporal, realizowanej przez `generator/`.

## 1. Architektura generatora

- Backend: Python `ast` module (decyzja #15), bez string templating.
- Pipeline: IR JSON → walidator → builder AST → `ast.unparse()` → `black.format_file_in_place()` → zapis na dysk.
- Uzasadnienie AST:
  - Type safety na poziomie konstrukcji języka (niemożliwe `SyntaxError` z literalu).
  - Idempotentny output po formatterze (deterministyczna serializacja).
  - Refactor-friendly: transformacje na drzewie zamiast regex po tekście.
  - Każdy task type → dedykowany builder zwracający `list[ast.stmt]`.

## 2. Layout wygenerowanego pliku

| Element | Wartość |
|---|---|
| Ścieżka | `generated/workflows/<snake_id>__v<n>.py` |
| Class name | `<PascalCaseId>_v<n>` (suffix kosmetyczny, decyzja #17) |
| Workflow `name` | `<snake_id>` (bez `_v<n>`; pinowanie Build ID, ADR-005) |
| Manifest | `generated/manifest.json` aktualizowany atomowo |

### Header (komentarze)

```
# Generated from Blueprint <id> v<n> at <iso8601_ts>
# Source hash: <sha256>
# DO NOT EDIT
```

### Sekcje pliku (kolejność)

1. Header.
2. Importy: `temporalio.workflow`, `temporalio.common.RetryPolicy`, `temporalio.exceptions.ApplicationError`, `dataclasses`, `pydantic.BaseModel`, `asyncio`, `jq`.
3. Importy Tools/Specialized Agents: `from activities.tools.<integration> import <operation>`, `from activities.specialized_agents import call_specialized_agent, AgentCall`.
4. Pydantic typy I/O: `class Input(BaseModel)`, `class Output(BaseModel)`, typy per task (`<Task>Input`, `<Task>Output`).
5. Top-level `_JQ_CACHE` i funkcja `_eval()`.
6. Klasa `@workflow.defn(name="<snake_id>") class <PascalCaseId>_v<n>:` z metodą `@workflow.run async def run(self, inp: Input) -> Output`.

## 3. Mapping CNCF SW task types → Python Temporal

| Task | Python Temporal |
|---|---|
| `call` (`weaver_tool`) | `await workflow.execute_activity(<module>.<operation>, <input>, start_to_close_timeout=..., retry_policy=...)` |
| `call` (`weaver_specialized_agent`) | `await workflow.execute_activity(activities.specialized_agents.call_specialized_agent, AgentCall(...), ...)` |
| `do` | sekwencja `await` w bloku |
| `for` | `for <each> in _eval("<expr>", ctx):` z body z `do` |
| `fork` (`compete=False`) | `await asyncio.gather(*tasks)` |
| `fork` (`compete=True`) | `await workflow.wait(tasks, return_when=asyncio.FIRST_COMPLETED)` + cancel pozostałych |
| `switch` | `if/elif/else` z `_eval(...)` na warunkach |
| `try` | `try: ... except ApplicationError as e: ... <catch.do>` |
| `wait` | `await workflow.sleep(<duration_seconds>)` |
| `listen` | `await workflow.wait_condition(lambda: ...)` lub signal handler |
| `emit` | `await workflow.execute_activity(emit_event, ...)` |
| `raise` | `raise ApplicationError(message, type=..., non_retryable=...)` |
| `run` (workflow) | `await workflow.execute_child_workflow(<Class>.run, ...)` |
| `run` (script/shell/container) | activity dispatcher (`run_script`, `run_shell`, `run_container`) |
| `set` | `steps_output["<key>"] = <value>` |

## 4. Typed locals + steps_output

- Per task generator emituje typowaną zmienną lokalną:
  ```python
  send_welcome: SendEmailOutput = await workflow.execute_activity(...)
  ```
- Auto-export do dict (decyzja #12):
  ```python
  steps_output["send_welcome"] = send_welcome
  ```
- `steps_output: dict[str, Any]` inicjalizowany na początku `run()`.
- JQ runtime czyta przez `_eval(expr, {"input": inp, "steps": steps_output})`.
- Typowane locale dają type checker coverage; dict zapewnia dynamiczny dostęp z JQ.

## 5. `_eval()` helper z compiled JQ cache

```python
import jq
from typing import Any

_JQ_CACHE: dict[str, jq._Program] = {}

def _eval(expr: str, ctx: dict) -> Any:
    prog = _JQ_CACHE.get(expr)
    if prog is None:
        prog = jq.compile(expr)
        _JQ_CACHE[expr] = prog
    return prog.input(ctx).first()
```

- Cache module-level; kompilacja per unikalny expr raz na proces workera.
- Sandbox warning (decyzja #15): `libjq` (C-level) może wykonywać I/O lub trzymać global state niezgodny z Workflow Sandbox.
- Action item: zweryfikować passthrough `libjq` przez sandbox restrictions.
- Fallback: ewaluacja JQ w activity (`eval_jq` activity), jeśli sandbox blokuje.

## 6. Mapping retry / timeout

### Retry (decyzja #20)

| CNCF SW (`use.retries.<name>`) | Temporal `RetryPolicy` |
|---|---|
| `delay` | `initial_interval` |
| `backoff.exponential.multiplier` | `backoff_coefficient` |
| `limit.attempt.count` | `maximum_attempts` |
| `limit.attempt.duration` | `maximum_interval` |
| `except.type` | `non_retryable_error_types` |

### Timeout (decyzje #21, #22, #28)

| CNCF SW (`use.timeouts.<name>`) | Temporal |
|---|---|
| `run` | `start_to_close_timeout` |
| `heartbeat` | `heartbeat_timeout` |
| `total` | `schedule_to_close_timeout` |

- Cascade resolution `default_timeout` (Tenant → Client Org → Blueprint) wykonywana przed codegen; generator otrzymuje rozwinięte wartości.
- Pola CNCF SW bez Temporal mapping (`jitter`, `when` w retry policy, `limit.duration` overlapping z timeout): walidator IR blokuje przed generatorem (#21).
- Generator zakłada że IR przeszedł walidator; brak runtime check.

## 7. Error handling

- Multi-catch z UI → IR redukuje do single `catch` z `switch` na `e.type` w `catch.do` (mapper, decyzja #25).
- Generator emituje:
  ```python
  try:
      <task body>
  except ApplicationError as e:
      <catch.do body z switch na e.type>
  ```
- Niezłapany `ApplicationError` → propagacja → fail-fast workflow (decyzja #26).
- Brak workflow-level retry/handler — Temporal Workflow zawsze fail na uncaught.

## 8. Source hash + idempotency

- Hash: `sha256(json.dumps(ir, sort_keys=True, separators=(",", ":")))` (decyzja #17).
- Hash w header pliku (`# Source hash: <sha>`).
- CI check: regenerate z tego samego IR → `diff generated/ generated.new/` musi być pusty.
- Black formatter w fixed wersji w `pyproject.toml` (gwarancja byte-identical).

## 9. Worker Versioning Build ID (ADR-005)

- File per wersja: `<snake_id>__v<n>.py`.
- Class: `<PascalCaseId>_v<n>` (suffix kosmetyczny dla unikalności w Pythonie).
- `@workflow.defn(name="<snake_id>")` — Temporal `name` bez suffix; Build ID pinuje wersję workera.
- `generated/manifest.json` aktualizowany dopiskiem:
  ```json
  {"id": "<snake_id>", "version": <n>, "class": "<PascalCaseId>_v<n>", "file": "workflows/<snake_id>__v<n>.py", "hash": "<sha>"}
  ```

## 10. Formatter

- `black` z fixed config (line-length 100; `pyproject.toml`).
- Wywołanie: `black.format_file_in_place(Path(out), fast=False, mode=black.Mode(line_length=100), write_back=black.WriteBack.YES)` lub `subprocess.run(["black", "--line-length", "100", out])`.
- Formatter uruchamiany po `ast.unparse()` przed obliczeniem hash sprawdzającego idempotencję.

## 11. Test strategy

| Test | Lokalizacja | Kryterium |
|---|---|---|
| Golden files | `tests/generator/golden/<name>/{cncf-sw.json, expected.py}` | byte-equal po formatterze |
| Replay | `tests/generator/replay/` | stary `.py` przechodzi `Replayer.replay_workflow()` na historii z poprzedniej wersji |
| Idempotency | CI | regenerate → byte-identical output |
| AST validity | smoke | `ast.parse(generated_source)` bez exception |

## 12. Workflow Sandbox compliance

- Generator emituje wyłącznie konstrukcje zgodne z sandbox (`docs/WORKFLOW_RULES.md`).
- Zakazane: `time.sleep`, `random.random`, `datetime.now`, `open()`, `requests`, `socket`.
- Zamiana w generatorze:

| Niedeterministyczne | Substytut |
|---|---|
| `time.sleep(s)` | `await workflow.sleep(s)` |
| `random.random()` | `workflow.random().random()` |
| `datetime.now()` | `workflow.now()` |
| `uuid.uuid4()` | `workflow.uuid4()` |
| Network/file I/O | activity |

- Wszystko niedeterministyczne wynoszone do activities z odpowiednim retry policy.

## 13. Referencje

- `docs/SESSION_STATE.md` — decyzje #12, #14, #15, #17, #20, #21, #22, #25, #26, #28.
- `docs/ARCHITECTURE.md` — komponenty pipeline.
- `docs/PIPELINE.md` — pełny flow Blueprint → registered worker.
- `docs/WORKFLOW_RULES.md` — reguły Workflow Sandbox.
- `docs/IR_SPEC.md` — schema IR JSON.
- `docs/ACTIVITY_CATALOG.md` — katalog activities (Tools, Specialized Agents).
- `docs/adr/ADR-001-*.md` — wybór Temporal.
- `docs/adr/ADR-003-*.md` — strategia codegen.
- `docs/adr/ADR-005-*.md` — Worker Versioning / Build ID.
- `generator/` — implementacja.
