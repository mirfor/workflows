"""Tool: `write_artifact` — persist engagement output (JSON / CSV) to a local
artifact store and return a stable URL.

The artifact root is configurable via `ARTIFACT_ROOT` (default `/tmp/agent-designer-artifacts`).
Artifacts are namespaced by tenant + engagement id so listing is deterministic.

For CSV, the input must be a list of flat dicts (no nested objects); column
order is taken from the first row.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from temporalio import activity
from temporalio.exceptions import ApplicationError

from activities.tools._heartbeat import safe_heartbeat

_ARTIFACT_ROOT = Path(os.environ.get("ARTIFACT_ROOT", "/tmp/agent-designer-artifacts"))
_PUBLIC_BASE = os.environ.get("ARTIFACT_PUBLIC_BASE_URL", "file://").rstrip("/")
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class WriteArtifactInput(BaseModel):
    tenant_id: str = Field(..., min_length=1)
    engagement_id: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1)
    format: Literal["json", "csv"]
    data: Any = Field(
        ...,
        description="For JSON: any value. For CSV: list[dict[str, scalar]] with consistent keys.",
    )


class WriteArtifactOutput(BaseModel):
    artifact_url: str
    absolute_path: str
    bytes: int
    format: Literal["json", "csv"]


def _safe_segment(value: str) -> str:
    cleaned = _SAFE_NAME.sub("_", value).strip("_") or "x"
    return cleaned[:120]


def _render_csv(rows: Any) -> bytes:
    if not isinstance(rows, list) or not rows:
        raise ApplicationError(
            "CSV format requires a non-empty list of dicts.",
            type="ValidationError",
            non_retryable=True,
        )
    if not all(isinstance(r, dict) for r in rows):
        raise ApplicationError(
            "CSV rows must be dicts.",
            type="ValidationError",
            non_retryable=True,
        )
    columns = list(rows[0].keys())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


@activity.defn(name="write_artifact")
async def write_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    safe_heartbeat("started")
    parsed = WriteArtifactInput.model_validate(payload)

    if parsed.format == "json":
        body = json.dumps(parsed.data, ensure_ascii=False, indent=2).encode("utf-8")
    else:
        body = _render_csv(parsed.data)

    tenant_dir = (
        _ARTIFACT_ROOT / _safe_segment(parsed.tenant_id) / _safe_segment(parsed.engagement_id)
    )
    tenant_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_segment(parsed.filename)
    if not safe_name.lower().endswith(f".{parsed.format}"):
        safe_name = f"{safe_name}.{parsed.format}"
    path = tenant_dir / safe_name
    path.write_bytes(body)

    rel = path.relative_to(_ARTIFACT_ROOT).as_posix()
    url = f"{_PUBLIC_BASE}/{rel}" if _PUBLIC_BASE else f"file://{path}"

    safe_heartbeat("completed")
    return WriteArtifactOutput(
        artifact_url=url,
        absolute_path=str(path),
        bytes=len(body),
        format=parsed.format,
    ).model_dump()


TOOL_MANIFEST: dict[str, Any] = {
    "name": "write_artifact",
    "operation": "write_artifact",
    "input_schema": WriteArtifactInput.model_json_schema(),
    "output_schema": WriteArtifactOutput.model_json_schema(),
    "errors": [
        {"type": "ValidationError", "is_base": True, "retryable": False},
    ],
    "default_retry_profile": None,
    "default_timeout_profile": "default_timeout",
    "idempotent": True,
}
