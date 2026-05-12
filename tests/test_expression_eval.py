"""Unit tests for generator/expression_eval.py — S2 expression evaluation."""

from __future__ import annotations

import pytest

from generator.expression_eval import (
    evaluate,
    extract_program,
    is_expression,
    resolve_with,
)

# ---------- is_expression ---------------------------------------------------------


def test_is_expression_returns_true_for_dollar_brace() -> None:
    assert is_expression("${ .input.files }") is True


def test_is_expression_returns_true_with_variable_ref() -> None:
    assert is_expression("${ $file.name }") is True


def test_is_expression_returns_false_for_plain_string() -> None:
    assert is_expression("agent-designer-demo-invoices") is False


def test_is_expression_returns_false_for_empty_string() -> None:
    assert is_expression("") is False


def test_is_expression_returns_false_for_non_string() -> None:
    assert is_expression(42) is False
    assert is_expression(None) is False
    assert is_expression({"key": "val"}) is False


def test_is_expression_requires_exact_wrapping() -> None:
    assert is_expression("prefix ${ .x }") is False
    assert is_expression("${ .x } suffix") is False


# ---------- extract_program -------------------------------------------------------


def test_extract_program_strips_wrapper_and_whitespace() -> None:
    assert extract_program("${ .input.files }") == ".input.files"


def test_extract_program_normalizes_variable_ref() -> None:
    assert extract_program("${ $file.name }") == ".file.name"


def test_extract_program_normalizes_multiple_vars() -> None:
    result = extract_program("${ $file.name + $ctx.id }")
    assert result == ".file.name + .ctx.id"


def test_extract_program_raises_on_non_expression() -> None:
    with pytest.raises(ValueError, match="Not a"):
        extract_program("plain string")


def test_extract_program_no_spaces_in_braces() -> None:
    assert extract_program("${.input}") == ".input"


# ---------- evaluate — basic cases ------------------------------------------------


def test_evaluate_simple_input_path() -> None:
    ctx = {"input": {"batch_size": 10}, "steps": {}}
    assert evaluate("${ .input.batch_size }", ctx) == 10


def test_evaluate_nested_step_output() -> None:
    ctx = {"input": {}, "steps": {"extract": {"invoice_data": {"total": 99.9}}}}
    result = evaluate("${ .steps.extract.invoice_data.total }", ctx)
    assert result == 99.9


def test_evaluate_file_variable_ref() -> None:
    ctx = {
        "input": {},
        "steps": {},
        "file": {"name": "invoice.pdf", "mime": "application/pdf"},
    }
    assert evaluate("${ $file.name }", ctx) == "invoice.pdf"
    assert evaluate("${ $file.mime }", ctx) == "application/pdf"


def test_evaluate_file_data_b64() -> None:
    ctx = {"input": {}, "steps": {}, "file": {"data_b64": "abc123=="}}
    assert evaluate("${ $file.data_b64 }", ctx) == "abc123=="


def test_evaluate_returns_non_expression_unchanged() -> None:
    ctx: dict = {}
    assert evaluate("plain value", ctx) == "plain value"
    assert evaluate("", ctx) == ""


def test_evaluate_returns_list_from_jq() -> None:
    ctx = {"input": {"items": [1, 2, 3]}, "steps": {}}
    assert evaluate("${ .input.items }", ctx) == [1, 2, 3]


def test_evaluate_returns_none_for_missing_key() -> None:
    ctx = {"input": {}, "steps": {}}
    assert evaluate("${ .input.missing }", ctx) is None


def test_evaluate_raises_on_invalid_jq_program() -> None:
    ctx = {"input": {}, "steps": {}}
    with pytest.raises(ValueError, match="Expression eval failed"):
        evaluate("${ @@invalid@@ }", ctx)


def test_evaluate_integer_result() -> None:
    ctx = {"input": {"count": 5}, "steps": {}}
    result = evaluate("${ .input.count }", ctx)
    assert result == 5
    assert isinstance(result, int)


def test_evaluate_boolean_result() -> None:
    ctx = {"input": {"active": True}, "steps": {}}
    assert evaluate("${ .input.active }", ctx) is True


# ---------- resolve_with ----------------------------------------------------------


def test_resolve_with_replaces_expressions_leaves_literals() -> None:
    ctx = {
        "input": {},
        "steps": {},
        "file": {"name": "invoice.pdf", "mime": "application/pdf", "data_b64": "abc="},
    }
    with_dict = {
        "collection_name": "agent-designer-demo-invoices",
        "file_name": "${ $file.name }",
        "mime_type": "${ $file.mime }",
        "data_b64": "${ $file.data_b64 }",
    }
    result = resolve_with(with_dict, ctx)
    assert result["collection_name"] == "agent-designer-demo-invoices"
    assert result["file_name"] == "invoice.pdf"
    assert result["mime_type"] == "application/pdf"
    assert result["data_b64"] == "abc="


def test_resolve_with_empty_dict() -> None:
    assert resolve_with({}, {}) == {}


def test_resolve_with_no_expressions() -> None:
    with_dict = {"key": "value", "num": 42}
    result = resolve_with(with_dict, {})
    assert result == {"key": "value", "num": 42}


def test_resolve_with_steps_reference() -> None:
    ctx = {
        "input": {},
        "steps": {"extract": {"invoice": {"vendor": "ACME"}}},
    }
    with_dict = {"invoice": "${ .steps.extract.invoice }"}
    result = resolve_with(with_dict, ctx)
    assert result["invoice"] == {"vendor": "ACME"}


# ---------- jq cache is shared between calls (no mutation test) -------------------


def test_evaluate_uses_cached_program_consistently() -> None:
    ctx1 = {"input": {"x": 1}, "steps": {}}
    ctx2 = {"input": {"x": 2}, "steps": {}}
    expr = "${ .input.x }"
    assert evaluate(expr, ctx1) == 1
    assert evaluate(expr, ctx2) == 2
