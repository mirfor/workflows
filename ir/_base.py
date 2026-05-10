"""Wspólne podstawy Pydantic dla IR."""

from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

# Rust regex nie wspiera lookaround — split na osobny pattern + funkcyjny check non-empty body.
_ISO_DURATION_RE = re.compile(r"^P(\d+Y)?(\d+M)?(\d+W)?(\d+D)?(T(\d+H)?(\d+M)?(\d+(?:\.\d+)?S)?)?$")


def _validate_iso_duration(v: str) -> str:
    if not _ISO_DURATION_RE.match(v):
        raise ValueError(f"Niepoprawny format ISO 8601 duration: {v!r}")
    if v in {"P", "PT"}:
        raise ValueError("ISO 8601 duration nie może być pusty (`P` ani `PT`)")
    if "T" in v and v.endswith("T"):
        raise ValueError(f"ISO 8601 duration kończący się na `T` bez sekcji czasowej: {v!r}")
    return v


class StrictModel(BaseModel):
    """Bazowy model: zabronione nieznane pola, zachowanie aliasów, walidacja przy przypisaniu."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        validate_assignment=True,
        str_strip_whitespace=True,
    )

    def model_dump_cncf(self, **kwargs: Any) -> dict[str, Any]:
        """Dump w formacie wire CNCF SW (by_alias, pomija defaults)."""
        return self.model_dump(by_alias=True, exclude_none=True, **kwargs)


IsoDuration = Annotated[str, AfterValidator(_validate_iso_duration)]
"""ISO 8601 duration (np. `PT5M`, `PT30S`, `P1DT2H`)."""


JqExpression = Annotated[str, StringConstraints(min_length=1)]
"""Wyrażenie JQ. Walidacja składni odbywa się w `validator/` (libjq compile)."""
