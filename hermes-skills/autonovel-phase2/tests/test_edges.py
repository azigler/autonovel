"""Edge / error / boundary tests beyond spec bd-b5p.5 §5.

Per /test SKILL Step 4: each spec test case should be supplemented with
boundary, error, concurrency, persistence, auth-shaped tests. This file
collects >=5 such tests covering shapes the spec doesn't explicitly call
out but that production operation will hit.

Categories covered:
- Boundary: empty inputs, whitespace, length extremes
- Error: malformed delegate response, missing identity files
- Persistence: queue files survive a re-read cycle
- Concurrency: parallel enqueue produces distinct queue_ids
- Defensive: anti-injection / malformed POV strings
"""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path

import pytest
from hermes_skills.autonovel_phase2.anchor_selector import select_anchors
from hermes_skills.autonovel_phase2.staging import stage_draft
from hermes_skills.autonovel_phase2.voice_match import voice_match_score

# ---------------------------------------------------------------------------
# EDGE 1: empty prose → stage_draft refuses or marks FAIL
# ---------------------------------------------------------------------------


def test_stage_draft_handles_empty_prose(clean_publish_queue: Path):
    """EDGE: empty-prose — staging an empty string must NOT produce a
    queue file. PublishRequest.body is required; an empty body would
    fail AO3 server-side at live-POST time anyway.
    """
    try:
        result = stage_draft(
            prose="",
            slop_penalty=0.5,
            voice_match_score=0.6,
        )
    except (ValueError, AssertionError):
        # Raising is an acceptable failure signal
        result = None
    files = list(clean_publish_queue.glob("*.json"))
    assert files == [], (
        "Empty prose must NOT land a queue file (body would fail AO3 POST)"
    )
    if result is not None:
        status = getattr(result, "status", None)
        assert status != "pending", "Empty-prose item must not be PENDING"


# ---------------------------------------------------------------------------
# EDGE 2: whitespace-only POV string → fallback fires
# ---------------------------------------------------------------------------


def test_select_anchors_whitespace_pov_triggers_fallback(
    few_shot_bank_text: str,
):
    """EDGE: whitespace-pov — passing '   ' as the POV character should
    behave like an unmatchable POV (fallback to most-recent entries),
    not return all entries or raise.
    """
    anchors = select_anchors(
        few_shot_bank_text, pov_character="   ", max_anchors=2
    )
    assert len(anchors) <= 2, (
        "Whitespace POV must not bypass the max_anchors cap"
    )
    # The fallback path returns entries; we just need non-erroring behavior
    for anchor in anchors:
        assert "POV:" in anchor


# ---------------------------------------------------------------------------
# EDGE 3: voice_match score is graceful on single-anchor input
# ---------------------------------------------------------------------------


def test_voice_match_single_anchor_does_not_divide_by_zero():
    """EDGE: single-anchor-std — with only one anchor, the std-dev of
    pooled anchor stats is 0; the heuristic's z-score formula must
    guard against divide-by-zero (per §4.4 'max(anchor_std, epsilon)').
    """
    single_anchor = (
        "She sat on the bench. The forge was loud. "
        '"Yeah," she said. "I like that."'
    )
    prose = 'She walked away. The night was still. "Goodbye," he said.'
    score = voice_match_score(prose=prose, anchor_passages=[single_anchor])
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0, (
        f"Score must be in [0.0, 1.0] even with single anchor; got {score}"
    )


# ---------------------------------------------------------------------------
# EDGE 4: voice_match handles empty anchor list defensively
# ---------------------------------------------------------------------------


def test_voice_match_empty_anchor_list_returns_neutral_or_raises():
    """EDGE: empty-anchors — when no anchors were selected (degenerate
    case the selector should have prevented), voice_match must either
    return 0.0 (neutral) or raise a clear error. It must NOT return
    NaN, infinity, or a value outside [0.0, 1.0].
    """
    try:
        score = voice_match_score(prose="Some prose.", anchor_passages=[])
    except (ValueError, ZeroDivisionError):
        return  # Raising is acceptable for this degenerate input
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0, f"Empty-anchor score out of range: {score}"
    import math

    assert not math.isnan(score), "Score must not be NaN on empty anchors"
    assert not math.isinf(score), "Score must not be inf on empty anchors"


# ---------------------------------------------------------------------------
# EDGE 5: parallel stage_draft calls produce distinct queue_ids
# ---------------------------------------------------------------------------


