# CONTRIBUTING

## 1. Workflow contribution

- **Pierwszy krok przy modyfikacji**: zidentyfikuj który compliance test w `tests/test_compliance.py` jest dotknięty (mapping w `docs/COMPLIANCE.md`).
- Jeśli zmiana dodaje nowe wymaganie / decyzję: **najpierw dodaj test**, potem implementację.
- Jeśli implementuje pending decyzję: zdejmij `xfail` marker po implementacji + passing assertion.
- Fork repozytorium lub utwórz branch z `main`: `feat/<slug>`, `fix/<slug>`, `docs/<slug>`, `refactor/<slug>`.
- Commit messages: [Conventional Commits](https://www.conventionalcommits.org/) — `<type>(<scope>): <subject>`.
- Dozwolone typy: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `build`, `ci`.
- Pull Request:
  - Tytuł = pierwsza linia commit message.
  - Opis: kontekst, zakres zmian, linki do ADR/Issue.
  - CI musi przejść (lint, typecheck, testy, compliance).
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
uv run ruff check && uv run ruff format --check && \
uv run pytest tests/test_compliance.py && \
uv run pytest && \
uv run mypy mapper validator generator activities scripts
```

- Wszystkie kroki muszą zwrócić exit code 0 przed push.
- `compliance` uruchamiany jako separate run aby był explicit.
- Identyczny zestaw uruchamiany w CI.

## 4a. Compliance-first workflow

- 30 decyzji #1–#30 (`docs/SESSION_STATE.md`) → 1 compliance test każda + dodatkowe testy `F3.E.1`, `F5`.
- PR review — pierwsze pytanie reviewera: który compliance test się zmienił z `xfail` → `pass`?
- CI gate `compliance` blokuje merge gdy któryś test fail bez markeru `xfail`.
- Code review checklist:
  - [ ] Compliance test passing (lub explicitly `xfail` z `reason`).
  - [ ] Multi-tenant aware? Sprawdź `--tenant` arg.
  - [ ] Per-Tenant paths poprawne (`blueprints/<tenant>/...`, `generated/<tenant>/...`).
  - [ ] No hardcoded values w cascade defaults.

## 5. Modyfikacje IR (CNCF SW models w `ir/`)

- Każda zmiana modeli IR jest breaking dla `mapper/`, `validator/`, `generator/`.
- Wymagania:
  - ADR w `docs/adr/` jeśli zmiana semantyczna.
  - Regeneracja `schemas/ir.schema.json` przez `uv run python -m scripts.export_ir_schema`.
  - Idempotency check schematu w CI.
  - Migration plan jeśli zmiana łamie istniejące Blueprinty (skrypt migracji + test na fixture'ach).
- Każde nowe pole w Pydantic IR → odpowiadająca asercja w compliance test (np. nowy retry policy field → test #21).
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
- Update `tests/test_compliance.py` jeśli Tool dodaje custom error type → test #23 powinien akceptować nowy typ.

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
- Każda zmiana w `_build_*` per task type: smoke test w `test_decision_06` (assert że `"not yet implemented"` nie pojawia się w output).
- Replay test (post-MVP) sprawdza determinizm.

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

## 12. Multi-tenant guidelines

- Każdy nowy script / CLI ma `--tenant` arg (lub explicit dokumentacja dlaczego nie).
- Bulk operations: zawsze również wariant per-Tenant.
- Compliance test wymagany dla każdej zmiany struktury katalogów dotykającej `blueprints/` lub `generated/`.

## 13. Powiązane dokumenty

| Dokument | Zakres |
|---|---|
| `docs/DEV_SETUP.md` | Lokalne setup, dependencies, uv |
| `docs/ARCHITECTURE.md` | Overview systemu |
| `docs/WORKFLOW_RULES.md` | Sandbox restrictions dla generated workflows |
| `docs/IR_SPEC.md` | Specyfikacja IR (CNCF SW) |
| `docs/ACTIVITY_CATALOG.md` | Katalog Activity / Tool / Specialized Agent |
| `docs/SESSION_STATE.md` | Historyczne decyzje, stan migracji |
| `docs/adr/` | Architecture Decision Records |
