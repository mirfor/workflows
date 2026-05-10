# Publish Flow — od kliknięcia w Designerze do uruchomionego Engagementu

**Dwa tryby:** lokalny (development, sekundy) i chmurowy (production, minuty). Pełna ścieżka: jak Agent Blueprint zaprojektowany w UI staje się działającym Workerem na Temporalu.

> **Model:** GitOps. Developer pracuje lokalnie → testuje lokalnie → `git push` (świadomy krok). Push triggeruje CI/CD, który buduje obraz workera i deployuje do chmury. **Nie** ma "magicznego publish-via-UI w cloudzie" — dev decyduje kiedy promować zmiany.

## Dwa tryby — porównanie

| Wymiar | **Tryb lokalny (dev)** | **Tryb chmurowy (production)** |
|---|---|---|
| Cel | Szybki dev cycle, smoke test po zmianach | Stabilny deploy z auditem i versioningiem |
| Cykl Publish → działa | **5–10 sekund** | ~5 minut |
| Persistence Blueprintu | Bezpośrednio w lokalnym katalogu (`blueprints/`, `generated/`) | Git commit + push |
| Build / pakowanie | Brak — generator pisze `.py` na dysk | Docker build + push do Artifact Registry |
| Worker | Proces lokalny (`python worker.py`) | Cloud Run service per Tenant |
| Worker Versioning | Brak — restart workera po zmianie | Build ID, rolling deploy bez przerwy |
| Temporal | `temporal server start-dev` lokalnie | Temporal Cloud / self-hosted |
| Co potrzebne | Python 3.12, `uv`, `temporal` CLI, Docker (opcjonalnie dla Sonara) | GCP project, Artifact Registry, Cloud Run, GitHub Actions, Temporal Cloud account |

---

## Tryb lokalny (development) — TL;DR

```mermaid
flowchart LR
    A[Designer<br>localhost:5174] -->|REST POST /publish| B[weaver-core<br>localhost:8000]
    B -->|in-process import| C[Pipeline:<br>mapper / walidator / generator]
    C -->|zapis na dysk| D[blueprints/...<br>generated/...]
    D -->|file watcher / restart| E[worker.py --tenant demo<br>lokalny proces]
    E -->|gRPC| F[Temporal<br>localhost:7233]
    F -.->|task dispatch| E
```

Brak gita, brak CI, brak Cloud Run, brak Build ID. Edycja → publish → restart workera → workflow działa. **5–10 sekund**.

## Tryb chmurowy (production) — TL;DR

```mermaid
flowchart LR
    A[Dev:<br/>lokalny smoke test OK] -->|git add + commit + push| B[GitHub repo]
    B -->|webhook| C[GitHub Actions:<br/>lint / test / compliance]
    C -->|docker build| D[Docker image:<br/>worker.py + generated/...]
    D -->|push| E[Artifact Registry]
    E -->|gcloud run deploy| F[Cloud Run:<br/>Worker per Tenant]
    F -->|register Build ID| G[Temporal Cloud]
    G -.->|nowe Engagementy| F
```

**Cloud flow zaczyna się od `git push`** — czyli świadomej decyzji devu po przejściu lokalnego smoke testu. Nie ma "publish via UI" w cloudzie. ~5 minut od push do "v3 active w Cloud Run".

---

## Tryb lokalny — szczegóły

### Setup raz (one-time)

```bash
# 1. Temporal Server lokalnie (jeden raz, w tle)
temporal server start-dev --port 7233 --ui-port 8233 &

# 2. Stwórz namespace per Tenant (jednorazowo, idempotentne)
temporal operator namespace create demo --address localhost:7233

# 3. Zainstaluj zależności
cd ~/Desktop/workflows && uv sync --all-extras
```

Temporal UI: http://localhost:8233 (możesz tam podglądać Engagementy).

