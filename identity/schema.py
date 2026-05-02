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
# Ordinal scales for drift limiting (Section 4.2)
# ---------------------------------------------------------------------------

ORDINAL_SCALES: dict[str, tuple[str, ...]] = {
    "interiority_depth": ("shallow", "medium", "deep"),
    "metaphor_density": ("sparse", "moderate", "dense"),
    "humor_frequency": ("rare", "occasional", "frequent", "pervasive"),
    "sensory_detail_density": ("low", "medium", "high"),
    "emotional_directness": ("direct", "mixed", "indirect"),
    "pacing_preference": ("fast", "moderate", "slow_burn"),
    "vocabulary_register": (
        "colloquial",
        "literary_accessible",
        "literary_dense",
        "formal",
    ),
}

# Numeric drift limits: (min_bound, max_bound, max_drift_description)
# For most numerics, max drift is 15% of current value.
# dialogue_ratio uses an absolute drift of 0.05.
NUMERIC_BOUNDS: dict[str, tuple[float, float]] = {
    "sentence_length.mean": (5, 35),
    "sentence_length.std": (2, 15),
    "sentence_length.min": (1, 10),
    "sentence_length.max": (20, 80),
    "paragraph_length.mean": (1, 10),
    "paragraph_length.std": (1, 5),
    "dialogue_ratio": (0.0, 0.8),
    "chapter_length_target.min": (1000, 10000),
    "chapter_length_target.max": (2000, 20000),
}

# Non-ordinal categorical parameters that can change freely
FREE_CATEGORICALS = {"pov", "tense"}


def _ordinal_distance(scale: tuple[str, ...], a: str, b: str) -> int:
    """Compute the ordinal distance between two values on a scale."""
    return abs(scale.index(a) - scale.index(b))


def _get_nested_value(data: dict, dotted_key: str) -> float:
    """Get a value from a nested dict using dotted notation."""
    parts = dotted_key.split(".")
    current = data
    for part in parts:
        current = current[part]
    return current


# ---------------------------------------------------------------------------
# Validation (Section 4.3)
# ---------------------------------------------------------------------------


def validate_voice_priors(priors: VoicePriors) -> list[str]:
    """Check all parameter bounds on a VoicePriors instance.

    Returns a list of error strings. An empty list means the priors are valid.
    """
    errors: list[str] = []
    d = priors.to_dict()

    # Numeric bounds
    for dotted_key, (lo, hi) in NUMERIC_BOUNDS.items():
        val = _get_nested_value(d, dotted_key)
        if not (lo <= val <= hi):
            errors.append(f"{dotted_key} out of bounds: {val}")

    # Consistency checks
    if priors.sentence_length.min >= priors.sentence_length.max:
        errors.append(
            "sentence_length.min must be less than sentence_length.max"
        )
    if priors.chapter_length_target.min >= priors.chapter_length_target.max:
        errors.append("chapter_length_target.min must be less than max")

    # Categorical membership
    valid_sets: dict[str, tuple[str, ...]] = {
        "interiority_depth": ("shallow", "medium", "deep"),
        "metaphor_density": ("sparse", "moderate", "dense"),
        "pov": ("first", "second", "third_limited", "third_omniscient"),
        "tense": ("past", "present"),
        "vocabulary_register": (
            "colloquial",
            "literary_accessible",
            "literary_dense",
            "formal",
        ),
        "humor_frequency": ("rare", "occasional", "frequent", "pervasive"),
        "sensory_detail_density": ("low", "medium", "high"),
        "emotional_directness": ("direct", "indirect", "mixed"),
        "pacing_preference": ("fast", "moderate", "slow_burn"),
    }
    for field_name, valid_vals in valid_sets.items():
        val = getattr(priors, field_name)
        if val not in valid_vals:
            errors.append(f"invalid {field_name}: {val}")

    # List bounds
    if len(priors.strengths) > 10:
        errors.append(f"strengths list too long: {len(priors.strengths)}")
    if len(priors.weaknesses) > 10:
        errors.append(f"weaknesses list too long: {len(priors.weaknesses)}")

    # Version
    if priors.version < 1:
        errors.append(f"version must be >= 1: {priors.version}")

    return errors


# ---------------------------------------------------------------------------
# Drift limiting (Section 4.2)
# ---------------------------------------------------------------------------


