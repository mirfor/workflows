# Plan dokumentacji projektu

**Cel:** Workflow platform na Temporal — React Flow / BPMN.io → IR → Python → Temporal worker.

**Status:** Plan inicjalny. Aktualizujemy w miarę postępów.

**Ostatnia aktualizacja:** 2026-05-09

---

## Struktura katalogów

Cała dokumentacja żyje w `docs/`. Wszystkie ścieżki w tym planie są relatywne do `docs/`.

```
workflows/
├── CLAUDE.md                       (config Claude Code, w roocie)
└── docs/
    ├── DOCS_PLAN.md                (ten plik)
    ├── ARCHITECTURE.md
    ├── PIPELINE.md
    ├── DEPLOYMENT.md
    ├── SECURITY.md
    ├── OBSERVABILITY.md
    ├── USER_GUIDE.md
    ├── USER_ERROR_CATALOG.md
    ├── CONTRIBUTING.md
    ├── DEV_SETUP.md
    ├── README.md
    ├── ACTIVITY_CATALOG.md
    ├── WORKFLOW_RULES.md
    ├── IR_SPEC.md
    ├── adr/
    │   ├── ADR-001-python-over-dsl.md
    │   ├── ADR-002-source-of-truth-ui.md
    │   ├── ADR-003-runner-vs-physical-py.md
    │   ├── ADR-004-ir-as-contract.md
    │   ├── ADR-005-worker-versioning.md
    │   └── ADR-006-preview-isolation.md
    ├── codegen/
    │   ├── REACTFLOW_TO_IR.md
    │   ├── BPMN_TO_IR.md
    │   ├── IR_TO_PYTHON.md
    │   └── templates/
    │       ├── workflow.py.j2
    │       ├── activity_step.py.j2
    │       ├── signal_wait.py.j2
    │       └── conditional.py.j2
    ├── schemas/
    │   └── ir.schema.json
    ├── prompts/
    │   ├── system_generate_ir.md
    │   ├── system_repair.md
    │   ├── eval_set.md
    │   └── CHANGELOG.md
    └── runbooks/
        └── (pliki rosną organicznie)
```

---

## Legenda

- [ ] do zrobienia
- [~] w trakcie / draft
- [x] gotowe (wymaga review co kwartał)
- [?] zablokowane — czeka na decyzję / odpowiedź na pytanie

---

## Warstwa 1: Fundament architektoniczny

> Bez tego nie ruszamy z kodem. Pisane raz, zmieniane przez ADR.

- [ ] **`ARCHITECTURE.md`** — overview, max 5 stron
  - diagram pipeline'u (UI → IR → codegen → worker → Temporal)
  - granica platforma vs definicje workflow
  - preview vs production split
  - model wersjonowania
  - **zależności:** decyzje z ADR-001..006

- [ ] **`adr/ADR-001-python-over-dsl.md`** — decyzja: Python zamiast własnego DSL
  - decyzja **już podjęta** w rozmowie, zostaje tylko spisać
  - **najłatwiejszy do napisania pierwszego**

- [?] **`adr/ADR-002-source-of-truth-ui.md`** — React Flow vs BPMN.io jako source of truth
  - **BLOKER:** czeka na decyzję (pytanie 1 poniżej)

- [?] **`adr/ADR-003-runner-vs-physical-py.md`** — GenericWorkflowRunner czy fizyczny .py per workflow
  - **BLOKER:** czeka na decyzję (pytanie 2 poniżej)

- [ ] **`adr/ADR-004-ir-as-contract.md`** — IR jako kontrakt UI ↔ generator
  - decyzja przesądzona w rozmowie

- [ ] **`adr/ADR-005-worker-versioning.md`** — strategia Worker Versioning Temporala
  - wymaga research konkretnej wersji Temporal SDK używanej w projekcie

- [ ] **`adr/ADR-006-preview-isolation.md`** — model izolacji sandboxa preview
  - **zależy od:** decyzji o tenancy (pytanie 3)

---

## Warstwa 2: Kontrakty (źródło prawdy dla kodu)

> Najważniejsza warstwa techniczna. IR_SPEC jest fundamentem wszystkiego.

- [?] **`IR_SPEC.md`** + **`schemas/ir.schema.json`** — struktura IR
  - JSON Schema, typy kroków, reguły walidacji, wersjonowanie IR
  - **BLOKER:** czeka na listę typów kroków (pytanie 4)

- [?] **`codegen/REACTFLOW_TO_IR.md`** — transformacja UI → IR
  - mapowanie typów node'ów, reguły topologii, błędy walidacji
  - **zależy od:** ADR-002, IR_SPEC

- [?] **`codegen/BPMN_TO_IR.md`** — transformacja BPMN.io → IR
  - jeśli BPMN.io zostaje w architekturze
  - **zależy od:** ADR-002

- [?] **`codegen/IR_TO_PYTHON.md`** — generator kodu z IR
  - mapowanie IR → Temporal Python SDK, szablony, walidacja
  - **zależy od:** ADR-003, IR_SPEC, WORKFLOW_RULES

