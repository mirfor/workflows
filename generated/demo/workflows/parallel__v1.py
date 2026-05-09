# Generated from Blueprint demo/parallel v1 at 2026-05-09T15:09:53+00:00
# Source hash: c7ff8600b273831d2e67242023290fec0f803e139a2cf4b1b8c554af945c1204
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


@workflow.defn(name="parallel")
class Parallel_v1:

    @workflow.run
    async def run(self, input: dict[str, Any]) -> dict[str, Any]:
        steps_output: dict[str, Any] = {}
        ctx: dict[str, Any] = {"input": input, "steps": steps_output}

        async def _branch_spread_0():
            steps_output["branch_a"] = {"name": "branch_a", "result": 1}

        async def _branch_spread_1():
            steps_output["branch_b"] = {"name": "branch_b", "result": 2}

        async def _branch_spread_2():
            steps_output["branch_c"] = {"name": "branch_c", "result": 3}

        await asyncio.gather(_branch_spread_0(), _branch_spread_1(), _branch_spread_2())
        steps_output["spread"] = "completed"
        return steps_output
