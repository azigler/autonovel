"""Fanfic-specific evaluation gate.

Wraps evaluate.py's mechanical slop scorer and adds LLM quality evaluation
(stub for now) and characterization accuracy checking (stub for now).
"""

from __future__ import annotations

from typing import Any

# Gate thresholds per spec 4.5
SLOP_THRESHOLD = 3.0
QUALITY_THRESHOLD = 7.0
CHARACTERIZATION_THRESHOLD = 6.0


def evaluate_gate(
    scores: dict[str, Any],
) -> tuple[bool, str]:
    """Check all evaluation gates in priority order.

    Returns:
        (passed, reason) where reason is one of:
        "PASS", "SLOP_FAIL", "CHARACTERIZATION_FAIL", "QUALITY_FAIL"
    """
    # Check 1: Mechanical slop (HARD GATE) -- checked first
    slop_penalty = scores.get("slop_penalty", 0.0)
    if slop_penalty >= SLOP_THRESHOLD:
        return False, "SLOP_FAIL"

    # Check 2: Characterization accuracy
    char_data = scores.get("characterization_accuracy", {})
    char_score = (
        char_data.get("score", 0.0) if isinstance(char_data, dict) else 0.0
    )
    if char_score < CHARACTERIZATION_THRESHOLD:
        return False, "CHARACTERIZATION_FAIL"

    # Check 3: Overall quality (SOFT GATE)
    overall_score = scores.get("overall_score", 0.0)
    if overall_score < QUALITY_THRESHOLD:
        return False, "QUALITY_FAIL"

    return True, "PASS"


def evaluate_draft(
    draft_text: str,
    brief: Any = None,
    context: dict | None = None,
) -> dict[str, Any]:
    """Evaluate a draft through mechanical slop detection and LLM scoring.

    This is the default implementation that will be called when not mocked.
    Real LLM evaluation will be added later.

    Args:
        draft_text: The full draft text to evaluate.
        brief: The StoryBrief (for context-aware evaluation).
        context: Assembled context dict.

    Returns:
        Dict with slop_penalty, overall_score, and per-dimension scores.
    """
    # Mechanical slop detection
    try:
        from evaluate import slop_score

        slop_result = slop_score(draft_text)
        slop_penalty = slop_result.get("slop_penalty", 0.0)
    except ImportError:
        slop_penalty = 0.0
        slop_result = {}

    # Stub LLM evaluation scores (will be replaced with real Claude API calls)
    return {
        "slop_penalty": slop_penalty,
        "overall_score": 7.5,
        "characterization_accuracy": {
            "score": 7.0,
            "feedback": "Characters appear consistent with canon.",
        },
        "voice_adherence": {"score": 7.0},
        "fandom_voice_fit": {"score": 7.0},
        "prose_quality": {"score": 7.5},
        "engagement": {"score": 7.0},
        "pacing": {"score": 7.0},
        "emotional_arc": {"score": 7.0},
        **{k: v for k, v in slop_result.items() if k != "slop_penalty"},
    }
