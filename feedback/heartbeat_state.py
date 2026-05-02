"""Heartbeat loop state persistence.

Implements spec bd-49j Section 4.4 (state schema) and Section 3.9 (anti-entropy
clock). Pure module: no imports from ``write/``, ``identity/``, or ``api/`` —
heartbeat state is foundational and read by every loop branch.

Persisted as JSON at ``feedback/heartbeat-state.json``. Atomic writes via
``tempfile`` + ``os.replace``; never leaves a half-written file on disk.

Public surface (used by ``/heartbeat`` and downstream skills):

- ``HeartbeatState`` — dataclass schema (Section 4.4)
- ``load_state(path)`` — returns defaults if file missing / empty
- ``write_state(state, path)`` — atomic write
- ``update_last_fire(state, skill, ts)`` — per-skill stamp + creative-fire reset
- ``record_error(state)`` — bump consecutive-errors counter
- ``record_success(state)`` — clear consecutive-errors counter
- ``compute_entropy(state, now)`` — silence-vs-adaptive-threshold check
- ``record_comment_interval(state, interval)`` — FIFO cap 50
- ``append_heartbeat_log(line, log_path)`` — append-only line log
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import statistics
import tempfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: FIFO cap on the comment-interval ring buffer (Section 3.9).
COMMENT_INTERVALS_CAP: int = 50

#: Minimum number of observed intervals before the adaptive threshold engages;
#: until then the entropy clock uses ``ENTROPY_FLOOR`` flat (Section 3.9 cold
#: start).
ENTROPY_COLD_START_MIN_INTERVALS: int = 5

#: Hard floor on the entropy threshold (Section 3.9).
ENTROPY_FLOOR: timedelta = timedelta(hours=72)

#: Map skill name -> attribute on ``HeartbeatState`` driven by ``update_last_fire``.
_SKILL_FIELD_MAP: dict[str, str] = {
    "/write": "last_write_at",
    "/conceive": "last_conceive_at",
    "/learn": "last_learn_at",
    # Aliases without the leading slash, in case a caller passes the bare name.
    "write": "last_write_at",
    "conceive": "last_conceive_at",
    "learn": "last_learn_at",
}


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class HeartbeatState:
    """Persistent state for the ``/heartbeat`` loop (spec bd-49j Section 4.4).

    All datetime fields are timezone-aware UTC. ``comment_intervals_observed``
    is a FIFO ring buffer capped at :data:`COMMENT_INTERVALS_CAP`. The
    ``housekeeping_done_week`` field is an ISO-week string like ``"2026-W18"``.
    """

    last_heartbeat_at: datetime | None = None
    last_creative_fire_at: datetime | None = None
    last_non_self_comment_at: datetime | None = None
    last_write_at: datetime | None = None
    last_conceive_at: datetime | None = None
    last_learn_at: datetime | None = None
    comment_intervals_observed: list[timedelta] = field(default_factory=list)
    consecutive_errors: int = 0
    housekeeping_done_week: str | None = None
    ao3_calls_today: int = 0
    ao3_calls_date: date | None = None


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _dt_to_iso(value: datetime | None) -> str | None:
    """Serialize a datetime to ISO-8601 (or ``None`` passthrough)."""
    if value is None:
        return None
    return value.isoformat()


def _iso_to_dt(value: Any) -> datetime | None:
    """Deserialize ISO-8601 to a datetime; tolerate ``None`` and bad input."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _date_to_iso(value: date | None) -> str | None:
    """Serialize a ``date`` to ``YYYY-MM-DD`` (or ``None`` passthrough)."""
    if value is None:
        return None
    return value.isoformat()


def _iso_to_date(value: Any) -> date | None:
    """Deserialize ``YYYY-MM-DD`` to a ``date``; tolerate ``None`` / bad input."""
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _timedelta_to_iso(td: timedelta) -> str:
    """Serialize a ``timedelta`` as an ISO-8601 duration (e.g. ``"PT72H"``).

    We emit a single ``PT<seconds>S`` form (always seconds, in fractional form
    if there are microseconds). This is unambiguous and round-trips cleanly
    via :func:`_iso_to_timedelta`. Negative durations are preserved with a
    leading ``-`` prefix.
    """
    if td == timedelta(0):
        return "PT0S"
    negative = td < timedelta(0)
    abs_td = -td if negative else td
    total_seconds = abs_td.total_seconds()
    # Emit integer seconds when possible; otherwise fractional.
    if total_seconds == int(total_seconds):
        body = f"PT{int(total_seconds)}S"
    else:
        body = f"PT{total_seconds}S"
    return f"-{body}" if negative else body


_ISO_DURATION_RE = re.compile(
    r"""^(?P<sign>-)?P
        (?:(?P<days>\d+(?:\.\d+)?)D)?
        (?:T
            (?:(?P<hours>\d+(?:\.\d+)?)H)?
            (?:(?P<minutes>\d+(?:\.\d+)?)M)?
            (?:(?P<seconds>\d+(?:\.\d+)?)S)?
        )?$""",
    re.VERBOSE,
)


