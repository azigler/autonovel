"""Revision brief generation and revision execution.

Generates focused revision briefs based on evaluation gate results
and calls the revision model to produce improved drafts. Supports
multi-pass revision with specialized passes: structure, depth, voice, cut.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default pass selection based on revision_passes count
_PASS_SUBSETS: dict[int, list[str]] = {
    1: ["structure"],
    2: ["structure", "voice"],
    3: ["structure", "depth", "voice"],
    4: ["structure", "depth", "voice", "cut"],
}

# Which passes to run for each gate failure type
GATE_FAILURE_PASSES: dict[str, list[str]] = {
    "SLOP_FAIL": ["voice"],
    "CHARACTERIZATION_FAIL": ["structure", "depth"],
    "QUALITY_FAIL": ["structure", "depth", "voice", "cut"],
}


def generate_revision_brief(
    scores: dict[str, Any],
    gate_result: str,
    draft_text: str,
    fandom_context: str,
) -> str:
    """Generate a revision brief from evaluation results.

    The brief is tailored to the specific gate failure:
    - SLOP_FAIL: Focus on specific slop hits and banned word replacements.
    - CHARACTERIZATION_FAIL: Include character notes and canonical behavior.
    - QUALITY_FAIL: Highlight weakest scoring dimensions.

    Args:
        scores: Evaluation scores dict.
        gate_result: One of "SLOP_FAIL", "CHARACTERIZATION_FAIL", "QUALITY_FAIL".
        draft_text: The current draft text.
        fandom_context: Fandom context for character notes.

    Returns:
        A structured revision brief string.
    """
    parts: list[str] = ["REVISION BRIEF", "=" * 40, ""]

    if gate_result == "SLOP_FAIL":
        parts.append("PROBLEM: Mechanical slop detection failed (hard gate).")
        parts.append(f"Slop penalty: {scores.get('slop_penalty', 'unknown')}")
        parts.append("")

        # List specific tier1 hits
        tier1_hits = scores.get("tier1_hits", [])
        if tier1_hits:
            parts.append("BANNED WORDS FOUND (must remove):")
            for word, count in tier1_hits:
                parts.append(f"  - '{word}' appears {count} time(s)")
            parts.append("")

        # Fiction AI tells
        fiction_tells = scores.get("fiction_ai_tells", [])
        if fiction_tells:
            parts.append("FICTION AI TELLS (must rewrite):")
            for pattern, count in fiction_tells:
                parts.append(f"  - Pattern '{pattern}': {count} match(es)")
            parts.append("")

        parts.append("WHAT TO DO:")
        parts.append("- Replace every banned word with a natural alternative.")
        parts.append("- Rewrite any sentence matching AI tell patterns.")
        parts.append("- Vary sentence structure and rhythm.")
        parts.append("- Preserve the story content and emotional beats.")

    elif gate_result == "CHARACTERIZATION_FAIL":
        char_data = scores.get("characterization_accuracy", {})
        feedback = char_data.get("feedback", "No specific feedback.")
        char_score = char_data.get("score", 0)

        parts.append("PROBLEM: Characters are out-of-character (OOC).")
        parts.append(f"Characterization score: {char_score}")
        parts.append(f"Feedback: {feedback}")
        parts.append("")
        parts.append(f"FANDOM CONTEXT: {fandom_context}")
        parts.append("")
        parts.append("WHAT TO DO:")
        parts.append(
            "- Review each character's dialogue and actions against canon."
        )
        parts.append(
            "- Ensure voice, mannerisms, and reactions match the character."
        )
        parts.append("- Preserve story structure but fix character behavior.")

    elif gate_result == "QUALITY_FAIL":
        parts.append("PROBLEM: Overall quality below threshold.")
        parts.append(f"Overall score: {scores.get('overall_score', 'unknown')}")
        parts.append("")

        # Find weakest dimensions
        dimension_keys = [
            "voice_adherence",
            "fandom_voice_fit",
            "prose_quality",
            "engagement",
            "pacing",
            "emotional_arc",
            "characterization_accuracy",
        ]
        weak_dims = []
        for key in dimension_keys:
            dim_data = scores.get(key, {})
            if isinstance(dim_data, dict):
                score = dim_data.get("score", 10.0)
                feedback = dim_data.get("feedback", "")
                if score < 7.0:
                    weak_dims.append((key, score, feedback))

        weak_dims.sort(key=lambda x: x[1])

        if weak_dims:
            parts.append("WEAKEST DIMENSIONS:")
            for key, score, feedback in weak_dims:
                label = key.replace("_", " ").title()
                parts.append(f"  - {label}: {score}/10")
                if feedback:
                    parts.append(f"    Feedback: {feedback}")
            parts.append("")

        parts.append("WHAT TO DO:")
        parts.append("- Focus revision on the weakest dimensions above.")
        parts.append("- Preserve what works (high-scoring dimensions).")
        parts.append("- Add more sensory detail and emotional specificity.")

    return "\n".join(parts)


def generate_revision(
    draft_text: str,
    revision_brief: str,
    context: dict[str, Any] | None = None,
) -> str:
    """Generate a revised draft from the existing draft and revision brief.

    This is a stub that calls a mock-able revision model. The real
    implementation will call the Claude API.

    Args:
        draft_text: The current draft text.
        revision_brief: The focused revision brief.
        context: Assembled context dict (identity, fandom, etc.).

    Returns:
        The revised draft text.
    """
    return call_revision_model(
        draft_text=draft_text,
        revision_brief=revision_brief,
        context=context,
    )


def call_revision_model(
    draft_text: str,
    revision_brief: str,
    context: dict[str, Any] | None = None,
) -> str:
    """Call the Claude API to revise a draft according to the revision brief.

    The model receives the full draft and specific revision instructions,
    and returns the complete revised text.
    """
    from write.api import call_claude

    system = (
        "You are revising a piece of fanfiction. Apply the revision brief "
        "exactly. Preserve everything that works. Only change what the brief "
        "specifies. Return the complete revised text, not a diff or summary."
    )

    # Include identity/voice context if available so the revision
    # preserves the correct character voices and writing style.
    context_block = ""
    if context:
        identity = context.get("identity", "")
        fandom = context.get("fandom_context", "")
        anti_slop = context.get("anti_slop_rules", "")
        if identity:
            context_block += f"\nVOICE REFERENCE:\n{identity}\n"
        if fandom:
            context_block += f"\nFANDOM CONTEXT:\n{fandom}\n"
        if anti_slop:
            context_block += f"\nANTI-SLOP RULES:\n{anti_slop}\n"

    prompt = f"""{context_block}
