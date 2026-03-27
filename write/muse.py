"""Muse system -- creative subconscious for the write loop.

Generates oblique creative provocations at three points in the pipeline:
pre-draft, mid-revision, and post-feedback. Each call returns a list of
seed strings that the writer model can use or ignore.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _call_muse(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    model: str,
    max_tokens: int = 2000,
) -> str:
    """Call the Claude API as the muse and return raw text."""
    from write.api import call_claude

    return call_claude(
        system=system_prompt,
        prompt=user_prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        model=model,
    )


def _parse_seeds(raw: str, expected_count: int) -> list[str]:
    """Parse numbered seeds from raw muse output.

    Handles formats like "1. ...", "1) ...", or just lines separated
    by blank lines. Returns up to expected_count seeds.
    """
    # Try numbered pattern first
    parts = re.split(r"\n\s*\d+[\.\)]\s*", "\n" + raw)
    seeds = [p.strip() for p in parts if p.strip()]

    if not seeds:
        # Fallback: split on blank lines
        seeds = [s.strip() for s in raw.split("\n\n") if s.strip()]

    if not seeds:
        # Last resort: the whole thing is one seed
        seeds = [raw.strip()] if raw.strip() else []

    return seeds[:expected_count]


def generate_creative_seeds(
    soul: str,
    brief: str,
    fandom_context: str,
    config: Any,
) -> list[str]:
    """Pre-draft muse: generate creative seeds before drafting.

    Fires after CONTEXT assembly, before DRAFT. Seeds are oblique
    creative provocations, not plot suggestions or craft advice.

    Args:
        soul: Full text of SOUL.md.
        brief: Formatted story brief text.
        fandom_context: Fandom context and character sheets.
        config: WriteConfig instance (needs muse_enabled, muse_model,
                muse_temperature, muse_seed_count).

    Returns:
        List of creative seed strings. Empty if muse is disabled.
    """
    if not getattr(config, "muse_enabled", True):
        return []

    seed_count = getattr(config, "muse_seed_count", 4)
    temperature = getattr(config, "muse_temperature", 1.0)

    from write.config import MODEL_MAP

    model_name = getattr(config, "muse_model", "haiku")
    model = MODEL_MAP.get(model_name, model_name)

    system_prompt = (
        "You are the creative subconscious of a fiction writer. Your job is to generate "
        "oblique creative provocations -- unexpected connections, thematic angles, sensory "
        "suggestions, emotional undercurrents. You are NOT plotting. You are NOT giving "
        "craft advice. You are whispering the things the writer's subconscious notices "
        "before the conscious mind catches up.\n\n"
        f"Generate exactly {seed_count} creative seeds. Each seed should be 1-3 sentences. "
        "Each seed should offer a different angle. At least one seed should connect the "
        "story's situation to the writer's thematic obsessions from SOUL.md. At least one "
        "should be purely sensory.\n\n"
        "Format: number each seed on its own line."
    )

    user_prompt = (
        f"SOUL (the writer's thematic DNA):\n{soul}\n\n"
        f"STORY BRIEF:\n{brief}\n\n"
        f"FANDOM CONTEXT:\n{fandom_context}\n\n"
        f"Generate {seed_count} creative seeds for this piece."
    )

    raw = _call_muse(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        model=model,
    )

    return _parse_seeds(raw, seed_count)


def generate_depth_notes(
    draft: str,
    soul: str,
    scores: dict[str, Any],
    config: Any,
) -> list[str]:
    """Mid-revision muse: identify what is emotionally missing.

    Fires after the first EVALUATE pass. Produces soul-level observations
    about the draft's emotional and thematic interior, not craft notes.

    Args:
        draft: The draft text.
        soul: Full text of SOUL.md.
        scores: Evaluation scores dict (per-dimension).
        config: WriteConfig instance.

    Returns:
        List of soul note strings. Empty if muse is disabled.
    """
    if not getattr(config, "muse_enabled", True):
        return []

    seed_count = getattr(config, "muse_seed_count", 4)
    temperature = getattr(config, "muse_temperature", 1.0) * 0.9

    from write.config import MODEL_MAP

    model_name = getattr(config, "muse_model", "haiku")
    model = MODEL_MAP.get(model_name, model_name)

    # Format scores for the muse
    score_lines = []
    for key, val in scores.items():
        if isinstance(val, dict) and "score" in val:
            feedback = val.get("feedback", "")
            score_lines.append(
                f"  {key}: {val['score']}/10"
                + (f" -- {feedback}" if feedback else "")
            )
        elif key in ("slop_penalty", "overall_score"):
            score_lines.append(f"  {key}: {val}")
    formatted_scores = "\n".join(score_lines)

    system_prompt = (
        "You are the creative subconscious reviewing a draft. You have read the writer's "
        "thematic DNA (SOUL.md) and the evaluation scores. Your job is to identify what is "
        "emotionally missing -- not craft problems (those are handled elsewhere) but soul "
        "problems. Where is the piece skating on the surface of something it should sit "
        "with? Where does the emotional logic break? What thematic thread is present but "
        "not yet pulled taut?\n\n"
        f"Generate exactly {seed_count} soul notes. Each should be 1-3 sentences. These are "
        "not revision instructions -- they are observations about the emotional and thematic "
        "interior of the piece."
    )

    user_prompt = (
        f"SOUL (the writer's thematic DNA):\n{soul}\n\n"
        f"EVALUATION SCORES:\n{formatted_scores}\n\n"
        f"DRAFT:\n{draft}\n\n"
        "What is emotionally missing?"
    )

    raw = _call_muse(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        model=model,
    )

    return _parse_seeds(raw, seed_count)


def generate_soul_evolution(
    soul: str,
    feedback_digest: str,
    config: Any,
) -> list[str]:
    """Post-feedback muse: propose SOUL.md updates from reader feedback.

    Fires during the /learn skill after reader feedback has been collected.
    Produces proposed edits to SOUL.md sections, grounded in what readers
    actually responded to.

    Args:
        soul: Full text of current SOUL.md.
        feedback_digest: Digest of reader responses, quotes, and praise.
        config: WriteConfig instance.

    Returns:
        List of proposed SOUL.md edit strings. Empty if muse is disabled.
    """
    if not getattr(config, "muse_enabled", True):
        return []

    seed_count = getattr(config, "muse_seed_count", 4)
    temperature = getattr(config, "muse_temperature", 1.0) * 0.8

    from write.config import MODEL_MAP

    model_name = getattr(config, "muse_model", "haiku")
    model = MODEL_MAP.get(model_name, model_name)

    system_prompt = (
        "You are the creative subconscious processing reader feedback. You have the writer's "
        "current thematic DNA (SOUL.md) and a digest of reader responses. Your job is to "
        "identify which thematic veins readers responded to most strongly and propose "
        "specific updates to SOUL.md.\n\n"
        'Propose updates as concrete edits: "Add to Obsessions: ...", "Strengthen in '
        'Motifs: ...", "New Growth Edge: ...". Be specific. Reference reader quotes where '
        "possible."
    )

    user_prompt = (
        f"CURRENT SOUL.md:\n{soul}\n\n"
        f"FEEDBACK DIGEST:\n{feedback_digest}\n\n"
        "What should evolve in the writer's thematic DNA?"
    )

    raw = _call_muse(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        model=model,
    )

    return _parse_seeds(raw, seed_count)
