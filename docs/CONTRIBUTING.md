# CONTRIBUTING

## 1. Workflow contribution

- Fork repozytorium lub utwórz branch z `main`: `feat/<slug>`, `fix/<slug>`, `docs/<slug>`, `refactor/<slug>`.
- Commit messages: [Conventional Commits](https://www.conventionalcommits.org/) — `<type>(<scope>): <subject>`.
- Dozwolone typy: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `build`, `ci`.
- Pull Request:
  - Tytuł = pierwsza linia commit message.
  - Opis: kontekst, zakres zmian, linki do ADR/Issue.
  - CI musi przejść (lint, typecheck, testy).
  - Wymagany review przez minimum 1 reviewera.
  - Squash merge do `main`.

## 2. Code style (Python)

| Narzędzie | Zakres | Konfiguracja |
|---|---|---|
| `ruff check` | lint | `pyproject.toml` |
| `ruff format` | format manualnego kodu | line-length 100 |
| `mypy` | strict mode | `pyproject.toml` |
| `black` | formatowanie wyłącznie `generated/workflows/*.py` | wywoływany przez generator |

- `black` nie jest stosowany do kodu manualnego.
- Type hints obowiązkowe dla wszystkich publicznych funkcji, metod i atrybutów dataclass.
- Domyślne style: `from __future__ import annotations`, `pathlib.Path`, immutable dataclasses gdzie możliwe.

## 3. Test policy

- Każdy moduł `mapper/`, `validator/`, `generator/` posiada testy w `tests/test_<module>_*.py`.
- Coverage cel: 80% dla nowego kodu (delta coverage).
- Idempotency tests dla codegen + manifest: regenerate → byte-identical output.
- Replay tests dla generatora: post-MVP, faza F5.
- Testy zewnętrznych integracji używają mocków; brak realnych wywołań sieciowych w CI.

## 4. Pre-commit checks

```bash
uv run ruff check && \
uv run ruff format --check && \
uv run pytest && \
uv run mypy mapper validator generator activities scripts
```

- Wszystkie cztery kroki muszą zwrócić exit code 0 przed push.
- Identyczny zestaw uruchamiany w CI.

## 5. Modyfikacje IR (CNCF SW models w `ir/`)

- Każda zmiana modeli IR jest breaking dla `mapper/`, `validator/`, `generator/`.
- Wymagania:
  - ADR w `docs/adr/` jeśli zmiana semantyczna.
  - Regeneracja `schemas/ir.schema.json`.
  - Migration plan jeśli zmiana łamie istniejące Blueprinty (skrypt migracji + test na fixture'ach).
- Update `docs/IR_SPEC.md` w tym samym PR.

## 6. Dodawanie nowego Tool

- Plik: `activities/tools/<integration>.py`.
- Zawartość:
  - Funkcja z dekoratorem `@activity.defn`.
  - Stała `TOOL_MANIFEST: dict` z polami: `name`, `operation`, `input_schema`, `output_schema`, `errors[]`, `idempotent`.
- Pydantic models dla input/output (decyzja #13).
- Errors deklarowane jawnie (decyzja #23) — każdy typ błędu z kodem i opisem.
- Test: `tests/test_<tool>.py`, mock zewnętrznych wywołań.
- Regeneracja manifestu: `uv run python -m scripts.build_manifest`.
- Update `docs/ACTIVITY_CATALOG.md`.

## 7. Dodawanie nowego Specialized Agent

- Wpis w `activities/specialized_agents.json`:
  - `name`, `endpoint_url`, `operation`, `openapi_url`, `errors[]`.
- `scripts/build_manifest.py` pobiera OpenAPI automatycznie.
- Generic dispatcher `call_specialized_agent` obsługuje runtime — kod Python per-agent nie jest potrzebny.
- Test: kontraktowy na podstawie pobranego OpenAPI (mock HTTP).

## 8. Modyfikacje generatora (`generator/codegen.py`)

Każda zmiana mapowania `task type → Python` wymaga:

- Update `docs/codegen/IR_TO_PYTHON.md`.
- Update testów `tests/test_generator_basic.py`.
- Sprawdzenie idempotency: regenerate → byte-identical output.
- Replay test (post-MVP).

Generator emituje wyłącznie konstrukcje zgodne z Workflow Sandbox — patrz `docs/WORKFLOW_RULES.md`.

## 9. Modyfikacje walidatora

- Reguły mają deterministic kody: `A001`, `E102`, ... — patrz `validator/validator.py`.
- Severity:
  - `error` — blokuje publish Blueprintu.
  - `warning` — notyfikacja, nie blokuje.
- Każda nowa reguła:
  - Nowy unikalny kod.
  - Test pozytywny i negatywny.
  - Wpis w dokumentacji walidatora.

## 10. Decyzje projektowe

- Przed implementacją zmiany architektonicznej → ADR w `docs/adr/ADR-<NNN>-<slug>.md`.
- Format ADR:
  - Kontekst.
  - Decyzja.
  - Rozważone alternatywy.
  - Konsekwencje.
- 30 historycznych decyzji udokumentowanych w `docs/SESSION_STATE.md`.
- Nowe ADR numerowane sekwencyjnie od ostatniego istniejącego.

## 11. Dokumentacja

- Każda zmiana publicznego API = update odpowiedniego dokumentu:
  - IR → `docs/IR_SPEC.md`.
  - Activity / Tool → `docs/ACTIVITY_CATALOG.md`.
  - Sandbox / generator → `docs/WORKFLOW_RULES.md`.
- Styl: technical reference (`CLAUDE.md`) — info-dense, bez fillera, bullet listy i tabele preferowane.

## 12. Powiązane dokumenty

| Dokument | Zakres |
|---|---|
| `docs/DEV_SETUP.md` | Lokalne setup, dependencies, uv |
| `docs/ARCHITECTURE.md` | Overview systemu |
| `docs/WORKFLOW_RULES.md` | Sandbox restrictions dla generated workflows |
| `docs/IR_SPEC.md` | Specyfikacja IR (CNCF SW) |
| `docs/ACTIVITY_CATALOG.md` | Katalog Activity / Tool / Specialized Agent |
| `docs/SESSION_STATE.md` | Historyczne decyzje, stan migracji |
| `docs/adr/` | Architecture Decision Records |
