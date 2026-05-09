# ACTIVITY_CATALOG

## 1. Cel manifestu

- Single source of truth dla funkcji wywoływanych w workflow `call`.
- Definiuje dostępne **Tools** (lokalne aktywności Pythona) i **Specialized Agents** (zewnętrzne usługi HTTP).
- Każdy wpis zawiera: input/output schema, taksonomię błędów, defaultowe profile retry/timeout.
- Konsumenci: walidator IR, UI palette, generator kodu (`.py`).

## 2. Lokalizacja

| Element | Ścieżka |
|---|---|
| Manifest | `activities/manifest.json` |
| Generator | `scripts/build_manifest.py` |
| Źródła Tools | `activities/tools/<integration>.py` (Pydantic models) |
| Źródła Specialized Agents | external `<endpoint_url>/openapi.json` |

## 3. Struktura JSON

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-05-09T15:00:00Z",
  "tools": [...],
  "specialized_agents": [...],
  "base_errors": [...]
}
```

Top-level pola:

| Pole | Typ | Opis |
|---|---|---|
| `schema_version` | string | Semver manifestu |
| `generated_at` | ISO-8601 UTC | Timestamp regeneracji |
| `tools` | array<ToolSpec> | Lokalne aktywności |
| `specialized_agents` | array<SpecializedAgentSpec> | Zdalne agenty HTTP |
| `base_errors` | array<ErrorSpec> | Zamknięta taksonomia 7 base types |

## 4. Tool spec

| Pole | Typ | Wymagane | Opis |
|---|---|---|---|
| `name` | string | tak | Globalny identyfikator (snake_case) |
| `type` | const `"weaver_tool"` | tak | Dyskryminator |
| `module` | string | tak | Python import path (np. `activities.tools.slack`) |
| `operation` | string | tak | Nazwa funkcji activity |
| `input_schema` | JSON Schema | tak | Eksport z Pydantic `model_json_schema()` |
| `output_schema` | JSON Schema | tak | jw. |
| `errors` | array<ErrorSpec> | tak | Tool-specific + referencje do base |
| `default_retry_profile` | string | nie | Ref do `use.retries.<name>` |
| `default_timeout_profile` | string | nie | Ref do `use.timeouts.<name>` |
| `idempotent` | bool | tak | Wpływa na retry safety |

Przykład:

```json
{
  "name": "slack.post_message",
  "type": "weaver_tool",
  "module": "activities.tools.slack",
  "operation": "post_message",
  "input_schema": {"$ref": "#/components/SlackPostInput"},
  "output_schema": {"$ref": "#/components/SlackPostOutput"},
  "errors": [
    {"type": "RateLimitError", "is_base": true, "retryable": true},
    {"type": "ChannelNotFound", "is_base": false, "retryable": false}
  ],
  "default_retry_profile": "standard",
  "default_timeout_profile": "short",
  "idempotent": false
}
```

## 5. Specialized Agent spec

| Pole | Typ | Wymagane | Opis |
|---|---|---|---|
| `name` | string | tak | Globalny identyfikator |
| `type` | const `"weaver_specialized_agent"` | tak | Dyskryminator |
| `endpoint_url` | URL | tak | Base URL HTTP |
| `openapi_url` | URL | tak | Źródło OpenAPI 3.x |
| `operation` | string | tak | `operationId` z OpenAPI |
| `input_schema` | JSON Schema | tak | Z `requestBody.content.application/json` |
| `output_schema` | JSON Schema | tak | Z `responses.200.content.application/json` |
| `errors` | array<ErrorSpec> | tak | Mapowane z `responses.4xx/5xx` + base |
| `default_retry_profile` | string | nie | jw. |
| `default_timeout_profile` | string | nie | jw. |
| `idempotent` | bool | tak | Z `x-idempotent` extension lub HTTP method |

Przykład:

```json
{
  "name": "doc_classifier.classify",
  "type": "weaver_specialized_agent",
  "endpoint_url": "https://classifier.internal/api",
  "openapi_url": "https://classifier.internal/openapi.json",
  "operation": "classifyDocument",
  "input_schema": {"$ref": "..."},
  "output_schema": {"$ref": "..."},
  "errors": [
    {"type": "ValidationError", "is_base": true, "retryable": false},
    {"type": "ModelOverloaded", "is_base": false, "retryable": true}
  ],
  "idempotent": true
}
```

## 6. ErrorSpec

| Pole | Typ | Wymagane | Opis |
|---|---|---|---|
| `type` | string | tak | Identyfikator (PascalCase) |
| `description` | string | nie | Krótki opis warunku |
| `retryable` | bool | tak | Default; nadpisywalny przez profile retry (#24) |
| `output_schema_ref` | string | nie | JSON Pointer do payload errora |
| `is_base` | bool | tak | `true` jeśli z taksonomii base (sekcja 7) |

## 7. Base error types

| Type | Retryable (default) | Warunek |
|---|---|---|
| `ValidationError` | false | Niepoprawny input |
| `AuthError` | false | Brak/nieważne credentials |
| `RateLimitError` | true | 429 / throttling |
| `TimeoutError` | true | Przekroczony timeout |
| `NotFoundError` | false | Zasób nie istnieje |
| `IntegrationError` | true | 5xx / błąd zewnętrzny |
| `InternalError` | false | Bug w Tool/Agent |

Taksonomia jest **zamknięta** — nowych base types nie dodaje się ad-hoc.

## 8. Build process

`scripts/build_manifest.py`:

1. **Tools**: import modułów `activities/tools/*.py`, introspekcja Pydantic models, eksport `model_json_schema()` dla input/output.
2. **Specialized Agents**: HTTP GET `<endpoint_url>/openapi.json`, parse `paths` (operationId, requestBody, responses) i `components.schemas`.
3. **Cascade resolution** dla `default_timeout_profile` (#28): Tenant → Client Org → Blueprint; manifest zapisuje wartość Blueprint, runtime overlay-uje wyższe poziomy.
4. **Atomic write**: zapis do `activities/manifest.json.tmp`, `os.rename()` na docelową ścieżkę.
5. **Idempotency**: powtórny run bez zmian źródeł → identyczny output (ordered keys, deterministic schema dump).

## 9. Konsumenci

| Konsument | Sposób użycia |
|---|---|
| Walidator IR | `call.with` type-compatible z `input_schema` (#13); `catch.with.type` ∈ (`base_errors` ∪ `tool.errors`) (#23); referowane profile retry/timeout muszą istnieć (#20) |
| UI palette | Dropdown task types z `tools` + `specialized_agents`; autocomplete pól I/O ze schem; dropdown `catch.with.type` filtrowany do błędów wybranego Tool/Agent + base |
| Generator | Dispatch po `type`: `weaver_tool` → import `module.operation` + `workflow.execute_activity`; `weaver_specialized_agent` → `call_specialized_agent(endpoint_url, operation, payload)` |

## 10. Lifecycle

| Trigger | Akcja |
|---|---|
| Dodanie/zmiana Pydantic model w `activities/tools/` | CI: `build_manifest.py` regenerate, commit diff |
| Zmiana OpenAPI w external Specialized Agent | Scheduled job (np. nightly) lub manual trigger; PR z diffem |
| CI gate | `build_manifest.py` → `git diff --exit-code activities/manifest.json` (idempotency check) |

## 11. Versioning

- Pojedyncze pole `schema_version` (semver).
- **Major bump** (breaking): zmiana struktury `ToolSpec` / `ErrorSpec` / wymagane pola → migration step w `scripts/migrations/manifest_<from>_to_<to>.py`.
- **Minor**: nowe opcjonalne pola, kompatybilne wstecz.
- Walidator i generator deklarują obsługiwany zakres `schema_version`.

## 12. Referencje

- ADR-001..006
- `docs/SESSION_STATE.md` decyzje: #7 (Tools vs Specialized Agents), #13 (type compatibility), #18 (palette), #20 (profile retry/timeout), #23 (taksonomia błędów), #24 (override retryable), #28 (cascade resolution Tenant/Client Org/Blueprint)
