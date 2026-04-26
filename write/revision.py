"""Revision brief generation.

Generates focused revision briefs from evaluation gate results. The
brief is a structured plain-text document the orchestrator then feeds
to a revision subagent (built via :mod:`write.prompts`).

The previous direct-API revision callers (``generate_revision``,
``call_revision_model``, ``run_revision_passes``,
``_build_pass_system_prompt``) lived here too. They were retired in the
bd-75p migration: the orchestrator now drives revision through
in-harness subagents using the builders in :mod:`write.prompts`. What
remains is :func:`generate_revision_brief`, which is pure (no I/O, no
API) and produces the brief that revision prompts consume.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default pass selection based on revision_passes count.
# The orchestrator reads this when deciding which revision passes to dispatch.
_PASS_SUBSETS: dict[int, list[str]] = {
    1: ["structure"],
    2: ["structure", "voice"],
    3: ["structure", "depth", "voice"],
    4: ["structure", "depth", "voice", "cut"],
}

# Which passes to run for each gate failure type.
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

    * ``SLOP_FAIL`` -- focus on specific slop hits and banned word
      replacements.
    * ``CHARACTERIZATION_FAIL`` -- include character notes and canonical
      behavior.
    * ``QUALITY_FAIL`` -- highlight weakest scoring dimensions.

    Args:
        scores: Evaluation scores dict.
        gate_result: One of ``"SLOP_FAIL"``, ``"CHARACTERIZATION_FAIL"``,
            ``"QUALITY_FAIL"``.
        draft_text: The current draft text. Currently unused by the body;
            present for forward-compat (a future iteration may quote
            offending excerpts).
        fandom_context: Fandom context for character notes.

    Returns:
        A structured revision brief string.
    """
    # ``draft_text`` is reserved for future excerpt-quoting passes.
    _ = draft_text

    parts: list[str] = ["REVISION BRIEF", "=" * 40, ""]

    if gate_result == "SLOP_FAIL":
        parts.append("PROBLEM: Mechanical slop detection failed (hard gate).")
        parts.append(f"Slop penalty: {scores.get('slop_penalty', 'unknown')}")
        parts.append("")

        tier1_hits = scores.get("tier1_hits", [])
        if tier1_hits:
            parts.append("BANNED WORDS FOUND (must remove):")
            for word, count in tier1_hits:
                parts.append(f"  - '{word}' appears {count} time(s)")
            parts.append("")

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
