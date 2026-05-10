"""Build `activities/manifest.json` (Tools + Specialized Agents + base errors).

Decyzje:
- #7 / #18: Tools deklarowane w `activities/tools/<integration>.py` przez `TOOL_MANIFEST`;
  Specialized Agents deklarowane w `activities/specialized_agents.json` (lista endpoint-ów).
- #13: schemy I/O = Pydantic JSON Schema dla Tools; OpenAPI pull dla Specialized Agents.
- #23: errors per Tool — eksportowane z manifestu Tool jako `errors[]` (ErrorSpec).
- #28: cascade resolution `default_timeout` (Tenant → Client Org → Blueprint).

MVP:
- Tool module deklaruje moduł-level zmienną `TOOL_MANIFEST: dict[str, Any]` z polami
  `name`, `operation`, `module`, `input_schema`, `output_schema`, `errors`,
  `default_retry_profile`, `default_timeout_profile`, `idempotent`.
- Specialized Agents pullowane przez httpx; jeśli endpoint niedostępny, manifest pomija ten agent
  (warning w stderr).
- Cascade resolution to czysta funkcja na słownikach.
"""

from __future__ import annotations

import importlib
import json
import pkgutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ir.errors import BaseErrorType

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_PACKAGE = "activities.tools"
SPECIALIZED_AGENTS_INDEX = REPO_ROOT / "activities" / "specialized_agents.json"
OUTPUT_PATH = REPO_ROOT / "activities" / "manifest.json"
MANIFEST_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class CascadeDefaults:
    """Defaults zbierane z 3 poziomów (#28)."""

    default_start_to_close: str = "PT5M"
    default_heartbeat: str | None = "PT30S"
    default_schedule_to_close: str | None = None


def cascade_resolve(
    tenant: CascadeDefaults | None,
    client_org: CascadeDefaults | None,
    blueprint: CascadeDefaults | None,
) -> CascadeDefaults:
    """Resolve cascade Tenant → Client Org → Blueprint (Blueprint nadpisuje Client Org nadpisuje Tenant).

    `None` wartości na danym poziomie = dziedziczenie z wyższego.
    """
    levels = [lv for lv in (tenant, client_org, blueprint) if lv is not None]
    if not levels:
        return CascadeDefaults()

    result = CascadeDefaults()
    for lv in levels:
        result = CascadeDefaults(
            default_start_to_close=lv.default_start_to_close or result.default_start_to_close,
            default_heartbeat=lv.default_heartbeat
            if lv.default_heartbeat is not None
            else result.default_heartbeat,
            default_schedule_to_close=lv.default_schedule_to_close
            if lv.default_schedule_to_close is not None
            else result.default_schedule_to_close,
        )
    return result


def discover_tools() -> list[dict[str, Any]]:
    """Iteruj `activities/tools/*.py`, wczytaj `TOOL_MANIFEST` zmienną z każdego modułu."""
    tools: list[dict[str, Any]] = []
    try:
        pkg = importlib.import_module(TOOLS_PACKAGE)
    except ImportError:
        return tools
    if not hasattr(pkg, "__path__"):
        return tools
    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"{TOOLS_PACKAGE}.{info.name}")
        manifest = getattr(mod, "TOOL_MANIFEST", None)
        if manifest is None:
            continue
        merged = {
            "type": "weaver_tool",
            "module": f"{TOOLS_PACKAGE}.{info.name}",
            "errors": [],
            "default_retry_profile": None,
            "default_timeout_profile": None,
            "idempotent": False,
            **manifest,
        }
        merged.setdefault("name", info.name)
        merged.setdefault("operation", info.name)
        tools.append(merged)
    return tools


