# Generated from Blueprint demo/e2e-1778500854162 v1 at 2026-05-11T12:00:55+00:00
# Source hash: 0784b573029957d070e22175816f5534c5b53dc409d2d88f67d182ff11003345
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


@workflow.defn(name="e2e-1778500854162")
class E2e1778500854162_v1:

    @workflow.run
    async def run(self, input: dict[str, Any]) -> dict[str, Any]:
        steps_output: dict[str, Any] = {}
        ctx: dict[str, Any] = {"input": input, "steps": steps_output}
        log_intro = await workflow.execute_activity(
            activities.tools.log_message.log_message,
            {"level": "INFO", "message": "E2E run started"},
            start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=timedelta(seconds=30.0),
        )
        steps_output["log_intro"] = log_intro
        steps_output["log_done"] = {}
        return steps_output
