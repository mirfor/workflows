"""Regeneruj jeden Blueprint: RF JSON → CNCF SW IR JSON → `.py` + manifest update.

Idempotentne (decyzja #17). Wywołanie:
```
uv run python -m scripts.regenerate_workflow blueprints/<id>/v<n>/reactflow.json
```
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from generator import generate, update_manifest
from mapper import map_reactflow_to_cncfsw
from validator import apply_default_timeout, validate

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED_WORKFLOWS = REPO_ROOT / "generated" / "workflows"
MANIFEST_PATH = REPO_ROOT / "generated" / "manifest.json"


def regenerate(rf_path: Path, *, activate: bool = True) -> dict[str, str]:
    """Pełny pipeline dla pojedynczego Blueprint × wersja. Zwraca dict z paths."""
    rf = json.loads(rf_path.read_text("utf-8"))

    # 1. Map RF → IR
    workflow = map_reactflow_to_cncfsw(rf)

    # 2. Auto-default_timeout (cascade — w produkcji wartości z Tenant/Client Org settings)
    apply_default_timeout(workflow)

    # 3. Validate
    report = validate(workflow)
    if report.has_errors:
        msgs = "\n".join(f"  - {i}" for i in report.errors)
        raise SystemExit(f"Walidator IR zgłosił {len(report.errors)} błędów:\n{msgs}")

    # 4. Save IR JSON next to RF JSON (Blueprint version dir)
    ir_path = rf_path.with_name("cncf-sw.json")
    ir_path.write_text(
        json.dumps(workflow.model_dump(by_alias=True, exclude_none=True), indent=2, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )

    # 5. Generate `.py`
    ts = datetime.now(tz=UTC)
    gen = generate(workflow, generated_at=ts)
    GENERATED_WORKFLOWS.mkdir(parents=True, exist_ok=True)
    py_path = GENERATED_WORKFLOWS / gen.file_name
    py_path.write_text(gen.source, encoding="utf-8")

    # 6. Update manifest
    update_manifest(
        MANIFEST_PATH, gen,
        build_id=None,  # CI ustala (sha krótki commit)
        generated_at=ts.isoformat(timespec="seconds"),
        activate=activate,
    )

    return {
        "blueprint_id": gen.blueprint_id,
        "version": gen.version,
        "ir_path": str(ir_path.relative_to(REPO_ROOT)),
        "py_path": str(py_path.relative_to(REPO_ROOT)),
        "source_hash": gen.source_hash,
        "warnings": [str(i) for i in report.warnings],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate a single Blueprint version.")
    parser.add_argument("rf_path", type=Path, help="Path to reactflow.json")
    parser.add_argument("--no-activate", action="store_true", help="Skip activation in manifest")
    args = parser.parse_args()

    result = regenerate(args.rf_path.resolve(), activate=not args.no_activate)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
