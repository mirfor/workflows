"""Top-level CNCF Serverless Workflow document (#5).

Workflow = Document header + Input + Output + Use (registry) + do[] (tasks) + metadata.
Trigger trzyma się w `metadata.weaver.trigger` (#10).
Workflow-level timeout w `metadata.temporal.workflow_run_timeout` (#27).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ir._base import IsoDuration, JqExpression, StrictModel
from ir.errors import ErrorDefinition
from ir.functions import FunctionDefinition
from ir.policies import RetryPolicy, TimeoutPolicy
from ir.tasks import NamedTask
from ir.triggers import Trigger


class Document(StrictModel):
    dsl: Literal["1.0.0"] = "1.0.0"
    namespace: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    """Forma `<n>` lub `<major>.<minor>.<patch>` — wersja Blueprintu."""
    summary: str | None = None
    metadata: dict[str, Any] | None = None


class Input(StrictModel):
    schema_: dict[str, Any] | str | None = Field(default=None, alias="schema")
    from_: JqExpression | None = Field(default=None, alias="from")


class Output(StrictModel):
    schema_: dict[str, Any] | str | None = Field(default=None, alias="schema")
    as_: JqExpression | None = Field(default=None, alias="as")


class Use(StrictModel):
    """Reusable definitions per CNCF SW spec — referowane przez nazwę z task fields."""

    authentications: dict[str, dict[str, Any]] = Field(default_factory=dict)
    errors: dict[str, ErrorDefinition] = Field(default_factory=dict)
    extensions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    functions: dict[str, FunctionDefinition] = Field(default_factory=dict)
    retries: dict[str, RetryPolicy] = Field(default_factory=dict)
    """Profile retry — referowane z `task.retries: <name>` (#20)."""
    secrets: list[str] = Field(default_factory=list)
    timeouts: dict[str, TimeoutPolicy] = Field(default_factory=dict)
    """Profile timeout — referowane z `task.timeout: <name>` (#20).
    Built-in `default_timeout` wstrzykiwany przy publish (cascade Tenant→ClientOrg→Blueprint, #28).
    """


class TemporalWorkflowMetadata(StrictModel):
    """`metadata.temporal.*` na poziomie workflow."""

    workflow_run_timeout: IsoDuration | None = None
    """Decyzja #27. `workflow_execution_timeout` i `workflow_task_timeout` poza MVP."""


class WorkflowMetadata(StrictModel):
    """Wygodny widok na typowe sekcje `metadata.*` workflowu (Weaver + Temporal).

    Pełna mapa pozostaje `dict[str, Any]` w `Workflow.metadata`; ten model daje strukturę
    dla mapper/walidatora/generatora przy znanych kluczach.
    """

    weaver: _WeaverWorkflowMetadata | None = None
    temporal: TemporalWorkflowMetadata | None = None


class _WeaverWorkflowMetadata(StrictModel):
    trigger: Trigger | None = None
    """Pierwszy node grafu (#10) — extension Weaver."""
    blueprint_id: str | None = None
    tenant_id: str | None = None
    client_org_id: str | None = None


class Workflow(StrictModel):
    """Korzeń CNCF SW IR — pełen workflow document."""

    document: Document
    input: Input | None = None
    output: Output | None = None
    use: Use = Field(default_factory=Use)
    do: list[NamedTask]

    timeout: TimeoutPolicy | str | None = None
    """Workflow-level timeout — w naszym MVP używamy `metadata.temporal.workflow_run_timeout` (#27).
    Pole CNCF SW `timeout` zostawione dla kompatybilności ze spec."""

    schedule: dict[str, Any] | None = None
    """Workflow-level schedule (CNCF SW). Dla nas `ScheduleTrigger` w `metadata.weaver.trigger`."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Patrz `WorkflowMetadata` dla typowanego widoku znanych kluczy."""


from ir.tasks import NamedTask as _NamedTask  # noqa: E402
from ir.tasks import Task as _Task  # noqa: E402

WorkflowMetadata.model_rebuild()
Workflow.model_rebuild(_types_namespace={"NamedTask": _NamedTask, "Task": _Task})
