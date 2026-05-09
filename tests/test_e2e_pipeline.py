"""E2E pipeline test (offline; bez Temporal Server).

Pełny pipeline: RF JSON → IR → walidacja → generacja `.py` → import jako moduł →
sprawdzenie że workflow class jest valid Temporal `@workflow.defn`.

Pełny replay test (z lokalnym Temporal Server) odłożony — patrz F3.C.7 / F5.3 notes
w `docs/IMPLEMENTATION_PLAN.md`.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

from generator import generate
from mapper import map_reactflow_to_cncfsw
from validator import apply_default_timeout, validate

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RF = REPO_ROOT / "blueprints" / "sample" / "v1" / "reactflow.json"


def test_sample_blueprint_e2e_pipeline() -> None:
    """RF → IR → walidacja → generacja `.py` → import → workflow class introspection."""
    assert SAMPLE_RF.exists(), f"Brak sample RF JSON: {SAMPLE_RF}"
    rf = json.loads(SAMPLE_RF.read_text("utf-8"))

    # 1. Map RF → IR
    workflow = map_reactflow_to_cncfsw(rf)
    assert workflow.document.name == "sample"
    assert workflow.document.version == "1"
    assert workflow.metadata["weaver"]["trigger"]["type"] == "manual_trigger"

    # 2. Apply default timeout (idempotent — sample już ma `default_timeout`)
    apply_default_timeout(workflow)

    # 3. Validate — bez błędów, OK warningi
    report = validate(workflow)
    assert not report.has_errors, f"Walidator zgłosił błędy: {report.errors}"

    # 4. Generate `.py`
    gen = generate(workflow, generated_at=datetime(2026, 5, 9, 16, 0, 0, tzinfo=UTC))
    assert gen.file_name == "sample__v1.py"
    assert gen.class_name == "Sample_v1"
    assert gen.workflow_temporal_name == "sample"

    # 5. Importuj wygenerowany moduł jako prawdziwy moduł (jak Worker w `worker.py`)
    py_path = REPO_ROOT / "generated" / "workflows" / gen.file_name
    py_path.parent.mkdir(parents=True, exist_ok=True)
    py_path.write_text(gen.source, encoding="utf-8")

    spec = importlib.util.spec_from_file_location(f"_test_{gen.class_name}", py_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # 6. Sprawdź że klasa workflow istnieje i ma metadane Temporal `@workflow.defn`
    cls = getattr(module, gen.class_name, None)
    assert cls is not None, f"Klasa {gen.class_name} nie istnieje w wygenerowanym module."
    assert hasattr(cls, "__temporal_workflow_definition"), (
        "Klasa nie jest oznaczona @workflow.defn"
    )

    # 7. Source hash deterministyczny — re-generate da ten sam hash
    workflow2 = map_reactflow_to_cncfsw(rf)
    apply_default_timeout(workflow2)
    gen2 = generate(workflow2, generated_at=datetime(2026, 5, 9, 16, 0, 0, tzinfo=UTC))
    assert gen.source_hash == gen2.source_hash
    assert gen.source == gen2.source


def test_sample_blueprint_files_exist_on_disk() -> None:
    """Sample artifacts powinny być commit-ed: reactflow.json + cncf-sw.json + .py + manifest."""
    files = {
        "reactflow.json": REPO_ROOT / "blueprints" / "sample" / "v1" / "reactflow.json",
        "cncf-sw.json": REPO_ROOT / "blueprints" / "sample" / "v1" / "cncf-sw.json",
        "sample__v1.py": REPO_ROOT / "generated" / "workflows" / "sample__v1.py",
        "manifest.json": REPO_ROOT / "generated" / "manifest.json",
    }
    for name, path in files.items():
        assert path.exists(), f"Brak {name} ({path})"

    manifest = json.loads(files["manifest.json"].read_text("utf-8"))
    assert "sample" in manifest["blueprints"]
    assert manifest["blueprints"]["sample"]["active_version"] == "1"


def test_codegen_idempotency() -> None:
    """CI invariant: regenerate sample → byte-identical output (#17)."""
    rf = json.loads(SAMPLE_RF.read_text("utf-8"))
    wf = map_reactflow_to_cncfsw(rf)
    apply_default_timeout(wf)

    gen1 = generate(wf, generated_at=datetime(2026, 5, 9, 16, 0, 0, tzinfo=UTC))
    gen2 = generate(wf, generated_at=datetime(2026, 5, 9, 16, 0, 0, tzinfo=UTC))

    assert gen1.source == gen2.source
    assert gen1.source_hash == gen2.source_hash


def test_loaded_workflow_class_is_imported_via_spec() -> None:
    """Test alternatywny: import wygenerowanego pliku przez importlib (jak Worker)."""
    py_path = REPO_ROOT / "generated" / "workflows" / "sample__v1.py"
    if not py_path.exists():
        return  # pierwsze wykonanie — plik wygeneruje regenerate_workflow

    spec = importlib.util.spec_from_file_location("sample_v1", py_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    cls = module.Sample_v1
    assert hasattr(cls, "__temporal_workflow_definition")
