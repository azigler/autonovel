"""Context assembly for the write loop.

Loads identity, fandom context, few-shot examples, and anti-slop rules.
Respects token budget allocation per spec 4.3.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import identity.schema as _schema
from write.brief import StoryBrief

# Re-exported so test fixtures (and any future callers) can monkeypatch
# the directory without reaching into identity.schema. The IDENTITY_DIR
# attribute mirrors identity.schema.IDENTITY_DIR; FANDOMS_DIR is the
# convenience alias used in spec 4.7.
IDENTITY_DIR: Path = _schema.IDENTITY_DIR
FANDOMS_DIR: Path = _schema.IDENTITY_DIR / "fandoms"

# Token budget allocation (out of 200K total)
BUDGET_IDENTITY = 30_000
BUDGET_FANDOM = 40_000
BUDGET_ANTI_SLOP = 10_000
BUDGET_FEW_SHOT = 30_000
BUDGET_BRIEF = 10_000
BUDGET_TOTAL = 200_000

# Conservative estimate: 4 chars per token for English prose
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate token count using ~4 chars per token heuristic."""
    if not text:
        return 0
    return len(text) // CHARS_PER_TOKEN


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate text to fit within a token budget."""
    max_chars = max_tokens * CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def assemble_context(
    brief: StoryBrief,
    identity: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the full context package within token budget.

    Args:
        brief: The story brief for this run.
        identity: Identity context dict from load_identity().

    Returns:
        Dict with assembled context blocks and token counts.
    """
    # --- Identity block (15% = 30K tokens) ---
    self_md = identity.get("self", "")
    pen_name = identity.get("pen_name", "")
    inspirations = identity.get("inspirations", "")
    voice_priors = identity.get("voice_priors")

    voice_priors_text = ""
    if voice_priors is not None:
        if hasattr(voice_priors, "to_dict"):
            voice_priors_text = str(voice_priors.to_dict())
        else:
            voice_priors_text = str(asdict(voice_priors))

    # Truncation priority: inspirations first, then self history
    identity_parts = [self_md, pen_name, voice_priors_text, inspirations]
    identity_tokens = sum(estimate_tokens(p) for p in identity_parts)

    if identity_tokens > BUDGET_IDENTITY:
        # Truncate inspirations first
        overshoot = identity_tokens - BUDGET_IDENTITY
        insp_tokens = estimate_tokens(inspirations)
        if insp_tokens >= overshoot:
            inspirations = _truncate_to_tokens(
                inspirations, insp_tokens - overshoot
            )
        else:
            inspirations = ""
            remaining_overshoot = overshoot - insp_tokens
            self_tokens = estimate_tokens(self_md)
            self_md = _truncate_to_tokens(
                self_md, max(0, self_tokens - remaining_overshoot)
            )

    identity_block = f"{self_md}\n\n{pen_name}\n\n{voice_priors_text}"
    final_identity_tokens = estimate_tokens(identity_block)

    # --- Fandom context block (20% = 40K tokens) ---
    # Spec bd-49j 4.7: resolve identity/fandoms/{slug}.md per brief.
    # The slug is brief.fandom when set, otherwise identity[currently_writing_in].
    # Unknown slug → FileNotFoundError (no silent fall-back to bg3).
    fandom_context = _resolve_fandom_context(brief, identity)
    fandom_tokens = estimate_tokens(fandom_context)
    if fandom_tokens > BUDGET_FANDOM:
        fandom_context = _truncate_to_tokens(fandom_context, BUDGET_FANDOM)
    fandom_tokens = estimate_tokens(fandom_context)

    # --- Anti-slop rules block (5% = 10K tokens) ---
    anti_slop_rules = _build_anti_slop_rules()
    anti_slop_tokens = estimate_tokens(anti_slop_rules)
    if anti_slop_tokens > BUDGET_ANTI_SLOP:
        anti_slop_rules = _truncate_to_tokens(anti_slop_rules, BUDGET_ANTI_SLOP)
        anti_slop_tokens = estimate_tokens(anti_slop_rules)

    # --- Few-shot examples (15% = 30K tokens) ---
    few_shot_examples: list[str] = []
    few_shot_count = 0
    few_shot_tokens = 0

    # --- Brief block (5% = 10K tokens) ---
    brief_text = _format_brief(brief)
    brief_tokens = estimate_tokens(brief_text)
    if brief_tokens > BUDGET_BRIEF:
        brief_text = _truncate_to_tokens(brief_text, BUDGET_BRIEF)
        brief_tokens = estimate_tokens(brief_text)

    return {
        "identity": identity_block,
        "fandom_context": fandom_context,
        "anti_slop_rules": anti_slop_rules,
        "few_shot_examples": few_shot_examples,
        "few_shot_count": few_shot_count,
        "brief_text": brief_text,
        "token_counts": {
            "identity": final_identity_tokens,
            "fandom": fandom_tokens,
            "anti_slop": anti_slop_tokens,
            "few_shot": few_shot_tokens,
            "brief": brief_tokens,
        },
    }


