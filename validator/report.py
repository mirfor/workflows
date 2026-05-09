"""Wyniki walidacji."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Issue:
    code: str
    """Krótki identyfikator (np. `A001`, `E102`); `<kategoria><number>`."""
    severity: Severity
    path: str
    """JSON pointer / dotted path do pola w IR (np. `do[0].n1.retries`)."""
    message: str

    def __str__(self) -> str:
        return f"[{self.severity.value.upper()} {self.code}] {self.path}: {self.message}"


@dataclass(slots=True)
class ValidationReport:
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == Severity.WARNING]

    @property
    def has_errors(self) -> bool:
        return any(i.severity == Severity.ERROR for i in self.issues)

    def add(self, code: str, severity: Severity, path: str, message: str) -> None:
        self.issues.append(Issue(code=code, severity=severity, path=path, message=message))

    def extend(self, other: ValidationReport) -> None:
        self.issues.extend(other.issues)

    def __bool__(self) -> bool:
        return not self.has_errors
