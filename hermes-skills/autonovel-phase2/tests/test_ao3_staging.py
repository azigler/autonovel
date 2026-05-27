"""T-A-* coverage: AO3 staging (publish_queue) + PublishRequest contract.

Spec: bd-b5p.5 §5 (test cases T-A-1, T-A-2, T-A-3, T-A-4, T-A-5)
Sub-spec: §3.6 (AO3 staging — local queue, not live POST)

Phase 2's last orthogonal axis: the parent agent constructs a
PublishRequest from generated prose + brief metadata and calls
api.queue.enqueue to land it at publish_queue/<id>.json with
status=PENDING. Live AO3 POST is explicitly deferred to Phase 3.
"""

from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest
from hermes_skills.autonovel_phase2.staging import stage_draft

# ---------------------------------------------------------------------------
# T-A-1: PublishRequest fields all set
# ---------------------------------------------------------------------------


def test_stage_draft_lands_queue_item_with_all_publish_request_fields(
    clean_publish_queue: Path,
):
    """TEST: T-A-1 (spec bd-b5p.5, queue contract complete) — successful
    staging must produce publish_queue/<id>.json whose publish_request
    has all 7 fields populated and status=pending.
    """
    prose = (
        "She sat on the bench. The moths kept circling the lamp. "
        "Astarion was quiet, for once. She did not break the silence."
    )
    item = stage_draft(
        prose=prose,
        slop_penalty=1.5,
        voice_match_score=0.7,
    )
    queue_file = clean_publish_queue / f"{item.queue_id}.json"
    assert queue_file.exists(), "stage_draft must write a queue file"
    data = json.loads(queue_file.read_text())
    pr = data["publish_request"]
    for field in (
        "title",
        "fandom",
        "rating",
        "tags",
        "summary",
        "body",
        "author_notes",
    ):
        assert pr.get(field), f"publish_request.{field} must be non-empty"
    assert pr["tags"], "tags list must be non-empty"
    assert data["status"] == "pending"
    assert data.get("ao3_work_id") is None, (
        "ao3_work_id must be null on a freshly-staged item"
    )


def test_stage_draft_uses_phase2_canonical_fandom_string(
    clean_publish_queue: Path,
):
    """TEST: T-A-1 (spec bd-b5p.5, AO3 canonical fandom) — per §3.6 the
    fandom field must be the AO3-canonical 'Baldur's Gate 3 (Video
    Game)' for Phase 2's hardcoded brief.
    """
    item = stage_draft(
        prose="A short paragraph that fits.",
        slop_penalty=1.0,
        voice_match_score=0.6,
    )
    assert item.publish_request.fandom == "Baldur's Gate 3 (Video Game)", (
        "Phase 2 §3.6 mandates AO3-canonical fandom string"
    )


# ---------------------------------------------------------------------------
# T-A-2: summary truncation respects 250-char limit
# ---------------------------------------------------------------------------


def test_stage_draft_truncates_summary_to_250_chars(
    clean_publish_queue: Path,
):
    """TEST: T-A-2 (spec bd-b5p.5, AO3 summary limit) — if the prose's
    first sentence exceeds 250 chars, publish_request.summary length
    must be <= 250. AO3 enforces 250-char summaries; oversized would
    error at live-POST time.
    """
    long_first_sentence = "She " + ("walked, " * 200) + "and stopped."
    assert len(long_first_sentence.split(".")[0]) > 250
    item = stage_draft(
        prose=long_first_sentence,
        slop_penalty=1.0,
        voice_match_score=0.6,
    )
    assert len(item.publish_request.summary) <= 250, (
        f"summary length {len(item.publish_request.summary)} > 250"
    )


def test_stage_draft_summary_is_first_sentence_when_short(
    clean_publish_queue: Path,
):
    """TEST: T-A-2 (spec bd-b5p.5, summary derivation rule) — when the
    first sentence is short, the summary equals the first sentence
    (stripped). Per §3.6: summary = prose.split('.')[0].strip()[:250].
    """
    prose = "She sat on the bench. The moths kept circling."
    item = stage_draft(
        prose=prose,
        slop_penalty=1.0,
        voice_match_score=0.6,
    )
    assert item.publish_request.summary == "She sat on the bench"


# ---------------------------------------------------------------------------
# T-A-3: author_notes contains bead ID + slop + voice scores
# ---------------------------------------------------------------------------


def test_stage_draft_author_notes_contain_bead_id(clean_publish_queue: Path):
    """TEST: T-A-3 (spec bd-b5p.5, audit trail bead ID) — the
    author_notes HTML comment must contain the bead ID 'bd-b5p.5' so
    operators reviewing the queue can trace provenance.
    """
    item = stage_draft(
        prose="A short paragraph.",
        slop_penalty=1.2,
        voice_match_score=0.65,
    )
    notes = item.publish_request.author_notes
    assert "bd-b5p.5" in notes, (
        "author_notes must contain the bead ID for provenance"
    )


def test_stage_draft_author_notes_contain_slop_and_voice_scores(
    clean_publish_queue: Path,
):
    """TEST: T-A-3 (spec bd-b5p.5, audit trail scores) — the
    author_notes must include the numeric slop_penalty and the
    numeric voice_match_score.
    """
    item = stage_draft(
        prose="A short paragraph.",
        slop_penalty=1.234,
        voice_match_score=0.567,
    )
    notes = item.publish_request.author_notes
    assert "1.234" in notes or "1.23" in notes, (
        "author_notes must include slop_penalty numeric value"
    )
    assert "0.567" in notes or "0.57" in notes, (
        "author_notes must include voice_match_score numeric value"
    )


