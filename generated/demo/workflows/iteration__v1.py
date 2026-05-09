# Generated from Blueprint demo/iteration v1 at 2026-05-09T15:09:53+00:00
# Source hash: 6511caac8bd194fb0d810213b0f5af4cee14b3f61b91e89ec1456f838bc79210
# DO NOT EDIT — regeneruj przez generator (`scripts/regenerate_*` lub publish flow).
from __future__ import annotations
import asyncio
from datetime import timedelta
from typing import Any
import jq
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
import activities.tools.log_message

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


@workflow.defn(name="iteration")
class Iteration_v1:

    @workflow.run
    async def run(self, input: dict[str, Any]) -> dict[str, Any]:
        steps_output: dict[str, Any] = {}
        ctx: dict[str, Any] = {"input": input, "steps": steps_output}
        steps_output["loop"] = []
        for item in _eval(".input.items", ctx):
            ctx["item"] = item
            steps_output["log_each"] = {"ref": "$item"}
            steps_output["loop"].append(item)
        return steps_output
