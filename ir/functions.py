"""Functions registry — wpisy w `Use.functions.<name>` (#7, #13, #18).

Tools (in-process activities) i Specialized Agents (osobne FastAPI serwisy).
`type` discriminuje sposób dispatchu w generatorze:
- `weaver_tool`        → import `module.operation`, wywołanie jako lokalna activity
- `weaver_specialized_agent` → generic dispatcher `call_specialized_agent(...)` przez HTTP

Schemy I/O = JSON Schema (eksportowany z Pydantic / FastAPI OpenAPI), referowany przez `$ref`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Discriminator, Field, Tag

from ir._base import StrictModel
from ir.errors import ErrorSpec


class _FunctionBase(StrictModel):
    name: str = Field(..., min_length=1)
    type: str
    operation: str
    """Nazwa metody/operation w docelowym module/serwisie."""
    input_schema: dict[str, Any] | str | None = Field(default=None, alias="inputSchema")
    """Inline JSON Schema albo `$ref` do `schemas/`."""
    output_schema: dict[str, Any] | str | None = Field(default=None, alias="outputSchema")
    errors: list[ErrorSpec] = Field(default_factory=list)
    default_retry_profile: str | None = Field(default=None, alias="defaultRetryProfile")
    """Referencja do `Use.retries.<name>`."""
    default_timeout_profile: str | None = Field(default=None, alias="defaultTimeoutProfile")
    idempotent: bool = False
    metadata: dict[str, Any] | None = None


class ToolFunction(_FunctionBase):
    type: Literal["weaver_tool"] = "weaver_tool"
    module: str = Field(..., min_length=1)
    """Python import path do modułu z `@activity.defn` (np. `activities.tools.gmail`)."""


class SpecializedAgentFunction(_FunctionBase):
    type: Literal["weaver_specialized_agent"] = "weaver_specialized_agent"
    endpoint_url: str = Field(..., alias="endpointUrl")
    openapi_url: str | None = Field(default=None, alias="openapiUrl")


def _function_discriminator(v: Any) -> str | None:
    if isinstance(v, dict):
        return v.get("type")
    return getattr(v, "type", None)


FunctionDefinition = Annotated[
    Annotated[ToolFunction, Tag("weaver_tool")]
    | Annotated[SpecializedAgentFunction, Tag("weaver_specialized_agent")],
    Discriminator(_function_discriminator),
]
