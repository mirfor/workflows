# IR_SPEC — CNCF Serverless Workflow 1.0 IR

Kanoniczna reprezentacja Blueprintu między mapperem (RF → IR), walidatorem i generatorem (#5, #19).

**Source of truth = Pydantic models w `ir/`.** JSON Schema (`schemas/ir.schema.json`) auto-generowany przez `scripts/export_ir_schema.py`. Spec referencyjny: CNCF Serverless Workflow 1.0.

## Top-level workflow document

```json
{
  "document":  { "dsl": "1.0.0", "namespace": "...", "name": "...", "version": "1" },
  "input":     { "schema": "...", "from": "<jq>" },
  "output":    { "schema": "...", "as": "<jq>" },
  "use":       { "functions": {}, "retries": {}, "timeouts": {}, "errors": {}, ... },
  "do":        [ { "<task_name>": <Task> }, ... ],
  "timeout":   "<TimeoutPolicy ref or inline>",
  "schedule":  { ... },
  "metadata":  { "weaver": { "trigger": <Trigger> }, "temporal": { "workflow_run_timeout": "PT1H" } }
}
```

| Pole | Typ | Wymagane | Notatka |
|---|---|---|---|
| `document.dsl` | `Literal["1.0.0"]` | tak | Pinning wersji spec |
| `document.namespace` | `string` | tak | Tenant/Client Org scoping (#4) |
| `document.name` | `string` | tak | Identyfikator Blueprintu (snake_case) |
| `document.version` | `string` | tak | `<n>` lub semver |
| `do[]` | `list[NamedTask]` | tak | Każdy element = `{ <task_name>: <Task> }` (single-key dict) |
| `metadata.weaver.trigger` | `Trigger` | nie | Pierwszy node w grafie (#10) |
| `metadata.temporal.workflow_run_timeout` | `IsoDuration` | nie | Workflow-level timeout (#27) |

## 12 task types (decyzja #6)

| Task | Pole-klucz | Główne pola | Mapping na Temporal Python |
|---|---|---|---|
| `call` | `call: <function_name>` | `with`, `timeout`, `retries`, `export` | `await workflow.execute_activity(<dispatched>, ...)` |
| `do` | `do: list[NamedTask]` | sekwencja podzadań | sekwencja `await` |
| `for` | `for: { each, in, at? }` | `while`, `do[]` | `for ... in ...:` (deterministic iteration) |
| `fork` | `fork: { branches[], compete }` | — | `asyncio.gather(...)` lub `wait(FIRST_COMPLETED)` jeśli `compete` |
| `switch` | `switch: list[{ case_id: { when?, then } }]` | — | `if/elif/else` |
| `try` | `try: list[NamedTask]`, `catch: TryCatch` | retry, multi-catch (przez switch w `catch.do`, #25) | `try: ... except ApplicationError as e: ...` |
| `wait` | `wait: <IsoDuration>` | — | `await workflow.sleep(...)` |
| `listen` | `listen: { to: { all/any/one } }` | `foreach` | `await workflow.wait_condition(...)` lub signal handler |
| `emit` | `emit: { event: { with } }` | — | `workflow.signal_external_workflow(...)` lub event publish activity |
| `raise` | `raise: { error }` | — | `raise ApplicationError(...)` |
| `run` | `run: { script\|shell\|workflow\|container }` | — | child workflow lub activity dispatcher |
| `set` | `set: dict[str, Any]` | — | przypisanie do `steps_output[<key>]` |

## Wspólne pola każdego task (`_TaskBase`)

| Pole | Typ | Cel |
|---|---|---|
| `if` | `JqExpression` | Skip when false (decyzja #11 — UI builder kompiluje do JQ) |
| `input` | `dict` | Inline I/O schema/transform |
| `output` | `dict` | Inline output schema |
| `export.as` | `JqExpression` | Opcjonalne nazwane export — bez tego runtime auto-eksportuje pod `steps.<id>.output` (#12) |
| `timeout` | `TimeoutPolicy \| str` | Inline lub ref do `use.timeouts.<name>` (#20) |
| `retries` | `RetryPolicy \| str` | Inline lub ref do `use.retries.<name>` (#20) |
| `metadata` | `dict` | Extensions (`metadata.weaver.*`, `metadata.temporal.*`) |

## `use.functions.<name>` — Tools / Specialized Agents (#7, #13, #18)

```json
{
  "name": "send_email",
  "type": "weaver_tool",                    // lub "weaver_specialized_agent"
  "module": "activities.tools.gmail",       // dla weaver_tool
  "endpointUrl": "https://...",             // dla weaver_specialized_agent
  "operation": "send_email",
  "inputSchema": "<JSON Schema or $ref>",
  "outputSchema": "<JSON Schema or $ref>",
  "errors": [ { "type": "...", "retryable": true, "is_base": false }, ... ],
  "defaultRetryProfile": "default_retry",
  "defaultTimeoutProfile": "default_timeout",
  "idempotent": false
}
```

Generator dispatchuje:

| `type` | Wygenerowane wywołanie |
|---|---|
| `weaver_tool` | `await workflow.execute_activity(<module>.<operation>, ...)` |
| `weaver_specialized_agent` | `await workflow.execute_activity(activities.specialized_agents.call_specialized_agent, AgentCall(...))` |

## `use.retries.<name>` — RetryPolicy (#20, #21)

```json
{
  "delay": "PT1S",
  "backoff": { "exponential": { "multiplier": 2.0 } },
  "limit": { "attempt": { "count": 3 } },
  "nonRetryableTypes": ["ValidationError"],
  "metadata": { "temporal": { "non_retryable_error_types": [...], "maximum_interval": "PT60S" } }
}
```

| Pole CNCF SW | Mapping na Temporal `RetryPolicy` |
|---|---|
| `delay` | `initial_interval` |
| `backoff.exponential.multiplier` | `backoff_coefficient` |
| `limit.attempt.count` | `maximum_attempts` |
| `metadata.temporal.maximum_interval` | `maximum_interval` |
| `nonRetryableTypes` ∪ `metadata.temporal.non_retryable_error_types` | `non_retryable_error_types` (merged) |

**Walidator IR blokuje publish** dla pól bez mapping (#21): `when`, `exceptWhen`, `jitter`, `limit.duration`, `limit.attempt.duration`.

## `use.timeouts.<name>` — TimeoutPolicy (#20, #22)

```json
{
  "after": "PT5M",
  "metadata": {
    "temporal": { "heartbeat": "PT30S", "schedule_to_close": "PT15M" }
  }
}
```

| Pole | Mapping |
|---|---|
| `after` | `start_to_close_timeout` (**wymagane**) |
| `metadata.temporal.heartbeat` | `heartbeat_timeout` |
| `metadata.temporal.schedule_to_close` | `schedule_to_close_timeout` |
| `schedule_to_start_timeout` | **NIE w MVP** (#22) |

## Defaulty cascade (#28)

`use.timeouts.default_timeout` jest auto-aplikowany dla `call`/`run` bez explicit profile. Wartości konfigurowalne 3-poziomowo: **Tenant → Client Org → Blueprint** (cascade override). Brak hardcoded values w kodzie. Generator wykonuje resolution w momencie publish i wstrzykuje finalne wartości do `use.timeouts.default_timeout` w wygenerowanym IR.

**Brak `default_retry`** — task bez `retries` = no retry, fail-fast (świadoma decyzja, #28).

## Error taxonomy (#23, #24)

| Base error type | Retryable default |
|---|---|
| `ValidationError` | ❌ |
| `AuthError` | ❌ |
| `RateLimitError` | ✅ |
| `TimeoutError` | ✅ |
| `NotFoundError` | ❌ |
| `IntegrationError` | ✅ |
| `InternalError` | ❌ |

Tools / Specialized Agents deklarują custom errors w manifest (`activities/manifest.json`). Walidator IR wymaga `try.catch.errors.with.type ∈ (base ∪ tool.errors)` dla każdego task w `try.try[]`.

## Trigger (extension Weaver, #10)

Trigger trzyma się w `metadata.weaver.trigger`, dyskryminowany po `type`:

| Type | Pola |
|---|---|
| `manual_trigger` | `input_schema_ref` (opcjonalnie) |
| `webhook_trigger` | `path`, `method`, `auth_ref` |
| `schedule_trigger` | `cron` lub `every`, `start_at`, `end_at`, `timezone` |
| `event_trigger` | `source`, `eventType`, `filter` (JQ) |

Mapper RF wykrywa pierwszy node bez incoming edges i odkłada go do `metadata.weaver.trigger`.

## Pełen przykład

```json
{
  "document": { "dsl": "1.0.0", "namespace": "demo", "name": "send_welcome", "version": "1" },
  "input": { "schema": "#/components/Input" },
  "use": {
    "functions": {
      "send_email": {
        "name": "send_email", "type": "weaver_tool",
        "module": "activities.tools.gmail", "operation": "send_email",
        "errors": [
          { "type": "ValidationError", "is_base": true, "retryable": false },
          { "type": "GmailQuotaExceeded", "retryable": true }
        ],
        "defaultRetryProfile": "default_retry",
        "defaultTimeoutProfile": "default_timeout"
      }
    },
    "retries": {
      "default_retry": {
        "delay": "PT1S",
        "backoff": { "exponential": { "multiplier": 2.0 } },
        "limit": { "attempt": { "count": 3 } },
        "nonRetryableTypes": ["ValidationError"]
      }
    },
    "timeouts": {
      "default_timeout": {
        "after": "PT5M",
        "metadata": { "temporal": { "heartbeat": "PT30S" } }
      }
    }
  },
  "do": [
    { "send_welcome": {
        "call": "send_email",
        "with": { "to": ".input.email", "subject": "Witaj" },
        "timeout": "default_timeout",
        "retries": "default_retry"
    } }
  ],
  "metadata": {
    "weaver": { "trigger": { "type": "manual_trigger" } },
    "temporal": { "workflow_run_timeout": "PT1H" }
  }
}
```

## Reguły walidacji

Walidator IR (`validator/`, decyzja #16) sprawdza 6 kategorii: A (struktura grafu), B (handles/edges), C (registry funkcji), D (schemy/typy), E (polityki Temporala), F (CNCF SW spec compliance).

Severity: `error` blokuje publish; `warning` notyfikacja.

## Versioning IR

`document.dsl` pinuje wersję CNCF SW spec. Migracja do nowszej wersji spec = bump pola + migration script (poza MVP).

## Generowanie schematu

```bash
uv run python -m scripts.export_ir_schema
```

Idempotentne; CI sprawdza brak diff-u (`PIPELINE.md` — codegen idempotency check).

## Powiązane dokumenty

- `ARCHITECTURE.md` — pipeline overview
- `PIPELINE.md` — drzewo zdarzeń edycja → produkcja
- `WORKFLOW_RULES.md` — sandbox restrictions w generated `.py`
- `ACTIVITY_CATALOG.md` — format manifestu Tools / Specialized Agents / errors
- `adr/ADR-004-cncf-sw-ir-as-contract.md`
- `schemas/ir.schema.json` — auto-generated JSON Schema
- `ir/` — Pydantic source of truth
