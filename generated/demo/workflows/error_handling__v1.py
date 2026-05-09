# Generated from Blueprint demo/error_handling v1 at 2026-05-09T15:09:53+00:00
# Source hash: 86f61cd088b7464a66b7ec5f6688c47d5775c03ae5451327e6285d561b70819c
# DO NOT EDIT — regeneruj przez generator (`scripts/regenerate_*` lub publish flow).
from __future__ import annotations
import asyncio
from datetime import timedelta
from typing import Any
import jq
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

_JQ_CACHE: dict[str, Any] = {}


def _eval(expr: str, ctx: dict[str, Any]) -> Any:
    """Wyewaluuj wyrażenie JQ przez kontekst.

    Action item (#15): zweryfikować że libjq nie łamie Workflow Sandbox.
    Fallback: przenieść do activity (deterministic eval).
    """
    prog = _JQ_CACHE.get(expr)
    if prog is None:
        prog = jq.compile(expr)
        _JQ_CACHE[expr] = prog
    return prog.input(ctx).first()


@workflow.defn(name="error_handling")
class ErrorHandling_v1:

    @workflow.run
    async def run(self, input: dict[str, Any]) -> dict[str, Any]:
        steps_output: dict[str, Any] = {}
        ctx: dict[str, Any] = {"input": input, "steps": steps_output}
        try:
            raise ApplicationError("ValidationError", non_retryable=True)
        except ApplicationError as err:
            steps_output["recover"] = {"error_caught": "ValidationError", "recovered": True}
        return steps_output
