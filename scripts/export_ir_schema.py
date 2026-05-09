"""Export JSON Schema z Pydantic models w `ir/` do `schemas/ir.schema.json`.

Idempotentny: regeneracja produkuje identyczny plik. Wywoływane w CI (idempotency check).
"""

from __future__ import annotations

import json
from pathlib import Path

from ir import Workflow

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "ir.schema.json"
SCHEMA_ID = "https://workflows.weaver/schemas/ir.schema.json"
SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"


def build_schema() -> dict:
    schema = Workflow.model_json_schema(by_alias=True)
    schema["$id"] = SCHEMA_ID
    schema["$schema"] = SCHEMA_DRAFT
    schema["title"] = "Workflow Platform Temporal — CNCF SW 1.0 IR"
    schema["description"] = (
        "JSON Schema dla CNCF Serverless Workflow 1.0 IR z extensions Weaver/Temporal. "
        "Auto-generated z Pydantic models w `ir/`. "
        "NIE EDYTOWAĆ RĘCZNIE — regeneruj przez `uv run python -m scripts.export_ir_schema`."
    )
    return schema


def main() -> None:
    schema = build_schema()
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {SCHEMA_PATH} ({SCHEMA_PATH.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
