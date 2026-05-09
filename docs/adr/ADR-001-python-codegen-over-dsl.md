# ADR-001: Python codegen zamiast własnego DSL / interpretera

**Status:** Accepted
**Data:** 2026-05-09
**Decyzje źródłowe:** #30 (`docs/SESSION_STATE.md`)

## Kontekst

- Projekt = migracja z istniejącego DSL na architekturę Temporal-native.
- Pipeline docelowy: React Flow JSON → CNCF Serverless Workflow 1.0 IR → generated `.py` → Temporal Worker.
- Utrzymanie interpretera IR oznaczałoby kontynuację modelu DSL, którego projekt się pozbywa.
- Temporal SDK wymaga deterministycznego kodu workflow w Pythonie; warstwa interpretacji dokłada własny model wykonania ponad SDK.
- Skala long-tail: tysiące Blueprintów per tenant, wymagana izolacja wersji i deploy bez rebuildu całego Workera.

## Decyzja

Wykonanie Blueprintów odbywa się wyłącznie przez kompilację CNCF SW IR do pliku `.py` per Blueprint × wersja. Worker importuje wygenerowane moduły na startup. Interpreter IR oraz model hybrydowy są wykluczone.

## Rozważone alternatywy

| Opcja | Opis | Dlaczego nie |
|---|---|---|
| A. Interpreter IR w runtime | Worker ładuje IR i wykonuje krok po kroku | Powrót do modelu DSL; własny silnik wykonania duplikuje Temporal SDK; trudniejszy determinizm i replay; gorszy debugging (brak stack trace w kodzie domeny) |
| B. Codegen do `.py` (wybrana) | IR → plik `.py` per Blueprint × wersja, import na startup | — |
| C. Hybryda codegen + interpreter dla long-tail | Kompilacja gorących Blueprintów, interpretacja zimnych | Utrzymanie dwóch modeli wykonania; interpreter ponownie staje się DSL-em; problem skali rozwiązywalny bez niego |

## Konsekwencje

### Pozytywne

- Jeden model wykonania, jeden ścieżka debugowania (Python stack trace = kod Blueprintu).
- Kod workflow jest standardowym Temporal Python SDK — pełne wsparcie replay, versioning, testów.
- Wersjonowanie Blueprintu = wersjonowanie artefaktu `.py`; deterministyczny build hash.
- Brak własnego silnika do utrzymania.

### Trade-offs

- Każda zmiana Blueprintu wymaga regeneracji `.py` i redeployu Workera (lub Worker Versioning).
- Rejestr Blueprintów rośnie liniowo z liczbą wersji × tenantów; potrzebna strategia partycjonowania.
- Zmiana semantyki codegen wymaga rekompilacji wszystkich aktywnych Blueprintów.

### Follow-up

- Skala long-tail rozwiązywana przez per-tenant Worker partitioning lub Temporal Worker Versioning — patrz ADR osobne.
- ADR-003 definiuje layout artefaktu `.py` per Blueprint × wersja.
- ADR-004 ustala CNCF SW IR jako kontrakt wejściowy codegen.
- Wymagany pipeline CI: walidacja IR → codegen → testy determinizmu → publikacja artefaktu.

## Referencje

- `docs/SESSION_STATE.md` #30
- ADR-003 (compiled `.py` per Blueprint), ADR-004 (CNCF SW IR jako kontrakt) — powiązane