def _check_drift(current_dict: dict, adjustments: dict) -> list[str]:
    """Check that adjustments respect drift limits.

    Returns a list of violation descriptions. Empty list means all OK.
    """
    violations: list[str] = []

    for key, new_value in adjustments.items():
        if key not in current_dict:
            continue

        old_value = current_dict[key]

        # Skip non-voice fields
        if key in ("version", "updated_at"):
            continue

        # Nested dict fields (sentence_length, paragraph_length,
        # chapter_length_target)
        if isinstance(old_value, dict) and isinstance(new_value, dict):
            for sub_key, sub_new in new_value.items():
                if sub_key not in old_value:
                    continue
                sub_old = old_value[sub_key]
                dotted = f"{key}.{sub_key}"
                if dotted in NUMERIC_BOUNDS and isinstance(
                    sub_old, int | float
                ):
                    _check_numeric_drift(dotted, sub_old, sub_new, violations)
            continue

        # Ordinal categorical fields
        if key in ORDINAL_SCALES:
            scale = ORDINAL_SCALES[key]
            if old_value in scale and new_value in scale:
                dist = _ordinal_distance(scale, old_value, new_value)
                if dist > 1:
                    violations.append(
                        f"{key}: ordinal change from '{old_value}' to "
                        f"'{new_value}' is {dist} steps (max 1)"
                    )
            continue

        # Free categoricals (pov, tense) -- no drift limit
        if key in FREE_CATEGORICALS:
            continue

        # dialogue_ratio (absolute drift limit of 0.05)
        if key == "dialogue_ratio":
            if (
                isinstance(old_value, int | float)
                and isinstance(new_value, int | float)
                and abs(new_value - old_value) > 0.05 + 1e-9
            ):
                violations.append(
                    f"dialogue_ratio: change from {old_value} to "
                    f"{new_value} exceeds max drift of 0.05"
                )
            continue

        # List fields (strengths, weaknesses)
        if key in ("strengths", "weaknesses"):
            if isinstance(old_value, list) and isinstance(new_value, list):
                old_set = set(old_value)
                new_set = set(new_value)
                added = new_set - old_set
                removed = old_set - new_set
                if len(added) > 2:
                    violations.append(
                        f"{key}: {len(added)} items added (max 2)"
                    )
                if len(removed) > 1:
                    violations.append(
                        f"{key}: {len(removed)} items removed (max 1)"
                    )
            continue

    return violations


def _check_numeric_drift(
    dotted_key: str,
    old_val: int | float,
    new_val: int | float,
    violations: list[str],
) -> None:
    """Check a single numeric field for drift limit violation."""
    if old_val == 0:
        return  # avoid division by zero; no drift from zero
    max_drift = abs(old_val) * 0.15
    actual_drift = abs(new_val - old_val)
    if actual_drift > max_drift + 1e-9:
        violations.append(
            f"{dotted_key}: change from {old_val} to {new_val} "
            f"exceeds 15% drift (max {max_drift:.2f})"
        )


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
# Token estimation
# ---------------------------------------------------------------------------

DEFAULT_IDENTITY_BUDGET = 4000  # tokens


def _estimate_tokens(text: str) -> int:
    """Estimate token count using the 4 chars per token approximation."""
    return len(text) // 4


# ---------------------------------------------------------------------------
# Persistence functions
# ---------------------------------------------------------------------------

_VOICE_PRIORS_PATH = IDENTITY_DIR / "voice_priors.json"
_SELF_PATH = IDENTITY_DIR / "self.md"
_MAX_VERSION_DRIFT = 5  # guard against runaway version bumps

# Default fandom slug when self.md does not yet declare currently_writing_in.
# bg3 is the agent's bootstrap fandom (per bd-49j Section 3.8).
_DEFAULT_FANDOM_SLUG = "bg3"


