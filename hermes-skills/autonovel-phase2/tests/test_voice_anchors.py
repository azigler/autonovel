"""T-V-* coverage: POV-aware voice-anchor selection + voice-match heuristic.

Spec: bd-b5p.5 §5 (test cases T-V-1, T-V-2, T-V-3, T-V-4, T-V-5)
Sub-spec: §3.4 (anchor_selector) + §3.5 (voice_match heuristic)

The voice anchor pipeline replaces Phase 1's "first 3K chars of
few_shot_bank dumped indiscriminately" with structured POV-aware
selection, plus a downstream heuristic that scores draft prose against
the selected anchors. The gate is ADVISORY in Phase 2 (score logged but
draft is not blocked).
"""

from __future__ import annotations

from hermes_skills.autonovel_phase2.anchor_selector import select_anchors
from hermes_skills.autonovel_phase2.voice_match import (
    passes_voice_gate,
    voice_match_score,
)

# ---------------------------------------------------------------------------
# T-V-1: POV selector returns Karlach anchors for Karlach brief
# ---------------------------------------------------------------------------


def test_select_anchors_karlach_returns_karlach_pov_entries(
    few_shot_bank_text: str,
):
    """TEST: T-V-1 (spec bd-b5p.5, POV match basic) — select_anchors with
    pov_character='Karlach' must return entries whose POV line contains
    'Karlach' (case-insensitive substring).

    Per the current bank: Entry 001 (Karlach) and Entry 005 (Karlach
    with Dammon in dialogue) both qualify.
    """
    anchors = select_anchors(
        few_shot_bank_text, pov_character="Karlach", max_anchors=2
    )
    assert len(anchors) == 2, (
        f"Expected 2 Karlach POV anchors, got {len(anchors)}"
    )
    for anchor in anchors:
        assert "karlach" in anchor.lower(), (
            "Each returned anchor must reference Karlach in its POV line"
        )
        # POV line shape: **POV:** Karlach...
        assert "POV:" in anchor, (
            "Each anchor block must include the **POV:** marker"
        )


def test_select_anchors_respects_max_anchors_cap(few_shot_bank_text: str):
    """TEST: T-V-1 (spec bd-b5p.5, max_anchors cap) — even if more than
    max_anchors entries match the POV, the selector must cap at
    max_anchors. Per §3.4 MAX_ANCHORS=2 token-budget rationale.
    """
    anchors = select_anchors(
        few_shot_bank_text, pov_character="Karlach", max_anchors=1
    )
    assert len(anchors) == 1, (
        f"max_anchors=1 must return exactly 1 anchor, got {len(anchors)}"
    )


def test_select_anchors_shadowheart_returns_shadowheart_entries(
    few_shot_bank_text: str,
):
    """TEST: T-V-1 (spec bd-b5p.5, POV match coverage) — Shadowheart
    POV must select Entry 003 and Entry 004 (the two Shadowheart
    entries in the current bank).
    """
    anchors = select_anchors(
        few_shot_bank_text, pov_character="Shadowheart", max_anchors=2
    )
    assert len(anchors) == 2
    for anchor in anchors:
        assert "shadowheart" in anchor.lower()


# ---------------------------------------------------------------------------
# T-V-2: POV selector fallback when no matches
# ---------------------------------------------------------------------------


def test_select_anchors_fallback_when_no_pov_match(few_shot_bank_text: str):
    """TEST: T-V-2 (spec bd-b5p.5, fallback path) — when zero entries
    match the requested POV (e.g. 'Halsin' not in current bank), the
    selector returns the max_anchors most-recently-dated entries by
    the **Source:** date suffix.
    """
    anchors = select_anchors(
        few_shot_bank_text, pov_character="Halsin", max_anchors=2
    )
    assert len(anchors) == 2, (
        "Fallback must still return max_anchors entries; non-empty bank"
    )
    # The fallback must still produce valid entry blocks
    for anchor in anchors:
        assert "POV:" in anchor
        assert "Source:" in anchor


def test_select_anchors_returns_empty_for_empty_bank():
    """TEST: T-V-2 (spec bd-b5p.5, defensive on empty bank) — when the
    bank text is empty, the selector must return an empty list (no
    fallback can fire if there's nothing to fall back TO).
    """
    anchors = select_anchors("", pov_character="Karlach", max_anchors=2)
    assert anchors == [], "Empty bank text must return empty list, not raise"