### Dev cycle (powtarzane przy każdej zmianie Agent Blueprintu)

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Dev
    participant FS as Local Filesystem
    participant Pipe as Pipeline lib
    participant Worker as Worker Proces
    participant Temp as Temporal localhost:7233

    Dev->>FS: edytuj blueprints/demo/<id>/v1/reactflow.json<br/>(albo eksport z designera lokalnego)
    Dev->>Pipe: make regen<br/>(uv run python -m scripts.regenerate_all)
    Pipe->>Pipe: mapper RF→IR
    Pipe->>Pipe: walidator (6 kategorii)
    Pipe->>Pipe: generator → Python AST → black
    Pipe->>FS: zapis blueprints/.../cncf-sw.json<br/>+ generated/demo/workflows/<id>__v1.py<br/>+ generated/demo/manifest.json
    Pipe-->>Dev: ✓ regenerate complete

    Note over Dev,Worker: Worker NIE podgląda generated/ w runtime —<br/>moduły wczytuje TYLKO na startup

    Dev->>Worker: pkill -f worker.py<br/>(ubij stary proces)
    Worker-->>Dev: terminated

    Dev->>Worker: uv run python worker.py --tenant demo &<br/>(start nowy proces)
    Worker->>FS: czyta generated/demo/manifest.json
    Worker->>FS: importuje active wersje (importlib)
    Worker->>Temp: register: namespace=demo, queue=weaver-demo
    Worker-->>Dev: "Worker startuje: workflows=N activities=M"

    Dev->>Temp: start_workflow (Python client albo Temporal UI)<br/>name=<id>, input={...}
    Temp->>Worker: task dispatch
    Worker->>Worker: wykonaj <ClassName>_v1.run(input)
    Worker-->>Temp: result
    Temp-->>Dev: workflow completed {output}
```

### Konkretne komendy

```bash
# Pełen cykl publish-and-test:
cd ~/Desktop/workflows

# 1. Edytuj blueprint
$EDITOR blueprints/demo/sample/v1/reactflow.json

# 2. Regenerate (pisze IR + .py + manifest)
make regen
# albo per blueprint: uv run python -m scripts.regenerate_workflow blueprints/demo/sample/v1/reactflow.json

# 3. Restart worker
pkill -f "worker.py"
uv run python worker.py --tenant demo --target localhost:7233 &

# 4. Trigger workflow
uv run python -c "
import asyncio
from temporalio.client import Client

async def main():
    c = await Client.connect('localhost:7233', namespace='demo')
    h = await c.start_workflow('sample', {'tier': 'vip'},
                                id='dev-test-001', task_queue='weaver-demo')
    print(await h.result())

asyncio.run(main())
"

# 5. Podgląd w Temporal UI
open http://localhost:8233
```

### Co zawiera target `make regen` (już w `Makefile`)

```makefile
regen:
	uv run python -m scripts.regenerate_all
```

Skrypt `regenerate_all.py` iteruje wszystkie `blueprints/<tenant>/<bp>/v<n>/reactflow.json`, wywołuje `regenerate_workflow.py` per blueprint (pipeline RF→IR→walidator→generator + manifest update). Idempotentny — niezmienione IR (source hash match) NIE regeneruje `.py`.

### Skróty (które można dodać do Makefile)

```makefile
.PHONY: dev-cycle restart-worker

restart-worker:
	pkill -f "worker.py" 2>/dev/null || true
	sleep 1
	nohup uv run python worker.py --tenant $${TENANT:-demo} \
	      --target localhost:7233 > /tmp/worker-$${TENANT:-demo}.log 2>&1 &
	@echo "Worker restartowany. Log: /tmp/worker-$${TENANT:-demo}.log"

dev-cycle: regen restart-worker
	@echo "✓ regenerate + worker restart complete"
