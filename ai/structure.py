import re
from typing import Any

from pydantic import BaseModel, Field, field_validator


TERM_SEPARATOR_PATTERN = re.compile(r"[,;，；、。]+")


def normalize_term_list(value: Any) -> list[str]:
    """Normalize current and legacy structured-output term representations."""
    if value is None:
        return []
    if isinstance(value, str):
        values = TERM_SEPARATOR_PATTERN.split(value)
    elif isinstance(value, list):
        values = value
    else:
        raise TypeError("terms must be a list of strings, a separated string, or null")

    normalized = []
    seen = set()
    for term in values:
        if not isinstance(term, str):
            raise TypeError("each term must be a string")
        cleaned = term.strip()
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            normalized.append(cleaned)
    return normalized


class Structure(BaseModel):
    tldr: str = Field(description="a concise summary of the paper")
    method: str = Field(description="the main method or approach used in the paper")
    tags: list[str] = Field(
        description=(
            "approximately 3-6 stable topic-level phrases, such as topological "
            "superconductivity, vortex physics, or quantum geometry"
        )
    )
    specific_terms: list[str] = Field(
        description=(
            "approximately 3-8 paper-specific materials, methods, mechanisms, "
            "observables, device geometries, or named physical phenomena"
        )
    )

    @field_validator("tags", "specific_terms", mode="before")
    @classmethod
    def normalize_terms(cls, value: Any) -> list[str]:
        return normalize_term_list(value)
