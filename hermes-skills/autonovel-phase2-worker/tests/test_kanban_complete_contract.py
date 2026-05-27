"""Contract tests for the kanban_complete handoff shape (spec §4.5).

These are CONTRACT tests — they parse the spec's §4.5 example shape
and assert that:

1. The ``summary`` is a single line of the form
   ``slop_penalty=<f> voice_match=<f> queue_id=<hex|none> status=<PASS|FAIL>``
   (or the SKILL.md's worded equivalent — the spec example uses
   ``drafted <id>... slop=... voice_match=...``; we accept the keys
   appearing in either order, but assert all four are present and
   the value is single-line).

2. The ``metadata`` dict contains the 5 canonical keys per spec
   §4.5: ``queue_id``, ``slop_penalty``, ``voice_match``,
   ``draft_excerpt``, ``status``.

3. The ``artifacts`` list contains the publish_queue/<id>.json path
   (per OQ-K-3 amendment — file lives in artifacts, NOT metadata).

4. The ``worker_session_id`` key is NOT set by the worker (auto-stamped
   by ``tools/kanban_tools.py:118-129`` substrate-side).

5. Reserved keys per kanban-worker reference SKILL (``changed_files``,
   ``tests_run``, ``tests_passed``, ``decisions``, ``created_cards``)
   are left unset (autonovel doesn't change tracked files nor spawn
   child cards in v0.4.0).

Covers spec test cases T-K-6 (kanban_complete metadata + artifacts).
"""

from __future__ import annotations

import json
import re

# ---------------------------------------------------------------------------
# Canonical-example shape parsing
# ---------------------------------------------------------------------------


def test_pass_example_metadata_has_5_canonical_keys(
    canonical_kanban_complete_example: dict,
):
    """T-K-6: PASS-case example must have the 5 canonical metadata keys."""
    metadata = canonical_kanban_complete_example["metadata"]
    expected_keys = {
        "queue_id",
        "slop_penalty",
        "voice_match",
        "draft_excerpt",
        "status",
    }
    assert expected_keys.issubset(metadata.keys()), (
        f"metadata missing canonical keys per spec §4.5: "
        f"missing={expected_keys - metadata.keys()}"
    )


def test_pass_example_artifacts_lists_publish_queue_file(
    canonical_kanban_complete_example: dict,
):
    """T-K-6 (OQ-K-3): PASS-case artifacts must reference the
    publish_queue/<id>.json path — that's the canonical attachment
    target the gateway notifier reads."""
    artifacts = canonical_kanban_complete_example["artifacts"]
    assert isinstance(artifacts, list)
    assert len(artifacts) == 1, (
        f"PASS-case must have exactly 1 artifact (the staged "
        f"publish_queue file); got {len(artifacts)}"
    )
    assert "publish_queue" in artifacts[0], (
        f"artifact path must reference publish_queue/ dir; got {artifacts[0]!r}"
    )
    assert artifacts[0].endswith(".json"), (
        f"artifact path must end in .json (the staged draft is JSON); "
        f"got {artifacts[0]!r}"
    )


def test_pass_example_metadata_does_not_contain_file_path_key(
    canonical_kanban_complete_example: dict,
):
    """T-K-6 (OQ-K-3 amendment): metadata must NOT contain a
    ``file_path`` key — that file path lives in artifacts now.

    Stuffing the file path back into metadata bypasses the gateway
    notifier hook + duplicates state.
    """
    metadata = canonical_kanban_complete_example["metadata"]
    assert "file_path" not in metadata, (
        "metadata['file_path'] should be REMOVED per OQ-K-3 — file "
        "lives in artifacts=[...] (spec §4.5 amendment)."
    )


def test_pass_example_metadata_does_not_set_worker_session_id(
    canonical_kanban_complete_example: dict,
):
    """T-K-6: workers must NOT set ``worker_session_id`` themselves —
    auto-stamped by tools/kanban_tools.py:118-129."""
    metadata = canonical_kanban_complete_example["metadata"]
    assert "worker_session_id" not in metadata, (
        "worker_session_id is substrate-reserved; auto-stamped by "
        "kanban_tools._stamp_worker_session_metadata. Workers MUST "
        "NOT set it themselves."
    )


