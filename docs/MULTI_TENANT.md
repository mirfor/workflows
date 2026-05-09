# Multi-tenant — operacyjny guide

Konkretny przewodnik po multi-tenant routing w Workflow Platform Temporal. Decyzja #4 (fizyczna izolacja per Tenant); ADR-006.

## Layout

```
blueprints/
├── <tenant_id>/
│   └── <blueprint_id>/
│       └── v<n>/
│           ├── reactflow.json    # Form 1 (UI)
│           └── cncf-sw.json      # Form 2 (IR — source of truth)

generated/
└── <tenant_id>/
    ├── manifest.json             # active/deprecated/build_id_lineage per Tenant
    └── workflows/
        └── <snake_id>__v<n>.py   # Form 3 (runtime)
```

Przykład istniejący w repo:

| Tenant | Blueprint | Wersja | Pliki |
|---|---|---|---|
| `demo` | `sample` | v1 | `blueprints/demo/sample/v1/{reactflow,cncf-sw}.json`, `generated/demo/workflows/sample__v1.py` |
| `demo` | `iteration` | v1 | analogicznie |
| `demo` | `parallel` | v1 | analogicznie |
| `demo` | `error_handling` | v1 | analogicznie |
| `acme` | `hello` | v1 | `blueprints/acme/hello/v1/...`, `generated/acme/workflows/hello__v1.py` |

## Manifest per Tenant

Każdy `generated/<tenant_id>/manifest.json` zawiera **tylko** Blueprinty tego Tenanta. Format:

```json
{
  "schema_version": "1.0",
  "tenant_id": "<tenant_id>",
  "blueprints": {
    "<bp_id>": {
      "active_version": "<n>",
      "deprecated_versions": [],
      "versions": {
        "<n>": {
          "file_path": "generated/<tenant_id>/workflows/<snake>__v<n>.py",
          "class_name": "<PascalCase>_v<n>",
          "source_hash": "<sha256>",
          "build_id": null,
          "generated_at": "<iso>"
        }
      }
    }
  }
}
```

`update_manifest()` waliduje że `gen.tenant_id` jest spójny z `manifest_path` — odrzuca write gdy mismatch.

## Worker per Tenant

```bash
uv run python worker.py --tenant <tenant_id> --target localhost:7233
```

Defaults:
- `namespace = <tenant_id>` (Temporal namespace; jeśli nie istnieje, utwórz: `temporal operator namespace create <tenant_id>`)
- `task_queue = weaver-<tenant_id>`

Worker ładuje **tylko** workflowy z `generated/<tenant_id>/manifest.json`. Workflowy innych Tenantów są niewidoczne.

Override przez ENV / args:

| ENV | Arg | Default |
|---|---|---|
| `TEMPORAL_TARGET` | `--target` | `localhost:7233` |
| `TEMPORAL_NAMESPACE` | `--namespace` | `<tenant>` |
| `TEMPORAL_TASK_QUEUE` | `--task-queue` | `weaver-<tenant>` |
| `TEMPORAL_BUILD_ID` | `--build-id` | `None` |

## Bulk operations

| Skrypt | Zakres domyślny | Filtry |
|---|---|---|
| `scripts/regenerate_all.py` | wszystkie Tenanty / wszystkie Blueprinty | `--tenant <id>`, `--blueprint <bp>` (wymaga `--tenant`) |
| `scripts/validate_all.py` | jak wyżej (bez generacji) | `--strict` (warningi też powodują niezerowy exit) |
| `scripts/regenerate_workflow.py` | pojedynczy Blueprint × wersja | argument: `<rf_path>` |

Idempotencja: source hash check per `(tenant, blueprint, version)` — niezmienione IR nie regeneruje `.py`.

## Cross-tenant isolation

Mechanizmy izolacji:

| Layer | Mechanizm |
|---|---|
| Filesystem | osobne katalogi `blueprints/<tenant>/` i `generated/<tenant>/` |
| Manifest | `tenant_id` field + `update_manifest` sanity check |
| Worker | `--tenant` arg ładuje **tylko** swój manifest |
| Temporal | osobny namespace per Tenant (`tenant_id` jako namespace name) |
| Task queue | `weaver-<tenant_id>` — Workflowy startowane przez `start_workflow` muszą trafić w odpowiednią kolejkę |

