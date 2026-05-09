"""Smoke testy buildera manifestu (F3.D.6)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.build_manifest import (
    CascadeDefaults,
    base_errors,
    build_manifest,
    cascade_resolve,
    write_manifest,
)


def test_base_errors_contain_seven_types() -> None:
    errs = base_errors()
    assert len(errs) == 7
    types = {e["type"] for e in errs}
    assert {"ValidationError", "AuthError", "RateLimitError", "TimeoutError",
            "NotFoundError", "IntegrationError", "InternalError"} == types
    for e in errs:
        assert e["is_base"] is True


def test_base_error_retryability() -> None:
    by_type = {e["type"]: e["retryable"] for e in base_errors()}
    assert by_type["ValidationError"] is False
    assert by_type["RateLimitError"] is True
    assert by_type["TimeoutError"] is True
    assert by_type["IntegrationError"] is True


def test_cascade_resolve_blueprint_overrides() -> None:
    tenant = CascadeDefaults(default_start_to_close="PT10M", default_heartbeat="PT1M")
    client_org = CascadeDefaults(default_start_to_close="PT8M", default_heartbeat="PT45S")
    blueprint = CascadeDefaults(default_start_to_close="PT3M", default_heartbeat=None)

    resolved = cascade_resolve(tenant, client_org, blueprint)
    assert resolved.default_start_to_close == "PT3M"
    # Blueprint heartbeat=None → dziedziczy z Client Org
    assert resolved.default_heartbeat == "PT45S"


def test_cascade_resolve_no_levels_returns_default() -> None:
    resolved = cascade_resolve(None, None, None)
    assert resolved.default_start_to_close == "PT5M"
    assert resolved.default_heartbeat == "PT30S"


def test_build_manifest_structure() -> None:
    m = build_manifest(pull_openapi=False)
    assert m["schema_version"] == "1.0"
    assert isinstance(m["tools"], list)
    assert isinstance(m["specialized_agents"], list)
    assert m["specialized_agents"] == []
    assert "default_timeout" in m
    assert m["default_timeout"]["after"] == "PT5M"


def test_build_manifest_with_cascade_overrides_default_timeout() -> None:
    cascade = CascadeDefaults(
        default_start_to_close="PT15M",
        default_heartbeat="PT2M",
        default_schedule_to_close="PT30M",
    )
    m = build_manifest(cascade=cascade, pull_openapi=False)
    assert m["default_timeout"]["after"] == "PT15M"
    assert m["default_timeout"]["metadata"]["temporal"]["heartbeat"] == "PT2M"
    assert m["default_timeout"]["metadata"]["temporal"]["schedule_to_close"] == "PT30M"


def test_write_manifest_atomic(tmp_path: Path) -> None:
    m = build_manifest(pull_openapi=False)
    path = tmp_path / "manifest.json"
    write_manifest(m, path)
    assert path.exists()
    loaded = json.loads(path.read_text("utf-8"))
    assert loaded == m
