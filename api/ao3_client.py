"""AO3 client — wraps httpx + BeautifulSoup for reading AO3 data.

Includes aggressive rate limiting (1 req / 3 s) and disk-based caching.
This module is only used when MOCK_MODE is off.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag

from api.models import (
    ChapterDetail,
    Comment,
    UserStats,
    WorkDetail,
    WorkStats,
    WorkSummary,
)

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

_MIN_INTERVAL = 3.0  # seconds between requests
_last_request_time: float = 0.0


def _rate_limit() -> None:
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_request_time = time.monotonic()


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

CACHE_DIR = Path("api/cache")

# TTLs in seconds
_TTL_WORK_TEXT = 0  # indefinite
_TTL_METADATA = 86400  # 1 day
_TTL_STATS = 86400
_TTL_COMMENTS = 86400


def _cache_key(namespace: str, identifier: str) -> Path:
    h = hashlib.sha256(f"{namespace}:{identifier}".encode()).hexdigest()[:16]
    return CACHE_DIR / namespace / f"{h}.json"


def _cache_get(namespace: str, identifier: str, ttl: int) -> dict | None:
    path = _cache_key(namespace, identifier)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    if ttl > 0:
        cached_at = data.get("_cached_at", 0)
        if time.time() - cached_at > ttl:
            return None
    return data.get("payload")


def _cache_set(namespace: str, identifier: str, payload: dict) -> None:
    path = _cache_key(namespace, identifier)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"_cached_at": time.time(), "payload": payload}
    path.write_text(json.dumps(data, default=str))


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

_BASE = "https://archiveofourown.org"
_HEADERS = {
    "User-Agent": "autonovel-research/0.1 (respectful academic project)",
    "Accept": "text/html",
}


def _get(path: str, params: dict | None = None) -> BeautifulSoup:
    """Fetch a page from AO3 with rate limiting."""
    _rate_limit()
    url = f"{_BASE}{path}"
    with httpx.Client(
        headers=_HEADERS, follow_redirects=True, timeout=30
    ) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _text(tag: Tag | None) -> str:
    return tag.get_text(strip=True) if tag else ""


def _int_text(tag: Tag | None) -> int:
    txt = _text(tag).replace(",", "")
    try:
        return int(txt)
    except (ValueError, TypeError):
        return 0


def _parse_work_blurb(blurb: Tag) -> WorkSummary | None:
    """Parse a work blurb from a listing page."""
    heading = blurb.find("h4", class_="heading")
    if heading is None:
        return None
    link = heading.find("a")
    if link is None:
        return None
    href = link.get("href", "")
    if not isinstance(href, str) or "/works/" not in href:
        return None
    try:
        work_id = int(href.split("/works/")[1].split("/")[0])
    except (ValueError, IndexError):
        return None

    title = _text(link)
    authors = [_text(a) for a in heading.find_all("a", rel="author")]

    fandom_tags = blurb.find("h5", class_="fandoms")
    fandoms = (
        [_text(a) for a in fandom_tags.find_all("a", class_="tag")]
        if fandom_tags
        else []
    )

    tags_ul = blurb.find("ul", class_="tags")
    tags = (
        [
            _text(li)
            for li in tags_ul.find_all("li")
            if li.find("a", class_="tag")
        ]
        if tags_ul
        else []
    )

    rating_tag = blurb.find("span", class_="rating")
    rating = _text(rating_tag)

    summary_tag = blurb.find("blockquote", class_="userstuff")
    summary = _text(summary_tag)

    stats_tag = blurb.find("dl", class_="stats")
    kudos = _int_text(
        stats_tag.find("dd", class_="kudos") if stats_tag else None
    )
    hits = _int_text(stats_tag.find("dd", class_="hits") if stats_tag else None)
    bookmarks = _int_text(
        stats_tag.find("dd", class_="bookmarks") if stats_tag else None
    )
    comments = _int_text(
        stats_tag.find("dd", class_="comments") if stats_tag else None
    )

    words_tag = stats_tag.find("dd", class_="words") if stats_tag else None
    word_count = _int_text(words_tag)

    chapters_tag = (
        stats_tag.find("dd", class_="chapters") if stats_tag else None
    )
    chapter_text = _text(chapters_tag)
    try:
        chapter_count = int(chapter_text.split("/")[0])
    except (ValueError, IndexError):
        chapter_count = 1

    return WorkSummary(
        id=work_id,
        title=title,
        authors=authors,
        fandoms=fandoms,
        tags=tags,
        rating=rating,
        summary=summary,
        word_count=word_count,
        chapter_count=chapter_count,
        stats=WorkStats(
            kudos=kudos,
            hits=hits,
            bookmarks=bookmarks,
            comment_count=comments,
        ),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_works_by_fandom(
    fandom: str,
    sort: str = "kudos",
    tags: list[str] | None = None,
    page: int = 1,
) -> list[WorkSummary]:
    """List works in a fandom tag."""
    cache_id = f"{fandom}:{sort}:{tags}:{page}"
    cached = _cache_get("fandom_works", cache_id, _TTL_METADATA)
    if cached is not None:
        return [WorkSummary.model_validate(w) for w in cached]

    sort_map = {
        "kudos": "kudos_count",
        "hits": "hits",
        "date_posted": "created_at",
        "date_updated": "revised_at",
        "bookmarks": "bookmarks_count",
    }
    params: dict[str, str] = {
        "work_search[sort_column]": sort_map.get(sort, "kudos_count"),
        "page": str(page),
    }
    if tags:
        params["work_search[other_tag_names]"] = ",".join(tags)

    tag_path = fandom.replace(" ", "%20")
    soup = _get(f"/tags/{tag_path}/works", params)
    blurbs = soup.find_all("li", class_="work")
    works = [w for b in blurbs if (w := _parse_work_blurb(b)) is not None]

    _cache_set("fandom_works", cache_id, [w.model_dump() for w in works])
    return works


def list_works_by_tag(
    tag: str, page: int = 1, sort: str = "kudos"
) -> list[WorkSummary]:
    """List works with a specific tag."""
    return list_works_by_fandom(tag, sort=sort, page=page)


def search_works(
    query: str = "",
    fandom: str = "",
    tags: list[str] | None = None,
    sort: str = "kudos",
    page: int = 1,
) -> list[WorkSummary]:
    """Search AO3 works."""
    cache_id = f"search:{query}:{fandom}:{tags}:{sort}:{page}"
    cached = _cache_get("search", cache_id, _TTL_METADATA)
    if cached is not None:
        return [WorkSummary.model_validate(w) for w in cached]

    sort_map = {
        "kudos": "kudos_count",
        "hits": "hits",
        "date_posted": "created_at",
        "date_updated": "revised_at",
    }
    params: dict[str, str] = {
        "work_search[query]": query,
        "work_search[sort_column]": sort_map.get(sort, "kudos_count"),
        "page": str(page),
    }
    if fandom:
        params["work_search[fandom_names]"] = fandom
    if tags:
        params["work_search[other_tag_names]"] = ",".join(tags)

    soup = _get("/works/search", params)
    blurbs = soup.find_all("li", class_="work")
    works = [w for b in blurbs if (w := _parse_work_blurb(b)) is not None]

    _cache_set("search", cache_id, [w.model_dump() for w in works])
    return works


def get_work(work_id: int) -> WorkDetail | None:
    """Get full work detail including chapter text."""
    cached = _cache_get("work_detail", str(work_id), _TTL_WORK_TEXT)
    if cached is not None:
        return WorkDetail.model_validate(cached)

    try:
        soup = _get(
            f"/works/{work_id}",
            {"view_adult": "true", "view_full_work": "true"},
        )
    except httpx.HTTPStatusError:
        return None

    title_tag = soup.find("h2", class_="title")
    title = _text(title_tag)

    author_tags = soup.find_all("a", rel="author")
    authors = [_text(a) for a in author_tags]

    fandom_dd = soup.find("dd", class_="fandom")
    fandoms = (
        [_text(a) for a in fandom_dd.find_all("a", class_="tag")]
        if fandom_dd
        else []
    )

    tag_dd = soup.find("dd", class_="freeform")
    tags = (
        [_text(a) for a in tag_dd.find_all("a", class_="tag")] if tag_dd else []
    )

    rating_dd = soup.find("dd", class_="rating")
    rating = _text(rating_dd.find("a") if rating_dd else None)

    summary_div = soup.find("div", class_="summary")
    summary = _text(summary_div.find("blockquote") if summary_div else None)

    stats_dl = soup.find("dl", class_="stats")
    kudos = _int_text(stats_dl.find("dd", class_="kudos") if stats_dl else None)
    hits = _int_text(stats_dl.find("dd", class_="hits") if stats_dl else None)
    bookmarks = _int_text(
        stats_dl.find("dd", class_="bookmarks") if stats_dl else None
    )
    comments_count = _int_text(
        stats_dl.find("dd", class_="comments") if stats_dl else None
    )
    word_count = _int_text(
        stats_dl.find("dd", class_="words") if stats_dl else None
    )

    # Parse chapters
    chapters: list[ChapterDetail] = []
    chapter_divs = soup.find_all("div", class_="chapter")
    if chapter_divs:
        for i, ch_div in enumerate(chapter_divs, 1):
            ch_id_attr = ch_div.get("id", "")
            try:
                ch_id = int(str(ch_id_attr).replace("chapter-", ""))
            except (ValueError, TypeError):
                ch_id = i
            ch_title_tag = ch_div.find("h3", class_="title")
            ch_title = _text(ch_title_tag)
            ch_body_div = ch_div.find("div", role="article")
            ch_body = _text(ch_body_div)
            chapters.append(
                ChapterDetail(
                    id=ch_id,
                    number=i,
                    title=ch_title,
                    body=ch_body,
                    word_count=len(ch_body.split()),
                )
            )
    else:
        # Single-chapter work
        body_div = soup.find("div", role="article")
        body_text = _text(body_div)
        chapters.append(
            ChapterDetail(
                id=work_id,
                number=1,
                title=title,
                body=body_text,
                word_count=len(body_text.split()),
            )
        )

    full_body = "\n\n".join(ch.body for ch in chapters)

    work = WorkDetail(
        id=work_id,
        title=title,
        authors=authors,
        fandoms=fandoms,
        tags=tags,
        rating=rating,
        summary=summary,
        word_count=word_count,
        chapter_count=len(chapters),
        stats=WorkStats(
            kudos=kudos,
            hits=hits,
            bookmarks=bookmarks,
            comment_count=comments_count,
        ),
        chapters=chapters,
        body=full_body,
    )

    _cache_set("work_detail", str(work_id), work.model_dump())
    return work


def get_work_stats(work_id: int) -> WorkStats | None:
    """Get stats for a work."""
    cached = _cache_get("work_stats", str(work_id), _TTL_STATS)
    if cached is not None:
        return WorkStats.model_validate(cached)

    work = get_work(work_id)
    if work is None:
        return None
    _cache_set("work_stats", str(work_id), work.stats.model_dump())
    return work.stats


def get_user_works(username: str) -> list[WorkSummary]:
    """List all works by a user."""
    cache_id = f"user_works:{username}"
    cached = _cache_get("user_works", cache_id, _TTL_METADATA)
    if cached is not None:
        return [WorkSummary.model_validate(w) for w in cached]

    try:
        soup = _get(f"/users/{username}/works")
    except httpx.HTTPStatusError:
        return []

    blurbs = soup.find_all("li", class_="work")
    works = [w for b in blurbs if (w := _parse_work_blurb(b)) is not None]

    _cache_set("user_works", cache_id, [w.model_dump() for w in works])
    return works


def get_user_stats(username: str) -> UserStats | None:
    """Aggregate stats across a user's works."""
    works = get_user_works(username)
    if not works:
        return None
    return UserStats(
        username=username,
        total_works=len(works),
        total_kudos=sum(w.stats.kudos for w in works),
        total_hits=sum(w.stats.hits for w in works),
        total_bookmarks=sum(w.stats.bookmarks for w in works),
        total_subscriptions=sum(w.stats.subscriptions for w in works),
        total_comments=sum(w.stats.comment_count for w in works),
        total_word_count=sum(w.word_count for w in works),
    )


