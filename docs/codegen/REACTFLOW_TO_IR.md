# REACTFLOW_TO_IR

Specyfikacja deterministycznej transformacji React Flow JSON → CNCF SW IR JSON, realizowanej przez `mapper/reactflow_to_cncfsw.py`.

## 1. Struktura React Flow JSON

| Pole | Typ | Opis |
|---|---|---|
| `nodes[]` | array | Lista węzłów grafu |
| `edges[]` | array | Lista krawędzi |
| `viewport` | object | Stan kamery (ignorowany przez mapper) |

Node:

| Pole | Wymagane | Opis |
|---|---|---|
| `id` | tak | Unikalny identyfikator |
| `type` | tak | Typ węzła (patrz §2) |
| `data` | tak | Pola specyficzne dla task type |
| `parentNode` | nie | ID kontenera (`for`, `try`) |

Edge:

| Pole | Wymagane | Opis |
|---|---|---|
| `id` | tak | Unikalny identyfikator |
| `source` | tak | ID node źródłowego |
| `target` | tak | ID node docelowego |
| `sourceHandle` | nie | Nazwa portu wyjściowego |
| `targetHandle` | nie | Nazwa portu wejściowego |

## 2. Konwencje nazewnictwa

- Node `id` → `node_id` w IR (nazwa task w `do[]`).
- `data` mapowane bezpośrednio na pola Task danego typu.

Dozwolone wartości `node.type`:

```
manual_trigger, webhook_trigger, schedule_trigger, event_trigger,
call, switch, fork, try, for, wait, listen, emit, raise, run, set, do
```

## 3. Trigger (decyzja #10)

- Trigger node = node z `incoming_edges == 0`.
- Walidator wymusza dokładnie 1 trigger node (0 dopuszczalne tylko dla draft/test).
- Trigger przenoszony do `metadata.weaver.trigger`; nie pojawia się w `do[]`.

## 4. Mapping węzłów na task types

| RF `node.type` | CNCF SW Task | Pola `data` → Task |
|---|---|---|
| `manual_trigger` | `ManualTrigger` (metadata) | `description` |
| `webhook_trigger` | `WebhookTrigger` (metadata) | `path`, `method`, `auth` |
| `schedule_trigger` | `ScheduleTrigger` (metadata) | `cron`, `timezone` |
| `event_trigger` | `EventTrigger` (metadata) | `source`, `type`, `filter` |
| `call` | `CallTask` | `function`, `with`, `output` |
| `switch` | `SwitchTask` | `cases[]` (z handles) |
| `fork` | `ForkTask` | `branches[]` (z handles) |
| `try` | `TryTask` | `try.do`, `catch[]`, `retry` |
| `for` | `ForTask` | `each`, `in`, `do` |
| `wait` | `WaitTask` | `duration` lub `until` |
| `listen` | `ListenTask` | `to.events[]` |
| `emit` | `EmitTask` | `event.type`, `event.data` |
| `raise` | `RaiseTask` | `error.type`, `error.message` |
| `run` | `RunTask` | `script` lub `container` |
| `set` | `SetTask` | `variables` (dict) |
| `do` | `DoTask` | `do[]` (sub-sekwencja) |

## 5. Mapping krawędzi (decyzja #9)

### 5.1 Atomowe sekwencje

- Dotyczy `call`, `wait`, `emit`, `raise`, `run`, `set`.
- Domyślne handles: `out` (source), `in` (target).
- Sekwencja flat → kolejne wpisy w `do[]`.

### 5.2 Switch

- Multi outgoing edges.
- `sourceHandle = "case_<id>"` lub `"default"`.
- Każda case → wpis w `cases[]` z `then: <target_node_id>`.

### 5.3 Fork

- Multi outgoing edges.
- `sourceHandle = "branch_<n>"`.
- Każdy branch zaczyna się od konkretnego node (target edge).

### 5.4 Listen

- Multi outgoing edges.
- `sourceHandle = "event_<id>"`.

### 5.5 Container nodes (`for`, `try`)

- Body = wszystkie node z `parentNode == <container_id>`.
- Topologia wewnętrzna kompilowana rekurencyjnie do `do[]` kontenera.

### 5.6 Try handles

| Handle | Znaczenie |
|---|---|
| `main` | Sukces (do `try.do`) |
| `catch_<error_type>` | Handler dla danego typu błędu |

## 6. Multi-catch UI helper (decyzja #25)

UI prezentuje wiele catch blocks w tabeli; mapper kompiluje je do pojedynczego CNCF SW `catch` z `switch` task wewnątrz `catch.do`, matchującego po `error.type`.

Algorytm:

1. Dla try node z >1 catch blocks zbierz pary `(error_type, handler_node)`.
2. Generuj synthetyczny `switch` task w `catch.do`.
3. Dla każdej pary: `case` z `when: ".error.type == \"<error_type>\""`, `then: <handler_node>`.
4. Default catch (brak match) → `case` bez `when`.

## 7. Determinizm (decyzja #19)

- Mapper jednokierunkowy: RF → CNCF SW IR.
- Reverse mapping (IR → RF) nie istnieje.
- Persystencja RF JSON obowiązkowa — Blueprint przechowywany w 3 formach (RF JSON, CNCF SW IR JSON, wygenerowany `.py`).

## 8. Walidacja preconditions

Wykonywana przed mappingiem; failure → abort z błędem.

| Reguła | Warunek |
|---|---|
| Trigger count | ∈ {0, 1}; 0 tylko draft/test |
| Reachability | Każdy node reachable z trigger lub jest triggerem |
| Acykliczność | Brak cykli poza body `for`/`try` |
| `parentNode` reference | Wskazuje istniejący container node |
| Switch completeness | Co najmniej `default` lub exhaustive set cases |

## 9. Output

- Pydantic model `Workflow` z `ir/`.
- Serializacja do CNCF SW IR JSON.
- Konsumowany przez walidator IR i generator `.py`.

## 10. Test approach

- Golden files: `tests/mapper/golden/<name>/{reactflow.json,cncf-sw.json}`.
- Identyczny input → identyczny output (byte-equal po normalizacji JSON).
- Test runner: load `reactflow.json`, run mapper, compare z `cncf-sw.json`.

## 11. Referencje

| Źródło | Zakres |
|---|---|
| `docs/SESSION_STATE.md` | Decyzje #1, #2, #9, #10, #19, #25 |
| `docs/ARCHITECTURE.md` | Trzy formy Blueprintu |
| `docs/IR_SPEC.md` | Pydantic models target |
| ADR-002 | React Flow jako source of truth |
| ADR-004 | CNCF SW IR jako kontrakt |
| `mapper/reactflow_to_cncfsw.py` | Implementacja |