```

Wtedy jedna komenda: `make dev-cycle` (lub `make dev-cycle TENANT=acme` dla innego tenanta).

### Czego NIE robimy lokalnie

| Krok cloud flow | Czemu pominięty lokalnie |
|---|---|
| Git commit | Pliki idą bezpośrednio na dysk; w lokalnym dev nie potrzebujemy historii |
| GitHub Actions | Brak buildu — generator produkuje `.py` od ręki |
| Docker build / image push | Worker uruchamiany jako proces Pythona, nie kontener |
| Cloud Run rolling deploy | Brak — `pkill + start` to "rolling deploy" lokalny |
| Build ID Versioning | Tylko 1 wersja workera w danym momencie; restart = cutover |
| Temporal Cloud | `temporal server start-dev` na localhost |

### Compromise: brak rolling deployu lokalnie

Lokalnie po `pkill worker.py` przez 1-2 sekundy (zanim nowy worker wstanie) **żaden Engagement nie jest wykonywany**. Już running Engagementy są pauzowane przez Temporal (czeka aż worker wróci) — dane nie giną. Dla dev acceptable; dla produkcji potrzebny Build ID Versioning (cloud flow).

### Worker — czy może hot-reload bez restartu?

Krótka odpowiedź: **nie w MVP**, bo:
1. Python sam nie reloduje już zaimportowanych modułów (`importlib.reload` ma ograniczenia z classes / dependencies)
2. Temporal Worker SDK rejestruje workflow classes na starcie; zmiana kodu wymaga ponownej rejestracji
3. Workflow Sandbox cache'uje pre-imported moduły

Możliwe rozszerzenie post-MVP: file watcher (`watchdog`) na `generated/<tenant>/manifest.json` — przy zmianie wysłanie sygnału do workera, on wykonuje `os.execv()` (re-exec procesu Pythona) z tym samym command line. To efektywnie restart, ale "z poziomu siebie" — bez konieczności pkill z zewnątrz. Nie konieczne dla MVP.

---

## Tryb chmurowy — szczegóły

---

## 1. Aktorzy — kto gdzie żyje

| Aktor | Co to fizycznie | Gdzie działa | Kto napisał |
|---|---|---|---|
| **Designer** | Strona w przeglądarce (TypeScript/React + React Flow) | Komputer użytkownika | `weaver-designer` repo |
| **weaver-core** | Serwer Python (FastAPI) | Kontener Cloud Run | `weaver-core` repo |
| **Pipeline `workflows`** | **Biblioteka Pythona** zaimportowana przez core (in-process) | Wewnątrz tego samego kontenera co core | `workflows` repo (to nasze) |
| **Git repository** | Repo na GitHubie z Blueprintami i wygenerowanym kodem | github.com | infrastruktura |
| **GitHub Actions** | Efemeryczna VM uruchamiająca build | runner GitHuba | `.github/workflows/build-worker.yml` |
| **Artifact Registry** | Magazyn obrazów Docker | GCP Artifact Registry | infrastruktura |
| **Cloud Run service** | Serverless container runtime — jeden service per Tenant | GCP, region `europe-west2` | infrastruktura + `worker.py` |
| **Temporal Server** | Silnik durable workflow (orkiestrator) | Temporal Cloud lub self-hosted | infrastruktura |
| **Worker (proces)** | Kontener z `worker.py` + wygenerowane `.py` per tenant | Cloud Run instance | `workflows` repo |

---

## 2. Cloud Promotion — sekwencja (swimlane, gitops)

Punkt startu: dev ma już lokalnie zweryfikowany blueprint + wygenerowane `.py`. Decyduje że gotowe na cloud.

```mermaid
sequenceDiagram
    autonumber
    actor Dev as Dev
    participant Local as Lokalne repo<br/>~/Desktop/workflows
    participant GH as GitHub repo
    participant CI as GitHub Actions
    participant AR as Artifact Registry
    participant CR as Cloud Run<br/>(Worker per Tenant)
    participant Temp as Temporal Cloud

    Note over Dev,Local: Lokalnie zweryfikowane:<br/>make regen + restart worker<br/>+ start_workflow zwrócił poprawny wynik

    Dev->>Local: git add blueprints/ generated/<br/>git commit -m "Publish acme/onboarding v3"
    Dev->>GH: git push origin main
    GH-->>Dev: push OK, sha=abc1234

    GH->>CI: webhook: push to main
    activate CI
    CI->>CI: checkout
    CI->>CI: uv sync --all-extras
    CI->>CI: ruff check, mypy, pytest<br/>(compliance gate: 34 testy)
    CI->>CI: codegen idempotency:<br/>regenerate_all → diff(generated/) == empty?

    alt którykolwiek check fail
        CI-->>Dev: red ❌ (PR comment / email)
        Note over Dev: dev naprawia, kolejny push
    else wszystko green
        CI->>CI: docker build<br/>image:abc1234 = worker.py + generated/<acme>/...
        CI->>AR: docker push gcr.io/.../weaver-worker-acme:abc1234

        CI->>CR: gcloud run deploy weaver-worker-acme<br/>--image=...:abc1234<br/>--update-env-vars TEMPORAL_BUILD_ID=abc1234
        deactivate CI

        activate CR
        CR->>CR: start nowej instancji z image:abc1234
        CR->>CR: health check OK
        CR->>Temp: register Worker:<br/>namespace=acme, task_queue=weaver-acme,<br/>build_id=abc1234
        Temp-->>CR: registered

        CR->>CR: rolling: stare instancje (build_id=old-xyz)<br/>kończą running Engagementy, potem terminate
        deactivate CR

        Note over Temp: nowe Engagementy pinowane do build_id=abc1234<br/>stare nadal działają na old-xyz aż do końca
    end