- [ ] **`codegen/templates/`** — szablony Jinja2 (lub równoważne)
  - `workflow.py.j2`, `activity_step.py.j2`, `signal_wait.py.j2`, `conditional.py.j2`
  - **zależy od:** IR_TO_PYTHON

- [?] **`ACTIVITY_CATALOG.md`** — rejestr klocków biznesowych
  - input/output schema, retry policy, idempotencja
  - **zależy od:** listy istniejących activity (pytanie 5)

- [ ] **`WORKFLOW_RULES.md`** — reglamentacja workflow code
  - lista zakazanych konstrukcji (sandbox restrictions)
  - dozwolone wzorce
  - reguły dla `workflow.patched()`
  - **używany jako system prompt dla LLM!**

---

## Warstwa 3: Pipeline i operacje

- [ ] **`PIPELINE.md`** — drzewko zdarzeń edycja → produkcja
  - preview path, production path, gates, SLO

- [ ] **`DEPLOYMENT.md`** — jak budować i wdrażać workery
  - **zależy od:** decyzji o targecie (pytanie 6)

- [ ] **`runbooks/`** — procedury operacyjne
  - on-call playbooks, typowe incydenty
  - rośnie organicznie, startujemy z 3-4 najczęstszymi

---

## Warstwa 4: Bezpieczeństwo

- [?] **`SECURITY.md`** — threat model + mitygacje
  - sandbox isolation, tenant isolation, LLM safety
  - **zależy od:** tenancy model (pytanie 3)

---

## Warstwa 5: LLM specifics

- [ ] **`prompts/system_generate_ir.md`** — system prompt dla generacji IR
- [ ] **`prompts/system_repair.md`** — system prompt dla repair loop
- [ ] **`prompts/eval_set.md`** — zestaw regresyjny "trudnych" workflow
- [ ] **`prompts/CHANGELOG.md`** — wersjonowanie promptów

---

## Warstwa 6: Monitoring

- [ ] **`OBSERVABILITY.md`**
  - Search Attributes (lista, semantyka, ownership)
  - custom metryki kroków
  - dashboardy
  - format logów

---

## Warstwa 7: User-facing

- [ ] **`USER_GUIDE.md`** — jak budować workflow w UI (dla nietechnicznego usera)
- [ ] **`USER_ERROR_CATALOG.md`** — mapowanie błędów technicznych → komunikatów biznesowych

---

## Warstwa 8: Dev experience

- [ ] **`CONTRIBUTING.md`** — jak współpracować, code style, review
- [ ] **`DEV_SETUP.md`** — postawienie lokalnego środowiska
  - lokalny Temporal, sandbox worker, sample workflow
- [ ] **`README.md`** — entry point projektu

---

## Sugerowana kolejność pisania

1. **`ADR-001`** ← trywialne, decyzja podjęta, rozgrzewka
2. **Odpowiedzi na pytania blokujące** (1, 2, 3, 4 poniżej)
3. **`ADR-002`, `ADR-003`** ← po odpowiedziach
4. **`ARCHITECTURE.md`** ← gdy ADR-y stoją
5. **`IR_SPEC.md`** + schema ← fundament techniczny
6. **`WORKFLOW_RULES.md`** ← bo bez tego LLM/codegen produkuje śmieci
7. **`codegen/IR_TO_PYTHON.md`** + pierwsze szablony
8. **`codegen/REACTFLOW_TO_IR.md`** (lub BPMN, zależnie od ADR-002)
9. **`PIPELINE.md`**
10. **`SECURITY.md`** ← przed pierwszym preview wystawionym do usera
11. Reszta organicznie

---

## Pytania blokujące (musimy odpowiedzieć przed dalszą pracą)

1. **Source of truth UI:** React Flow czy BPMN.io? Czy oba równorzędnie?
   → blokuje ADR-002, REACTFLOW_TO_IR, BPMN_TO_IR

2. **Model wykonania:** GenericWorkflowRunner interpretujący IR, czy fizyczny `.py` per workflow generowany i deployowany?
   → blokuje ADR-003, IR_TO_PYTHON, cały model deploymentu

3. **Tenancy:** single-tenant (jeden klient), multi-tenant SaaS, czy on-prem per klient?
   → blokuje SECURITY, ADR-006, DEPLOYMENT

4. **Typy kroków workflow:** jakie konstrukcje user może użyć? (activity call, wait_for_signal, timer, branch, parallel, loop, sub-workflow, human task — które?)
   → blokuje IR_SPEC

5. **Stan obecny:** co już istnieje? (działający DSL, jakie activities są zdefiniowane, jaka jest skala obecna)
   → blokuje ACTIVITY_CATALOG, migracja

## Pytania ważne ale nie-blokujące

6. **Target deployment:** Cloud Run, GKE, self-hosted? Temporal Cloud czy własny?
7. **Skala docelowa:** ile workflowów (definicji), ile executions/dzień?
8. **Zespół:** solo, czy więcej devów dołączy? (wpływa na ton dokumentacji)
9. **Audience UI:** kto buduje workflowy — programiści, analitycy biznesowi, użytkownicy końcowi bez tła technicznego?
10. **Język interfejsu:** PL/EN/oba? (ważne dla USER_ERROR_CATALOG i USER_GUIDE)
