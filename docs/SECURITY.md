# SECURITY

## 1. Cel

Dokument definiuje threat model i mitygacje dla Workflow Platform Temporal — komponentu wykonawczego Weaver (AI Agent Orchestrator). Zakres: izolacja sandbox (Workflow code), izolacja tenanta i Client Org, bezpieczeństwo LLM (post-MVP), zarządzanie sekretami, walidacja IR, zabezpieczenia CI.

## 2. Threat model

| Zagrożenie | Wektor | Mitygacja |
|---|---|---|
| Cross-tenant data leak | Workflow z Tenant A czyta dane Tenant B | Fizyczna izolacja per Tenant: osobny Temporal namespace + DB (decyzja #4, ADR-006) |
| Cross-org data leak (w obrębie Tenanta) | Workflow Client Org A widzi dane Client Org B | Logiczna izolacja: row-level filter + Search Attribute `client_org_id`; opt-in fizyczny dla regulowanych |
| Złośliwy/błędny generowany kod | `.py` przeszedł walidator ale ma side effects | Workflow Sandbox Temporala (zakazane I/O); `WORKFLOW_RULES.md`; generator emituje wyłącznie bezpieczne konstrukcje; replay test w CI |
| Niedeterminizm w workflow code | `.py` używa `time.sleep()`, `datetime.now()`, network/file I/O | Sandbox blokuje runtime; generator nie emituje takich konstrukcji (decyzja #15); replay test wykrywa |
| Prompt injection (LLM features post-MVP) | LLM-generated IR z malicious payload | Strict walidator IR (6 kategorii reguł); whitelist Tools/Specialized Agents per Tenant; LLM safety polityka (post-MVP) |
| Compromise of secrets | Secrets w plain-text w IR / `.py` | `Use.secrets[]` referuje wpisy w secret store (Vault/Secrets Manager); generator emituje lookup, nie sam secret |
| DOS przez infinite loops | `for`/`while` nie terminuje | Walidator IR sprawdza terminację (best-effort) + Temporal `workflow_run_timeout` (#27) jako last-resort guard |
| Replay attack na webhook trigger | Stary payload odtworzony | Idempotency keys w webhook handler; signature verification (Tool implementation) |
| Manifest tampering | `activities/manifest.json` zmodyfikowany ręcznie | CI idempotency check (regenerate → diff = empty); Git as source of truth |
| Worker credential leak | Worker image zawiera klucze | Workload identity (GCP/AWS) zamiast plaintext credentials; secret rotation |
| Specialized Agent compromise | Złośliwy Agent zwraca zatrutą odpowiedź | OpenAPI schema validation; output_schema wymuszany; allowlist endpoint URL per Tenant |

## 3. Sandbox isolation

- Temporal Workflow Sandbox blokuje: I/O, threading, `time.sleep`, `datetime.now`, `random`.
- Generator emituje wyłącznie whitelist konstrukcji (patrz `WORKFLOW_RULES.md`).
- Activities (poza sandbox) mogą wykonywać I/O — muszą być deterministycznie idempotent (`idempotent` flag w manifest).

## 4. Tenant isolation (decyzja #4, ADR-006)

| Poziom | Zakres | Mechanizm |
|---|---|---|
| Fizyczna | Tenant | Namespace per Tenant + DB per Tenant; brak shared infrastructure |
| Logiczna (default) | Client Org | Row-level filter + Search Attribute `client_org_id` |
| Logiczna → Fizyczna (opt-in) | Client Org regulowany (HIPAA, GDPR, banking) | Dedykowany namespace |

Każde workflow execution ma Search Attributes: `tenant_id`, `client_org_id` (`OBSERVABILITY.md`).

## 5. Secrets management

- `Use.secrets: list[str]` w IR — referencja po nazwie do external store.
- Tool implementation pobiera secret w runtime z Vault/Secrets Manager.
- Generator nie emituje plaintext secret-ów do `.py`.
- Audyt access do secret-ów: log per access wymagany.

## 6. Walidator IR jako gateway (decyzja #16)

- 6 kategorii reguł: A (graf), B (handles), C (registry), D (schemy), E (polityki Temporala), F (spec compliance).
- Severity `error` blokuje publish; brak "force publish".
- Custom error types poza manifestem → blokowane (#23).
- Retry policy z polami bez Temporal mapping → blokowane (#21).

## 7. CI security checks

| Check | Cel |
|---|---|
| Codegen idempotency (regenerate → diff = empty) | Wykrywanie tamperingu manifestu i artefaktów |
| Lint (ruff) | Statyczne reguły stylu i bezpieczeństwa |
| Type (mypy) | Wykrywanie niespójności typów |
| Test (pytest) | Regresja jednostkowa i integracyjna |
| Sandbox compliance (replay test) | Detekcja niedeterminizmu (post-MVP, F5) |
| SBOM / dependency scan (`uv pip audit`) | TODO post-MVP |

## 8. Input validation

- Pydantic models z `extra="forbid"` — odrzuca nieznane pola.
- JSON Schema z `schemas/ir.schema.json` jako wire format guard.
- Manifest functions wymuszają walidację `input_schema` per call (Tool implementation).

## 9. Webhook trigger security

- HMAC signature verification (Tool sprawdza per integration).
- Auth ref (`Use.authentications.<name>`) — Bearer token, OAuth2.
- Rate limiting per webhook (Worker / API gateway).

## 10. LLM safety (post-MVP)

- LLM-generated IR przechodzi pełen walidator + manual review przed publish.
- Prompts versioned w `prompts/CHANGELOG.md`.
- Eval set (`prompts/eval_set.md`) — regresyjne testy "trudnych" workflow.

## 11. Reporting vulnerabilities

| Pole | Wartość |
|---|---|
| Email | security@weaver.example (placeholder) |
| PGP key | TODO |
| SLA ack | < 24h |
| SLA fix (high) | < 30d |

## 12. Powiązane dokumenty

- `ARCHITECTURE.md`
- `PIPELINE.md` — gates, idempotency
- `WORKFLOW_RULES.md` — sandbox restrictions
- `OBSERVABILITY.md` — audit log
- `adr/ADR-006-tenancy-isolation.md`
