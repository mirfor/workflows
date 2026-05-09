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
temporal server start-dev \
  --ui-port 8233 \
  --port 7233 \
  --namespace default
```

| Endpoint | Port | Protokół |
|----------|------|----------|
| Frontend gRPC | 7233 | gRPC |
| Web UI | 8233 | HTTP |

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

Wejście: `blueprints/sample/v1/reactflow.json` (React Flow JSON).

```bash
uv run python -m scripts.regenerate_workflow blueprints/sample/v1/reactflow.json
```

Wyjście: `blueprints/sample/v1/ir.json` + `blueprints/sample/v1/workflow.py`.

Jeśli `regenerate_workflow.py` nie istnieje — wywołać manualnie w REPL:

```python
from mapper import map_reactflow_to_ir
from generator import generate_workflow_py
ir = map_reactflow_to_ir(open("blueprints/sample/v1/reactflow.json").read())
open("blueprints/sample/v1/workflow.py", "w").write(generate_workflow_py(ir))
```

## 6. Worker

```bash
uv run python worker.py \
  --target localhost:7233 \
  --namespace default \
  --task-queue weaver-default
```

Worker rejestruje wszystkie workflow z `generated/manifest.json` (`active_version`) oraz activity z `activities/`.

## 7. Sample Engagement

```python
import asyncio
from temporalio.client import Client

async def main():
    client = await Client.connect("localhost:7233", namespace="default")
    handle = await client.start_workflow(
        "SampleWorkflow",
        {"input": "value"},
        id="engagement-001",
        task_queue="weaver-default",
    )
    print(await handle.result())

asyncio.run(main())
```

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

## 12. Częste problemy

| Symptom | Rozwiązanie |
|---------|-------------|
| `pyjq` build error: `libjq` | macOS: `brew install jq`; Debian/Ubuntu: `apt install libjq-dev libonig-dev` |
| `connection refused` na 7233 | sprawdź czy Temporal Server działa; w Dockerze: `--target host.docker.internal:7233` |
| `Workflow not found` | sprawdź `generated/manifest.json` → `active_version`; potwierdź obecność `.py` w `blueprints/<name>/<version>/workflow.py` |
| `mypy` błąd na `generated/` | regeneruj manifest; nie edytuj plików generowanych ręcznie |
| `ruff` błędy w `blueprints/*/workflow.py` | regeneruj — generator emituje formatowanie zgodne z `ruff` |

## 13. Powiązane dokumenty

| Plik | Zakres |
|------|--------|
| `README.md` | entry point repo |
| `ARCHITECTURE.md` | komponenty, granice modułów |
| `PIPELINE.md` | drzewo zdarzeń edycja → produkcja |
| `WORKFLOW_RULES.md` | restrykcje sandboxa workflow |
| `CONTRIBUTING.md` | code style, proces review |
| `IR_SPEC.md` | specyfikacja IR |
| `ACTIVITY_CATALOG.md` | rejestr activity |
