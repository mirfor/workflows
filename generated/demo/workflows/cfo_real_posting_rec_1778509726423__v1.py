# Generated from Blueprint demo/cfo-real-posting-rec-1778509726423 v1 at 2026-05-11T14:28:53+00:00
# Source hash: ab9ef09a8d4dc765ec14383992bb907f5e54c4ecdee0d34b384dcaf68491f7c3
# DO NOT EDIT — regeneruj przez generator (`scripts/regenerate_*` lub publish flow).
from __future__ import annotations
import asyncio
from datetime import timedelta
from typing import Any
import jq
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
import activities.tools.http_get
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


@workflow.defn(name="cfo-real-posting-rec-1778509726423")
class CfoRealPostingRec1778509726423_v1:

    @workflow.run
    async def run(self, input: dict[str, Any]) -> dict[str, Any]:
        steps_output: dict[str, Any] = {}
        ctx: dict[str, Any] = {"input": input, "steps": steps_output}
        health_check = await workflow.execute_activity(
            activities.tools.http_get.http_get,
            {
                "headers": {"X-API-Key": "pk_demo_e2e_9b1ea024f9224052"},
                "url": "http://localhost:8100/health",
            },
            start_to_close_timeout=timedelta(seconds=30.0),
        )
        steps_output["health_check"] = health_check
        log_done = await workflow.execute_activity(
            activities.tools.log_message.log_message,
            {
                "level": "INFO",
                "message": "posting-rec reachable — X-API-Key header passed via http_get",
            },
            start_to_close_timeout=timedelta(seconds=30.0),
        )
        steps_output["log_done"] = log_done
        return steps_output
