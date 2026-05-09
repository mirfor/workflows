# OBSERVABILITY.md

## 1. Cel

- Monitorowanie wykonań workflow generowanych jako `.py` per Blueprint i uruchamianych na Temporal.
- Zakres:
  - **Search Attributes** — filtrowanie i scoping per Tenant / Client Org / Blueprint / Engagement.
  - **Custom metryki** — workflow, task, activity (Tool / Specialized Agent).
  - **Dashboardy** — Engagement health, Tool reliability, Specialized Agent latency, Build ID rollout.
  - **Logi** — JSON lines z wymaganym kontekstem multi-tenant.
- Cel operacyjny: end-to-end korelacja `tenant_id` → `client_org_id` → `engagement_id` → `workflow_id` → task → activity.

## 2. Search Attributes

Decyzja #4 — Tenant / Client Org isolation.

| Search Attribute | Typ | Wartość | Cel |
|---|---|---|---|
| `tenant_id` | KEYWORD | UUID Tenanta | Scoping audit/observability per Tenant namespace |
| `client_org_id` | KEYWORD | UUID Client Org | Filtering per klient |
| `blueprint_id` | KEYWORD | snake_id Blueprintu | Tracking per definicja |
| `version` | KEYWORD | numer wersji `<n>` | Tracking per wersja |
| `engagement_id` | KEYWORD | UUID konkretnego uruchomienia | Korelacja end-to-end |
| `build_id` | KEYWORD | sha krótki commita | Worker Versioning Build ID lineage |

## 3. Konfiguracja SA per Tenant namespace

- Rejestracja przez `tctl admin search-attribute create` lub Cloud UI.
- Każdy Tenant namespace musi mieć powyższe SA przed pierwszym workflow execution.
- Brak SA w namespace blokuje start workflow (Temporal odrzuca `upsert_search_attributes`).

## 4. Setting SA w wygenerowanym `.py`

- Generator emituje `workflow.upsert_search_attributes({...})` na początku `run()`.
- Status: post-MVP — TODO w F3.C extension.

## 5. Custom metryki

### Workflow-level
- `weaver_workflow_started_total{tenant_id, blueprint_id, version}`
- `weaver_workflow_completed_total{tenant_id, blueprint_id, version}`
- `weaver_workflow_failed_total{tenant_id, blueprint_id, version, error_type}`
- `weaver_workflow_duration_seconds_bucket{tenant_id, blueprint_id, version}`

### Task-level
- `weaver_task_started_total{tenant_id, blueprint_id, task_name, task_type}`
- `weaver_task_failed_total{tenant_id, blueprint_id, task_name, task_type, error_type}`

### Activity-level
- `weaver_tool_invocation_total{tool_name, status}`
- `weaver_specialized_agent_invocation_total{agent_name, status}`

## 6. Eksport metryk

- Temporal Worker → Prometheus endpoint (`metrics_path` config w `worker.py` — TODO).
- Tenant-level scrape z labelem `tenant_id` na każdej metryce.

## 7. Format logów

- JSON lines, jeden event per linia.
- Wymagane pola:

| Pole | Typ | Opis |
|---|---|---|
| `timestamp` | string | ISO 8601 UTC |
| `level` | string | DEBUG / INFO / WARN / ERROR |
| `tenant_id` | string | UUID Tenanta |
| `client_org_id` | string | UUID Client Org |
| `engagement_id` | string | UUID Engagementu |
| `workflow_id` | string | Temporal Workflow ID |
| `task_name` | string | Nazwa kroku Blueprintu |
| `message` | string | Treść |
| `event_type` | string | Klasa zdarzenia (start / complete / fail / tool_call / agent_call) |

- Logger: stdlib `logging` + `python-json-logger` lub `structlog` (TODO wybór).

## 8. Dashboardy

| Dashboard | Audience | Główne wykresy |
|---|---|---|
| Engagement health (per Tenant) | Ops | Started / Completed / Failed rate; p50/p95/p99 duration; top failing Blueprints |
| Tool reliability | Platform | Invocation rate, error rate, p95 latency per Tool |
| Specialized Agent latency | Platform | p95 per agent, error breakdown by HTTP status |
| Build ID rollout | Platform | Running executions per Build ID, deprecated cleanup progress |

## 9. Tracing

- Temporal natywnie traceuje każdy workflow + activity.
- Custom span tags: `tenant_id`, `blueprint_id`, `task_name` (post-MVP).
- Eksport do Tempo / Jaeger via OTLP.

## 10. Alerting

Progi rekomendowane dla MVP.

| Warunek | Okno | Akcja |
|---|---|---|
| Failed rate > 5% per Blueprint | 10 min | page Ops |
| p99 duration > 2× baseline | 10 min | notify Platform |
| Build ID rollout stuck (deprecated > 7d w running executions) | — | notify Platform |
| Manifest mismatch (Worker startup error) | — | page Platform |

## 11. Audit log

- Compliance dla regulowanych Client Org (decyzja #4).
- Każdy workflow start / complete / fail = audit event z pełnym SA + input hash.
- Storage: per Tenant (osobna DB).
- Retencja: 7 lat (placeholder — TODO Compliance team).

## 12. Powiązane dokumenty

- `ARCHITECTURE.md` — overview.
- `PIPELINE.md` — gates, SLO.
- `adr/ADR-006-tenancy-isolation.md` — model izolacji.
- `runbooks/` — operacyjne playbooks.
