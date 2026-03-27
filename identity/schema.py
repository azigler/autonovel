"""Identity system models and persistence functions.

Defines the data structures for voice parameters, self-reflection,
and feedback digests. Provides functions to load, update, and persist
the agent's evolving creative identity.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

IDENTITY_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# Voice parameter sub-models
# ---------------------------------------------------------------------------

InterirorityDepth = Literal["shallow", "medium", "deep"]
MetaphorDensity = Literal["sparse", "moderate", "dense"]
POV = Literal["first", "second", "third_limited", "third_omniscient"]
Tense = Literal["past", "present"]
VocabularyRegister = Literal[
    "colloquial",
    "literary_accessible",
    "literary_dense",
    "formal",
]
FrequencyLevel = Literal["rare", "occasional", "frequent", "pervasive"]
SensoryDensity = Literal["low", "medium", "high"]
EmotionalDirectness = Literal["direct", "indirect", "mixed"]
PacingPreference = Literal["fast", "moderate", "slow_burn"]


@dataclass
class SentenceLength:
    """Statistical distribution for sentence length in words."""

    mean: int = 14
    std: int = 8
    min: int = 3
    max: int = 45


@dataclass
class ParagraphLength:
    """Statistical distribution for paragraph length in sentences."""

    mean: int = 4
    std: int = 2


@dataclass
class ChapterLengthTarget:
    """Word-count range the agent aims for per chapter."""

    min: int = 3000
    max: int = 6000


@dataclass
class VoicePriors:
    """Quantified style parameters that the learning engine can update.

    This is the single machine-readable representation of the agent's voice.
    Every field corresponds to a key in ``voice_priors.json``.
    """

    sentence_length: SentenceLength = field(default_factory=SentenceLength)
    paragraph_length: ParagraphLength = field(default_factory=ParagraphLength)
    dialogue_ratio: float = 0.35
    interiority_depth: InterirorityDepth = "medium"
    metaphor_density: MetaphorDensity = "sparse"
    pov: POV = "third_limited"
    tense: Tense = "past"
    vocabulary_register: VocabularyRegister = "literary_accessible"
    humor_frequency: FrequencyLevel = "occasional"
    sensory_detail_density: SensoryDensity = "high"
    emotional_directness: EmotionalDirectness = "indirect"
    pacing_preference: PacingPreference = "slow_burn"
    chapter_length_target: ChapterLengthTarget = field(
        default_factory=ChapterLengthTarget
    )
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    updated_at: str | None = None
    version: int = 1

    # -- serialization helpers ------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> VoicePriors:
        """Construct from a plain dict (e.g. parsed JSON)."""
        data = dict(data)  # shallow copy to avoid mutating caller's dict
        if isinstance(data.get("sentence_length"), dict):
            data["sentence_length"] = SentenceLength(**data["sentence_length"])
        if isinstance(data.get("paragraph_length"), dict):
            data["paragraph_length"] = ParagraphLength(
                **data["paragraph_length"]
            )
        if isinstance(data.get("chapter_length_target"), dict):
            data["chapter_length_target"] = ChapterLengthTarget(
                **data["chapter_length_target"]
            )
        return cls(**data)


# ---------------------------------------------------------------------------
# Reflection and feedback models
# ---------------------------------------------------------------------------


@dataclass
class SelfReflection:
    """Input to the self.md update cycle.

    Captures what happened during a writing/publication cycle and what
    the agent learned from it. The learning engine converts this into
    concrete edits to ``self.md``.
    """

    publication_title: str
    fandom: str
    date: str = field(default_factory=lambda: _utcnow_iso())
    what_happened: str = ""
    what_worked: str = ""
    what_didnt_work: str = ""
    lesson: str = ""
    voice_prior_adjustments: dict = field(default_factory=dict)


@dataclass
class ReaderComment:
    """A single reader comment, lightly structured."""

    author: str
    text: str
    chapter: int | None = None
    sentiment: Literal["positive", "negative", "neutral", "mixed"] = "neutral"
    themes: list[str] = field(default_factory=list)


@dataclass
class FeedbackDigest:
    """Summarized reader feedback for one publication cycle.

    The feedback collector populates this; the learning engine reads it
    to decide how voice priors and self.md should evolve.
    """

    publication_title: str
    fandom: str
    date: str = field(default_factory=lambda: _utcnow_iso())
    hits: int = 0
    kudos: int = 0
    bookmarks: int = 0
    comment_count: int = 0
    subscriber_delta: int = 0
    comments: list[ReaderComment] = field(default_factory=list)
    top_praise: list[str] = field(default_factory=list)
    top_criticism: list[str] = field(default_factory=list)
    recurring_themes: list[str] = field(default_factory=list)
    engagement_trend: Literal["rising", "stable", "declining"] = "stable"


# ---------------------------------------------------------------------------
# Persistence functions
# ---------------------------------------------------------------------------

_VOICE_PRIORS_PATH = IDENTITY_DIR / "voice_priors.json"
_SELF_PATH = IDENTITY_DIR / "self.md"
_MAX_VERSION_DRIFT = 5  # guard against runaway version bumps


def load_identity() -> dict:
    """Load the full identity context as a dict of file contents.

    Returns a dict with keys ``self``, ``pen_name``, ``inspirations``,
    ``fandom_context`` (all markdown strings) and ``voice_priors``
    (a :class:`VoicePriors` instance).
    """
    md_files = {
        "self": "self.md",
        "pen_name": "pen_name.md",
        "inspirations": "inspirations.md",
        "fandom_context": "fandom_context.md",
    }
    result: dict = {}
    for key, filename in md_files.items():
        path = IDENTITY_DIR / filename
        result[key] = path.read_text(encoding="utf-8") if path.exists() else ""

    result["voice_priors"] = _load_voice_priors()
    return result


def update_self(reflection: SelfReflection) -> str:
    """Append a history entry to self.md from a SelfReflection.

    Returns the new history entry text that was appended.
    """
    entry_lines = [
        f"### {reflection.date} - {reflection.publication_title} "
        f"({reflection.fandom})",
        f"- **What worked:** {reflection.what_worked}",
        f"- **What didn't:** {reflection.what_didnt_work}",
        f"- **Lesson:** {reflection.lesson}",
        "",
    ]
    entry = "\n".join(entry_lines)

    current = (
        _SELF_PATH.read_text(encoding="utf-8") if _SELF_PATH.exists() else ""
    )
    # Append before closing comment or at the very end
    updated = current.rstrip() + "\n\n" + entry
    _SELF_PATH.write_text(updated, encoding="utf-8")
    return entry


def update_voice_priors(
    adjustments: dict,
    *,
    bump_version: bool = True,
) -> VoicePriors:
    """Apply incremental adjustments to voice_priors.json.

    ``adjustments`` is a flat or nested dict whose keys match
    :class:`VoicePriors` fields.  Only the supplied keys are changed;
    everything else is preserved. Returns the updated priors.
    """
    priors = _load_voice_priors()
    current = priors.to_dict()

    for key, value in adjustments.items():
        if key not in current:
            continue
        if isinstance(current[key], dict) and isinstance(value, dict):
            current[key].update(value)
        else:
            current[key] = value

    if bump_version:
        current["version"] = current.get("version", 0) + 1
    current["updated_at"] = _utcnow_iso()

    updated = VoicePriors.from_dict(current)
    _save_voice_priors(updated)
    return updated


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_voice_priors() -> VoicePriors:
    if _VOICE_PRIORS_PATH.exists():
        with open(_VOICE_PRIORS_PATH, encoding="utf-8") as f:
            return VoicePriors.from_dict(json.load(f))
    return VoicePriors()


def _save_voice_priors(priors: VoicePriors) -> None:
    with open(_VOICE_PRIORS_PATH, "w", encoding="utf-8") as f:
        json.dump(priors.to_dict(), f, indent=2)
        f.write("\n")


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")
