"""Regeneruj jeden Blueprint: RF JSON → CNCF SW IR JSON → `.py` + manifest update.

Multi-tenant aware (decyzja #4) — `tenant_id` jest wymagany.

Wywołanie:
```
uv run python -m scripts.regenerate_workflow blueprints/<tenant>/<bp>/v<n>/reactflow.json
```

Idempotentne (decyzja #17).
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from generator import generate, manifest_path_for, update_manifest
from mapper import map_reactflow_to_cncfsw
from validator import apply_default_timeout, validate

REPO_ROOT = Path(__file__).resolve().parents[1]


def _resolve_tenant_from_path(rf_path: Path) -> tuple[str, str, str]:
    """Z `blueprints/<tenant>/<bp>/v<n>/reactflow.json` wyłuska (tenant, bp, version).

    Walidator sprawdza że ścieżka jest zgodna z multi-tenant layoutem (decyzja #4).
    """
    parts = rf_path.resolve().relative_to(REPO_ROOT).parts
    if len(parts) < 5 or parts[0] != "blueprints" or not parts[3].startswith("v"):
        raise SystemExit(
            f"Niewłaściwy layout RF JSON: {rf_path}. "
            f"Oczekiwany: blueprints/<tenant>/<bp>/v<n>/reactflow.json (decyzja #4)."
        )
    tenant_id = parts[1]
    blueprint_dir = parts[2]
    version = parts[3][1:]
    return tenant_id, blueprint_dir, version


def regenerate(rf_path: Path, *, activate: bool = True) -> dict[str, str | list[str]]:
    """Pełen pipeline dla pojedynczego Blueprint × wersja. Zwraca dict z paths."""
    tenant_id, _bp_dir_name, _version = _resolve_tenant_from_path(rf_path)
    rf = json.loads(rf_path.read_text("utf-8"))

    # 1. Map RF → IR
    workflow = map_reactflow_to_cncfsw(rf)

    # 2. Auto-default_timeout (cascade w produkcji z Tenant/Client Org settings)
    apply_default_timeout(workflow)

    # 3. Validate
    report = validate(workflow)
    if report.has_errors:
        msgs = "\n".join(f"  - {i}" for i in report.errors)
        raise SystemExit(f"Walidator IR zgłosił {len(report.errors)} błędów:\n{msgs}")

    # 4. Save IR JSON next to RF JSON
    ir_path = rf_path.with_name("cncf-sw.json")
    ir_path.write_text(
        json.dumps(workflow.model_dump(by_alias=True, exclude_none=True), indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    # 5. Generate `.py` per Tenant
    ts = datetime.now(tz=UTC)
    gen = generate(workflow, tenant_id=tenant_id, generated_at=ts)
    py_path = REPO_ROOT / gen.relative_path
    py_path.parent.mkdir(parents=True, exist_ok=True)
    py_path.write_text(gen.source, encoding="utf-8")

    # 6. Update manifest per Tenant
    update_manifest(
        manifest_path_for(REPO_ROOT, tenant_id), gen,
        build_id=None,  # CI ustala (sha krótki commit)
        generated_at=ts.isoformat(timespec="seconds"),
        activate=activate,
    )

    return {
        "tenant_id": tenant_id,
        "blueprint_id": gen.blueprint_id,
        "version": gen.version,
        "ir_path": str(ir_path.relative_to(REPO_ROOT)),
        "py_path": gen.relative_path,
        "source_hash": gen.source_hash,
        "warnings": [str(i) for i in report.warnings],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate a single Blueprint version.")
    parser.add_argument("rf_path", type=Path, help="Path to reactflow.json (multi-tenant layout)")
    parser.add_argument("--no-activate", action="store_true", help="Skip activation in manifest")
    args = parser.parse_args()

    result = regenerate(args.rf_path.resolve(), activate=not args.no_activate)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