REVISION BRIEF (follow these instructions exactly):
{revision_brief}

CURRENT DRAFT (revise this):
{draft_text}

Write the complete revised text now."""

    # Give enough room for the full revised draft
    max_tokens = max(4000, len(draft_text.split()) * 2)
    max_tokens = min(max_tokens, 32000)

    return call_claude(
        system=system,
        prompt=prompt,
        max_tokens=max_tokens,
        temperature=0.7,
    )


# ---------------------------------------------------------------------------
# Multi-pass revision system
# ---------------------------------------------------------------------------


def _build_pass_system_prompt(
    pass_name: str,
    context: dict[str, Any],
    muse_notes: list[str] | None = None,
    soul: str = "",
) -> str:
    """Build the system prompt for a specific revision pass.

    Args:
        pass_name: One of "structure", "depth", "voice", "cut".
        context: Assembled context dict (identity, fandom, anti-slop).
        muse_notes: Mid-revision muse notes (used in depth pass).
        soul: SOUL.md text (used in cut pass).

    Returns:
        The system prompt string for this pass.
    """
    identity_block = context.get("identity", "")
    anti_slop_rules = context.get("anti_slop_rules", "")

    if pass_name == "structure":
        return (
            "You are a structural editor. Read this piece for shape and movement. "
            "Your ONLY concern is structure:\n\n"
            "- Does the piece have forward motion, or does it stall?\n"
            "- Does each scene/section earn its place?\n"
            "- Is there a turn -- a moment where something shifts?\n"
            "- Does the ending feel earned by what came before?\n"
            "- Are there sections that repeat the same emotional beat without "
            "progression?\n\n"
            "If the structure works, make minimal changes. If it doesn't, "
            "restructure. Preserve voice and prose quality -- you are NOT line "
            "editing. Return the complete revised text."
        )

    if pass_name == "depth":
        notes_block = ""
        if muse_notes:
            formatted = "\n".join(f"- {n}" for n in muse_notes)
            notes_block = (
                f"\nSOUL NOTES (what the muse noticed):\n{formatted}\n"
            )
        return (
            "You are a depth editor. Read this piece for emotional and thematic "
            "depth. Your ONLY concern is interiority and resonance:\n\n"
            "- Where is the piece skating on the surface of something it should "
            "sit with?\n"
            "- Where could a character's internal experience be more specific, "
            "more embodied?\n"
            "- Where does the prose tell us what a character feels instead of "
            "showing us what they do with that feeling?\n"
            "- Are the thematic concerns of the piece present in the texture "
            "(sensory details, physical gestures, rhythms) or only in the "
            "dialogue/internal monologue?\n"
            f"{notes_block}\n"
            "Deepen where needed. Do NOT restructure. Do NOT line edit. Return "
            "the complete revised text."
        )

    if pass_name == "voice":
        return (
            "You are a voice editor. Read this piece sentence by sentence for "
            "voice consistency. Your ONLY concern is whether every line sounds "
            "like the same writer:\n\n"
            f"VOICE REFERENCE:\n{identity_block}\n\n"
            f"ANTI-SLOP RULES:\n{anti_slop_rules}\n\n"
            "Check for:\n"
            "- Sentences that shift register (suddenly more formal, more casual, "
            "more purple)\n"
            "- Repetitive constructions (same sentence opener, same rhythm, same "
            "verb)\n"
            "- Moments where craft overrides character (a beautiful sentence that "
            "doesn't sound like how this character would think)\n"
            "- Slop patterns: banned words, AI tells, structural tics\n"
            "- Em-dash density (max 8 per 1000 words)\n"
            '- "He/She looked at" frequency (max 3 per chapter)\n\n'
            "Fix voice breaks. Do NOT restructure. Do NOT change emotional "
            "content. Return the complete revised text."
        )

    # pass_name == "cut"
    return (
        "You are a cutting editor. Your ONLY job is removal. Read the piece and "
        "identify anything that can be cut without losing meaning, emotion, or "
        "thematic resonance.\n\n"
        f"SOUL.md (thematic DNA -- passages serving these themes earn their place):\n"
        f"{soul}\n\n"
        "Cut rules:\n"
        "- Remove redundant beats (if a gesture shows the emotion, cut the "
        "sentence that explains it)\n"
        "- Remove filler transitions that don't do work\n"
        "- Remove any sentence where the prose admires itself rather than "
        "serving the story\n"
        "- DO NOT cut passages that serve SOUL.md themes, even if they are "
        '"slow" -- these are the point\n'
        "- DO NOT cut for the sake of cutting -- only cut what genuinely adds "
        "nothing\n"
        "- If nothing needs cutting, return the text unchanged\n\n"
        "Return the complete text with cuts applied."
    )


def run_revision_passes(
    draft: str,
    passes: list[str] | None,
    context: dict[str, Any],
    soul: str = "",
    config: Any = None,
    muse_notes: list[str] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Orchestrate multi-pass revision on a draft.

    Each pass is a separate Claude call with a system prompt focused on
    that pass's intent. The draft evolves through all passes sequentially.

    Args:
        draft: The current draft text.
        passes: Which passes to run, in order. If None, selects based on
                config.revision_passes count.
        context: Assembled context dict (identity, fandom, anti-slop).
        soul: Full SOUL.md text (used in cut and depth passes).
        config: WriteConfig instance (optional -- uses defaults if None).
        muse_notes: Mid-revision muse output (used in depth pass).

    Returns:
        (revised_text, pass_log) where pass_log is a list of dicts
        recording each pass's name, input word count, and output word count.
    """
    from write.api import call_claude

    # Determine which passes to run
    if passes is None:
        revision_count = 4
        if config is not None:
            revision_count = getattr(config, "revision_passes", 4)
        passes = _PASS_SUBSETS.get(revision_count, _PASS_SUBSETS[4])

    # Get temperature from config
    revision_temp = 0.7
    if config is not None:
        revision_temp = getattr(config, "revision_temperature", 0.7)

    pass_log: list[dict[str, Any]] = []
    current_text = draft

    for pass_name in passes:
        input_wc = len(current_text.split())

        system = _build_pass_system_prompt(
            pass_name=pass_name,
            context=context,
            muse_notes=muse_notes if pass_name == "depth" else None,
            soul=soul if pass_name == "cut" else "",
        )

        prompt = (
            f"CURRENT DRAFT (revise this):\n{current_text}\n\n"
            "Write the complete revised text now."
        )

        # Voice pass uses slightly lower temperature
        temp = revision_temp
        if pass_name == "voice":
            temp = max(0.5, revision_temp - 0.1)

        max_tokens = max(4000, input_wc * 2)
        max_tokens = min(max_tokens, 32000)

        current_text = call_claude(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temp,
        )

        output_wc = len(current_text.split())
        pass_log.append(
            {
                "pass": pass_name,
                "input_word_count": input_wc,
                "output_word_count": output_wc,
            }
        )

        logger.info(
            "Revision pass '%s': %d -> %d words",
            pass_name,
            input_wc,
            output_wc,
        )

    return current_text, pass_log