```

### Kluczowe timing

| Krok | Czas typowy |
|---|---|
| 1-3 (commit + push) | <10s |
| 4-7 (CI: lint, type, test, compliance, idempotency) | 1-2 min |
| 8-9 (CI: docker build + push) | 2-3 min |
| 10-13 (Cloud Run deploy + Temporal register) | 30-90s |
| **Razem od `git push` do "v3 active w Cloud Run"** | **≈ 5 min** |

### Dlaczego dev push do gita zamiast UI publish

| Argument | Szczegół |
|---|---|
| Świadomy promotion | Dev decyduje kiedy zmiana jest gotowa, po lokalnym teście |
| Code review przed deploy | PR-y, recenzja zmian w `generated/` (sanity check że nikt nie ręcznie modyfikował) |
| Audit trail | git history = dokładnie co i kiedy poszło na produkcję, kto zatwierdził |
| Rollback | `git revert` + push → CI buduje stary stan, deploy = rollback |
| GitOps standard | Wszystkie zmiany infrastruktury / kodu przez git, jeden mental model |
| Nie ma "live UI publishing prod" | Mniejsze ryzyko że ktoś przez przypadek wypchnie zmianę na prod |

---

## 3. Lifecycle Agent Blueprintu

```mermaid
stateDiagram-v2
    [*] --> Draft: utworzenie / edycja w Designer
    Draft --> Draft: Save Draft (autosave)
    Draft --> Validated: walidator IR przeszedł

    Validated --> Published: Anna klika Publish<br/>(gate: walidator + lock + source hash check)
    Published --> Built: CI build OK<br/>(image w Artifact Registry)
    Built --> Active: Cloud Run rolling deploy<br/>nowy Build ID rejestruje się w Temporal

    Active --> Deprecated: następna wersja (v_n+1) staje się Active<br/>running Engagementy nadal na tym Build ID
    Deprecated --> Retired: housekeeping<br/>(0 running Engagementów na Build ID)

    Retired --> [*]: Worker image cleanup<br/>(pliki .py zostają w git history forever)

    state Published {
        [*] --> CIqueued
        CIqueued --> CIrunning: GitHub Actions start
        CIrunning --> CIfailed: lint/test/compliance fail
        CIrunning --> CIpassed: wszystkie gates green
        CIfailed --> [*]: Anna naprawia, próbuje publish ponownie
        CIpassed --> [*]
    }
```

### Stany w manifeście

```mermaid
flowchart LR
    M[generated/acme/manifest.json]
    M --> A["active_version: '3'"]
    M --> D["deprecated_versions: ['2', '1']"]
    M --> V["versions: { 1: {...}, 2: {...}, 3: {...} }"]
    V --> V1["v1: file_path, source_hash, build_id, generated_at"]
    V --> V2["v2: ... (deprecated)"]
    V --> V3["v3: ... (active)"]
```

---

## 4. Architektura komponentowa (kto z kim gada)

```mermaid
flowchart TB
    subgraph browser[Przeglądarka użytkownika]
        designer[Agent Studio<br/>weaver-designer]
        opsfe[Operations<br/>weaver-fe]
    end

    subgraph cloud[Chmura - GCP / Temporal Cloud]
        subgraph core_pod[Cloud Run: weaver-core]
            core[FastAPI server]
            pipe[Pipeline lib<br/>mapper/walidator/generator]
            core -.imports.-> pipe
        end

        subgraph worker_pods[Cloud Run: Workery per Tenant]
            wacme[Worker acme<br/>weaver-worker-acme]
            wother[Worker other<br/>weaver-worker-...]
        end

        subgraph backend[Backend services]
            wh[weaver-webhooks]
            ai[weaver-ai-service]
            litellm[weaver-litellm]
        end

        subgraph data[Data + state]
            db[(Postgres)]
            git[(Git repo<br/>blueprints + generated)]
            temp[Temporal Server]
        end

        subgraph observability[Observability]
            otel[OTEL Collector]
            graf[Grafana / Prometheus / Loki / Tempo]
        end
    end

    designer -->|REST: agents, publish| core
    opsfe -->|REST: cases, tasks| core

    core -->|persist Draft, cases, tasks| db
    core -->|git CLI / GitHub API| git
    core -->|start_workflow| temp

    wh -->|signal| temp

    temp -->|task dispatch| wacme
    temp -->|task dispatch| wother

    wacme -->|HTTP Internal API<br/>X-Internal-Key| core
    wacme -->|execute_activity:<br/>AI Skill| ai
    ai --> litellm

    wacme -.OTEL spans/metrics.-> otel
    core -.OTEL.-> otel
    otel --> graf
