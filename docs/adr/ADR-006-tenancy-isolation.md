# ADR-006: Model izolacji Tenant / Client Org

**Status:** Accepted
**Data:** 2026-05-09
**Decyzje źródłowe:** #4 (`docs/SESSION_STATE.md`)

## Kontekst
- Workflow Platform Temporal jest komponentem ekosystemu Weaver (AI Agent Orchestrator).
- Hierarchia: Tenant (organizacja korzystająca z platformy) > Client Org (klient Tenanta) > Branch.
- Tenanci operują w branżach regulowanych (finanse, healthcare, legal) z wymogami separacji danych.
- Workflow execution operuje na danych Client Org różnych Tenantów w jednym klastrze Temporal bez izolacji domyślnej.
- Wymóg: separacja danych w spoczynku, w runtime workflow oraz w warstwie observability/audit.

## Decyzja
| Poziom | Izolacja | Mechanizm |
|---|---|---|
| Tenant | **fizyczna** | osobny Temporal namespace + osobna DB |
| Client Org | **logiczna** (default) | row-level filter + Search Attribute |
| Client Org regulowany | **fizyczna opt-in** | osobny Temporal namespace dedykowany Client Org |

## Search Attributes
Wymagane na każdym workflow execution:
- `tenant_id` — identyfikator Tenanta
- `client_org_id` — identyfikator Client Org
- `blueprint_id` — identyfikator Blueprintu
- `version` — wersja Blueprintu
- `engagement_id` — identyfikator Engagement (instancja wykonania dla Client Org)

## Implikacje per warstwa
| Warstwa | Konsekwencja |
|---|---|
| DB designer | row-level filter po `tenant_id` + `client_org_id` |
| Worker | osobny deployment per Tenant namespace |
| Blueprint registry | scoping per Tenant; Client Org-specific Blueprints w opt-in fizycznym |
| Manifest (`generated/manifest.json`) | scope per Tenant |
| Audit / observability | filtrowalne po SA |

## Rozważone alternatywy
| Opcja | Opis | Dlaczego nie |
|---|---|---|
| Pełna izolacja fizyczna na każdym poziomie | osobny namespace per Client Org | Koszt (n × namespace), niepotrzebne dla większości Client Org |
| Pełna izolacja logiczna | jeden namespace dla wszystkich Tenantów, SA na każdym poziomie | Naruszenie compliance dla Tenantów wymagających separacji danych |

## Konsekwencje
### Pozytywne
- Compliance per Tenant zapewniony przez separację namespace + DB.
- Koszt infrastruktury skaluje się z liczbą Tenantów, nie Client Org.
- Opt-in fizyczny pozwala obsłużyć regulowane Client Org bez zmiany modelu bazowego.
- Search Attributes umożliwiają cross-cutting queries i audit w obrębie Tenanta.

### Trade-offs
- Dwa modele izolacji Client Org (logiczny vs fizyczny opt-in) zwiększają złożoność deployment.
- Worker pool per Tenant namespace zwiększa narzut operacyjny (n × deployment).
- Row-level filter wymaga dyscypliny w każdym query — błąd skutkuje wyciekiem cross-Client Org w obrębie Tenanta.
- Migracja Client Org z izolacji logicznej do fizycznej wymaga procedury przenoszenia stanu między namespace.

### Follow-up
- Procedura provisioning Tenant namespace + DB (automatyzacja).
- Procedura opt-in fizyczny dla Client Org (kryteria, runbook migracji).
- Test enforcement row-level filter (statyczna analiza query lub middleware DB).
- Polityka retention i backup per namespace.
- Mechanizm rejestracji Search Attributes w Temporal cluster per Tenant.

## Referencje
- `docs/SESSION_STATE.md` #4
- `~/Desktop/weaver-root/docs/content/architecture/b2b-client-model.md` — Tenant / Client Org / Branch hierarchia
