# DEV_SETUP

Lokalne środowisko deweloperskie Workflow Platform Temporal.

## 1. Wymagania

| Narzędzie | Wersja | Cel |
|-----------|--------|-----|
| Python | ≥ 3.12 | runtime worker, generator, testy |
| `uv` | aktualna | package + venv manager |
| Docker | aktualna | lokalny Temporal Server (alternatywa) |
| `temporal` CLI | opcjonalnie | `temporal server start-dev` |
| `jq` / `libjq-dev` | systemowo | dependency dla `pyjq` |

## 2. Repo setup

```bash
git clone <repo>
cd workflows
uv sync --all-extras
```

`uv sync` tworzy `.venv/` i instaluje extras: `dev`, `test`, `codegen`.

## 3. Lokalny Temporal Server

### 3.1 Wariant A — `temporal` CLI (rekomendowany)

```bash
temporal server start-dev --port 7233 --ui-port 8233
# Stwórz namespace per Tenant
temporal operator namespace create demo --address localhost:7233
temporal operator namespace create acme --address localhost:7233
```

| Endpoint | Port | Protokół |
|----------|------|----------|
| Frontend gRPC | 7233 | gRPC |
| Web UI | 8233 | HTTP |

Namespace = `tenant_id` (decyzja #4 — fizyczna izolacja per Tenant).

### 3.2 Wariant B — Docker

```bash
docker run --rm -p 7233:7233 -p 8233:8233 \
  temporalio/auto-setup:latest
```

Lub `docker compose up` z `docker-compose.yml` w root repo (jeśli obecny).

## 4. Build manifestu activity

```bash
uv run python -m scripts.build_manifest
```

Generuje `generated/manifest.json` z deklaracji activity w `activities/`.

## 5. Generowanie sample Blueprint

Wejście: `blueprints/<tenant>/<blueprint>/<version>/reactflow.json`.

```bash
# Pojedynczy
uv run python -m scripts.regenerate_workflow blueprints/demo/sample/v1/reactflow.json

# Bulk — wszystkie Tenanty / wszystkie Blueprinty
uv run python -m scripts.regenerate_all
uv run python -m scripts.regenerate_all --tenant demo
uv run python -m scripts.regenerate_all --tenant demo --blueprint sample

# Walidacja (bez generacji `.py`)
uv run python -m scripts.validate_all
uv run python -m scripts.validate_all --tenant demo --strict
```

Wyjście: `blueprints/<tenant>/<blueprint>/<version>/ir.json` + `workflow.py`; manifest per Tenant w `generated/<tenant>/manifest.json`.

## 6. Worker

```bash
# Worker per Tenant (osobny namespace = tenant_id, task queue = weaver-<tenant>)
uv run python worker.py --tenant demo --target localhost:7233 &
uv run python worker.py --tenant acme --target localhost:7233 &
```

`--tenant` jest **wymagany** (decyzja #4 — fizyczna izolacja). Worker rejestruje workflow z `generated/<tenant>/manifest.json` (`active_version`) oraz activity z `activities/`; łączy się do namespace = `<tenant>` i task queue = `weaver-<tenant>`.

## 7. Sample Engagement

```python
from temporalio.client import Client
client = await Client.connect("localhost:7233", namespace="demo")
handle = await client.start_workflow(
    "sample", {"tier": "vip"},
    id="my-engagement", task_queue="weaver-demo",
)
result = await handle.result()
```

`namespace` = `tenant_id`; `task_queue` = `weaver-<tenant>`; nazwa workflow = `blueprint_id`.

## 8. Testy i lint

| Komenda | Zakres |
|---------|--------|
| `uv run pytest` | pełen suite |
| `uv run pytest tests/test_mapper_basic.py -v` | pojedynczy moduł |
| `uv run ruff check` | lint |
| `uv run mypy mapper validator generator activities scripts` | type check |

## 9. JSON Schema dla IR

```bash
uv run python -m scripts.export_ir_schema
```

Zapisuje `schemas/ir.schema.json` z modeli Pydantic w `ir/`.

## 10. Codegen idempotency

Po `build_manifest` i `export_ir_schema`:

```bash
git diff --exit-code generated/ schemas/
```

Brak diffu = pass. CI: `.github/workflows/ci.yml` job `codegen-idempotency` powiela tę logikę.

## 11. Pełna walidacja przed push

```bash
uv run ruff check && \
uv run pytest && \
uv run python -m scripts.export_ir_schema && \
uv run python -m scripts.build_manifest && \
git diff --exit-code generated/ schemas/
```

## 12. Compliance check

```bash
uv run pytest tests/test_compliance.py -v   # 34 testów (#1–#30 + F3.E + F5)
```

Każda decyzja projektowa ma assertion test. CI blokuje merge przy fail.

## 13. Częste problemy

| Symptom | Rozwiązanie |
|---------|-------------|
| `pyjq` build error: `libjq` | macOS: `brew install jq`; Debian/Ubuntu: `apt install libjq-dev libonig-dev` |
| `connection refused` na 7233 | sprawdź czy Temporal Server działa; w Dockerze: `--target host.docker.internal:7233` |
| `Workflow not found` | sprawdź `generated/<tenant>/manifest.json` → `active_version`; potwierdź obecność `.py` w `blueprints/<tenant>/<blueprint>/<version>/workflow.py` |
| `mypy` błąd na `generated/` | regeneruj manifest; nie edytuj plików generowanych ręcznie |
| `ruff` błędy w `blueprints/*/workflow.py` | regeneruj — generator emituje formatowanie zgodne z `ruff` |
| `Worker startuje bez workflows` | brak `generated/<tenant>/manifest.json` — uruchom `regenerate_all.py --tenant <id>` |
| `Manifest tenant_id mismatch` | pole `tenant_id` w manifest ≠ argument `--tenant` workera |

## 14. Powiązane dokumenty

| Plik | Zakres |
|------|--------|
| `README.md` | entry point repo |
| `ARCHITECTURE.md` | komponenty, granice modułów |
| `PIPELINE.md` | drzewo zdarzeń edycja → produkcja |
| `WORKFLOW_RULES.md` | restrykcje sandboxa workflow |
| `CONTRIBUTING.md` | code style, proces review |
| `IR_SPEC.md` | specyfikacja IR |
| `ACTIVITY_CATALOG.md` | rejestr activity |
