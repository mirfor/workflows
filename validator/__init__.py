"""Walidator IR: 6 kategorii reguł (decyzja #16).

A: struktura grafu  | B: handles/edges      | C: registry funkcji
D: schemy/typy      | E: polityki Temporala | F: CNCF SW spec compliance
"""

from validator.report import Issue, Severity, ValidationReport
from validator.validator import (
    BASE_ERROR_TYPES,
    apply_default_timeout,
    validate,
)

__all__ = [
    "BASE_ERROR_TYPES",
    "Issue",
    "Severity",
    "ValidationReport",
    "apply_default_timeout",
    "validate",
]