Compliance test `test_f5_cross_tenant_isolation_via_separate_manifests` egzekwuje, że Tenant manifesty są disjoint w `blueprint_ids`.

E2E zweryfikowane (F5.6): `start_workflow("hello")` w `demo` namespace — gdy Worker `demo` nie ma `hello` w swoim manifeście — workflow nie może zostać wykonany przez tego Workera.

## Cascade defaults (Tenant → Client Org → Blueprint)

Decyzja #28. Funkcja `cascade_resolve(tenant, client_org, blueprint)` w `scripts/build_manifest.py` łączy 3 poziomy z override priority Blueprint > Client Org > Tenant.

```python
from scripts.build_manifest import CascadeDefaults, cascade_resolve

t = CascadeDefaults(default_start_to_close="PT10M", default_heartbeat="PT60S")
o = CascadeDefaults(default_start_to_close="PT5M")
b = CascadeDefaults(default_heartbeat="PT15S")
final = cascade_resolve(t, o, b)
# final.default_start_to_close == "PT5M" (Client Org override Tenant)
# final.default_heartbeat == "PT15S" (Blueprint override Tenant)
```

W produkcji wartości pochodzą z DB designerze (Tenant settings, Client Org settings, Blueprint settings); MVP wstrzykuje defaults bez integracji DB.

## Search Attributes

Każde workflow execution **musi** mieć:

| SA | Wartość | Cel |
|---|---|---|
| `tenant_id` | `<tenant_id>` | audit/observability scoping |
| `client_org_id` | UUID Client Org | filtering per klient |
| `blueprint_id` | `<bp_id>` (snake_case) | tracking per definicja |
| `version` | `"<n>"` | tracking per wersja |
| `engagement_id` | UUID uruchomienia | korelacja end-to-end |

Per Tenant namespace SA są niezależne; wymaga `temporal operator search-attribute create ... --namespace <tenant_id>` raz per Tenant.

## Local dev — pełny flow

```bash
# 1. Temporal Server
temporal server start-dev --port 7233 --ui-port 8233 &
temporal operator namespace create demo --address localhost:7233
temporal operator namespace create acme --address localhost:7233

# 2. Regeneracja wszystkich Blueprintów we wszystkich Tenantach
uv run python -m scripts.regenerate_all

# 3. Workery per Tenant
uv run python worker.py --tenant demo --target localhost:7233 &
uv run python worker.py --tenant acme --target localhost:7233 &

# 4. Start workflow per Tenant (Python client)
uv run python -c "
import asyncio, json
from temporalio.client import Client

async def main():
    c = await Client.connect('localhost:7233', namespace='demo')
    h = await c.start_workflow('sample', {'tier': 'vip'},
                                id='dev-001', task_queue='weaver-demo')
    print(json.dumps(await h.result(), indent=2, ensure_ascii=False))

asyncio.run(main())
"
```

## Compliance gate

Multi-tenant invariants są egzekwowane w `tests/test_compliance.py`:

| Test | Co sprawdza |
|---|---|
| `test_decision_04_tenant_isolation_layout` | layout `blueprints/<tenant>/<bp>/v<n>/`; `generate()` wymusza `tenant_id`; manifest path per Tenant; worker --tenant required |
| `test_decision_19_three_forms_persisted` | dla każdego Blueprintu istnieją wszystkie 3 formy w odpowiedniej ścieżce per Tenant |
| `test_f5_multi_blueprint_coverage_per_task_type` | task types pokryte przez Blueprinty w suite |
| `test_f5_cross_tenant_isolation_via_separate_manifests` | manifesty Tenantów disjoint w blueprint_ids; tenant_id field spójny |

CI job `compliance` (`.github/workflows/ci.yml`) blokuje merge gdy któryś test fail.

## Powiązane dokumenty

- `ARCHITECTURE.md` — diagram pipeline z multi-tenant routing
- `PIPELINE.md` — drzewo zdarzeń, bulk operations, cross-tenant isolation
- `DEV_SETUP.md` — local dev workflow per Tenant
- `CONTRIBUTING.md` — compliance-first workflow
- `OBSERVABILITY.md` — Search Attributes per Tenant
- `SECURITY.md` — threat model tenant isolation
- `adr/ADR-006-tenancy-isolation.md` — model izolacji
- `COMPLIANCE.md` — mapowanie decyzja → test