def _iso_to_timedelta(value: Any) -> timedelta | None:
    """Parse an ISO-8601 duration into a ``timedelta``.

    Supports the subset we emit (``PT<...>``) plus simple ``P<n>D`` /
    combined ``P<n>DT<...>`` forms. Returns ``None`` on unparseable input.
    """
    if value is None:
        return None
    if isinstance(value, timedelta):
        return value
    if isinstance(value, (int, float)):
        # Tolerate raw seconds for forward-compat / older snapshots.
        return timedelta(seconds=float(value))
    if not isinstance(value, str):
        return None
    match = _ISO_DURATION_RE.match(value.strip())
    if match is None:
        return None
    parts = match.groupdict()
    if not any(parts[k] for k in ("days", "hours", "minutes", "seconds")):
        # Bare ``P`` / ``PT`` with no components — degenerate but harmless;
        # treat as zero duration.
        return timedelta(0)
    days = float(parts["days"] or 0)
    hours = float(parts["hours"] or 0)
    minutes = float(parts["minutes"] or 0)
    seconds = float(parts["seconds"] or 0)
    td = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    return -td if parts["sign"] == "-" else td


def _state_to_dict(state: HeartbeatState) -> dict[str, Any]:
    """Convert a HeartbeatState into a JSON-ready dict."""
    return {
        "last_heartbeat_at": _dt_to_iso(state.last_heartbeat_at),
        "last_creative_fire_at": _dt_to_iso(state.last_creative_fire_at),
        "last_non_self_comment_at": _dt_to_iso(state.last_non_self_comment_at),
        "last_write_at": _dt_to_iso(state.last_write_at),
        "last_conceive_at": _dt_to_iso(state.last_conceive_at),
        "last_learn_at": _dt_to_iso(state.last_learn_at),
        "comment_intervals_observed": [
            _timedelta_to_iso(td) for td in state.comment_intervals_observed
        ],
        "consecutive_errors": int(state.consecutive_errors),
        "housekeeping_done_week": state.housekeeping_done_week,
        "ao3_calls_today": int(state.ao3_calls_today),
        "ao3_calls_date": _date_to_iso(state.ao3_calls_date),
    }


def _dict_to_state(data: dict[str, Any]) -> HeartbeatState:
    """Reconstruct a HeartbeatState from a JSON-loaded dict.

    Forward-compatible: missing fields fall back to dataclass defaults so
    older snapshots (pre-schema-extension) still load cleanly.
    """
    raw_intervals = data.get("comment_intervals_observed") or []
    intervals: list[timedelta] = []
    if isinstance(raw_intervals, list):
        for entry in raw_intervals:
            parsed = _iso_to_timedelta(entry)
            if parsed is not None:
                intervals.append(parsed)
    return HeartbeatState(
        last_heartbeat_at=_iso_to_dt(data.get("last_heartbeat_at")),
        last_creative_fire_at=_iso_to_dt(data.get("last_creative_fire_at")),
        last_non_self_comment_at=_iso_to_dt(
            data.get("last_non_self_comment_at")
        ),
        last_write_at=_iso_to_dt(data.get("last_write_at")),
        last_conceive_at=_iso_to_dt(data.get("last_conceive_at")),
        last_learn_at=_iso_to_dt(data.get("last_learn_at")),
        comment_intervals_observed=intervals,
        consecutive_errors=int(data.get("consecutive_errors") or 0),
        housekeeping_done_week=data.get("housekeeping_done_week"),
        ao3_calls_today=int(data.get("ao3_calls_today") or 0),
        ao3_calls_date=_iso_to_date(data.get("ao3_calls_date")),
    )


# ---------------------------------------------------------------------------
# load / write
# ---------------------------------------------------------------------------


def load_state(path: str | Path) -> HeartbeatState:
    """Load HeartbeatState from JSON at ``path``.

    Returns a fresh default :class:`HeartbeatState` if the file is missing
    or empty. Tolerates older snapshots that omit newer fields.
    """
    p = Path(path)
    if not p.exists():
        return HeartbeatState()
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return HeartbeatState()
    if not text.strip():
        return HeartbeatState()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Corrupt JSON: a hard halt is the spec response (Section 3.7), but
        # this module's contract is to return a valid state object — the
        # caller can detect corruption out-of-band. Fresh defaults is the
        # safest no-op behavior here.
        return HeartbeatState()
    if not isinstance(data, dict):
        return HeartbeatState()
    return _dict_to_state(data)


