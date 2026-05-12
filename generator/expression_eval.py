"""Expression evaluator for ${ ... } placeholders in with-blocks (S2).

Decyzja #15 / S2: ewaluacja wyrażeń jq w blokach `with` IR.

Context dict keys:
- `input`   — engagement input (dict)
- `steps`   — accumulated step outputs (dict keyed by task name)
- `file`    — current for_each iteration item (present inside a loop)
- any other key accessible as `.key` in jq programs

Variable refs `$var` in expressions are normalized to `.var` (field access on the
context dict), so `$file.name` becomes `.file.name` evaluated against the context.
"""

from __future__ import annotations

import re
from typing import Any

import jq

_EXPR_RE = re.compile(r"^\$\{([^}]*)\}$")
_VAR_RE = re.compile(r"\$(\w+)")

_JQ_CACHE: dict[str, Any] = {}


def is_expression(value: Any) -> bool:
    """Return True iff value is a ${ ... } template expression string."""
    return isinstance(value, str) and bool(_EXPR_RE.match(value))


def extract_program(expression: str) -> str:
    """Extract and normalize jq program from a ${ ... } expression.

    Raises ValueError if expression is not a ${ } template.
    Normalization: `$var` → `.var` (variable ref becomes field access on context dict).
    """
    m = _EXPR_RE.match(expression)
    if not m:
        raise ValueError(f"Not a ${{}} expression: {expression!r}")
    raw = m.group(1).strip()
    return _VAR_RE.sub(lambda match: f".{match.group(1)}", raw)


def evaluate(expression: str, context: dict[str, Any]) -> Any:
    """Evaluate a ${ jq_program } expression against context.

    Non-expression strings are returned unchanged.
    Raises ValueError on jq compilation or evaluation error.
    """
    m = _EXPR_RE.match(expression)
    if not m:
        return expression
    program = _VAR_RE.sub(lambda match: f".{match.group(1)}", m.group(1).strip())
    try:
        if program not in _JQ_CACHE:
            _JQ_CACHE[program] = jq.compile(program)
        return _JQ_CACHE[program].input(context).first()
    except Exception as exc:
        raise ValueError(f"Expression eval failed {expression!r}: {exc}") from exc


def resolve_with(with_dict: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Resolve all ${ ... } expressions in with-block values against context."""
    return {k: evaluate(v, context) if is_expression(v) else v for k, v in with_dict.items()}
