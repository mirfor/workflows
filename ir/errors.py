"""Error taxonomy: zamknięta baza + per-Tool extensions w manifest (#23, #24).

Mapping na Temporal: `ApplicationError(type=...)` z opcjonalnym `non_retryable`.
Generator emituje `non_retryable_error_types` jako merge (manifest defaults ∪ profile overrides).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from ir._base import JqExpression, StrictModel


class BaseErrorType(StrEnum):
    """Zamknięta baza error types (#23). Tool/Specialized Agent może rozszerzać w manifest."""

    VALIDATION_ERROR = "ValidationError"
    AUTH_ERROR = "AuthError"
    RATE_LIMIT_ERROR = "RateLimitError"
    TIMEOUT_ERROR = "TimeoutError"
    NOT_FOUND_ERROR = "NotFoundError"
    INTEGRATION_ERROR = "IntegrationError"
    INTERNAL_ERROR = "InternalError"


class ErrorSpec(StrictModel):
    """Wpis w manifest `tools[*].errors[*]` lub `specialized_agents[*].errors[*]`."""

    type: str
    description: str | None = None
    retryable: bool = True
    """Default; profile retry może rozszerzyć non-retryable list (#24)."""
    output_schema_ref: str | None = None
    """JSON pointer/URI do schemy payload-u erroru (np. `#/components/schemas/AuthErrorPayload`)."""
    is_base: bool = False
    """`True` dla `BaseErrorType`; `False` dla custom errors per Tool."""


class ErrorDefinition(StrictModel):
    """Definicja erroru w `Use.errors.<name>` (CNCF SW spec)."""

    type: str
    title: str | None = None
    status: int | None = None
    detail: str | None = None
    instance: str | None = None
    metadata: dict[str, Any] | None = None


class ErrorReference(StrictModel):
    """Filtr błędów w `try.catch.errors.with` lub argument do `raise.error`."""

    type: str | None = None
    """Match po `error.type` (referencja do `BaseErrorType` lub Tool error)."""
    status: int | None = None
    """Match po HTTP-like status code (CNCF SW spec)."""
    instance: str | None = None
    title: str | None = None

    when: JqExpression | None = Field(default=None)
    except_when: JqExpression | None = Field(default=None, alias="exceptWhen")
