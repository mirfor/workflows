"""Update manifestu per Tenant `generated/<tenant_id>/manifest.json` (decyzje #4, #14, #17).

Format:
```
{
  "schema_version": "1.0",
  "tenant_id": "<tenant>",
  "blueprints": {
    "<id>": {
      "active_version": "<n>",
      "deprecated_versions": ["<m>", ...],
      "versions": {
        "<n>": { "file_path": "...", "source_hash": "...", "build_id": "...",
                  "generated_at": "<iso>", "class_name": "..." },
        ...
      }
    }
  }
}
```
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from generator.codegen import GeneratedWorkflow

MANIFEST_VERSION = "1.0"


def manifest_path_for(repo_root: Path, tenant_id: str) -> Path:
    """Kanoniczna ścieżka manifestu per Tenant (decyzja #4)."""
    return repo_root / "generated" / tenant_id / "manifest.json"


def update_manifest(
    manifest_path: Path,
    gen: GeneratedWorkflow,
    *,
    build_id: str | None = None,
    generated_at: str | None = None,
    activate: bool = True,
) -> dict[str, Any]:
    """Wczytaj `manifest_path`, dodaj wpis, atomowo zapisz. Zwraca zaktualizowany manifest.

    `manifest_path` MUSI być per-Tenant — `generated/<tenant_id>/manifest.json` (decyzja #4).
    Walidator sprawdza spójność `gen.tenant_id` z `manifest_path`.
    """
    expected_segment = f"generated/{gen.tenant_id}/manifest.json"
    if not str(manifest_path).endswith(expected_segment):
        raise ValueError(
            f"Manifest path {manifest_path} nie jest per-Tenant zgodny z "
            f"`gen.tenant_id={gen.tenant_id}` (oczekiwane: ...{expected_segment})."
        )

    manifest = _read(manifest_path, tenant_id=gen.tenant_id)

    bp = manifest["blueprints"].setdefault(
        gen.blueprint_id,
        {"active_version": None, "deprecated_versions": [], "versions": {}},
    )

    bp["versions"][gen.version] = {
        "file_path": gen.relative_path,
        "class_name": gen.class_name,
        "source_hash": gen.source_hash,
        "build_id": build_id,
        "generated_at": generated_at,
    }

    if activate:
        prev = bp.get("active_version")
        if prev and prev != gen.version and prev not in bp["deprecated_versions"]:
            bp["deprecated_versions"].append(prev)
        bp["active_version"] = gen.version

    _write_atomic(manifest_path, manifest)
    return manifest


def _read(path: Path, *, tenant_id: str) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": MANIFEST_VERSION, "tenant_id": tenant_id, "blueprints": {}}
    with path.open(encoding="utf-8") as f:
        m = json.load(f)
    m.setdefault("schema_version", MANIFEST_VERSION)
    m.setdefault("tenant_id", tenant_id)
    m.setdefault("blueprints", {})
    if m["tenant_id"] != tenant_id:
        raise ValueError(
            f"Manifest tenant_id mismatch: file={m['tenant_id']!r}, oczekiwano={tenant_id!r}"
        )
    return m


def _write_atomic(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