def discover_specialized_agents(timeout_seconds: float = 5.0) -> list[dict[str, Any]]:
    """Wczytaj `activities/specialized_agents.json` (lista deklaracji), pull OpenAPI per endpoint.

    Format wpisu: `{"name": "...", "endpoint_url": "...", "operation": "...",
                    "openapi_url": "<endpoint>/openapi.json", "errors": [...]}`.
    """
    if not SPECIALIZED_AGENTS_INDEX.exists():
        return []
    declarations: list[dict[str, Any]] = json.loads(SPECIALIZED_AGENTS_INDEX.read_text("utf-8"))
    agents: list[dict[str, Any]] = []
    for d in declarations:
        merged: dict[str, Any] = {
            "type": "weaver_specialized_agent",
            "errors": [],
            "default_retry_profile": None,
            "default_timeout_profile": None,
            "idempotent": False,
            **d,
        }
        url = d.get("openapi_url")
        if url:
            try:
                resp = httpx.get(url, timeout=timeout_seconds)
                resp.raise_for_status()
                openapi = resp.json()
                merged["input_schema"] = _extract_request_schema(openapi, d.get("operation"))
                merged["output_schema"] = _extract_response_schema(openapi, d.get("operation"))
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                print(
                    f"[build_manifest] WARN: pull OpenAPI dla {d['name']!r} ({url}) "
                    f"nieudany: {exc}",
                    file=sys.stderr,
                )
        agents.append(merged)
    return agents


def _extract_request_schema(
    openapi: dict[str, Any], operation_id: str | None
) -> dict[str, Any] | None:
    """Best-effort wyciągnięcie request body schema dla operationId."""
    if not operation_id:
        return None
    for path_methods in openapi.get("paths", {}).values():
        for spec in path_methods.values():
            if spec.get("operationId") == operation_id:
                rb = spec.get("requestBody", {}).get("content", {})
                for ct in ("application/json", "*/*"):
                    if ct in rb:
                        return rb[ct].get("schema")
    return None


def _extract_response_schema(
    openapi: dict[str, Any], operation_id: str | None
) -> dict[str, Any] | None:
    """Best-effort wyciągnięcie 200/201 response schema dla operationId."""
    if not operation_id:
        return None
    for path_methods in openapi.get("paths", {}).values():
        for spec in path_methods.values():
            if spec.get("operationId") == operation_id:
                for code in ("200", "201", "default"):
                    resp = spec.get("responses", {}).get(code)
                    if resp:
                        rb = resp.get("content", {})
                        for ct in ("application/json", "*/*"):
                            if ct in rb:
                                return rb[ct].get("schema")
    return None


def base_errors() -> list[dict[str, Any]]:
    """7 base error types (#23)."""
    retryable_defaults = {
        BaseErrorType.VALIDATION_ERROR: False,
        BaseErrorType.AUTH_ERROR: False,
        BaseErrorType.RATE_LIMIT_ERROR: True,
        BaseErrorType.TIMEOUT_ERROR: True,
        BaseErrorType.NOT_FOUND_ERROR: False,
        BaseErrorType.INTEGRATION_ERROR: True,
        BaseErrorType.INTERNAL_ERROR: False,
    }
    return [
        {
            "type": e.value,
            "is_base": True,
            "retryable": retryable_defaults[e],
        }
        for e in BaseErrorType
    ]


def build_manifest(
    *,
    cascade: CascadeDefaults | None = None,
    pull_openapi: bool = True,
) -> dict[str, Any]:
    """Zbuduj manifest dict (bez zapisu)."""
    return {
        "schema_version": MANIFEST_VERSION,
        "default_timeout": {
            "after": (cascade or CascadeDefaults()).default_start_to_close,
            "metadata": {
                "temporal": {
                    k: v
                    for k, v in (
                        ("heartbeat", (cascade or CascadeDefaults()).default_heartbeat),
                        (
                            "schedule_to_close",
                            (cascade or CascadeDefaults()).default_schedule_to_close,
                        ),
                    )
                    if v
                }
            }
            if (cascade or CascadeDefaults()).default_heartbeat
            or (cascade or CascadeDefaults()).default_schedule_to_close
            else None,
        },
        "tools": discover_tools(),
        "specialized_agents": discover_specialized_agents() if pull_openapi else [],
        "base_errors": base_errors(),
    }


def write_manifest(manifest: dict[str, Any], path: Path = OUTPUT_PATH) -> None:
    """Atomowy zapis (temp + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> None:
    manifest = build_manifest()
    write_manifest(manifest)
    print(f"Wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size} bytes)")
    print(f"  - tools: {len(manifest['tools'])}")
    print(f"  - specialized_agents: {len(manifest['specialized_agents'])}")
    print(f"  - base_errors: {len(manifest['base_errors'])}")


if __name__ == "__main__":
    main()
