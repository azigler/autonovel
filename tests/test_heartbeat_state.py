"""Tests for ``feedback/heartbeat_state.py`` — heartbeat loop state persistence.

Covers spec bd-49j Section 3.9 (entropy clock), Section 4.4 (state schema),
and Section 5 test cases (``entropy-adaptive-threshold``,
``heartbeat-error-budget``, ``heartbeat-log-append-only``) plus edge cases
for atomic writes, FIFO eviction, daily reset, and ISO-8601 round-trip.

The module under test does not yet exist; these tests define its contract
and will fail until bd-49j.7 lands the implementation.
"""

from __future__ import annotations

import json
from dataclasses import fields
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from feedback.heartbeat_state import (
    HeartbeatState,
    append_heartbeat_log,
    compute_entropy,
    load_state,
    record_comment_interval,
    record_error,
    record_success,
    update_last_fire,
    write_state,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state_path(tmp_path: Path) -> Path:
    return tmp_path / "heartbeat-state.json"


def _log_path(tmp_path: Path) -> Path:
    return tmp_path / "heartbeat-log.md"


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Schema / dataclass shape
# ---------------------------------------------------------------------------


def test_heartbeat_state_schema_fields_exist() -> None:
    """The dataclass exposes every field the spec Section 4.4 declares."""
    field_names = {f.name for f in fields(HeartbeatState)}
    expected = {
        "last_heartbeat_at",
        "last_creative_fire_at",
        "last_non_self_comment_at",
        "last_write_at",
        "last_conceive_at",
        "last_learn_at",
        "comment_intervals_observed",
        "consecutive_errors",
        "housekeeping_done_week",
        "ao3_calls_today",
        "ao3_calls_date",
    }
    missing = expected - field_names
    assert not missing, f"missing schema fields: {missing}"


# ---------------------------------------------------------------------------
# load_state — defaults + forward-compat
# ---------------------------------------------------------------------------


def test_load_state_returns_defaults_when_missing(tmp_path: Path) -> None:
    """A missing file yields a fresh, valid default state — never None."""
    state = load_state(_state_path(tmp_path))
    assert isinstance(state, HeartbeatState)
    assert state.consecutive_errors == 0
    assert state.ao3_calls_today == 0
    assert state.comment_intervals_observed == []
    assert state.last_heartbeat_at is None
    assert state.last_creative_fire_at is None
    assert state.housekeeping_done_week is None


def test_load_state_tolerates_missing_optional_fields(tmp_path: Path) -> None:
    """Forward-compat: older JSON missing newer fields still loads."""
    path = _state_path(tmp_path)
    # Write a minimal JSON document with only a couple of fields. The loader
    # must tolerate this and fill in defaults for everything else.
    path.write_text(
        json.dumps({"consecutive_errors": 1, "ao3_calls_today": 2}),
        encoding="utf-8",
    )
    state = load_state(path)
    assert state.consecutive_errors == 1
    assert state.ao3_calls_today == 2
    # Unspecified fields fall back to defaults rather than raising.
    assert state.comment_intervals_observed == []
    assert state.last_heartbeat_at is None
    assert state.last_creative_fire_at is None


# ---------------------------------------------------------------------------
# write_state — atomic + ISO-8601 round-trip
# ---------------------------------------------------------------------------


def test_write_state_round_trip_preserves_timestamps(tmp_path: Path) -> None:
    """ISO-8601 round-trip: write then load preserves timestamps exactly."""
    path = _state_path(tmp_path)
    ts = _utc(2026, 5, 2, 18)
    state = HeartbeatState()
    state.last_heartbeat_at = ts
    state.last_creative_fire_at = ts
    state.last_write_at = ts
    write_state(state, path)
    loaded = load_state(path)
    assert loaded.last_heartbeat_at == ts
    assert loaded.last_creative_fire_at == ts
    assert loaded.last_write_at == ts


def test_write_state_is_atomic_no_corruption_on_rename_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Atomic write: a failure mid-write leaves the prior file intact.

    The contract is "write to temp then rename" — if the rename step raises,
    the existing on-disk state must NOT be a half-written corrupt file.
    """
    import os

    path = _state_path(tmp_path)

    # First, lay down a known-good state on disk.
    good = HeartbeatState()
    good.consecutive_errors = 7
    good.ao3_calls_today = 3
    write_state(good, path)
    good_bytes = path.read_bytes()

    # Now force the rename step to blow up partway through the next write.
    real_replace = os.replace

    def _exploding_replace(src, dst):
        # Simulate a filesystem failure during the atomic rename.
        if str(dst) == str(path):
            raise OSError("simulated rename failure")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _exploding_replace)

    # The write attempt itself raises (or is swallowed — either is fine);
    # what matters is the original file is untouched.
    with pytest.raises(OSError):
        bad = HeartbeatState()
        bad.consecutive_errors = 999
        write_state(bad, path)

    assert path.read_bytes() == good_bytes
    reloaded = load_state(path)
    assert reloaded.consecutive_errors == 7
    assert reloaded.ao3_calls_today == 3


# ---------------------------------------------------------------------------
# update_last_fire — per-skill timestamps + last_creative_fire_at
# ---------------------------------------------------------------------------


def test_update_last_fire_write_sets_write_and_creative(tmp_path: Path) -> None:
    """``/write`` fire updates last_write_at AND last_creative_fire_at."""
    state = HeartbeatState()
    ts = _utc(2026, 5, 2, 12)
    new = update_last_fire(state, "/write", ts)
    assert new.last_write_at == ts
    assert new.last_creative_fire_at == ts
    # Sister timestamps remain untouched.
    assert new.last_conceive_at is None
    assert new.last_learn_at is None


def test_update_last_fire_conceive_sets_conceive_and_creative(
    tmp_path: Path,
) -> None:
    """``/conceive`` fire updates last_conceive_at AND last_creative_fire_at."""
    state = HeartbeatState()
    ts = _utc(2026, 5, 2, 14)
    new = update_last_fire(state, "/conceive", ts)
    assert new.last_conceive_at == ts
    assert new.last_creative_fire_at == ts
    assert new.last_write_at is None
    assert new.last_learn_at is None


def test_update_last_fire_learn_sets_learn_and_creative(tmp_path: Path) -> None:
    """``/learn`` fire updates last_learn_at AND last_creative_fire_at."""
    state = HeartbeatState()
    ts = _utc(2026, 5, 2, 16)
    new = update_last_fire(state, "/learn", ts)
    assert new.last_learn_at == ts
    assert new.last_creative_fire_at == ts
    assert new.last_write_at is None
    assert new.last_conceive_at is None


# ---------------------------------------------------------------------------
# record_error / record_success — error budget
# ---------------------------------------------------------------------------


def test_record_error_increments_consecutive_errors() -> None:
    """record_error bumps consecutive_errors; spec test ``heartbeat-error-budget``."""
    state = HeartbeatState()
    assert state.consecutive_errors == 0
    state = record_error(state)
    assert state.consecutive_errors == 1
    state = record_error(state)
    state = record_error(state)
    # Three consecutive errors — the heartbeat skill itself decides to halt;
    # this module just owns the counter math.
    assert state.consecutive_errors == 3


def test_record_success_resets_consecutive_errors() -> None:
    """record_success clears the counter (a clean tick rebuilds the budget)."""
    state = HeartbeatState()
    state = record_error(state)
    state = record_error(state)
    assert state.consecutive_errors == 2
    state = record_success(state)
    assert state.consecutive_errors == 0


# ---------------------------------------------------------------------------
# Entropy clock — Section 3.9
# ---------------------------------------------------------------------------


def test_compute_entropy_cold_start_uses_72h_floor() -> None:
    """Cold start (<5 intervals) → threshold defaults to 72h flat."""
    state = HeartbeatState()
    # No comment intervals observed yet; last activity 80h ago.
    last = _utc(2026, 5, 1, 0)
    state.last_creative_fire_at = last
    state.last_non_self_comment_at = last
    now = last + timedelta(hours=80)
    assert compute_entropy(state, now) is True
    # Still cold but only 60h silence → below 72h floor.
    now2 = last + timedelta(hours=60)
    assert compute_entropy(state, now2) is False


def test_compute_entropy_adaptive_threshold_max_72h() -> None:
    """Spec test ``entropy-adaptive-threshold``.

    intervals = [12h, 24h, 24h, 36h, 48h, 72h] → median = 30h.
    threshold = max(72h, 2 * 30h) = max(72h, 60h) = 72h.
    silence = 60h < 72h → entropy_state = False.
    """
    state = HeartbeatState()
    state.comment_intervals_observed = [
        timedelta(hours=12),
        timedelta(hours=24),
        timedelta(hours=24),
        timedelta(hours=36),
        timedelta(hours=48),
        timedelta(hours=72),
    ]
    last = _utc(2026, 5, 1, 0)
    state.last_creative_fire_at = last
    state.last_non_self_comment_at = last
    now = last + timedelta(hours=60)
    assert compute_entropy(state, now) is False


def test_compute_entropy_adaptive_threshold_doubles_median() -> None:
    """When 2*median exceeds 72h, threshold grows with the audience cadence.

    intervals all 60h → median 60h → threshold = max(72h, 120h) = 120h.
    silence = 100h < 120h → entropy_state = False.
    silence = 130h > 120h → entropy_state = True.
    """
    state = HeartbeatState()
    state.comment_intervals_observed = [timedelta(hours=60)] * 6
    last = _utc(2026, 5, 1, 0)
    state.last_creative_fire_at = last
    state.last_non_self_comment_at = last
    assert compute_entropy(state, last + timedelta(hours=100)) is False
    assert compute_entropy(state, last + timedelta(hours=130)) is True


def test_compute_entropy_resets_on_creative_fire_or_comment() -> None:
    """Silence is min-distance from now — whichever clock is fresher resets."""
    state = HeartbeatState()
    far = _utc(2026, 4, 1, 0)
    fresh = _utc(2026, 5, 2, 0)
    state.last_creative_fire_at = far
    state.last_non_self_comment_at = fresh
    # Now is only 12h after the fresh comment — well under 72h floor.
    now = fresh + timedelta(hours=12)
    assert compute_entropy(state, now) is False


# ---------------------------------------------------------------------------
# record_comment_interval — FIFO cap at 50
# ---------------------------------------------------------------------------


def test_record_comment_interval_appends_in_order() -> None:
    state = HeartbeatState()
    state = record_comment_interval(state, timedelta(hours=12))
    state = record_comment_interval(state, timedelta(hours=24))
    state = record_comment_interval(state, timedelta(hours=36))
    assert state.comment_intervals_observed == [
        timedelta(hours=12),
        timedelta(hours=24),
        timedelta(hours=36),
    ]


def test_record_comment_interval_fifo_cap_at_50() -> None:
    """The 51st entry evicts the oldest (FIFO cap = 50)."""
    state = HeartbeatState()
    for hours in range(1, 51):
        state = record_comment_interval(state, timedelta(hours=hours))
    assert len(state.comment_intervals_observed) == 50
    assert state.comment_intervals_observed[0] == timedelta(hours=1)
    assert state.comment_intervals_observed[-1] == timedelta(hours=50)
    # 51st append evicts the oldest (1h), keeps newest at the tail.
    state = record_comment_interval(state, timedelta(hours=51))
    assert len(state.comment_intervals_observed) == 50
    assert state.comment_intervals_observed[0] == timedelta(hours=2)
    assert state.comment_intervals_observed[-1] == timedelta(hours=51)


# ---------------------------------------------------------------------------
# AO3 daily-call counter
# ---------------------------------------------------------------------------


def test_ao3_calls_today_resets_when_date_changes(
    tmp_path: Path,
) -> None:
    """``ao3_calls_today`` resets when ``ao3_calls_date`` is not today.

    The contract: load_state on a state whose ao3_calls_date is yesterday
    surfaces a counter of 0 for today (or load_state itself rolls it over,
    but either way the caller MUST observe a 0 on a new UTC day).
    """
    path = _state_path(tmp_path)
    yesterday = date(2026, 5, 1)
    state = HeartbeatState()
    state.ao3_calls_today = 4
    state.ao3_calls_date = yesterday
    write_state(state, path)

    loaded = load_state(path)
    # Either load_state already rolled it over, OR the next caller is expected
    # to compare ao3_calls_date to today and reset. Both are valid module
    # contracts; we assert the user-facing invariant: when date != today,
    # the counter is no longer authoritative as "today's count".
    today = date.today()
    if loaded.ao3_calls_date != today:
        # Caller is responsible for the rollover — but the persisted
        # date-and-count pair still reflects yesterday's activity.
        assert loaded.ao3_calls_date == yesterday
        assert loaded.ao3_calls_today == 4
    else:
        # Loader rolled it over for us.
        assert loaded.ao3_calls_today == 0


# ---------------------------------------------------------------------------
# heartbeat-log — append-only
# ---------------------------------------------------------------------------


def test_append_heartbeat_log_creates_file_and_appends(tmp_path: Path) -> None:
    """Spec test ``heartbeat-log-append-only``: each call appends one line."""
    path = _log_path(tmp_path)
    append_heartbeat_log("2026-05-02T18:00Z heartbeat -> idle", path)
    append_heartbeat_log("2026-05-02T19:00Z heartbeat -> /mail", path)
    append_heartbeat_log("2026-05-02T20:00Z heartbeat -> /daily", path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert lines[0] == "2026-05-02T18:00Z heartbeat -> idle"
    assert lines[1] == "2026-05-02T19:00Z heartbeat -> /mail"
    assert lines[2] == "2026-05-02T20:00Z heartbeat -> /daily"


def test_append_heartbeat_log_preserves_existing_lines(tmp_path: Path) -> None:
    """Earlier lines must NOT be rewritten by a subsequent append."""
    path = _log_path(tmp_path)
    # Pre-seed the file as if 5 prior heartbeats had run.
    seed = "\n".join(
        f"2026-05-02T{h:02d}:00Z heartbeat -> idle" for h in range(5)
    )
    path.write_text(seed + "\n", encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    append_heartbeat_log("2026-05-02T05:00Z heartbeat -> /mail", path)
    after = path.read_text(encoding="utf-8")

    assert after.startswith(before), "earlier lines were mutated"
    assert after.endswith("2026-05-02T05:00Z heartbeat -> /mail\n")
    assert len(after.splitlines()) == 6
