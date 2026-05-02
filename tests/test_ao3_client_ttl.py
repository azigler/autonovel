"""Tests for api/ao3_client.py TTL freshness helper + filter_self kwarg.

Covers spec bd-49j OQ-04 (per-resource 30min TTL on digest refetch) and
Section 3.2 / 4.5 (filter_self via identity.handles.is_self) per the
2026-04-26 self-comment incident.

All tests use mocked httpx (no live AO3). The freshness helper does not
exist yet on master — these tests are written against the contract in
spec Section 4.1 pseudocode and bead bd-49j.6 will satisfy them.

Contract under test:
- ``get_comments(work_id, filter_self: bool = True)`` — default ON drops
  comments where ``identity.handles.is_self(author)`` is True. Audit
  callers may pass ``filter_self=False``.
- ``needs_refetch(digest_path)`` — pure function. Returns True iff the
  digest at that path is missing ``last_fetched_at`` OR the gap exceeds
  the 30-minute TTL. (Boundary rule documented per-test below: a gap of
  EXACTLY 30 minutes is treated as STALE — refetch needed — to bias
  toward catching new comments. The "<30min" branch in pseudocode means
  "strictly less than" which is the skip path; a gap of 30min flat is
  not less than 30min, so it is NOT skipped.)
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

import pytest

# ---------------------------------------------------------------------------
# Fixtures: bypass MOCK_MODE + isolate cache + skip rate-limit sleeps
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _force_live_mode_and_isolate_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Override conftest's autouse MOCK_MODE so we exercise httpx codepath.

    Also isolate the on-disk cache to a tmp dir so tests don't share state
    with each other or pollute api/cache/.
    """
    monkeypatch.delenv("MOCK_MODE", raising=False)
    monkeypatch.setenv("AO3_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("AO3_TTL_COMMENTS", "0")  # disable on-disk cache TTL

    # Re-import to pick up env. Force a clean module each test.
    if "api.ao3_client" in sys.modules:
        del sys.modules["api.ao3_client"]
    # Now override the module-level CACHE_DIR (already imported during
    # _force_live above, but reload to be safe) and silence the throttle.
    import importlib

    import api.ao3_client  # noqa: F401  — registers under new env
    import api.ao3_client as ao3_module

    importlib.reload(ao3_module)
    monkeypatch.setattr(ao3_module, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(ao3_module, "_MIN_INTERVAL", 0.0)
    # Also no-op the time.sleep used by retry/backoff to keep tests fast.
    monkeypatch.setattr(ao3_module.time, "sleep", lambda _s: None)


# ---------------------------------------------------------------------------
# httpx mocking helpers
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal stand-in for httpx.Response."""

    def __init__(self, status_code: int = 200, text: str = "") -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            request = httpx.Request("GET", "https://archiveofourown.org/")
            response = httpx.Response(
                self.status_code, text=self.text, request=request
            )
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=request, response=response
            )


class _FakeClient:
    """Context-manager stand-in for httpx.Client; records calls."""

    calls: ClassVar[list[dict[str, Any]]] = []  # shared across instances

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._args = args
        self._kwargs = kwargs

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        return None

    def get(
        self, url: str, params: dict[str, Any] | None = None
    ) -> _FakeResponse:
        type(self).calls.append({"url": url, "params": params})
        return type(self)._next_response()

    # -- response queue API ---------------------------------------------------
    _responses: ClassVar[list[_FakeResponse]] = []

    @classmethod
    def _next_response(cls) -> _FakeResponse:
        if not cls._responses:
            raise AssertionError("_FakeClient: no queued response for GET")
        return cls._responses.pop(0)

    @classmethod
    def reset(cls) -> None:
        cls.calls = []
        cls._responses = []

    @classmethod
    def queue(cls, response: _FakeResponse) -> None:
        cls._responses.append(response)


def _comments_html(authors_with_ids: list[tuple[int, str, str]]) -> str:
    """Build a fake AO3 comments page.

    Each tuple is (comment_id, author_handle, body_text).
    Mirrors the structure that ``get_comments`` parses: ``li.comment`` with
    a nested ``h4.heading > a`` (author) and ``blockquote.userstuff``.
    """
    lis = []
    for cid, author, body in authors_with_ids:
        lis.append(
            f'<li id="comment_{cid}" class="comment">'
            f'<h4 class="heading"><a>{author}</a></h4>'
            f'<blockquote class="userstuff">{body}</blockquote>'
            f"</li>"
        )
    return "<html><body><ol>" + "".join(lis) + "</ol></body></html>"


@pytest.fixture()
def fake_httpx(monkeypatch: pytest.MonkeyPatch) -> type[_FakeClient]:
    """Patch httpx.Client in api.ao3_client to a fake; return the class."""
    import api.ao3_client as ao3_module

    _FakeClient.reset()
    monkeypatch.setattr(ao3_module.httpx, "Client", _FakeClient)
    return _FakeClient


@pytest.fixture()
def stub_is_self(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub identity.handles.is_self so tests don't require handles.json.

    Treats the literal author 'maren_eurynome' as self; everything else is
    not-self. The impl wires get_comments() through this helper for the
    filter_self path.
    """

    def _is_self(author: str) -> bool:
        return author.strip().lower() == "maren_eurynome"

    # Create a synthetic identity.handles module if the impl hasn't yet.
    import types

    handles_mod = types.ModuleType("identity.handles")
    handles_mod.is_self = _is_self  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "identity.handles", handles_mod)

    # Also drop any cached api.ao3_client so it picks up the fresh handles
    # module on next import inside the impl.
    if "api.ao3_client" in sys.modules:
        # Don't fully evict — tests above depend on the module being live —
        # but if the impl imports identity.handles lazily inside get_comments
        # this is enough; if it imports at module top level, force reload.
        import importlib

        import api.ao3_client as ao3_module

        importlib.reload(ao3_module)
        # Re-apply the patches our autouse fixture set, since reload reset
        # CACHE_DIR / _MIN_INTERVAL.
        from pathlib import Path as _P

        cache_dir = _P(ao3_module.os.getenv("AO3_CACHE_DIR", "api/cache"))
        ao3_module.CACHE_DIR = cache_dir
        ao3_module._MIN_INTERVAL = 0.0
        ao3_module.time.sleep = lambda _s: None
        # Re-patch httpx.Client too if a fake was installed.
        if (
            hasattr(ao3_module.httpx, "Client")
            and ao3_module.httpx.Client is not _FakeClient
        ):
            ao3_module.httpx.Client = _FakeClient


# ---------------------------------------------------------------------------
# 1. filter_self — default ON drops self-authored comments
# ---------------------------------------------------------------------------


def test_get_comments_default_filters_self_authored(
    fake_httpx: type[_FakeClient], stub_is_self: None
) -> None:
    """heartbeat-self-comment-filtered: default filter_self=True drops self.

    Spec 3.2: get_comments adds ``filter_self: bool = True`` and the
    default path runs results through ``identity.handles.is_self``.
    """
    from api.ao3_client import get_comments

    fake_httpx.queue(
        _FakeResponse(
            200,
            _comments_html(
                [
                    (90001, "TheIcyQueen", "loved this!"),
                    (90002, "maren_eurynome", "thank you so much"),
                ]
            ),
        )
    )

    comments = get_comments(82950256)

    assert len(comments) == 1, (
        "default filter_self=True should drop maren_eurynome's reply"
    )
    assert comments[0].author == "TheIcyQueen"
    assert comments[0].id == 90001


# ---------------------------------------------------------------------------
# 2. filter_self=False — audit / QA path returns ALL comments
# ---------------------------------------------------------------------------


def test_get_comments_filter_self_false_returns_all(
    fake_httpx: type[_FakeClient], stub_is_self: None
) -> None:
    """filter_self=False is the audit path — used to QA reply quality.

    Spec 3.2: 'ALL callers leave default ON unless explicitly auditing
    self-replies (e.g., reply quality QA).'
    """
    from api.ao3_client import get_comments

    fake_httpx.queue(
        _FakeResponse(
            200,
            _comments_html(
                [
                    (90001, "TheIcyQueen", "loved this!"),
                    (90002, "maren_eurynome", "thank you so much"),
                    (90003, "another_reader", "second the above"),
                ]
            ),
        )
    )

    comments = get_comments(82950256, filter_self=False)

    authors = sorted(c.author for c in comments)
    assert authors == ["TheIcyQueen", "another_reader", "maren_eurynome"]


# ---------------------------------------------------------------------------
# 3. TTL freshness — recent fetch is skipped (no AO3 call)
# ---------------------------------------------------------------------------


def test_needs_refetch_recent_fetch_returns_false(tmp_path: Path) -> None:
    """heartbeat-ao3-ttl: digest with last_fetched_at < 30min ago → skip.

    Tests the freshness helper directly (per bead spec: 'TTL check is in
    a wrapper / helper, not buried in _get'). Test does not hit AO3.
    """
    from api.ao3_client import needs_refetch  # impl will provide

    fifteen_min_ago = datetime.now(UTC) - timedelta(minutes=15)
    digest = {
        "publication_title": "What the Hands Remember",
        "last_fetched_at": fifteen_min_ago.isoformat(),
        "comments": [],
    }
    digest_path = tmp_path / "82950256_digest.json"
    digest_path.write_text(json.dumps(digest))

    assert needs_refetch(digest_path) is False


# ---------------------------------------------------------------------------
# 4. TTL freshness — old fetch needs refetch
# ---------------------------------------------------------------------------


def test_needs_refetch_stale_fetch_returns_true(tmp_path: Path) -> None:
    """Digest fetched ≫30min ago is stale; helper returns True."""
    from api.ao3_client import needs_refetch

    two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
    digest = {
        "publication_title": "What the Hands Remember",
        "last_fetched_at": two_hours_ago.isoformat(),
        "comments": [],
    }
    digest_path = tmp_path / "82950256_digest.json"
    digest_path.write_text(json.dumps(digest))

    assert needs_refetch(digest_path) is True


# ---------------------------------------------------------------------------
# 5. TTL boundary — exactly 30 minutes is treated as STALE
# ---------------------------------------------------------------------------


def test_needs_refetch_boundary_at_30_min_is_stale(tmp_path: Path) -> None:
    """Boundary rule: gap of EXACTLY 30 minutes → refetch (not skip).

    Spec Section 4.1 pseudocode reads ``(now - last_fetched_at) < 30min``
    for the SKIP branch. Strictly-less-than means a gap of exactly 30min
    is NOT less than 30min, so the helper must say 'refetch needed'. This
    biases toward catching new comments at the boundary rather than
    delaying them another full tick.
    """
    from api.ao3_client import needs_refetch

    exactly_30 = datetime.now(UTC) - timedelta(minutes=30)
    digest = {
        "last_fetched_at": exactly_30.isoformat(),
        "comments": [],
    }
    digest_path = tmp_path / "82950256_digest.json"
    digest_path.write_text(json.dumps(digest))

    assert needs_refetch(digest_path) is True


# ---------------------------------------------------------------------------
# 6. Cold start — no last_fetched_at field → fetch
# ---------------------------------------------------------------------------


def test_needs_refetch_no_last_fetched_at_returns_true(tmp_path: Path) -> None:
    """Cold start: digest exists but has never been fetched → refetch."""
    from api.ao3_client import needs_refetch

    digest = {
        "publication_title": "What the Hands Remember",
        "comments": [],
        # NB: no last_fetched_at key at all
    }
    digest_path = tmp_path / "82950256_digest.json"
    digest_path.write_text(json.dumps(digest))

    assert needs_refetch(digest_path) is True


# ---------------------------------------------------------------------------
# 7. Cold start — last_fetched_at is explicitly null → fetch
# ---------------------------------------------------------------------------


def test_needs_refetch_explicit_null_last_fetched_at(tmp_path: Path) -> None:
    """A digest with ``last_fetched_at: null`` is also cold-start."""
    from api.ao3_client import needs_refetch

    digest = {
        "publication_title": "x",
        "last_fetched_at": None,
        "comments": [],
    }
    digest_path = tmp_path / "82950256_digest.json"
    digest_path.write_text(json.dumps(digest))

    assert needs_refetch(digest_path) is True


# ---------------------------------------------------------------------------
# 8. Missing digest file — refetch (heartbeat must scrape fresh works)
# ---------------------------------------------------------------------------


def test_needs_refetch_missing_digest_file_returns_true(
    tmp_path: Path,
) -> None:
    """A digest path that doesn't exist on disk yet means we've never
    scraped this work — heartbeat should fetch (subject to OQ-04 cap)."""
    from api.ao3_client import needs_refetch

    digest_path = tmp_path / "never_existed_digest.json"
    assert not digest_path.exists()

    assert needs_refetch(digest_path) is True


# ---------------------------------------------------------------------------
# 9. Existing 3s/req throttle is still respected (not removed by TTL work)
# ---------------------------------------------------------------------------


def test_existing_throttle_constant_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 3s-per-request throttle remains a module-level constant.

    Light sanity check — bd-49j.6 should add the TTL helper WITHOUT
    weakening the existing rate limiter. We don't re-test the sleep
    behaviour exhaustively (test_api_proxy.py covers the live path); we
    just assert the constant is still there and still 3 seconds.
    """
    # Reload a clean module (without the autouse fixture's MIN_INTERVAL=0
    # patch) so we observe the on-disk default.
    monkeypatch.setenv("AO3_CACHE_DIR", "/tmp/whatever")
    if "api.ao3_client" in sys.modules:
        del sys.modules["api.ao3_client"]
    import api.ao3_client as ao3_module

    assert ao3_module._MIN_INTERVAL == 3.0


# ---------------------------------------------------------------------------
# 10. filter_self default kwarg is exposed on the public signature
# ---------------------------------------------------------------------------


def test_get_comments_signature_exposes_filter_self_kwarg() -> None:
    """Caller-facing contract: ``filter_self`` kwarg defaults to True.

    This test is a static guard against silent regressions where someone
    flips the default. Spec 3.2 states default ON.
    """
    import inspect

    from api.ao3_client import get_comments

    sig = inspect.signature(get_comments)
    assert "filter_self" in sig.parameters, (
        "get_comments must accept filter_self kwarg"
    )
    assert sig.parameters["filter_self"].default is True, (
        "filter_self default must be True (spec 3.2)"
    )


# ---------------------------------------------------------------------------
# 11. filter_self never sees ALL comments dropped to []
#     (regression guard: no-op filter when no self-authored comments)
# ---------------------------------------------------------------------------


def test_get_comments_returns_unchanged_when_no_self_authored(
    fake_httpx: type[_FakeClient], stub_is_self: None
) -> None:
    """When no self-authored comments are present, filter is a no-op."""
    from api.ao3_client import get_comments

    fake_httpx.queue(
        _FakeResponse(
            200,
            _comments_html(
                [
                    (90001, "TheIcyQueen", "first comment"),
                    (90002, "another_reader", "second comment"),
                ]
            ),
        )
    )

    comments = get_comments(82950256)

    assert len(comments) == 2
    assert {c.author for c in comments} == {"TheIcyQueen", "another_reader"}
