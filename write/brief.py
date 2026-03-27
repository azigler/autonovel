"""Story brief validation and schema.

Defines the StoryBrief dataclass and validation rules per spec 4.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from api.models import Rating


@dataclass
class StoryBrief:
    """Input to the write loop -- describes what to write."""

    # Required
    fandom: str = ""
    characters: list[str] = field(default_factory=list)
    premise: str = ""
    target_length: int = 5000
    rating: Rating = Rating.NOT_RATED

    # Required with defaults
    format: Literal["one_shot", "multi_chapter"] = "one_shot"
    genre: str = "general"
    tone: str = "neutral"

    # Optional
    title: str | None = None
    ship: str | None = None
    tags_hint: list[str] = field(default_factory=list)
    experiment_hypothesis: str | None = None
    chapter_count: int | None = None
    additional_context: str = ""


def validate_brief(brief: StoryBrief) -> None:
    """Validate a StoryBrief against the required schema.

    Raises ValueError if any validation rule is violated.
    Also derives chapter_count for multi-chapter briefs when not set.
    """
    errors: list[str] = []

    if not brief.fandom or not brief.fandom.strip():
        errors.append("fandom must be non-empty")

    if not brief.characters:
        errors.append("characters must contain at least one character")

    if not brief.premise or not brief.premise.strip():
        errors.append("premise must be non-empty")
    elif len(brief.premise) < 10:
        errors.append("premise must be at least 10 characters")
    elif len(brief.premise) > 2000:
        errors.append("premise must be at most 2000 characters")

    if brief.target_length < 1000:
        errors.append("target_length must be at least 1000")
    elif brief.target_length > 80000:
        errors.append("target_length must be at most 80000")

    if errors:
        raise ValueError("; ".join(errors))

    # Derive chapter_count for multi-chapter briefs
    if brief.format == "multi_chapter" and brief.chapter_count is None:
        derived = brief.target_length // 4000
        brief.chapter_count = max(2, min(derived, 20))
