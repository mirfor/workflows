# Generated from Blueprint sample v1 at 2026-05-09T16:00:00+00:00
# Source hash: b85a8d6da61d6f03a5f5d8175b4313f40f0905d94d347c3ed60a2b2aec28b99f
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


@workflow.defn(name="sample")
class Sample_v1:

    @workflow.run
    async def run(self, input: dict[str, Any]) -> dict[str, Any]:
        steps_output: dict[str, Any] = {}
        ctx: dict[str, Any] = {"input": input, "steps": steps_output}
        log_intro = await workflow.execute_activity(
            activities.tools.log_message.log_message,
            {"level": "INFO", "message": "Sample workflow started"},
            start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=timedelta(seconds=30.0),
        )
        steps_output["log_intro"] = log_intro
        if _eval('.input.tier == "vip"', ctx):
            steps_output["decision"] = "log_vip"
        else:
            steps_output["decision"] = "log_default"
        steps_output["log_default"] = {"next": "emit_regular", "path": "regular"}
        steps_output["log_vip"] = {"next": "emit_vip", "path": "vip"}
        workflow.logger.info({"event": {"msg": "Regular path taken", "tier": "regular"}})
        steps_output["emit_regular"] = {"msg": "Regular path taken", "tier": "regular"}
        workflow.logger.info({"event": {"msg": "VIP path taken", "tier": "vip"}})
        steps_output["emit_vip"] = {"msg": "VIP path taken", "tier": "vip"}
        return steps_output