def get_comments(work_id: int, chapter_id: int | None = None) -> list[Comment]:
    """Get comments on a work (optionally filtered to one chapter)."""
    cache_id = f"comments:{work_id}:{chapter_id}"
    cached = _cache_get("comments", cache_id, _TTL_COMMENTS)
    if cached is not None:
        return [Comment.model_validate(c) for c in cached]

    try:
        soup = _get(f"/works/{work_id}/comments")
    except httpx.HTTPStatusError:
        return []

    comments: list[Comment] = []
    for li in soup.find_all("li", class_="comment"):
        comment_id_attr = li.get("id", "")
        try:
            cid = int(str(comment_id_attr).replace("comment_", ""))
        except (ValueError, TypeError):
            continue

        byline = li.find("h4", class_="heading")
        author = _text(byline.find("a") if byline else None)

        date_tag = li.find("span", class_="posted")
        date_str = _text(date_tag)
        try:
            cdate = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %Z").replace(
                tzinfo=UTC
            )
        except (ValueError, TypeError):
            cdate = None

        body_div = li.find("blockquote", class_="userstuff")
        body = _text(body_div)

        is_reply = (
            "depth-greater" in li.get("class", [])
            if isinstance(li.get("class"), list)
            else False
        )

        comments.append(
            Comment(
                id=cid,
                author=author,
                date=cdate,
                chapter_id=chapter_id,
                body=body,
                is_reply=is_reply,
            )
        )

    _cache_set("comments", cache_id, [c.model_dump() for c in comments])
    return comments