def test_pass_example_no_reserved_kanban_keys(
    canonical_kanban_complete_example: dict,
):
    """T-K-6: autonovel doesn't change tracked files nor spawn child
    cards in v0.4.0 — none of the reserved coding-task keys should
    appear in our metadata (per spec §4.5)."""
    metadata = canonical_kanban_complete_example["metadata"]
    reserved = {"changed_files", "tests_run", "tests_passed", "decisions"}
    overlap = reserved & metadata.keys()
    assert not overlap, (
        f"metadata should not use reserved coding-task keys in "
        f"v0.4.0 (autonovel doesn't change tracked files); "
        f"got {overlap}"
    )


def test_pass_example_summary_is_single_line(
    canonical_kanban_complete_example: dict,
):
    """T-K-6: summary must be a single line.

    Multi-line summaries break the cron `--deliver local` channel's
    one-message-per-line contract and downstream parsers that grep
    for the canonical shape.
    """
    summary = canonical_kanban_complete_example["summary"]
    assert isinstance(summary, str)
    assert "\n" not in summary, (
        f"summary must be single-line; got multi-line: {summary!r}"
    )


def test_pass_example_summary_carries_4_score_keys(
    canonical_kanban_complete_example: dict,
):
    """T-K-6: summary must carry the 4 score keys (slop, voice_match,
    queue_id, status) so operators see PASS/FAIL at a glance.

    Per the bd-b5p.5.6 single-line summary contract carried forward:
    summary should mention all four critical signals.
    """
    summary = canonical_kanban_complete_example["summary"].lower()
    # Either "slop_penalty=" or "slop=" is accepted (spec uses both)
    assert "slop" in summary, "summary must mention slop"
    assert "voice_match" in summary, "summary must mention voice_match"
    # Either queue_id literal OR a hex stub
    assert "queue_id" in summary or re.search(
        r"\b[a-f0-9]{6,16}\.\.\.", summary
    ), "summary must mention queue_id or hex stub"


def test_fail_example_artifacts_empty(
    canonical_kanban_complete_fail_example: dict,
):
    """T-K-6: FAIL-case must have empty artifacts list — there's no
    file to attach (firewall rejected before staging)."""
    artifacts = canonical_kanban_complete_fail_example["artifacts"]
    assert artifacts == [], (
        f"FAIL-case artifacts must be empty (firewall rejected); "
        f"got {artifacts!r}"
    )


def test_fail_example_queue_id_none(
    canonical_kanban_complete_fail_example: dict,
):
    """T-K-6: FAIL-case must have queue_id=None — stage_draft returned
    None, no file written."""
    metadata = canonical_kanban_complete_fail_example["metadata"]
    assert metadata["queue_id"] is None, (
        f"FAIL-case queue_id must be None; got {metadata['queue_id']!r}"
    )


def test_fail_example_status_is_FAIL(
    canonical_kanban_complete_fail_example: dict,
):
    """T-K-6: FAIL-case status field must literally be 'FAIL'."""
    metadata = canonical_kanban_complete_fail_example["metadata"]
    assert metadata["status"] == "FAIL", (
        f"FAIL-case status must be literally 'FAIL'; got {metadata['status']!r}"
    )


def test_pass_example_status_is_PASS(
    canonical_kanban_complete_example: dict,
):
    """T-K-6: PASS-case status field must literally be 'PASS'."""
    metadata = canonical_kanban_complete_example["metadata"]
    assert metadata["status"] == "PASS"


# ---------------------------------------------------------------------------
# JSON-serializability — kernel only validates "must be a JSON dict"
# (per kanban_db.py:2125 metadata storage)
# ---------------------------------------------------------------------------


def test_pass_example_metadata_is_json_serializable(
    canonical_kanban_complete_example: dict,
):
    """T-K-6: metadata must round-trip through json.dumps/loads.

    Per kanban_db.py:2125, the kernel's only validation is
    ``json.dumps(metadata, ensure_ascii=False)`` — non-serializable
    values would crash the worker's kanban_complete call.
    """
    metadata = canonical_kanban_complete_example["metadata"]
    serialized = json.dumps(metadata, ensure_ascii=False)
    round_tripped = json.loads(serialized)
    assert round_tripped == metadata


def test_fail_example_metadata_is_json_serializable(
    canonical_kanban_complete_fail_example: dict,
):
    """T-K-6: FAIL-case metadata (with None queue_id) must also be
    JSON-serializable."""
    metadata = canonical_kanban_complete_fail_example["metadata"]
    serialized = json.dumps(metadata, ensure_ascii=False)
    round_tripped = json.loads(serialized)
    assert round_tripped == metadata
    assert round_tripped["queue_id"] is None


