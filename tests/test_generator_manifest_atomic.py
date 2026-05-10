"""Testy `generator/manifest.py` — atomic write, multi-version lineage, tenant guard."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from generator import GeneratedWorkflow, manifest_path_for, update_manifest


def _gen(tenant: str = "demo", bp: str = "sample", version: str = "1") -> GeneratedWorkflow:
    return GeneratedWorkflow(
        source="# stub\n",
        tenant_id=tenant,
        blueprint_id=bp,
        version=version,
        file_name=f"{bp}__v{version}.py",
        relative_path=f"generated/{tenant}/workflows/{bp}__v{version}.py",
        class_name=f"Sample_v{version}",
        workflow_temporal_name=bp,
        source_hash=f"hash-{tenant}-{bp}-{version}",
    )


def test_manifest_path_for_returns_per_tenant_layout(tmp_path: Path) -> None:
    p = manifest_path_for(tmp_path, "acme")
    assert p == tmp_path / "generated" / "acme" / "manifest.json"


def test_update_manifest_creates_file_on_first_write(tmp_path: Path) -> None:
    mf = tmp_path / "generated" / "demo" / "manifest.json"
    assert not mf.exists()
    update_manifest(mf, _gen(version="1"), generated_at="2026-05-09T12:00:00")
    assert mf.exists()
    data = json.loads(mf.read_text("utf-8"))
    assert data["tenant_id"] == "demo"
    assert data["blueprints"]["sample"]["active_version"] == "1"


def test_update_manifest_promotes_new_version_and_deprecates_previous(tmp_path: Path) -> None:
    mf = tmp_path / "generated" / "demo" / "manifest.json"
    update_manifest(mf, _gen(version="1"), generated_at="2026-05-09T12:00:00")
    update_manifest(mf, _gen(version="2"), generated_at="2026-05-09T13:00:00")
    update_manifest(mf, _gen(version="3"), generated_at="2026-05-09T14:00:00")

    data = json.loads(mf.read_text("utf-8"))
    bp = data["blueprints"]["sample"]
    assert bp["active_version"] == "3"
    assert "1" in bp["deprecated_versions"]
    assert "2" in bp["deprecated_versions"]
    assert "3" not in bp["deprecated_versions"]
    assert set(bp["versions"].keys()) == {"1", "2", "3"}


def test_update_manifest_no_activate_keeps_previous_active(tmp_path: Path) -> None:
    mf = tmp_path / "generated" / "demo" / "manifest.json"
    update_manifest(mf, _gen(version="1"))
    update_manifest(mf, _gen(version="2"), activate=False)
    data = json.loads(mf.read_text("utf-8"))
    assert data["blueprints"]["sample"]["active_version"] == "1"
    # v2 obecny w versions ale nie active
    assert "2" in data["blueprints"]["sample"]["versions"]


def test_update_manifest_path_tenant_mismatch_raises(tmp_path: Path) -> None:
    """Manifest path musi być spójny z gen.tenant_id."""
    wrong_path = tmp_path / "generated" / "OTHER" / "manifest.json"
    with pytest.raises(ValueError, match="nie jest per-Tenant"):
        update_manifest(wrong_path, _gen(tenant="demo"))


def test_update_manifest_existing_file_with_different_tenant_raises(tmp_path: Path) -> None:
    mf = tmp_path / "generated" / "demo" / "manifest.json"
    mf.parent.mkdir(parents=True)
    mf.write_text(json.dumps({"schema_version": "1.0", "tenant_id": "OTHER", "blueprints": {}}))
    with pytest.raises(ValueError, match="tenant_id mismatch"):
        update_manifest(mf, _gen(tenant="demo"))


def test_update_manifest_atomic_write_no_partial_file(tmp_path: Path) -> None:
    mf = tmp_path / "generated" / "demo" / "manifest.json"
    update_manifest(mf, _gen(version="1"))
    # Jeśli atomic write działa: nie ma plików .tmp
    leftovers = list(mf.parent.glob("manifest.json.tmp"))
    assert leftovers == []


def test_update_manifest_idempotent_same_version(tmp_path: Path) -> None:
    """Re-write tej samej wersji nadpisuje wpis bez zmiany active/deprecated."""
    mf = tmp_path / "generated" / "demo" / "manifest.json"
    update_manifest(mf, _gen(version="1"))
    first = json.loads(mf.read_text("utf-8"))

    update_manifest(mf, _gen(version="1"))
    second = json.loads(mf.read_text("utf-8"))

    assert first["blueprints"]["sample"]["active_version"] == "1"
    assert second["blueprints"]["sample"]["active_version"] == "1"
    assert second["blueprints"]["sample"]["deprecated_versions"] == []


def test_update_manifest_multiple_blueprints_same_tenant(tmp_path: Path) -> None:
    mf = tmp_path / "generated" / "demo" / "manifest.json"
    update_manifest(mf, _gen(bp="onboarding", version="1"))
    update_manifest(mf, _gen(bp="invoice_review", version="1"))
    update_manifest(mf, _gen(bp="onboarding", version="2"))

    data = json.loads(mf.read_text("utf-8"))
    assert set(data["blueprints"].keys()) == {"onboarding", "invoice_review"}
    assert data["blueprints"]["onboarding"]["active_version"] == "2"
    assert "1" in data["blueprints"]["onboarding"]["deprecated_versions"]
    assert data["blueprints"]["invoice_review"]["active_version"] == "1"


def test_update_manifest_carries_build_id_lineage(tmp_path: Path) -> None:
    mf = tmp_path / "generated" / "demo" / "manifest.json"
    update_manifest(mf, _gen(version="1"), build_id="build-abc")
    update_manifest(mf, _gen(version="2"), build_id="build-def")

    data = json.loads(mf.read_text("utf-8"))
    versions = data["blueprints"]["sample"]["versions"]
    assert versions["1"]["build_id"] == "build-abc"
    assert versions["2"]["build_id"] == "build-def"