def write_state(state: HeartbeatState, path: str | Path) -> None:
    """Atomically persist HeartbeatState to JSON at ``path``.

    Writes to a temp file in the same directory, fsyncs, then ``os.replace``s
    into place. If the rename step raises, the existing file at ``path``
    remains untouched.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(_state_to_dict(state), indent=2, sort_keys=True)
    # NamedTemporaryFile in the same directory so os.replace is atomic on POSIX.
    tmp_fd, tmp_path = tempfile.mkstemp(
        prefix=".heartbeat-state-", suffix=".json.tmp", dir=str(p.parent)
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            # Some filesystems (e.g. tmpfs in containers) don't support
            # fsync — that's fine, the rename is still atomic.
            with contextlib.suppress(OSError):
                os.fsync(fh.fileno())
        # NB: must use ``os.replace`` (not ``Path.replace``) so tests that
        # monkeypatch the module-level function see the call.
        os.replace(tmp_path, str(p))
    except BaseException:
        # The replace either never happened or raised before clobbering the
        # destination — clean up the tempfile and re-raise so the caller
        # knows the write didn't land.
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# Mutators
# ---------------------------------------------------------------------------


def update_last_fire(
    state: HeartbeatState, skill: str, ts: datetime
) -> HeartbeatState:
    """Mark ``skill`` as having fired at ``ts``.

    Updates the per-skill timestamp (e.g. ``last_write_at`` for ``"/write"``)
    AND the creative-fire reset clock (``last_creative_fire_at``) — any of
    /conceive, /write, /learn count as creative activity for the entropy
    clock (Section 3.9).

    Returns the mutated state for fluent chaining; mutation is in-place.
    """
    attr = _SKILL_FIELD_MAP.get(skill)
    if attr is None:
        raise ValueError(
            f"unknown skill {skill!r}; expected one of {sorted(_SKILL_FIELD_MAP)}"
        )
    setattr(state, attr, ts)
    state.last_creative_fire_at = ts
    return state


def record_error(state: HeartbeatState) -> HeartbeatState:
    """Increment the consecutive-error counter (Section 3.7 error budget).

    Three consecutive errors triggers a hard halt; that gate is enforced by
    ``/heartbeat`` itself, this function only owns the counter math.
    """
    state.consecutive_errors += 1
    return state


def record_success(state: HeartbeatState) -> HeartbeatState:
    """Clear the consecutive-error counter — a clean tick rebuilds the budget."""
    state.consecutive_errors = 0
    return state


def record_comment_interval(
    state: HeartbeatState, interval: timedelta
) -> HeartbeatState:
    """Append a new inter-comment interval; FIFO-evict to keep ``len <= 50``."""
    state.comment_intervals_observed.append(interval)
    overflow = len(state.comment_intervals_observed) - COMMENT_INTERVALS_CAP
    if overflow > 0:
        # Drop the oldest entries (FIFO).
        del state.comment_intervals_observed[:overflow]
    return state


# ---------------------------------------------------------------------------
# Entropy clock (Section 3.9)
# ---------------------------------------------------------------------------


def _silence(state: HeartbeatState, now: datetime) -> timedelta | None:
    """Return how long we've been silent.

    Silence is the smaller of (now - last_creative_fire_at) and
    (now - last_non_self_comment_at) — whichever clock is fresher resets.
    Returns ``None`` if both clocks are unset (caller treats as "infinite",
    but cold-start logic handles that path explicitly).
    """
    candidates: list[timedelta] = []
    if state.last_creative_fire_at is not None:
        candidates.append(now - state.last_creative_fire_at)
    if state.last_non_self_comment_at is not None:
        candidates.append(now - state.last_non_self_comment_at)
    if not candidates:
        return None
    return min(candidates)


def _entropy_threshold(state: HeartbeatState) -> timedelta:
    """Compute the adaptive entropy threshold.

    Cold start (<5 intervals): floor of 72h.
    Otherwise: ``max(72h, 2 * median(intervals))``.
    """
    intervals = state.comment_intervals_observed
    if len(intervals) < ENTROPY_COLD_START_MIN_INTERVALS:
        return ENTROPY_FLOOR
    # statistics.median on timedeltas works directly in Python 3.12+.
    median = statistics.median(intervals)
    doubled = median * 2
    return max(ENTROPY_FLOOR, doubled)


def compute_entropy(state: HeartbeatState, now: datetime) -> bool:
    """Return ``True`` iff silence has crossed the adaptive threshold.

    See :func:`_silence` and :func:`_entropy_threshold` for the math.
    A cold loop with no creative-fire and no comments yet is NOT entropic —
    we haven't earned the audience to be silent against.
    """
    silence = _silence(state, now)
    if silence is None:
        return False
    return silence > _entropy_threshold(state)


# ---------------------------------------------------------------------------
# Heartbeat log (append-only)
# ---------------------------------------------------------------------------


def append_heartbeat_log(line: str, log_path: str | Path) -> None:
    """Append one line to the heartbeat log (Section 3.10).

    Each call writes exactly one line followed by a newline; existing
    content is never rewritten. Creates the file (and parent dirs) if
    missing.
    """
    p = Path(log_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Strip a trailing newline from the caller's line, if any, so we don't
    # double up.
    if line.endswith("\n"):
        line = line.rstrip("\n")
    with p.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.write("\n")
