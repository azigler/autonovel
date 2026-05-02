"""Tests for identity/handles.py and identity/handles.json (Spec bd-49j Section 3.2, 4.5).

The self-recognition guard prevents the heartbeat/loop from treating
Maren's own AO3 replies as new mail. This is the load-bearing safety
net for the 2026-04-26 incident, in which `maren_eurynome`'s reply to
TheIcyQueen was nearly drafted as if it were fresh fanmail.

Spec test cases covered:
- `heartbeat-self-comment-filtered` — comment from `maren_eurynome` is_self=True;
  `TheIcyQueen` is_self=False.
- `identity-files-untouched-by-loop` — handles.json mutates only by hand
  (covered here by verifying is_self never writes).

Plus edge / error cases per bd-49j.1 task description:
- None / empty author returns False
- Case sensitivity (AO3 usernames are case-sensitive)
- Multiple handles supported
- Missing handles.json raises FileNotFoundError
- Malformed JSON raises a clear error
- handles.json schema fields: ao3_handles list, display_names list, updated_at ISO

Implementation note: the module identity.handles does not exist yet; the impl
agent (bd-49j.5) will satisfy the import. Until then, pytest --collect-only
parses cleanly and tests are skipped at collection via importorskip.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# The module under test does not exist until bd-49j.5 lands. importorskip
# keeps `pytest --collect-only` parse-clean and the test runs deterministically
# pass once impl arrives.
handles = pytest.importorskip("identity.handles")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_handles_file(
    path: Path,
    *,
    ao3_handles: list[str] | None = None,
    display_names: list[str] | None = None,
    updated_at: str = "2026-05-02",
) -> Path:
    """Write a handles.json file with the spec-defined schema."""
    payload = {
        "ao3_handles": ao3_handles
        if ao3_handles is not None
        else ["maren_eurynome"],
        "display_names": display_names
        if display_names is not None
        else ["Maren Solaire"],
        "updated_at": updated_at,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


@pytest.fixture()
def handles_path(tmp_path, monkeypatch):
    """Redirect identity.handles._PATH to a tmp file and yield the path.

    Per spec Section 4.5 the module computes `_PATH = Path(__file__).parent /
    'handles.json'`. Tests monkeypatch that module-level constant so reads
    happen against tmp_path and the real identity/handles.json (if it exists)
    is never touched by the test suite.
    """
    target = tmp_path / "handles.json"
    monkeypatch.setattr(handles, "_PATH", target, raising=False)
    return target


# ---------------------------------------------------------------------------
# Spec test case: heartbeat-self-comment-filtered
# ---------------------------------------------------------------------------


class TestSelfCommentFiltered:
    """Spec Section 5: heartbeat-self-comment-filtered.

    The 2026-04-26 incident — must not treat own replies as new mail.
    """

    def test_known_self_handle_is_self_true(self, handles_path):
        """is_self('maren_eurynome') -> True.

        Happy-path: the pen-name handle is recognised as self.
        """
        _write_handles_file(handles_path, ao3_handles=["maren_eurynome"])
        assert handles.is_self("maren_eurynome") is True

    def test_known_reader_handle_is_self_false(self, handles_path):
        """is_self('TheIcyQueen') -> False.

        The 2026-04-26 incident reader. Must be recognised as not-self so
        their comments can flow through /mail.
        """
        _write_handles_file(handles_path, ao3_handles=["maren_eurynome"])
        assert handles.is_self("TheIcyQueen") is False

    def test_unknown_random_handle_is_self_false(self, handles_path):
        """is_self('new_reader_42') -> False for unknown handles."""
        _write_handles_file(handles_path, ao3_handles=["maren_eurynome"])
        assert handles.is_self("new_reader_42") is False


# ---------------------------------------------------------------------------
# Edge cases: None, empty, case-sensitivity, multi-handle
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge-case coverage per bd-49j.1 task description."""

    def test_is_self_returns_false_for_none_author(self, handles_path):
        """is_self(None) -> False.

        Comment author may be None on edge AO3 responses (e.g., guest
        comments, deleted users). Must not crash; returns False.
        """
        _write_handles_file(handles_path, ao3_handles=["maren_eurynome"])
        assert handles.is_self(None) is False  # type: ignore[arg-type]

    def test_is_self_returns_false_for_empty_string(self, handles_path):
        """is_self('') -> False."""
        _write_handles_file(handles_path, ao3_handles=["maren_eurynome"])
        assert handles.is_self("") is False

    def test_is_self_is_case_sensitive(self, handles_path):
        """AO3 usernames are case-sensitive in the API; is_self must match.

        is_self('Maren_Eurynome') and is_self('MAREN_EURYNOME') should both
        be False when only 'maren_eurynome' is registered, because comparing
        case-insensitively would let an attacker spoof the handle.
        """
        _write_handles_file(handles_path, ao3_handles=["maren_eurynome"])
        assert handles.is_self("maren_eurynome") is True
        assert handles.is_self("Maren_Eurynome") is False
        assert handles.is_self("MAREN_EURYNOME") is False
        assert handles.is_self("maren_Eurynome") is False

    def test_multiple_handles_all_match(self, handles_path):
        """If handles.json lists multiple ao3_handles, each is is_self=True.

        Future: the agent may operate under more than one handle (e.g., a
        sockpuppet for a different fandom). The list form supports that.
        """
        _write_handles_file(
            handles_path,
            ao3_handles=["maren_eurynome", "maren_alt", "third_handle"],
        )
        assert handles.is_self("maren_eurynome") is True
        assert handles.is_self("maren_alt") is True
        assert handles.is_self("third_handle") is True
        # And a non-listed one is still False
        assert handles.is_self("not_us_at_all") is False

    def test_single_handle_list_only_matches_that_handle(self, handles_path):
        """Single-entry ao3_handles list: only that handle matches."""
        _write_handles_file(handles_path, ao3_handles=["maren_eurynome"])
        assert handles.is_self("maren_eurynome") is True
        assert handles.is_self("maren_alt") is False

    def test_empty_handles_list_means_nothing_is_self(self, handles_path):
        """Empty ao3_handles list -> is_self always False.

        This is the vacuous case (no pen name yet). Defensive: should not
        treat anyone as self.
        """
        _write_handles_file(handles_path, ao3_handles=[])
        assert handles.is_self("maren_eurynome") is False
        assert handles.is_self("anyone_else") is False