```

### Kanały komunikacji

| Skąd → Dokąd | Protokół | Po co |
|---|---|---|
| Designer → core | HTTPS REST | Save Draft, Publish, Read Blueprint history |
| Operations FE → core | HTTPS REST | Lista cases, task inbox, complete human task |
| core → Pipeline lib | in-process Python call | Mapper, walidator, generator (synchroniczne) |
| core → Postgres | TCP (asyncpg) | Persistence |
| core → Git | git CLI / GitHub API | Commit po Publish |
| core → Temporal | gRPC (Temporal SDK) | start_workflow, signal, query |
| Webhooks → Temporal | gRPC | Signal do oczekujących workflows |
| Temporal → Worker | gRPC long-poll | Task dispatch (Worker pulluje taski) |
| Worker → core (Internal API) | HTTPS REST + X-Internal-Key | Persist case events, status, human task creation |
| Worker → AI service | HTTPS REST | LLM completion |
| AI service → LiteLLM | HTTPS REST | Provider routing |
| Worker → OTEL | OTLP gRPC/HTTP | Telemetria |

---

## 5. Engagement Runtime — sekwencja

Co się dzieje gdy klient startuje Engagement (już po publishu, na działającym Workerze):

```mermaid
sequenceDiagram
    autonumber
    actor Klient as Klient<br/>(np. CRM Acme)
    participant Core as weaver-core
    participant DB as Postgres
    participant Temp as Temporal
    participant Worker as Worker acme<br/>(Build ID = abc1234)
    participant Tool as Tool / Specialized Agent
    participant FE as weaver-fe<br/>(Operations dashboard)
    actor Op as Operator

    Klient->>Core: POST /api/engagements<br/>{agent: "onboarding", tenant: "acme",<br/>input: {...}}
    Core->>DB: persist engagement (status: starting)
    Core->>Temp: start_workflow("onboarding",<br/>queue="weaver-acme", input)
    Temp-->>Core: workflow_id, run_id
    Core-->>Klient: 202 {engagement_id, run_id}

    Note over Temp,Worker: Temporal pinuje run do Build ID = abc1234<br/>(najnowszy default w queue weaver-acme)

    Worker->>Temp: poll task (long-poll)
    Temp-->>Worker: workflow task: Onboarding_v3, run_id=...
    Worker->>Worker: load Onboarding_v3 z<br/>generated/acme/workflows/onboarding__v3.py<br/>(już zaimportowane na startup)
    Worker->>Worker: run() — wykonuje krok po kroku

    loop dla każdego task w workflow.do[]
        alt CallTask (np. send_welcome_email)
            Worker->>Tool: execute_activity(send_email, {...})
            Tool-->>Worker: result
            Worker->>Worker: steps_output["send_welcome"] = result
        else SwitchTask
            Worker->>Worker: _eval(JQ condition, ctx)
            Note right of Worker: jeśli VIP → branch A<br/>else → branch B
        else HumanTask (Approval)
            Worker->>Core: POST /api/internal/tasks<br/>{type: approval, assignee: ...}
            Core->>DB: insert task
            Core->>FE: notyfikacja (SSE / polling)
            FE->>Op: pokaż w inbox
            Op->>FE: complete task<br/>(approve/reject + form data)
            FE->>Core: POST /api/tasks/{id}/complete
            Core->>Temp: signal workflow<br/>{task_id, decision, form_data}
            Temp-->>Worker: workflow signal received
            Worker->>Worker: kontynuuj
        end

        Worker->>Core: POST /api/internal/case-events<br/>{step, output, timestamp}
        Core->>DB: append event
    end

    Worker->>Temp: workflow completed, result={...}
    Temp->>Core: webhook? polling? -> status update
    Core->>DB: engagement status = completed
    Core-->>Klient: (jeśli synchronicznie czekał) result<br/>(jeśli asynchronicznie) webhook callback
    Core->>FE: live update -> case zniknął z inbox
