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
import re
from datetime import UTC, datetime
from pathlib import Path

from generator import compute_source_hash, generate, manifest_path_for, update_manifest
from mapper import map_reactflow_to_cncfsw
from validator import apply_default_timeout, validate

REPO_ROOT = Path(__file__).resolve().parents[1]

# Idempotency — gdy source_hash istniejącego `.py` matches obliczonego z aktualnego IR,
# nie regenerujemy pliku (zachowanie pierwotnego `generated_at` w headerze).
# Wzorzec dopasowuje "Source hash: <sha>" + "at <iso8601>" w headerze pliku.
_HEADER_HASH_RE = re.compile(r"^# Source hash:\s*([0-9a-f]+)\s*$", re.MULTILINE)
_HEADER_TS_RE = re.compile(
    r"^# Generated from Blueprint .+? at (?P<ts>[0-9T:+\-]+)\s*$", re.MULTILINE
)


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


def _existing_timestamp_if_hash_matches(py_path: Path, expected_hash: str) -> str | None:
    """Czytaj header istniejącego `.py`. Jeśli source_hash matches, zwróć stary timestamp.

    Idempotency: niezmieniony IR → nie zmieniamy `generated_at` (CI codegen-idempotency check).
    """
    if not py_path.exists():
        return None
    content = py_path.read_text(encoding="utf-8")
    hash_m = _HEADER_HASH_RE.search(content)
    ts_m = _HEADER_TS_RE.search(content)
    if hash_m and ts_m and hash_m.group(1) == expected_hash:
        return ts_m.group("ts")
    return None


def regenerate(rf_path: Path, *, activate: bool = True) -> dict[str, str | list[str]]:
    """Pełen pipeline dla pojedynczego Blueprint × wersja. Zwraca dict z paths.

    Idempotentny: jeśli IR ma ten sam source_hash co istniejący `.py`, zachowujemy
    pierwotny `generated_at` (zarówno w headerze pliku jak i w manifeście) — pliki
    zostają byte-identyczne, CI codegen-idempotency check przechodzi.
    """
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

    # 5. Compute source hash before generate, sprawdź idempotency
    new_hash = compute_source_hash(workflow)
    py_path = REPO_ROOT / "generated" / tenant_id / "workflows"
    py_path.mkdir(parents=True, exist_ok=True)

    # _to_snake nazywa: weaver-style "hello_world" → "hello_world__v1.py"
    # Rekonstrukcja sciezki bez wywoływania `generate()` — używamy tego samego algorytmu
    snake = re.sub(r"[^a-zA-Z0-9]+", "_", workflow.document.name).strip("_").lower()
    py_full_path = py_path / f"{snake}__v{workflow.document.version}.py"

    existing_ts = _existing_timestamp_if_hash_matches(py_full_path, new_hash)
    if existing_ts is not None:
        ts_str = existing_ts
        ts = datetime.fromisoformat(existing_ts)
    else:
        ts = datetime.now(tz=UTC)
        ts_str = ts.isoformat(timespec="seconds")

    # 6. Generate `.py` per Tenant z deterministic timestamp
    gen = generate(workflow, tenant_id=tenant_id, generated_at=ts)
    target_path = REPO_ROOT / gen.relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(gen.source, encoding="utf-8")

    # 7. Update manifest per Tenant z deterministic timestamp
    update_manifest(
        manifest_path_for(REPO_ROOT, tenant_id), gen,
        build_id=None,
        generated_at=ts_str,
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