# ---------------------------------------------------------------------------
# Error cases: missing file, malformed JSON
# ---------------------------------------------------------------------------


class TestErrorPaths:
    """Error-path coverage per bd-49j.1 task description."""

    def test_missing_handles_json_raises_filenotfounderror(self, handles_path):
        """is_self() raises FileNotFoundError when handles.json is absent.

        Per spec Section 4.5, the helper reads the file on every call. If
        the file is missing, raising FileNotFoundError surfaces the gap
        loudly rather than silently treating everyone as not-self (which
        would re-open the 2026-04-26 incident).
        """
        # handles_path fixture redirects _PATH but does NOT create the file.
        assert not handles_path.exists()
        with pytest.raises(FileNotFoundError):
            handles.is_self("maren_eurynome")

    def test_malformed_json_raises_clear_error(self, handles_path):
        """Malformed handles.json raises a JSON decode error.

        The file is hand-edited; corrupted JSON must fail loudly so the
        operator notices, rather than degrading to "no handles registered."
        """
        handles_path.write_text("{ not valid json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            handles.is_self("maren_eurynome")


# ---------------------------------------------------------------------------
# Schema tests: handles.json shape per spec Section 4.5
# ---------------------------------------------------------------------------


class TestSchema:
    """Schema validation for handles.json per spec Section 4.5."""

    def test_schema_has_ao3_handles_list(self, handles_path):
        """handles.json schema includes ao3_handles as a list."""
        _write_handles_file(
            handles_path, ao3_handles=["maren_eurynome", "maren_alt"]
        )
        data = json.loads(handles_path.read_text(encoding="utf-8"))
        assert "ao3_handles" in data
        assert isinstance(data["ao3_handles"], list)
        assert all(isinstance(h, str) for h in data["ao3_handles"])
        assert "maren_eurynome" in data["ao3_handles"]

    def test_schema_has_display_names_list(self, handles_path):
        """handles.json schema includes display_names as a list."""
        _write_handles_file(
            handles_path, display_names=["Maren Solaire", "Maren S."]
        )
        data = json.loads(handles_path.read_text(encoding="utf-8"))
        assert "display_names" in data
        assert isinstance(data["display_names"], list)
        assert all(isinstance(n, str) for n in data["display_names"])
        assert "Maren Solaire" in data["display_names"]

    def test_schema_has_updated_at_iso_string(self, handles_path):
        """handles.json schema includes updated_at as an ISO date string."""
        _write_handles_file(handles_path, updated_at="2026-05-02")
        data = json.loads(handles_path.read_text(encoding="utf-8"))
        assert "updated_at" in data
        assert isinstance(data["updated_at"], str)
        # ISO YYYY-MM-DD: exactly 10 chars, two dashes
        assert len(data["updated_at"]) == 10
        assert data["updated_at"].count("-") == 2

    def test_is_self_only_consults_ao3_handles_not_display_names(
        self, handles_path
    ):
        """is_self compares against ao3_handles only, NOT display_names.

        A reader could set their AO3 handle to 'Maren Solaire' (the display
        name); we must not treat that as self. Only the canonical ao3_handles
        list governs identity.
        """
        _write_handles_file(
            handles_path,
            ao3_handles=["maren_eurynome"],
            display_names=["Maren Solaire"],
        )
        assert handles.is_self("maren_eurynome") is True
        assert handles.is_self("Maren Solaire") is False


# ---------------------------------------------------------------------------
# Spec test case: identity-files-untouched-by-loop
# ---------------------------------------------------------------------------


class TestIdentityFilesUntouchedByLoop:
    """Spec Section 5: identity-files-untouched-by-loop.

    handles.json mutates by hand only. is_self is a pure read; calling it
    repeatedly must never modify the file (no mtime change, no content
    change, no truncation).
    """

    def test_is_self_does_not_mutate_handles_file(self, handles_path):
        """100 calls to is_self leave handles.json byte-identical."""
        _write_handles_file(handles_path, ao3_handles=["maren_eurynome"])
        before_bytes = handles_path.read_bytes()
        before_mtime = handles_path.stat().st_mtime_ns

        for _ in range(100):
            handles.is_self("maren_eurynome")
            handles.is_self("TheIcyQueen")
            handles.is_self("")
            handles.is_self(None)  # type: ignore[arg-type]

        after_bytes = handles_path.read_bytes()
        after_mtime = handles_path.stat().st_mtime_ns

        assert before_bytes == after_bytes
        assert before_mtime == after_mtime

    def test_is_self_picks_up_hand_edits_between_calls(self, handles_path):
        """Hand-edits to handles.json take effect on the next is_self call.

        The spec says new AO3 handles are added by hand only (deliberate
        identity drift). The helper reads on every call, so a hand-edit
        between calls is visible immediately — no caching that would mask
        a hand-add.
        """
        _write_handles_file(handles_path, ao3_handles=["maren_eurynome"])
        assert handles.is_self("maren_alt") is False

        # Hand-edit: add a new handle.
        _write_handles_file(
            handles_path, ao3_handles=["maren_eurynome", "maren_alt"]
        )
        assert handles.is_self("maren_alt") is True
        # Original still recognised.
        assert handles.is_self("maren_eurynome") is True
