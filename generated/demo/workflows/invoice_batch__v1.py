# Generated from Blueprint demo/invoice_batch v1 at 2026-05-12T12:48:12+00:00
# Source hash: 59ddb8739f5ff6a1163f51aba4725709e294114906a3630b72e9ea16b8d637b1
# DO NOT EDIT — regeneruj przez generator (`scripts/regenerate_*` lub publish flow).
from __future__ import annotations
import asyncio
from datetime import timedelta
from typing import Any
import jq
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError
import activities.tools.docrepo_upload
import activities.tools.invoice_extraction
from activities.specialized_agents import call_specialized_agent
import activities.tools.write_artifact

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


@workflow.defn(name="invoice_batch")
class InvoiceBatch_v1:

    @workflow.run
    async def run(self, input: dict[str, Any]) -> dict[str, Any]:
        steps_output: dict[str, Any] = {}
        ctx: dict[str, Any] = {"input": input, "steps": steps_output}
        steps_output["loop"] = []
        for file in _eval(".input.files", ctx):
            ctx["file"] = file
            archive = await workflow.execute_activity(
                activities.tools.docrepo_upload.docrepo_upload,
                {
                    "collection_name": "agent-designer-demo-invoices",
                    "data_b64": _eval(".file.data_b64", ctx),
                    "file_name": _eval(".file.name", ctx),
                    "mime_type": _eval(".file.mime", ctx),
                },
                start_to_close_timeout=timedelta(minutes=3),
                heartbeat_timeout=timedelta(seconds=30.0),
            )
            steps_output["archive"] = archive
            extract = await workflow.execute_activity(
                activities.tools.invoice_extraction.invoice_extraction,
                {"data_b64": _eval(".file.data_b64", ctx), "mime_type": _eval(".file.mime", ctx)},
                start_to_close_timeout=timedelta(minutes=3),
                heartbeat_timeout=timedelta(seconds=30.0),
            )
            steps_output["extract"] = extract
            recommend = await workflow.execute_activity(
                call_specialized_agent,
                {
                    "agent": "posting_recommendation",
                    "endpoint_url": "http://localhost:8600",
                    "operation": "recommend",
                    "with": {"invoice": _eval(".extract.output.invoice", ctx)},
                },
                start_to_close_timeout=timedelta(minutes=3),
                heartbeat_timeout=timedelta(seconds=30.0),
            )
            steps_output["recommend"] = recommend
            steps_output["loop"].append(file)
        write_postings = await workflow.execute_activity(
            activities.tools.write_artifact.write_artifact,
            {
                "data": _eval(".loop.output", ctx),
                "engagement_id": _eval(".context.workflowId", ctx),
                "filename": "postings",
                "format": "json",
                "tenant_id": "demo",
            },
            start_to_close_timeout=timedelta(minutes=3),
            heartbeat_timeout=timedelta(seconds=30.0),
        )
        steps_output["write_postings"] = write_postings
        return steps_output