# ---------------------------------------------------------------------------
# T-V-3: voice-match score for prose echoing anchor stats
# ---------------------------------------------------------------------------


def test_voice_match_score_high_for_anchor_self_match(
    few_shot_bank_text: str,
):
    """TEST: T-V-3 (spec bd-b5p.5, heuristic sanity) — when the prose
    is assembled by sampling sentences from the SELECTED anchors
    themselves, voice_match_score must be >= 0.8.

    Per §3.5 sanity rationale: if this fails, the heuristic is broken
    (can't recognize its own anchor stats).
    """
    anchors = select_anchors(
        few_shot_bank_text, pov_character="Karlach", max_anchors=2
    )
    # Concatenate the anchor passages as the "prose" — the stats should
    # be essentially identical to the pooled anchor stats.
    prose = "\n\n".join(anchors)
    score = voice_match_score(prose=prose, anchor_passages=anchors)
    assert 0.0 <= score <= 1.0, "Score must be in [0.0, 1.0]"
    assert score >= 0.8, (
        f"Anchor self-match should score >=0.8, got {score:.3f}"
    )


# ---------------------------------------------------------------------------
# T-V-4: voice-match score for adversarial off-voice prose
# ---------------------------------------------------------------------------


def test_voice_match_score_low_for_adversarial_prose(few_shot_bank_text: str):
    """TEST: T-V-4 (spec bd-b5p.5, heuristic discrimination) — uniformly
    short sentences with no dialogue and no em-dashes (opposite shape
    from the anchors) must score <= 0.3.

    If this passes too high, the heuristic is stuck-at-pass.
    """
    anchors = select_anchors(
        few_shot_bank_text, pov_character="Karlach", max_anchors=2
    )
    adversarial = (
        "It was a dark and stormy night. There were many things. "
        "They happened. The end. Bob walked. He stopped. He went. "
        "Things occurred. People did stuff. Time passed."
    )
    score = voice_match_score(prose=adversarial, anchor_passages=anchors)
    assert 0.0 <= score <= 1.0
    assert score <= 0.3, (
        f"Adversarial prose should score <=0.3, got {score:.3f}"
    )


# ---------------------------------------------------------------------------
# T-V-5: voice-match warning, not block, on Phase 2 (advisory only)
# ---------------------------------------------------------------------------


def test_passes_voice_gate_returns_pass_signal_above_threshold():
    """TEST: T-V-5 (spec bd-b5p.5, gate threshold) — passes_voice_gate
    returns True for scores >= 0.5 (the §3.5 advisory threshold).
    """
    assert passes_voice_gate(0.5) is True
    assert passes_voice_gate(0.7) is True
    assert passes_voice_gate(1.0) is True


def test_passes_voice_gate_returns_fail_signal_below_threshold():
    """TEST: T-V-5 (spec bd-b5p.5, gate threshold) — passes_voice_gate
    returns False for scores < 0.5. The signal is advisory; runner
    logs warning but does NOT abort enqueue.
    """
    assert passes_voice_gate(0.4) is False
    assert passes_voice_gate(0.0) is False


def test_voice_gate_is_advisory_not_blocking_phase2():
    """TEST: T-V-5 (spec bd-b5p.5, advisory contract) — confirm
    passes_voice_gate's return is a soft signal, NOT something that
    raises. Per §3.5: 'log a warning but DO NOT block the draft from
    queuing'. The contract is: callers may inspect the return; the
    function itself never raises on a low score.
    """
    # Should never raise across the full [0.0, 1.0] range
    for score in (0.0, 0.1, 0.25, 0.5, 0.75, 1.0):
        _ = passes_voice_gate(score)  # must not raise


# ---------------------------------------------------------------------------
# Cross-cutting: anchor selector output is non-overlapping and well-formed
# ---------------------------------------------------------------------------


def test_select_anchors_returns_distinct_entries(few_shot_bank_text: str):
    """TEST: T-V-1 (spec bd-b5p.5, distinctness invariant) — multiple
    selected anchors must be distinct entry blocks (selector must not
    return the same entry twice when more than one match exists).
    """
    anchors = select_anchors(
        few_shot_bank_text, pov_character="Karlach", max_anchors=2
    )
    if len(anchors) >= 2:
        assert anchors[0] != anchors[1], (
            "Distinct selected anchors required when bank has multiple "
            "matches for POV"
        )
