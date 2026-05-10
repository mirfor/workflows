"""Retry / timeout profiles per CNCF SW 1.0 + Temporal extensions.

Decyzje: #20 (profile), #21 (retry mapping), #22 (timeout mapping), #24 (non-retryable),
#28 (cascade defaults).
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from ir._base import IsoDuration, JqExpression, StrictModel


class BackoffExponential(StrictModel):
    multiplier: float = Field(
        ..., gt=0, description="Backoff coefficient (Temporal: backoff_coefficient)."
    )


class BackoffConstant(StrictModel):
    pass


class BackoffLinear(StrictModel):
    increment: IsoDuration


class Backoff(StrictModel):
    """Dokładnie jeden z trybów. Walidator sprawdza wzajemną wyłączność."""

    exponential: BackoffExponential | None = None
    constant: BackoffConstant | None = None
    linear: BackoffLinear | None = None


class RetryLimitAttempt(StrictModel):
    count: int | None = Field(default=None, ge=1)
    duration: IsoDuration | None = None
    """`limit.attempt.duration` — NIE mapuje się na Temporal RetryPolicy; walidator blokuje (#21)."""


class RetryLimit(StrictModel):
    attempt: RetryLimitAttempt | None = None
    duration: IsoDuration | None = None
    """`limit.duration` — NIE mapuje się na Temporal RetryPolicy; walidator blokuje (#21)."""


class RetryJitter(StrictModel):
    """CNCF SW jitter — NIE mapuje się na Temporal API; walidator blokuje publish (#21)."""

    from_: IsoDuration = Field(..., alias="from")
    to: IsoDuration


class RetryPolicy(StrictModel):
    """Profil retry definiowany w `Use.retries.<name>` lub inline.

    Pola CNCF SW spec + Temporal extensions w `metadata.temporal.*`.
    Pola bez mapping na Temporal (`when`, `exceptWhen`, `jitter`, `limit.duration`,
    `limit.attempt.duration`) — walidator IR blokuje publish (#21).
    """

    when: JqExpression | None = None
    except_when: JqExpression | None = Field(default=None, alias="exceptWhen")
    delay: IsoDuration | None = None
    """Mapuje się na Temporal `RetryPolicy.initial_interval`."""
    backoff: Backoff | None = None
    """`backoff.exponential.multiplier` → Temporal `backoff_coefficient`."""
    limit: RetryLimit | None = None
    """`limit.attempt.count` → Temporal `maximum_attempts`."""
    jitter: RetryJitter | None = None

    non_retryable_types: list[str] = Field(default_factory=list, alias="nonRetryableTypes")
    """Decyzja #24 — rozszerza manifest defaults; merged → Temporal `non_retryable_error_types`."""

    metadata: dict[str, Any] | None = None
    """Temporal extensions (#21): `metadata.temporal.maximum_interval`,
    `metadata.temporal.non_retryable_error_types` (alternatywa do `non_retryable_types`).
    """


class TemporalTimeoutMetadata(StrictModel):
    """Temporal extensions dla `TimeoutPolicy.metadata.temporal` (#22)."""

    heartbeat: IsoDuration | None = None
    """Temporal `heartbeat_timeout` — dla long-running activities."""
    schedule_to_close: IsoDuration | None = None
    """Temporal `schedule_to_close_timeout` — globalny deadline włącznie z retries."""


class TimeoutPolicy(StrictModel):
    """Profil timeout w `Use.timeouts.<name>` lub inline.

    Decyzja #22: `after` (= Temporal `start_to_close_timeout`, **wymagane**) +
    `metadata.temporal.heartbeat` + `metadata.temporal.schedule_to_close`.
    `schedule_to_start_timeout` odłożone w MVP.
    """

    after: IsoDuration
    metadata: dict[str, Any] | None = None
    """`metadata.temporal.{heartbeat, schedule_to_close}` — patrz `TemporalTimeoutMetadata`."""