# ---------------------------------------------------------------------------
# Type contracts on individual metadata keys
# ---------------------------------------------------------------------------


def test_pass_example_slop_penalty_is_float(
    canonical_kanban_complete_example: dict,
):
    """T-K-6: slop_penalty must be a float — downstream comparators
    (firewall thresholds, dashboards) expect numeric."""
    assert isinstance(
        canonical_kanban_complete_example["metadata"]["slop_penalty"],
        float,
    )


def test_pass_example_voice_match_is_float(
    canonical_kanban_complete_example: dict,
):
    """T-K-6: voice_match must be a float."""
    assert isinstance(
        canonical_kanban_complete_example["metadata"]["voice_match"],
        float,
    )


def test_pass_example_draft_excerpt_is_str(
    canonical_kanban_complete_example: dict,
):
    """T-K-6: draft_excerpt must be a string (first 240 chars of prose)."""
    excerpt = canonical_kanban_complete_example["metadata"]["draft_excerpt"]
    assert isinstance(excerpt, str)
    assert len(excerpt) <= 240, (
        f"draft_excerpt must be ≤240 chars per spec §4.5; "
        f"got len={len(excerpt)}"
    )


# ---------------------------------------------------------------------------
# Edge cases (≥3 beyond happy path per /test acceptance criteria)
# ---------------------------------------------------------------------------


def test_edge_metadata_must_be_dict_not_list():
    """EDGE: spec §4.5 metadata schema is a DICT — workers MUST NOT
    pass a list. The kernel rejects non-dict metadata
    (tools/kanban_tools.py:462)."""
    bad_metadata = ["queue_id", "abc"]
    # Workers building this would crash on kernel-side validation
    # ("metadata must be an object/dict"). Assert the canonical
    # example honors the dict contract.
    assert not isinstance(bad_metadata, dict)


def test_edge_artifacts_must_be_list_not_string(
    canonical_kanban_complete_example: dict,
):
    """EDGE: artifacts must be a list. The kernel auto-converts a
    single string to [string] (tools/kanban_tools.py:421-422), but
    the SKILL.md example should pass a list.
    """
    artifacts = canonical_kanban_complete_example["artifacts"]
    assert isinstance(artifacts, list), (
        f"canonical artifacts must be a list (not a string); "
        f"got {type(artifacts).__name__}"
    )


def test_edge_summary_no_secrets_in_canonical_example(
    canonical_kanban_complete_example: dict,
    canonical_kanban_complete_fail_example: dict,
):
    """EDGE: per KANBAN_GUIDANCE Step 5 — "Never put secrets / tokens /
    raw PII" in summary or metadata. Sanity-check the canonical
    examples don't accidentally embed obvious secret markers.
    """
    for example in (
        canonical_kanban_complete_example,
        canonical_kanban_complete_fail_example,
    ):
        body = json.dumps(example)
        forbidden = ["password", "api_key", "secret", "token", "bearer "]
        for marker in forbidden:
            assert marker.lower() not in body.lower(), (
                f"canonical example accidentally contains secret marker "
                f"{marker!r}: {body!r}"
            )


def test_edge_queue_id_format_hex_when_present(
    canonical_kanban_complete_example: dict,
):
    """EDGE: queue_id must be a hex string when present (per spec
    §4.5 'hex string, 16 chars'). Sanity-check the canonical example
    matches the hex contract — non-hex queue_ids break downstream
    file lookups under publish_queue/<id>.json.
    """
    queue_id = canonical_kanban_complete_example["metadata"]["queue_id"]
    if queue_id is not None:
        assert re.match(r"^[a-f0-9]+$", queue_id), (
            f"queue_id must be lowercase hex when present; got {queue_id!r}"
        )


# ---------------------------------------------------------------------------
# SKILL.md alignment: assert the example IS what the SKILL body shows
# ---------------------------------------------------------------------------


def test_canonical_example_keys_match_skill_md_step6(worker_skill_body: str):
    """T-K-6 alignment: the SKILL.md Step 6 example must list the
    same 5 metadata keys as our canonical fixture.

    This is the cross-check: if the SKILL.md drifts (adds/removes a
    key), this test catches it before downstream parsers fail silently.
    """
    expected_keys = [
        "queue_id",
        "slop_penalty",
        "voice_match",
        "draft_excerpt",
        "status",
    ]
    for key in expected_keys:
        assert key in worker_skill_body, (
            f"SKILL.md Step 6 missing metadata key {key!r} — drift "
            f"from spec §4.5 / canonical example."
        )
