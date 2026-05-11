# Generated from Blueprint demo/order-flow-1778501238082 v1 at 2026-05-11T12:07:20+00:00
# Source hash: 58154deb7c8823ef5ea5e561a22b7ca72f89a022bfedfcfd0d06b9c55cc5b365
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
import activities.tools.http_get

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


@workflow.defn(name="order-flow-1778501238082")
class OrderFlow1778501238082_v1:

    @workflow.run
    async def run(self, input: dict[str, Any]) -> dict[str, Any]:
        steps_output: dict[str, Any] = {}
        ctx: dict[str, Any] = {"input": input, "steps": steps_output}
        log_intro = await workflow.execute_activity(
            activities.tools.log_message.log_message,
            {"level": "INFO", "message": "Order received — starting processing"},
            start_to_close_timeout=timedelta(seconds=30.0),
        )
        steps_output["log_intro"] = log_intro
        notify_email = await workflow.execute_activity(
            activities.tools.log_message.log_message,
            {"level": "INFO", "message": "Email queued for customer"},
            start_to_close_timeout=timedelta(seconds=30.0),
        )
        steps_output["notify_email"] = notify_email
        notify_log = await workflow.execute_activity(
            activities.tools.log_message.log_message,
            {"level": "INFO", "message": "Audit log entry written"},
            start_to_close_timeout=timedelta(seconds=30.0),
        )
        steps_output["notify_log"] = notify_log
        steps_output["notify_metric"] = {"metric_sent": True}
        fetch_data = await workflow.execute_activity(
            activities.tools.http_get.http_get,
            {"url": "https://httpbin.org/json"},
            start_to_close_timeout=timedelta(seconds=30.0),
        )
        steps_output["fetch_data"] = fetch_data
        steps_output["finalize"] = {"finalized_at": "now", "status": "completed"}
        steps_output["extract"] = {"amount": 250, "order_id": "ORD-12345", "tier": ".input.tier"}
        log_done = await workflow.execute_activity(
            activities.tools.log_message.log_message,
            {"level": "INFO", "message": "Order processing complete"},
            start_to_close_timeout=timedelta(seconds=30.0),
        )
        steps_output["log_done"] = log_done
        if _eval('.tier == "vip"', ctx):
            steps_output["decision"] = "log_vip"
        elif _eval('.tier == "standard"', ctx):
            steps_output["decision"] = "log_standard"
        elif _eval('.tier == "low"', ctx):
            steps_output["decision"] = "log_low"
        return steps_output