```

### Kluczowe obserwacje runtime

| Obserwacja | Dlaczego ważne |
|---|---|
| Worker **pulluje** taski z Temporal (long-poll), nie odwrotnie | Skalowalność — nowe Workery dołączają, Temporal nie musi ich znać apriori |
| Workflow code jest **deterministyczny** | Temporal może odtworzyć stan po restarcie z historii (replay); bez determinizmu replay nie działa |
| Activity (Tool, Specialized Agent) **NIE** jest deterministyczna | Może mieć I/O, side effects; Temporal to zapamiętuje raz w historii i nie wykonuje ponownie |
| Human Task pauzuje workflow przez **Temporal signal** | Workflow wisi tygodniami, czekając aż operator kliknie — to OK, Temporal storage to obsługuje |
| Worker → core przez **Internal API** (osobny X-Internal-Key) | Bo komunikacja maszyna-maszyna, nie wymaga JWT usera |

---

## 6. Worker Versioning Build ID — co to znaczy w praktyce

Najtrudniejsza część do zrozumienia. Diagram timeline:

```mermaid
gantt
    title Życie wersji Workera podczas deploy v2 → v3
    dateFormat HH:mm
    axisFormat %H:%M

    section Build ID = old-xyz (v2)
    accepting nowe Engagementy : done, v2a, 09:00, 60m
    running Engagementy v2     : done, v2b, 09:00, 180m
    sunset (running only)      : done, v2c, after v2a, 120m
    drained (0 running)        : done, v2d, after v2b, 5m
    terminated (Cloud Run)     : crit, v2e, after v2d, 1m

    section Build ID = abc1234 (v3)
    image build (CI)           : active, v3a, 09:55, 5m
    deploy + register          : active, v3b, after v3a, 2m
    accepting nowe Engagementy : active, v3c, after v3b, 999m
```

### Faza 1: oba Build ID działają (overlap)

```
Czas 09:00 - 10:02
Worker pool acme:
  ├─ Instance #1 (Build ID = old-xyz, v2) — running 5 Engagementów
  ├─ Instance #2 (Build ID = old-xyz, v2) — running 3 Engagementy
  └─ Instance #3 (Build ID = abc1234, v3) — JUST STARTED, accepting new

Temporal kieruje:
  ├─ Engagementy started przed 10:02 → existing Build ID old-xyz (do skończenia)
  └─ Engagementy started po 10:02 → najnowszy default = abc1234
```

### Faza 2: stare Engagementy się skończyły, sunset starszego Build ID

```
Czas 12:00 (po 2h)
Worker pool acme:
  ├─ Instance #3 (Build ID = abc1234, v3) — running new Engagementy
  └─ Instance #1, #2 (Build ID = old-xyz, v2) — 0 running Engagementów

Cloud Run cleanup:
  └─ terminate Instance #1, #2 (są niepotrzebne)

Manifest update przez housekeeping job (cron):
  generated/acme/manifest.json:
    blueprints.onboarding.deprecated_versions = ["v2"] → status: retired
```

---

## 7. Dlaczego ta architektura — krótka justyfikacja

| Wybór | Alternatywa | Dlaczego tak |
|---|---|---|
| Pipeline jako **biblioteka in-process** w core, nie osobny serwis | Microservice `workflows-service` z gRPC | Prostota, transakcyjność z DB lock, mniej deployment surface; refaktor do mikroserwisu gdy publish staje się bottleneckiem |
| **Codegen `.py`** zamiast interpretera DSL | InterpreterWorkflow walking adjacency graph z DB | Native Temporal patterns (replay, versioning), type safety, audit przez git, nie dublujemy Temporal SDK — patrz ADR-001 |
| **Worker per Tenant** (osobny Cloud Run service) | Wspólny Worker dla wszystkich Tenantów | Fizyczna izolacja (decyzja #4), separate scaling, namespace per Tenant w Temporalu |
| **Build ID = sha krótki commit** | Semver / monotoniczny licznik | Kanonicznie identyfikuje konkretny stan kodu; deterministic; idempotent |
| **Pliki `.py` w git** zamiast w blob storage | Zapisywać artefakty do GCS / S3 | Git history = audit forever, replay starych Engagementów po refleksji, code review, easy diff między wersjami |
| **GitHub Actions** zamiast custom CI | Jenkins / Argo / TeamCity | Najmniejsza powierzchnia deployment; już mamy GitHub jako source of truth |

---

## Powiązane dokumenty

- `ARCHITECTURE.md` — wysokopoziomowa architektura
- `PIPELINE.md` — gates, idempotency, SLO
- `MULTI_TENANT.md` — operacyjny guide tenant isolation
- `IR_SPEC.md` — specyfikacja CNCF SW IR JSON
- `adr/ADR-003-compiled-py-per-blueprint.md` — uzasadnienie codegen
- `adr/ADR-005-worker-versioning-build-id.md` — Worker Versioning detail
- `adr/ADR-006-tenancy-isolation.md` — model izolacji