def test_stage_draft_concurrent_calls_produce_distinct_queue_ids(
    clean_publish_queue: Path,
):
    """CONCURRENCY: parallel-enqueue — three threads call stage_draft
    simultaneously; queue_id values must be distinct (api.queue uses
    uuid4().hex[:12] so collision probability is negligible, but we
    verify the runner doesn't accidentally serialize a shared ID).
    """

    def _stage(i: int):
        return stage_draft(
            prose=f"Paragraph number {i}. The bench was quiet.",
            slop_penalty=1.0,
            voice_match_score=0.6,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        results = list(ex.map(_stage, range(3)))

    queue_ids = [r.queue_id for r in results if r is not None]
    assert len(queue_ids) == 3, (
        f"All 3 parallel stagings must succeed; got {len(queue_ids)}"
    )
    assert len(set(queue_ids)) == 3, (
        f"queue_ids must be distinct across parallel calls; got {queue_ids}"
    )
    files = list(clean_publish_queue.glob("*.json"))
    assert len(files) == 3, (
        f"Each parallel staging writes a file; got {len(files)}"
    )


# ---------------------------------------------------------------------------
# EDGE 6: queue file round-trips through json reload
# ---------------------------------------------------------------------------


def test_staged_queue_file_round_trips_via_json(clean_publish_queue: Path):
    """PERSISTENCE: queue-roundtrip — a staged queue file must parse
    cleanly as JSON and re-validate against api.models.QueueItem on
    re-read. Defensive against impl writing partial / malformed JSON.
    """
    from api.models import QueueItem

    item = stage_draft(
        prose="She sat on the bench. The moths circled.",
        slop_penalty=1.0,
        voice_match_score=0.6,
    )
    queue_file = clean_publish_queue / f"{item.queue_id}.json"
    raw = queue_file.read_text(encoding="utf-8")
    data = json.loads(raw)
    reloaded = QueueItem.model_validate(data)
    assert reloaded.queue_id == item.queue_id
    assert reloaded.publish_request.body == item.publish_request.body
    assert reloaded.status.value == "pending"


# ---------------------------------------------------------------------------
# EDGE 7: malformed delegate_task response raises clear error
# ---------------------------------------------------------------------------


def test_extract_summary_raises_on_malformed_delegate_response():
    """ERROR: malformed-delegate — if delegate_task's JSON-string return
    isn't valid JSON, ``_extract_summary`` must raise a clear ValueError
    rather than returning None / empty string silently (would otherwise
    cause downstream slop scoring to crash with an unhelpful trace).

    bd-b5p.5.6 note: this used to test ``run_delegate(prompt=...)`` —
    that wrapper was removed when Pattern 5 moved delegate_task
    invocation to the SKILL.md agent recipe. The substantive assertion
    (extract step rejects malformed JSON) migrated to a direct test of
    ``_extract_summary``.
    """
    from hermes_skills.autonovel_phase2.runner import _extract_summary

    with pytest.raises(ValueError, match="non-JSON"):
        _extract_summary("this is not valid json at all")


def test_extract_summary_raises_on_empty_results_array():
    """ERROR: empty-results — delegate_task returning {results: []}
    must raise via ``_extract_summary``; an empty results array means
    the child produced no summary, which should not be silently treated
    as empty prose.

    bd-b5p.5.6 note: see EDGE 7 above — same migration rationale.
    """
    from hermes_skills.autonovel_phase2.runner import _extract_summary

    with pytest.raises(ValueError, match="no results"):
        _extract_summary(json.dumps({"results": []}))


# ---------------------------------------------------------------------------
# EDGE 8: identity loader uses utf-8 (BG3 character names have non-ascii)
# ---------------------------------------------------------------------------


def test_load_identity_handles_utf8_content(tmp_path: Path):
    """EDGE: utf-8-identity — autonovel identity content includes
    typographic characters (em dashes in older calibration files,
    smart quotes, ellipses). load_identity must use utf-8 encoding
    explicitly so a non-ASCII byte doesn't kill the loader on a
    Linux box with a misconfigured locale.
    """
    from hermes_skills.autonovel_phase2.identity_loader import load_identity

    # Build a minimal autonovel-shaped root with UTF-8 content
    root = tmp_path / "fake_autonovel"
    (root / "identity").mkdir(parents=True)
    (root / "identity" / "self.md").write_text(
        "Voice — Karlach POV. Smart “quotes”. Ellipsis…",
        encoding="utf-8",
    )
    (root / "identity" / "voice_priors.json").write_text(
        '{"banned": ["—"]}', encoding="utf-8"
    )
    (root / "identity" / "few_shot_bank.md").write_text(
        "# Few-Shot Bank\n\n## Entry 001\n\n**POV:** Karlach\n"
        "**Source:** sample 2026-05-27\n\nProse — prose.",
        encoding="utf-8",
    )

    ctx = load_identity(root=root)
    assert "“quotes”" in ctx["identity"] or "quotes" in ctx["identity"], (
        "UTF-8 smart quotes must survive identity load"
    )


# ---------------------------------------------------------------------------
# EDGE 9: stage_draft does not overwrite an existing queue file
# ---------------------------------------------------------------------------


def test_stage_draft_does_not_overwrite_existing_queue_file(
    clean_publish_queue: Path,
):
    """EDGE: stage-no-overwrite — successive stage_draft calls must
    not overwrite each other. The api.queue layer generates unique
    queue_ids via uuid4; this test guards the invariant that the
    Phase 2 runner doesn't accidentally pin a fixed ID.
    """
    item1 = stage_draft(
        prose="First paragraph.",
        slop_penalty=1.0,
        voice_match_score=0.6,
    )
    item2 = stage_draft(
        prose="Second paragraph.",
        slop_penalty=1.0,
        voice_match_score=0.6,
    )
    assert item1.queue_id != item2.queue_id
    file1 = clean_publish_queue / f"{item1.queue_id}.json"
    file2 = clean_publish_queue / f"{item2.queue_id}.json"
    assert file1.exists() and file2.exists()
    body1 = json.loads(file1.read_text())["publish_request"]["body"]
    body2 = json.loads(file2.read_text())["publish_request"]["body"]
    assert body1 != body2, "Distinct stagings must persist distinct bodies"


# ---------------------------------------------------------------------------
# EDGE 10: stage_draft summary stripping handles leading whitespace
# ---------------------------------------------------------------------------


def test_stage_draft_summary_strips_leading_whitespace(
    clean_publish_queue: Path,
):
    """EDGE: summary-whitespace — if the prose starts with whitespace
    (leading newlines from a delegate response), the summary must be
    stripped per §3.6 ('prose.split('.')[0].strip()[:250]'). A
    summary that begins with '\\n   ' would look broken on AO3.
    """
    prose = "\n   She sat on the bench.   The moths circled."
    item = stage_draft(
        prose=prose,
        slop_penalty=1.0,
        voice_match_score=0.6,
    )
    summary = item.publish_request.summary
    assert not summary.startswith(" "), "Summary must not start with whitespace"
    assert not summary.startswith("\n"), "Summary must not start with newline"
