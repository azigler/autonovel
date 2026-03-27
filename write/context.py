"""Context assembly for the write loop.

Loads identity, fandom context, few-shot examples, and anti-slop rules.
Respects token budget allocation per spec 4.3.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from write.brief import StoryBrief

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
    fandom_context = identity.get("fandom_context", "")
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