def _resolve_fandom_context(brief: StoryBrief, identity: dict[str, Any]) -> str:
    """Read the fandom context file for *brief* per spec bd-49j Section 4.7.

    Resolution order:

    1. ``brief.fandom`` -- when non-empty, treated as the slug. Reads
       ``FANDOMS_DIR/{brief.fandom}.md``.
    2. ``identity['currently_writing_in']`` -- the agent's current home
       fandom from ``identity/self.md`` (only present when identity was
       populated via ``identity.schema.load_identity``).

    A slug that points to a missing file raises ``FileNotFoundError``
    with a clear, slug-bearing message: silent fall-through to bg3
    would mean a brief tagged with the wrong fandom would still
    publish.

    Legacy (pre-bd-49j) callers pass an identity dict without the
    ``currently_writing_in`` marker and a pre-populated ``fandom_context``
    blob (e.g. mock identities in test fixtures). For those, fall back
    to the blob rather than raising, so existing test_write_loop briefs
    keep working.
    """
    raw = (brief.fandom or "").strip()
    is_post_migration = "currently_writing_in" in identity
    slug = raw or identity.get("currently_writing_in", "")

    if not slug:
        # No slug; legacy callers will already have a pre-loaded blob.
        return identity.get("fandom_context", "")

    path = FANDOMS_DIR / f"{slug}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")

    # Legacy / mock-identity path: brief.fandom isn't a slug we have a
    # file for, and the identity dict was assembled without the post-
    # migration markers. Use whatever fandom_context the caller pre-
    # populated. This keeps test_write_loop's mock identities working.
    if not is_post_migration and identity.get("fandom_context"):
        return identity["fandom_context"]

    raise FileNotFoundError(
        f"No fandom context file for slug {slug!r} at {path}. "
        "Add identity/fandoms/{slug}.md or correct brief.fandom."
    )


def _build_anti_slop_rules() -> str:
    """Build a compact anti-slop rules block from the databases."""
    # Import the slop lists from evaluate.py
    try:
        from evaluate import (
            FICTION_AI_TELLS,
            STRUCTURAL_AI_TICS,
            TIER1_BANNED,
            TIER2_SUSPICIOUS,
        )

        rules_parts = [
            "TIER 1 BANNED WORDS (never use): " + ", ".join(TIER1_BANNED),
            "",
            "TIER 2 SUSPICIOUS WORDS (avoid clustering): "
            + ", ".join(TIER2_SUSPICIOUS),
            "",
            "FICTION AI TELLS (rewrite these patterns):",
        ]
        for i, pattern in enumerate(FICTION_AI_TELLS[:10], 1):
            rules_parts.append(f"  {i}. {pattern}")

        rules_parts.append("")
        rules_parts.append("STRUCTURAL AI TICS (avoid these formulas):")
        for i, pattern in enumerate(STRUCTURAL_AI_TICS[:5], 1):
            rules_parts.append(f"  {i}. {pattern}")

        return "\n".join(rules_parts)
    except ImportError:
        return (
            "ANTI-SLOP: Avoid AI-typical words (delve, tapestry, myriad, "
            "utilize). Show emotions through action, not labels. Vary "
            "sentence length. Avoid triadic lists."
        )


def _format_brief(brief: StoryBrief) -> str:
    """Format a StoryBrief into a text block for the writer prompt."""
    lines = [
        f"FANDOM: {brief.fandom}",
        f"CHARACTERS: {', '.join(brief.characters)}",
        f"PREMISE: {brief.premise}",
        f"TARGET LENGTH: {brief.target_length} words",
        f"RATING: {brief.rating}",
        f"FORMAT: {brief.format}",
        f"GENRE: {brief.genre}",
        f"TONE: {brief.tone}",
    ]
    if brief.ship:
        lines.append(f"SHIP: {brief.ship}")
    if brief.title:
        lines.append(f"TITLE: {brief.title}")
    if brief.additional_context:
        lines.append(f"NOTES: {brief.additional_context}")
    return "\n".join(lines)
