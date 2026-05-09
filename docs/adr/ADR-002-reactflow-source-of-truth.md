# ADR-002: React Flow jako source of truth UI

**Status:** Accepted
**Data:** 2026-05-09
**Decyzje źródłowe:** #1, #2, #19 (`docs/SESSION_STATE.md`)

## Kontekst

- Designer wymaga edytora graficznego workflow z persystencją struktury i layoutu.
- Rozważane biblioteki:
  - **BPMN.io** — pełny standard BPMN 2.0, ciężki, narzuca semantykę procesową niezgodną z CNCF SW.
  - **React Flow** — niskopoziomowy graf node/edge, pełna kontrola nodów, integracja z React, custom handles.
  - **Własny editor (SVG/Canvas)** — maksymalna elastyczność, wysoki koszt utrzymania, brak ekosystemu.
- Drivery wyboru:
  - Stack frontend = React (TS).
  - Wymóg custom node types per primitive (Sequence/Branch/Loop/Parallel/WaitSignal).
  - Brak potrzeby zgodności z BPMN.
  - Deterministyczny mapping UI → IR semantyczny.

## Decyzja

- **React Flow** = source of truth warstwy UI Blueprintu.
- Zakres: layout (positions), styling, handles, identyfikatory nodów, struktura grafu w formie React Flow JSON.
- Semantyka workflow nie jest przechowywana w React Flow JSON — żyje w CNCF SW IR (ADR-004).

## Strukturalne ograniczenia primitivów UI

| Primitive    | Rola                                          | Krawędzie wychodzące             |
|--------------|-----------------------------------------------|----------------------------------|
| Sequence     | Liniowa kolejność kroków                      | Strukturalne (parent-child)      |
| Branch       | Rozgałęzienie warunkowe (if/switch)           | Per gałąź, definiowane przez node|
| Loop         | Iteracja (foreach/while)                      | Body + exit                      |
| Parallel     | Wykonanie współbieżne                         | Per gałąź                        |
| WaitSignal   | Oczekiwanie na sygnał zewnętrzny (Temporal)   | Strukturalne                     |

- Brak surowych krawędzi rysowanych przez użytkownika — krawędzie są pochodną zagnieżdżenia primitivów.
- Model analogiczny do **N8N**: użytkownik dokłada bloki do slotów, nie łączy wolno wiszących nodów.
- Walidator odrzuca grafy z krawędziami spoza zdefiniowanych slotów.

## Trzy formy Blueprintu

| Forma                | Zawartość                                                              | Persystencja                                |
|----------------------|------------------------------------------------------------------------|---------------------------------------------|
| 1. React Flow JSON   | UI layer (positions, styling, handles)                                 | DB (Draft + Published) + git po Publish     |
| 2. CNCF SW IR JSON   | Semantyka, source of truth dla source hash + walidator + generator     | DB (Draft + Published) + git po Publish     |
| 3. Generated `.py`   | Runtime (Temporal workflow code)                                       | git (immutable)                             |

- Mapper React Flow JSON → CNCF SW IR JSON jest deterministyczny.
- Z `.py` nie da się odtworzyć form (1) ani (2).
- Persystencja wszystkich trzech form jest obowiązkowa.
- Layout git po Publish: `blueprints/<id>/v<n>/{reactflow.json, cncf-sw.json}` + `generated/workflows/<id>__v<n>.py`.

## Rozważone alternatywy

| Opcja                              | Opis                                                              | Dlaczego nie                                                      |
|------------------------------------|-------------------------------------------------------------------|-------------------------------------------------------------------|
| BPMN.io                            | Standard BPMN 2.0, gotowy editor                                  | Niezgodność semantyczna z CNCF SW; nadmiarowy zakres notacji      |
| Własny editor (SVG/Canvas)         | Pełna kontrola renderowania                                       | Wysoki koszt budowy i utrzymania; brak ekosystemu pluginów        |
| Cytoscape.js / dagre standalone    | Renderowanie grafów                                               | Brak modelu interakcji edycyjnej; wymagałby własnego UI layer     |
| CNCF SW IR jako jedyny artefakt UI | Edycja bezpośrednio na IR, layout liczony deterministycznie       | Utrata pozycji ręcznych użytkownika; gorszy UX                    |
| `.py` jako source of truth         | Generowanie UI z kodu Pythona                                     | Brak odwracalności; utrata layoutu i metadanych UI                |

## Konsekwencje

### Pozytywne

- Pełna kontrola nad custom node types per primitive.
- Layout zachowany 1:1 między edycjami (pozycje, styling).
- Niezależność warstwy UI od ewolucji semantyki IR.
- Walidacja strukturalna na poziomie UI przed mapowaniem do IR.

### Trade-offs

- Dwa artefakty Draft/Published do utrzymania spójności (RF JSON + IR JSON).
- Mapper RF → IR wymaga testów regresyjnych przy każdej zmianie schematu nodów.
- React Flow JSON nie jest standardem branżowym — lock-in na bibliotekę.

### Follow-up

- ADR-004: definicja CNCF SW IR jako kontraktu między mapperem a generatorem.
- Specyfikacja schematu nodów React Flow per primitive.
- Strategia migracji wersji schematu RF JSON dla istniejących Blueprintów.
- Definicja source hash liczonego z IR JSON (nie z RF JSON).

## Referencje

- `docs/SESSION_STATE.md` #1, #2, #19
- ADR-004 (CNCF SW IR jako kontrakt) — powiązane
