"""Sanity-import coverage for the pure helpers that ship UNCHANGED
from the bd-b5p.5.6 Pattern 5 sibling per spec §3.7.

The new kanban-worker SKILL body re-uses the same helpers via
``execute_code`` snippets that ``importlib.util.spec_from_file_location``
them from
``/home/ubuntu/explore/autonovel/hermes-skills/autonovel-phase2/``.
We sanity-import each of the 5 helper modules + assert 1-2 baseline
behaviors so a regression in the helper API surface is caught BEFORE
the worker's execute_code snippet hits it at runtime.

Coverage:
- ``runner._wrap_prompt`` — string-concat sanity
- ``runner._check_preamble`` — raises on preamble leakage
- ``runner._extract_summary`` — parses delegate JSON shape
- ``staging.stage_draft`` — importable + accepts the documented args
- ``voice_match.voice_match_score`` — importable + returns float
- ``anchor_selector.select_anchors`` — importable + returns list
- ``identity_loader.load_identity`` — importable + returns dict

We deliberately avoid duplicating the full 65-test surface of the
bd-b5p.5.6 sibling — that lives in
``hermes-skills/autonovel-phase2/tests/`` and continues to run. These
are import-anchored sanity tests: "did the helpers MOVE under our
feet" (they shouldn't, per §3.7).

Covers spec test cases T-K-11 through T-K-15.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Import sanity — each module must be importable from the worker context
# ---------------------------------------------------------------------------


def test_import_runner_module():
    """T-K-15: ``hermes_skills.autonovel_phase2.runner`` must import.

    The worker's Step 3 execute_code snippet does this exact import
    via importlib.util.spec_from_file_location. If the module path
    breaks, generation fails before the wrapped prompt is built.
    """
    from hermes_skills.autonovel_phase2 import runner

    assert hasattr(runner, "_wrap_prompt"), "_wrap_prompt missing from runner"
    assert hasattr(runner, "_check_preamble"), "_check_preamble missing"
    assert hasattr(runner, "_extract_summary"), "_extract_summary missing"


def test_import_staging_module():
    """T-K-13: ``hermes_skills.autonovel_phase2.staging`` must import."""
    from hermes_skills.autonovel_phase2 import staging

    assert hasattr(staging, "stage_draft"), "stage_draft missing from staging"


def test_import_voice_match_module():
    """T-K-12: ``hermes_skills.autonovel_phase2.voice_match`` must import."""
    from hermes_skills.autonovel_phase2 import voice_match

    assert hasattr(voice_match, "voice_match_score"), (
        "voice_match_score missing"
    )


def test_import_anchor_selector_module():
    """T-K-11: ``hermes_skills.autonovel_phase2.anchor_selector`` must import."""
    from hermes_skills.autonovel_phase2 import anchor_selector

    assert hasattr(anchor_selector, "select_anchors"), "select_anchors missing"


def test_import_identity_loader_module():
    """T-K-11/12 prerequisite: ``identity_loader`` must import."""
    from hermes_skills.autonovel_phase2 import identity_loader

    assert hasattr(identity_loader, "load_identity"), (
        "load_identity missing from identity_loader"
    )


# ---------------------------------------------------------------------------
# T-K-14 / T-K-15 baseline behavior — runner.py helpers
# ---------------------------------------------------------------------------


def test_check_preamble_raises_on_leak():
    """T-K-14: ``_check_preamble`` raises on delegate preamble leakage.

    Re-asserts the bd-b5p.5.6 contract: prose starting with "I'll" /
    "Here is" / etc. must raise so staging skips the enqueue.
    """
    from hermes_skills.autonovel_phase2.runner import _check_preamble

    with pytest.raises(ValueError, match="preamble"):
        _check_preamble("I'll draft the fanfic chapter now...")


def test_check_preamble_accepts_clean_prose():
    """T-K-14 (negative case): clean prose must NOT raise."""
    from hermes_skills.autonovel_phase2.runner import _check_preamble

    # Clean prose starting with a character action, not preamble
    _check_preamble("Karlach leaned against the bedroll, fire still warm...")


def test_extract_summary_parses_delegate_json():
    """T-K-15: ``_extract_summary`` parses the delegate_task return shape.

    The contract is: input is a JSON string of the shape
    ``{"results": [{"summary": "...", "child_session_id": "..."}]}``.
    """
    from hermes_skills.autonovel_phase2.runner import _extract_summary

    payload = (
        '{"results": [{"summary": "PROSE HERE", "child_session_id": "abc"}]}'
    )
    result = _extract_summary(payload)
    assert result == "PROSE HERE"


def test_extract_summary_raises_on_malformed():
    """T-K-15 (negative): malformed JSON must raise — fail loud
    rather than silently enqueue empty prose."""
    from hermes_skills.autonovel_phase2.runner import _extract_summary

    with pytest.raises(ValueError):
        _extract_summary("not json at all")


def test_extract_summary_raises_on_empty_results():
    """T-K-15 (edge): empty results list must raise."""
    from hermes_skills.autonovel_phase2.runner import _extract_summary

    with pytest.raises(ValueError):
        _extract_summary('{"results": []}')


# ---------------------------------------------------------------------------
# T-K-11 baseline — anchor selector returns list
# ---------------------------------------------------------------------------


def test_select_anchors_returns_list():
    """T-K-11: ``select_anchors`` returns a list (even on empty bank)."""
    from hermes_skills.autonovel_phase2.anchor_selector import select_anchors

    result = select_anchors("", pov_character="Karlach", max_anchors=2)
    assert isinstance(result, list)


def test_select_anchors_respects_max_anchors_cap():
    """T-K-11: max_anchors caps the return list length."""
    from hermes_skills.autonovel_phase2.anchor_selector import select_anchors

    # Build a tiny fixture bank with 5 entries, all Karlach POV
    bank = "\n\n".join(
        f"## ANCHOR {i}\nPOV: Karlach\nText line {i}\n" for i in range(5)
    )
    result = select_anchors(bank, pov_character="Karlach", max_anchors=2)
    assert len(result) <= 2


# ---------------------------------------------------------------------------
# T-K-12 baseline — voice_match returns float
# ---------------------------------------------------------------------------


def test_voice_match_score_returns_float():
    """T-K-12: ``voice_match_score`` returns a float in [0.0, 1.0]
    range (heuristic gate output)."""
    from hermes_skills.autonovel_phase2.voice_match import voice_match_score

    score = voice_match_score(prose="some test prose", anchor_passages=[])
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0, f"voice_match_score out of [0,1]: {score}"


# ---------------------------------------------------------------------------
# T-K-13 baseline — stage_draft signature accepts documented kwargs
# ---------------------------------------------------------------------------


def test_stage_draft_signature_kwargs_accepted(
    clean_publish_queue,
    monkeypatch: pytest.MonkeyPatch,
):
    """T-K-13: ``stage_draft`` accepts the canonical kwargs
    (prose, slop_penalty, voice_match_score) — the worker's Step 5
    execute_code snippet uses exactly these.

    We don't assert pass/fail behavior here (that's covered by the
    bd-b5p.5.6 sibling test suite); we just exercise the call shape.
    """
    from hermes_skills.autonovel_phase2.staging import stage_draft

    # High slop_penalty should trip the firewall and return None
    result = stage_draft(
        prose="dummy prose for kwarg signature test",
        slop_penalty=99.0,
        voice_match_score=0.5,
    )
    # We expect None (firewall trip) — but the call shape itself must
    # not raise on the kwargs.
    assert result is None or hasattr(result, "queue_id")


# ---------------------------------------------------------------------------
# Conftest fixture exists for clean_publish_queue (copy of sibling pattern)
# ---------------------------------------------------------------------------


@pytest.fixture()
def clean_publish_queue(tmp_path, monkeypatch):
    """Mirror of the bd-b5p.5.6 sibling fixture — redirect QUEUE_DIR
    to a tmp dir for the test's stage_draft call."""
    import importlib

    queue_dir = tmp_path / "publish_queue"
    queue_dir.mkdir()
    api_queue = importlib.import_module("api.queue")
    monkeypatch.setattr(api_queue, "QUEUE_DIR", queue_dir)
    return queue_dir


# ---------------------------------------------------------------------------
# Identity loader sanity
# ---------------------------------------------------------------------------


def test_load_identity_returns_dict(autonovel_root):
    """T-K-11 prereq: ``load_identity()`` returns a dict with the
    documented keys. The worker's Step 3 execute_code snippet calls
    this to seed ctx for anchor selection.
    """
    from hermes_skills.autonovel_phase2.identity_loader import load_identity

    # load_identity reads from the autonovel repo's identity/ dir;
    # confirm dict shape (specific keys depend on the host's identity
    # files — we just assert the type contract).
    result = load_identity()
    assert isinstance(result, dict), (
        f"load_identity() must return a dict; got {type(result).__name__}"
    )