def _parse_fandom_state(self_md: str) -> dict:
    """Extract fandom-state fields from ``self.md`` content.

    Looks for the post bd-49j Section 3.8 markers:

    - ``currently_writing_in: <slug>``
    - ``fandom_history: [<slug>, ...]``
    - ``fandoms_explored:`` (followed by per-fandom indented entries)

    The parser is intentionally lenient: it returns sensible defaults
    when the file is empty or missing the markers, so legacy / partial
    self.md files don't crash ``load_identity``.
    """
    currently: str = _DEFAULT_FANDOM_SLUG
    history: list[str] = []
    explored: dict = {}

    if not self_md:
        return {
            "currently_writing_in": currently,
            "fandom_history": history,
            "fandoms_explored": explored,
        }

    in_explored = False
    for raw in self_md.splitlines():
        line = raw.strip()
        # Stop the fandoms_explored block when a new section / bullet starts
        # at the outermost indentation level without a leading dash.
        if in_explored and raw and not raw.startswith((" ", "\t", "-")):
            in_explored = False

        if line.startswith("- currently_writing_in:") or line.startswith(
            "currently_writing_in:"
        ):
            value = line.split(":", 1)[1].strip()
            if value:
                currently = value
        elif line.startswith("- fandom_history:") or line.startswith(
            "fandom_history:"
        ):
            value = line.split(":", 1)[1].strip()
            value = value.strip("[]")
            history = [
                s.strip().strip("'\"") for s in value.split(",") if s.strip()
            ]
        elif line.startswith("- fandoms_explored:") or line.startswith(
            "fandoms_explored:"
        ):
            tail = line.split(":", 1)[1].strip()
            in_explored = True
            if tail and tail != "":
                # Inline dict form, e.g. fandoms_explored: {bg3: {...}}
                # Best-effort: just record presence of slugs mentioned.
                _record_inline_explored(tail, explored)
        elif in_explored and line.startswith("- "):
            # Indented entry like "- bg3: { first_seen: ..., works_published: 1 }"
            entry = line[2:].strip()
            if ":" in entry:
                slug, payload = entry.split(":", 1)
                slug = slug.strip()
                if slug:
                    explored[slug] = _parse_fandom_meta(payload.strip())

    return {
        "currently_writing_in": currently,
        "fandom_history": history,
        "fandoms_explored": explored,
    }


def _record_inline_explored(tail: str, explored: dict) -> None:
    """Best-effort parse of an inline ``fandoms_explored: {...}`` value."""
    cleaned = tail.strip().strip("{}")
    if not cleaned:
        return
    # Split on commas at the top level only -- nested braces should not
    # split. This is intentionally simple; we only need slug presence.
    depth = 0
    current = []
    parts: list[str] = []
    for ch in cleaned:
        if ch == "{":
            depth += 1
            current.append(ch)
        elif ch == "}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current).strip())

    for part in parts:
        if ":" not in part:
            continue
        slug, payload = part.split(":", 1)
        slug = slug.strip()
        if slug:
            explored[slug] = _parse_fandom_meta(payload.strip())


def _parse_fandom_meta(payload: str) -> dict:
    """Best-effort parse of a per-fandom metadata blob.

    Accepts shapes like ``{ first_seen: 2026-03-27, works_published: 1 }``
    and returns a plain dict with the inner key/value pairs as strings.
    """
    inner = payload.strip().strip("{}").strip()
    if not inner:
        return {}
    out: dict = {}
    for token in inner.split(","):
        token = token.strip()
        if not token or ":" not in token:
            continue
        k, v = token.split(":", 1)
        out[k.strip()] = v.strip().strip("'\"")
    return out


def _read_fandom_file(slug: str) -> str:
    """Read ``IDENTITY_DIR/fandoms/{slug}.md`` for the given fandom slug.

    Falls back to the legacy ``IDENTITY_DIR/fandom_context.md`` for
    backward compatibility (e.g. test fixtures that have not yet been
    updated for the post-bd-49j layout). Returns ``""`` if neither
    exists.
    """
    primary = IDENTITY_DIR / "fandoms" / f"{slug}.md"
    if primary.exists():
        return primary.read_text(encoding="utf-8")
    legacy = IDENTITY_DIR / "fandom_context.md"
    if legacy.exists():
        return legacy.read_text(encoding="utf-8")
    return ""


def resolve_fandom_path(slug: str) -> Path:
    """Return the path to ``identity/fandoms/{slug}.md``.

    The path is returned regardless of whether the file exists. Callers
    that need a strict existence check should ``raise FileNotFoundError``
    themselves with a slug-bearing message.
    """
    return IDENTITY_DIR / "fandoms" / f"{slug}.md"


