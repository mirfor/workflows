# ADR-004: CNCF Serverless Workflow 1.0 IR jako kontrakt UI ↔ codegen

**Status:** Accepted
**Data:** 2026-05-09
**Decyzje źródłowe:** #5, #6, #19 (`docs/SESSION_STATE.md`)

## Kontekst
- Pipeline wymaga jednoznacznej formy semantycznej między edytorem (React Flow) a generatorem Python.
- Własny IR oznacza utrzymanie specyfikacji, walidatora, dokumentacji i wersjonowania bez ekosystemu.
- CNCF Serverless Workflow 1.0 dostarcza ustabilizowany model 12 task types, schema JSON, runtime semantykę, expression DSL.
- Standard zewnętrzny otwiera interop z istniejącymi runtime'ami (Synapse, SonataFlow) i narzędziami.
- Alternatywy rozważane: własny IR ad-hoc, BPMN 2.0, Temporal SDK jako bezpośredni model, Argo Workflows DSL.

## Decyzja
CNCF Serverless Workflow 1.0 JSON jest jedyną semantyczną reprezentacją Blueprintu — wire format między walidatorem, generatorem i source hashem; React Flow JSON jest warstwą prezentacji, generated `.py` jest artefaktem runtime.

## Implementacja
- Pydantic v2 models 1:1 z CNCF SW 1.0 schema — typy task, expressions, retry policy, error definitions.
- Walidacja: `model_validate(json)` na wejściu generatora i przy zapisie Blueprintu.
- Codegen konsumuje wyłącznie zwalidowany IR (Pydantic instance), nie React Flow.
- JSON jako wire format między usługami; Pydantic jako reprezentacja in-process.
- Mapper React Flow → CNCF SW deterministyczny i jednokierunkowy w runtime; reverse mapping tylko przy imporcie.

## 12 task types w MVP
| Task type | Rola |
|---|---|
| `call` | wywołanie Tool / Specialized Agent |
| `do` | sekwencja |
| `for` | iteracja |
| `fork` | parallel branches |
| `switch` | warunkowe rozgałęzienie |
| `try` | error handling |
| `wait` | pauza |
| `listen` | event subscription |
| `emit` | event publication |
| `raise` | error throw |
| `run` | external script/process |
| `set` | mutacja kontekstu |

## Rola IR w pipeline
| Konsumer | Cel |
|---|---|
| Walidator | sprawdzenie reguł (6 kategorii — patrz #16) |
| Generator | codegen IR → `.py` (Python AST) |
| Source hash | idempotency dla generatora |
| UI palette | wyznaczanie dostępnych task types/atrybutów |

## Rozważone alternatywy
| Opcja | Opis | Dlaczego nie |
|---|---|---|
| Własny IR ad-hoc | Schemat dopasowany do projektu | Koszt utrzymania spec/walidator/docs; brak ekosystemu |
| BPMN 2.0 | XML, model procesowy | Zbyt szeroki, ciężki XML, semantyka zorientowana na procesy biznesowe nie task graph |
| Temporal SDK jako model | Workflow Python jako źródło | Brak warstwy deklaratywnej dla UI; trudna walidacja statyczna; sprzężenie z runtime |
| Argo Workflows DSL | YAML, K8s-native | Sprzężenie z Kubernetes; brak event/listen/emit jako first-class |
| AWS Step Functions ASL | JSON, dojrzały | Vendor-locked semantyka; brak modelu agentów/eventów spec'owanego |

## Konsekwencje
### Pozytywne
- Specyfikacja, schema i dokumentacja utrzymywane przez CNCF.
- Możliwość exportu Blueprintu do innych runtime'ów zgodnych ze SW 1.0.
- Pydantic models = jedno źródło typów dla walidatora, generatora, API, testów.
- Source hash stabilny względem reorderowania węzłów w UI (hash z IR, nie z React Flow).

### Trade-offs
- Mapper React Flow → CNCF SW musi obsłużyć każdy task type i jego atrybuty.
- Niektóre konstrukty SW (np. `extensions`) niewykorzystywane w MVP — koszt poznawczy.
- Aktualizacja do SW 1.1+ wymaga migracji modeli i regeneracji `.py`.
- Walidacja po stronie UI ograniczona do podzbioru reguł — pełna walidacja serwerowa.

### Follow-up
- Generator Pydantic models z oficjalnego JSON Schema (skrypt + pin wersji spec).
- Test conformance: round-trip JSON → Pydantic → JSON na korpusie przykładów spec.
- Dokumentacja mapowania React Flow node types → CNCF SW task types (ADR-005 lub doc).
- Polityka wersjonowania IR w Blueprint metadata (`specVersion: "1.0.0"`).

## Referencje
- `docs/SESSION_STATE.md` #5, #6, #19
- ADR-002 (React Flow source of truth), ADR-003 (compiled .py per Blueprint) — powiązane
- CNCF Serverless Workflow 1.0 spec
