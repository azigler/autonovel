"""Voice-match heuristic for autonovel-phase2.

Spec bd-b5p.5 §3.5 + §4.4: compute four normalized stats on prose AND on
each anchor passage, z-score each prose metric against the pooled anchor
distribution, bucket per-metric to {1.0, 0.5, 0.0}, and average. Final
score in [0.0, 1.0]; ``passes_voice_gate`` returns True at >= 0.5.

The gate is ADVISORY in Phase 2 — callers log warnings on low scores
but do NOT block enqueue. Phase 3 may promote it to hard-gate after
seven days of calibration data (OQ-4).

Bead: bd-b5p.5
"""

from __future__ import annotations

import math
import re

# Default advisory threshold per spec §3.5 (OQ-4 ACCEPT, recalibrate
# from cron data after 7 days).
DEFAULT_THRESHOLD = 0.5

# Guard against divide-by-zero when only one anchor is available (std == 0).
_EPSILON = 1e-6

# Per-metric z-score buckets per spec §4.4.
_Z_TIGHT = 1.0  # z <= 1.0 -> per-metric score 1.0
_Z_LOOSE = 3.0  # z <= 3.0 -> per-metric score 0.5


def _sentences(text: str) -> list[str]:
    """Split text on terminal punctuation, dropping fragments < 3 words.

    Matches evaluate.py's sentence-extraction shape so the voice stats
    align with the slop scorer's view of the prose.
    """
    parts = re.split(r"[.!?]+", text)
    return [s.strip() for s in parts if len(s.strip().split()) >= 3]


def _avg_sentence_length(text: str) -> float:
    sents = _sentences(text)
    if not sents:
        return 0.0
    lengths = [len(s.split()) for s in sents]
    return sum(lengths) / len(lengths)


def _sentence_length_std(text: str) -> float:
    sents = _sentences(text)
    if len(sents) < 2:
        return 0.0
    lengths = [len(s.split()) for s in sents]
    mean = sum(lengths) / len(lengths)
    var = sum((length - mean) ** 2 for length in lengths) / len(lengths)
    return math.sqrt(var)


def _em_dashes_per_1000_words(text: str) -> float:
    words = text.split()
    if not words:
        return 0.0
    em = text.count("—") + text.count("--")
    return (em / len(words)) * 1000


def _dialogue_ratio(text: str) -> float:
    """Proportion of sentences whose content includes a dialogue quote.

    A "dialogue sentence" is one containing a double-quote span that
    closes (open " ... close "). This is a heuristic — matches the
    common ``"..." she said`` shape without over-counting attribution
    fragments.
    """
    sents = _sentences(text)
    if not sents:
        return 0.0
    dialogue = 0
    for sent in sents:
        if sent.count('"') >= 2 or sent.count("“") >= 1:
            dialogue += 1
    return dialogue / len(sents)


# Ordered for deterministic iteration in tests + debugging.
_METRIC_FNS = (
    ("avg_sentence_length", _avg_sentence_length),
    ("sentence_length_std", _sentence_length_std),
    ("em_dashes_per_1000_words", _em_dashes_per_1000_words),
    ("dialogue_ratio", _dialogue_ratio),
)


def _metric_vector(text: str) -> dict[str, float]:
    """Compute all four normalized metrics for a single text body."""
    return {name: fn(text) for name, fn in _METRIC_FNS}


def _per_metric_score(prose_value: float, mean: float, std: float) -> float:
    """Bucket the prose value's z-score per spec §4.4.

    Returns 1.0 if z <= 1, 0.5 if z <= 3, 0.0 otherwise.
    """
    denom = max(std, _EPSILON)
    z = abs(prose_value - mean) / denom
    if z <= _Z_TIGHT:
        return 1.0
    if z <= _Z_LOOSE:
        return 0.5
    return 0.0


def voice_match_score(prose: str, anchor_passages: list[str]) -> float:
    """Compare prose's voice-stat shape to the pooled anchor distribution.

    Args:
        prose: Generated paragraph (the child's response).
        anchor_passages: List of raw anchor markdown blocks (from
            ``anchor_selector.select_anchors``).

    Returns:
        Score in ``[0.0, 1.0]``. 1.0 = all four metrics within 1 std
        of the anchor mean; 0.0 = all metrics > 3 std off. Degenerate
        input (empty prose, empty anchors) returns 0.0 rather than NaN.
    """
    if not anchor_passages:
        return 0.0
    if not prose or not prose.strip():
        return 0.0

    prose_stats = _metric_vector(prose)

    # Compute each anchor's stats independently, then aggregate per
    # metric. Pooled mean+std lets us z-score the prose against the
    # author's empirical distribution across anchors.
    anchor_stats = [_metric_vector(a) for a in anchor_passages]

    per_metric_scores: list[float] = []
    for name, _ in _METRIC_FNS:
        values = [a[name] for a in anchor_stats]
        mean = sum(values) / len(values)
        if len(values) >= 2:
            var = sum((v - mean) ** 2 for v in values) / len(values)
            std = math.sqrt(var)
        else:
            # Single-anchor case: no spread to measure against. We use
            # a small fraction of the mean as the implied tolerance so
            # the per-metric score remains meaningful (prose close to
            # the single anchor scores 1.0; very different scores 0.0).
            # The 10% tolerance is the same shape Phase 1 used in
            # ad-hoc spot checks — see spec §3.5.
            std = max(abs(mean) * 0.1, _EPSILON)
        per_metric_scores.append(
            _per_metric_score(prose_stats[name], mean, std)
        )

    return sum(per_metric_scores) / len(per_metric_scores)


def passes_voice_gate(
    score: float,
    threshold: float = DEFAULT_THRESHOLD,
) -> bool:
    """Return True if the score meets the (advisory) voice-match gate.

    Per spec §3.5 the gate is ADVISORY in Phase 2 — never blocks the
    enqueue; callers log warnings on False but proceed regardless.

    Args:
        score: Output of ``voice_match_score``, range [0.0, 1.0].
        threshold: Pass threshold. Default ``DEFAULT_THRESHOLD`` (0.5).

    Returns:
        True if ``score >= threshold``, else False. Never raises.
    """
    return score >= threshold