def test_stage_draft_author_notes_are_html_comment_wrapped(
    clean_publish_queue: Path,
):
    """TEST: T-A-3 (spec bd-b5p.5, hidden-from-AO3-readers) — the
    metadata must be inside <!-- ... --> HTML comment markers so it
    doesn't render on the published AO3 page.
    """
    item = stage_draft(
        prose="A short paragraph.",
        slop_penalty=1.0,
        voice_match_score=0.6,
    )
    notes = item.publish_request.author_notes
    assert "<!--" in notes and "-->" in notes, (
        "author_notes metadata must be HTML-comment-wrapped"
    )


# ---------------------------------------------------------------------------
# T-A-4: slop gate failure skips queue entry
# ---------------------------------------------------------------------------


def test_stage_draft_skips_queue_when_slop_above_threshold(
    clean_publish_queue: Path,
):
    """TEST: T-A-4 (spec bd-b5p.5, slop gate firewall) — when
    slop_penalty >= 3.0 (production threshold per §4.6), stage_draft
    must NOT write a file and must signal failure (return None or
    raise, depending on impl design).
    """
    files_before = list(clean_publish_queue.glob("*.json"))
    result = stage_draft(
        prose="Some slop-laden prose with delve and tapestry.",
        slop_penalty=4.5,  # above the 3.0 prod threshold
        voice_match_score=0.6,
    )
    files_after = list(clean_publish_queue.glob("*.json"))
    assert len(files_after) == len(files_before), (
        "Slop gate failure must NOT add a file to publish_queue"
    )
    # Acceptable failure signals: returns None, returns a sentinel with
    # status=='FAIL', or raises. Tests guard the file-write invariant.
    if result is not None:
        # If impl returns an object, status must NOT be PENDING/published
        status = getattr(result, "status", None)
        assert status not in ("pending", "published"), (
            f"Failed slop gate must not produce a queued item; got "
            f"status={status!r}"
        )


def test_stage_draft_threshold_is_3_not_phase1_5(
    clean_publish_queue: Path,
):
    """TEST: T-A-4 (spec bd-b5p.5, production threshold tightening) —
    Phase 2 must use the production 3.0 threshold (NOT Phase 1's
    relaxed 5.0). A score of 3.5 must FAIL the gate.
    """
    files_before = list(clean_publish_queue.glob("*.json"))
    stage_draft(
        prose="prose body",
        slop_penalty=3.5,  # would pass Phase 1's 5.0, must fail Phase 2's 3.0
        voice_match_score=0.6,
    )
    files_after = list(clean_publish_queue.glob("*.json"))
    assert len(files_after) == len(files_before), (
        "slop_penalty=3.5 must fail Phase 2's 3.0 threshold"
    )


# ---------------------------------------------------------------------------
# T-A-5: no live AO3 POST attempted
# ---------------------------------------------------------------------------


def test_stage_draft_does_not_import_ao3_client(
    monkeypatch: pytest.MonkeyPatch,
):
    """TEST: T-A-5 (spec bd-b5p.5, no live POST) — the Phase 2 staging
    module must not import api.ao3_client at module load time.
    api.ao3_client is the live-AO3 POST client; Phase 2 is staging-only.
    """
    # Ensure api.ao3_client isn't pre-loaded by some other test
    sys.modules.pop("api.ao3_client", None)
    # Reload staging fresh and observe imports
    staging_name = "hermes_skills.autonovel_phase2.staging"
    if staging_name in sys.modules:
        del sys.modules[staging_name]
    importlib.import_module(staging_name)
    assert "api.ao3_client" not in sys.modules, (
        "Phase 2 staging path must NOT import api.ao3_client (T-A-5)"
    )


def test_stage_draft_source_does_not_reference_ao3_client():
    """TEST: T-A-5 (spec bd-b5p.5, static no-live-POST) — defensive
    static check: staging.py source must not contain 'ao3_client'
    or any 'archiveofourown.org' URL.
    """
    staging_mod = importlib.import_module(
        "hermes_skills.autonovel_phase2.staging"
    )
    src = inspect.getsource(staging_mod)
    assert "ao3_client" not in src, (
        "staging.py must not reference api.ao3_client (Phase 3 work)"
    )
    assert "archiveofourown.org" not in src, (
        "staging.py must not contain archiveofourown.org URL (Phase 3 work)"
    )


def test_stage_draft_blocks_httpx_post_to_ao3(
    clean_publish_queue: Path, monkeypatch: pytest.MonkeyPatch
):
    """TEST: T-A-5 (spec bd-b5p.5, runtime no-live-POST) — even if
    httpx is available in the environment, stage_draft must not POST
    to archiveofourown.org during a normal successful run.
    """
    blocked: list[str] = []
    try:
        import httpx

        def _block_post(url, *args, **kwargs):
            if "archiveofourown.org" in str(url):
                blocked.append(str(url))
                raise AssertionError(
                    f"Phase 2 must not POST to AO3; got: {url}"
                )
            return None

        monkeypatch.setattr(httpx, "post", _block_post, raising=False)
    except ImportError:
        pass

    stage_draft(
        prose="A short paragraph.",
        slop_penalty=1.0,
        voice_match_score=0.6,
    )
    assert not blocked, f"Phase 2 issued AO3 POST(s): {blocked}"