def read_fandom_context(slug: str) -> str:
    """Read the fandom context for *slug* or raise ``FileNotFoundError``.

    This is the strict variant used by the write loop: an unknown slug
    must be a hard error so a brief for an unwritten fandom does not
    silently inherit bg3 context (per spec Section 4.7).
    """
    path = resolve_fandom_path(slug)
    if not path.exists():
        raise FileNotFoundError(
            f"No fandom context file for slug {slug!r} at {path}. "
            "Add identity/fandoms/{slug}.md or correct brief.fandom."
        )
    return path.read_text(encoding="utf-8")


def load_identity(max_tokens: int | None = None) -> dict:
    """Load the full identity context as a dict of file contents.

    When *max_tokens* is ``None``, all identity files are loaded in full
    (the original behaviour). When a budget is given, components are loaded
    in priority order and lower-priority content is truncated or omitted
    to fit within the budget.

    Returns a dict with keys ``self``, ``pen_name``, ``inspirations``,
    ``fandom_context`` (all markdown strings), ``voice_priors``
    (a :class:`VoicePriors` instance), and the post-bd-49j fandom-state
    keys ``currently_writing_in`` (str), ``fandom_history`` (list[str]),
    and ``fandoms_explored`` (dict).
    """
    if max_tokens is None:
        # Original unbounded behaviour
        md_files = {
            "self": "self.md",
            "pen_name": "pen_name.md",
            "inspirations": "inspirations.md",
        }
        result: dict = {}
        for key, filename in md_files.items():
            path = IDENTITY_DIR / filename
            result[key] = (
                path.read_text(encoding="utf-8") if path.exists() else ""
            )

        # Fandom state derived from self.md (post bd-49j Section 3.8)
        fandom_state = _parse_fandom_state(result["self"])
        result["currently_writing_in"] = fandom_state["currently_writing_in"]
        result["fandom_history"] = fandom_state["fandom_history"]
        result["fandoms_explored"] = fandom_state["fandoms_explored"]

        # Read the fandom context file, post-migration to identity/fandoms/
        result["fandom_context"] = _read_fandom_file(
            result["currently_writing_in"]
        )

        result["voice_priors"] = _load_voice_priors()
        return result

    return _load_identity_budgeted(max_tokens)


