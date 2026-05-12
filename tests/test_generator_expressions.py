"""Integration tests: generator produces Python with runtime-evaluated ${ } expressions.

S2 acceptance: blueprint with for_each + with-block expressions generates valid Python
where each ${...} value is replaced by _eval(normalized_program, ctx) call.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from generator import generate
from ir import (
    CallTask,
    Document,
    ForTask,
    ToolFunction,
    Use,
    Workflow,
)

# ---------- Helpers ---------------------------------------------------------------

_RF_INVOICE_BATCH = (
    Path(__file__).parent.parent / "blueprints" / "demo" / "invoice_batch" / "v1" / "reactflow.json"
)


def _minimal_workflow_with_for_each() -> Workflow:
    """Minimal Workflow IR with a for_each containing with-block expressions."""
    return Workflow(
        document=Document(
            dsl="1.0.0",
            namespace="test",
            name="expr_test",
            version="1",
        ),
        use=Use(
            functions={
                "upload": ToolFunction(
                    name="upload",
                    module="activities.tools.upload_mock",
                    operation="upload",
                )
            }
        ),
        do=[
            {
                "loop": ForTask(
                    **{"for": {"each": "file", "in": ".input.files"}},
                    do=[
                        {
                            "archive": CallTask(
                                call="upload",
                                **{
                                    "with": {
                                        "bucket": "demo-bucket",
                                        "file_name": "${ $file.name }",
                                        "mime": "${ $file.mime }",
                                    }
                                },
                            )
                        }
                    ],
                )
            }
        ],
    )


# ---------- _build_with_code via generated source --------------------------------


def test_generated_code_contains_eval_for_file_name() -> None:
    wf = _minimal_workflow_with_for_each()
    result = generate(wf, tenant_id="test")
    assert '_eval(".file.name", ctx)' in result.source


def test_generated_code_contains_eval_for_file_mime() -> None:
    wf = _minimal_workflow_with_for_each()
    result = generate(wf, tenant_id="test")
    assert '_eval(".file.mime", ctx)' in result.source


def test_generated_code_preserves_literal_bucket() -> None:
    wf = _minimal_workflow_with_for_each()
    result = generate(wf, tenant_id="test")
    assert "demo-bucket" in result.source
    assert "_eval(" not in result.source.split("demo-bucket")[0].rsplit("{", 1)[-1]


def test_generated_code_has_for_loop_with_eval() -> None:
    wf = _minimal_workflow_with_for_each()
    result = generate(wf, tenant_id="test")
    assert "for file in _eval(" in result.source
    assert "ctx[" in result.source


def test_generated_code_is_valid_python_syntax() -> None:
    """Generated source must be parseable Python."""
    import ast

    wf = _minimal_workflow_with_for_each()
    result = generate(wf, tenant_id="test")
    ast.parse(result.source)  # raises SyntaxError if invalid


# ---------- invoice_batch blueprint integration -----------------------------------


@pytest.fixture(scope="module")
def invoice_batch_source() -> str:
    """Generate Python code from the real invoice_batch v1 blueprint."""
    from mapper import map_reactflow_to_cncfsw

    rf = json.loads(_RF_INVOICE_BATCH.read_text("utf-8"))
    wf = map_reactflow_to_cncfsw(rf)
    return generate(wf, tenant_id="demo").source


def test_invoice_batch_generated_code_is_valid_python(invoice_batch_source: str) -> None:
    import ast

    ast.parse(invoice_batch_source)


def test_invoice_batch_archive_file_name_uses_eval(invoice_batch_source: str) -> None:
    assert '_eval(".file.name", ctx)' in invoice_batch_source


def test_invoice_batch_archive_file_mime_uses_eval(invoice_batch_source: str) -> None:
    assert '_eval(".file.mime", ctx)' in invoice_batch_source


def test_invoice_batch_archive_data_b64_uses_eval(invoice_batch_source: str) -> None:
    assert '_eval(".file.data_b64", ctx)' in invoice_batch_source


def test_invoice_batch_extract_uses_eval(invoice_batch_source: str) -> None:
    """invoice_extraction step: both with-block values are ${ $file.* } expressions."""
    assert '_eval(".file.data_b64", ctx)' in invoice_batch_source
    assert '_eval(".file.mime", ctx)' in invoice_batch_source


def test_invoice_batch_for_loop_iterates_over_files(invoice_batch_source: str) -> None:
    assert 'for file in _eval(".input.files", ctx):' in invoice_batch_source


def test_invoice_batch_ctx_file_set_in_loop(invoice_batch_source: str) -> None:
    assert (
        "ctx['file'] = file" in invoice_batch_source or 'ctx["file"] = file' in invoice_batch_source
    )


def test_invoice_batch_specialized_agent_with_eval(invoice_batch_source: str) -> None:
    """posting_recommendation (SpecializedAgent) with expression in its with-block."""
    assert "_eval(" in invoice_batch_source
    assert "posting_recommendation" in invoice_batch_source


def test_invoice_batch_write_postings_has_literal_tenant(invoice_batch_source: str) -> None:
    """write_artifact has a literal tenant_id (not an expression)."""
    assert (
        "'tenant_id': 'demo'" in invoice_batch_source
        or '"tenant_id": "demo"' in invoice_batch_source
    )


def test_invoice_batch_no_raw_expression_strings(invoice_batch_source: str) -> None:
    """No ${ ... } raw strings must survive into generated Python (all resolved to _eval calls)."""
    import re

    # Raw expression strings would appear as: "${ ... }" in the generated source
    raw_exprs = re.findall(r'"\$\{', invoice_batch_source)
    assert raw_exprs == [], f"Raw ${{}} expressions found in generated code: {raw_exprs}"


# ---------- expression_eval contract (S2 acceptance) ------------------------------


def test_context_file_is_set_before_activity_calls() -> None:
    """Generated for_each body sets ctx['file'] = file before any activity call."""
    wf = _minimal_workflow_with_for_each()
    result = generate(wf, tenant_id="test")
    # Find position of ctx assignment and first execute_activity call
    src = result.source
    ctx_assign_pos = src.find("ctx[")
    activity_pos = src.find("execute_activity(")
    assert ctx_assign_pos != -1, "ctx assignment not found"
    assert activity_pos != -1, "execute_activity not found"
    assert ctx_assign_pos < activity_pos, "ctx must be set before execute_activity"