def _load_identity_budgeted(budget: int) -> dict:
    """Load identity components within a token budget.

    Components are loaded in priority order per spec Section 4.4.
    """
    result: dict = {
        "self": "",
        "pen_name": "",
        "inspirations": "",
        "fandom_context": "",
        "currently_writing_in": _DEFAULT_FANDOM_SLUG,
        "fandom_history": [],
        "fandoms_explored": {},
    }
    remaining = budget

    # Priority 1: voice_priors (always loaded in full)
    vp = _load_voice_priors()
    result["voice_priors"] = vp
    vp_tokens = _estimate_tokens(json.dumps(vp.to_dict()))
    remaining -= vp_tokens

    if remaining <= 0:
        return result

    # Helper to read a file safely
    def _read(filename: str) -> str:
        path = IDENTITY_DIR / filename
        return path.read_text(encoding="utf-8") if path.exists() else ""

    # Priority 2: self.md key sections (Voice + Current Focus)
    self_md = _read("self.md")
    fandom_state = _parse_fandom_state(self_md)
    result["currently_writing_in"] = fandom_state["currently_writing_in"]
    result["fandom_history"] = fandom_state["fandom_history"]
    result["fandoms_explored"] = fandom_state["fandoms_explored"]
    self_sections = _parse_sections(self_md)
    key_self = ""
    for section_name in ("voice", "current_focus"):
        content = self_sections.get(section_name, "")
        if content:
            key_self += content + "\n\n"
    key_self_tokens = _estimate_tokens(key_self)
    if key_self_tokens <= remaining:
        result["self"] = key_self.strip()
        remaining -= key_self_tokens
    else:
        # Truncate to fit
        chars = remaining * 4
        result["self"] = key_self[:chars].strip()
        remaining = 0
        return result

    # Priority 3: fandom_context key sections (Canon Summary + Character Voices)
    # Post bd-49j Section 4.7: read identity/fandoms/{currently_writing_in}.md
    # and fall back to the legacy fandom_context.md for old fixtures.
    fandom_md = _read_fandom_file(result["currently_writing_in"])
    fandom_sections = _parse_sections(fandom_md)
    key_fandom = ""
    for section_name in ("canon_summary", "character_voices"):
        content = fandom_sections.get(section_name, "")
        if content:
            key_fandom += content + "\n\n"
    key_fandom_tokens = _estimate_tokens(key_fandom)
    if key_fandom_tokens <= remaining:
        result["fandom_context"] = key_fandom.strip()
        remaining -= key_fandom_tokens
    else:
        chars = remaining * 4
        result["fandom_context"] = key_fandom[:chars].strip()
        remaining = 0
        return result

    # Priority 4: pen_name.md (Author's Note Voice section)
    pen_md = _read("pen_name.md")
    pen_sections = _parse_sections(pen_md)
    pen_note = pen_sections.get("authors_note_voice", "")
    if not pen_note:
        pen_note = pen_sections.get("author_s_note_voice", "")
    pen_tokens = _estimate_tokens(pen_note)
    if pen_tokens <= remaining:
        result["pen_name"] = pen_note.strip()
        remaining -= pen_tokens
    else:
        chars = remaining * 4
        result["pen_name"] = pen_note[:chars].strip()
        remaining = 0
        return result

    # Priority 5: self.md full
    self_full_tokens = _estimate_tokens(self_md)
    if self_full_tokens <= remaining:
        result["self"] = self_md.strip()
        remaining -= self_full_tokens
    elif remaining > 0:
        chars = remaining * 4
        result["self"] = self_md[:chars].strip()
        remaining = 0
        return result

    # Priority 6: fandom_context.md full
    if remaining > 0:
        fandom_full_tokens = _estimate_tokens(fandom_md)
        if fandom_full_tokens <= remaining:
            result["fandom_context"] = fandom_md.strip()
            remaining -= fandom_full_tokens
        else:
            chars = remaining * 4
            result["fandom_context"] = fandom_md[:chars].strip()
            remaining = 0
            return result

    # Priority 7: inspirations.md
    if remaining > 0:
        insp_md = _read("inspirations.md")
        insp_tokens = _estimate_tokens(insp_md)
        if insp_tokens <= remaining:
            result["inspirations"] = insp_md.strip()
            remaining -= insp_tokens
        else:
            chars = remaining * 4
            result["inspirations"] = insp_md[:chars].strip()
            remaining = 0
            return result

    # Priority 8: pen_name.md full
    if remaining > 0:
        pen_full_tokens = _estimate_tokens(pen_md)
        if pen_full_tokens <= remaining:
            result["pen_name"] = pen_md.strip()
            remaining -= pen_full_tokens
        else:
            chars = remaining * 4
            result["pen_name"] = pen_md[:chars].strip()

    return result


def _parse_sections(md_text: str) -> dict[str, str]:
    """Parse a markdown file into sections keyed by normalized header name.

    Headers are ``## Section Name`` lines. The key is lowercased with spaces
    replaced by underscores and non-alphanumeric characters (except ``_``)
    stripped. For example ``## Author's Note Voice`` becomes
    ``authors_note_voice``.
    """
    sections: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    for line in md_text.splitlines():
        if line.startswith("## "):
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines).strip()
            raw_header = line[3:].strip()
            normalized = raw_header.lower().replace(" ", "_").replace("'", "")
            # Strip remaining non-alnum/underscore
            normalized = "".join(
                c for c in normalized if c.isalnum() or c == "_"
            )
            current_key = normalized
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)

    if current_key is not None:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


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
    everything else is preserved.

    Enforces drift limits (Section 4.2) and validation (Section 4.3).
    Raises ``ValueError`` if drift limits or validation bounds are violated.

    Returns the updated priors.
    """
    priors = _load_voice_priors()
    current = priors.to_dict()

    # Check drift limits before applying
    drift_violations = _check_drift(current, adjustments)
    if drift_violations:
        raise ValueError(
            f"Drift limit violations: {'; '.join(drift_violations)}"
        )

    for key, value in adjustments.items():
        if key not in current:
            continue
        if isinstance(current[key], dict) and isinstance(value, dict):
            current[key].update(value)
        else:
            current[key] = value

    if bump_version:
        new_version = current.get("version", 0) + 1
        if new_version - priors.version > _MAX_VERSION_DRIFT:
            raise RuntimeError("Runaway version bump detected")
        current["version"] = new_version
    current["updated_at"] = _utcnow_iso()

    updated = VoicePriors.from_dict(current)

    # Validate the resulting priors
    errors = validate_voice_priors(updated)
    if errors:
        raise ValueError(f"Invalid voice priors: {'; '.join(errors)}")

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
