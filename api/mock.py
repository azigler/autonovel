"""Mock data provider for testing without hitting AO3."""

from __future__ import annotations

from datetime import UTC, date, datetime

from api.models import (
    ChapterDetail,
    Comment,
    UserStats,
    WorkDetail,
    WorkStats,
    WorkSummary,
)

# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

_WORKS: list[WorkDetail] = [
    WorkDetail(
        id=10001,
        title="The Stars Between Us",
        authors=["nightowl_writes"],
        fandoms=["Harry Potter - J. K. Rowling"],
        tags=[
            "Slow Burn",
            "Enemies to Lovers",
            "Post-War",
            "Hogwarts Eighth Year",
        ],
        rating="Teen And Up Audiences",
        summary="After the war, returning to Hogwarts feels like walking through a graveyard. Draco Malfoy is the last person Harry expected to find there.",
        word_count=48320,
        chapter_count=12,
        date_posted=date(2025, 6, 15),
        date_updated=date(2025, 11, 3),
        stats=WorkStats(
            kudos=1842,
            hits=23400,
            bookmarks=312,
            subscriptions=189,
            comment_count=97,
        ),
        chapters=[
            ChapterDetail(
                id=50001,
                number=1,
                title="September Again",
                body="The platform was quieter than Harry remembered...",
                word_count=4200,
            ),
            ChapterDetail(
                id=50002,
                number=2,
                title="Assigned Seats",
                body="McGonagall's seating chart was clearly designed as punishment...",
                word_count=3800,
            ),
        ],
        body="The platform was quieter than Harry remembered...",
    ),
    WorkDetail(
        id=10002,
        title="Rust and Bone",
        authors=["greyfalcon"],
        fandoms=["The Locked Tomb Series - Tamsyn Muir"],
        tags=["Canon Divergence", "Body Horror", "Necromancy", "Found Family"],
        rating="Mature",
        summary="Gideon wakes up in a body that is not quite hers. Harrow is responsible, obviously.",
        word_count=31500,
        chapter_count=8,
        date_posted=date(2025, 8, 1),
        date_updated=date(2025, 10, 22),
        stats=WorkStats(
            kudos=967,
            hits=11200,
            bookmarks=201,
            subscriptions=134,
            comment_count=45,
        ),
        chapters=[
            ChapterDetail(
                id=50010,
                number=1,
                title="Waking",
                body="The first thing Gideon noticed was the wrong number of fingers...",
                word_count=4100,
            ),
        ],
        body="The first thing Gideon noticed was the wrong number of fingers...",
    ),
    WorkDetail(
        id=10003,
        title="Coffee, Black",
        authors=["nightowl_writes"],
        fandoms=["Good Omens - Neil Gaiman & Terry Pratchett"],
        tags=["Fluff", "Domestic", "Post-Canon", "Ineffable Husbands"],
        rating="General Audiences",
        summary="Aziraphale discovers the concept of a morning routine. Crowley is not consulted.",
        word_count=6200,
        chapter_count=1,
        date_posted=date(2026, 1, 10),
        date_updated=date(2026, 1, 10),
        stats=WorkStats(
            kudos=524,
            hits=4300,
            bookmarks=88,
            subscriptions=12,
            comment_count=31,
        ),
        chapters=[
            ChapterDetail(
                id=50020,
                number=1,
                title="",
                body="The bookshop smelled of cocoa and old paper...",
                word_count=6200,
            ),
        ],
        body="The bookshop smelled of cocoa and old paper...",
    ),
]

_COMMENTS: list[Comment] = [
    Comment(
        id=90001,
        author="fanfic_lover42",
        date=datetime(2025, 11, 4, 14, 30, tzinfo=UTC),
        chapter_id=50001,
        body="This is SO good, the characterization is spot on!",
        is_reply=False,
    ),
    Comment(
        id=90002,
        author="nightowl_writes",
        date=datetime(2025, 11, 4, 16, 0, tzinfo=UTC),
        chapter_id=50001,
        body="Thank you so much! I spent ages getting the voices right.",
        is_reply=True,
        parent_id=90001,
    ),
    Comment(
        id=90003,
        author="draco_defense_squad",
        date=datetime(2025, 11, 5, 9, 15, tzinfo=UTC),
        chapter_id=50002,
        body="The seating chart scene had me SCREAMING. McGonagall knows exactly what she's doing.",
        is_reply=False,
    ),
    Comment(
        id=90004,
        author="bookworm99",
        date=datetime(2025, 10, 23, 20, 0, tzinfo=UTC),
        chapter_id=50010,
        body="The body horror is so well done. Creepy but compelling.",
        is_reply=False,
    ),
    Comment(
        id=90005,
        author="ineffable_fan",
        date=datetime(2026, 1, 11, 8, 0, tzinfo=UTC),
        chapter_id=50020,
        body="Pure fluff perfection. I needed this today.",
        is_reply=False,
    ),
]


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_work(work_id: int) -> WorkDetail | None:
    return next((w for w in _WORKS if w.id == work_id), None)


def get_work_summary(work_id: int) -> WorkSummary | None:
    work = get_work(work_id)
    if work is None:
        return None
    return WorkSummary(**work.model_dump(exclude={"chapters", "body"}))


def list_works(
    fandom: str | None = None,
    tag: str | None = None,
    query: str | None = None,
    author: str | None = None,
    sort: str = "kudos",
    page: int = 1,
    per_page: int = 20,
) -> list[WorkSummary]:
    results = list(_WORKS)

    if fandom:
        fandom_lower = fandom.lower()
        results = [
            w
            for w in results
            if any(fandom_lower in f.lower() for f in w.fandoms)
        ]

    if tag:
        tag_lower = tag.lower()
        results = [
            w for w in results if any(tag_lower in t.lower() for t in w.tags)
        ]

    if query:
        q = query.lower()
        results = [
            w for w in results if q in w.title.lower() or q in w.summary.lower()
        ]

    if author:
        author_lower = author.lower()
        results = [
            w
            for w in results
            if any(author_lower == a.lower() for a in w.authors)
        ]

    sort_keys: dict[str, str] = {
        "kudos": "kudos",
        "hits": "hits",
        "bookmarks": "bookmarks",
        "date_posted": "date_posted",
        "date_updated": "date_updated",
        "word_count": "word_count",
    }
    sort_key = sort_keys.get(sort, "kudos")
    if sort_key in ("date_posted", "date_updated"):
        results.sort(
            key=lambda w: getattr(w, sort_key) or date.min, reverse=True
        )
    elif sort_key == "word_count":
        results.sort(key=lambda w: w.word_count, reverse=True)
    else:
        results.sort(key=lambda w: getattr(w.stats, sort_key, 0), reverse=True)

    start = (page - 1) * per_page
    end = start + per_page
    return [
        WorkSummary(**w.model_dump(exclude={"chapters", "body"}))
        for w in results[start:end]
    ]


def get_work_stats(work_id: int) -> WorkStats | None:
    work = get_work(work_id)
    return work.stats if work else None


def get_user_works(username: str) -> list[WorkSummary]:
    return list_works(author=username)


def get_user_stats(username: str) -> UserStats | None:
    works = [
        w
        for w in _WORKS
        if any(username.lower() == a.lower() for a in w.authors)
    ]
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
    work = get_work(work_id)
    if work is None:
        return []
    chapter_ids = {c.id for c in work.chapters}
    results = [c for c in _COMMENTS if c.chapter_id in chapter_ids]
    if chapter_id is not None:
        results = [c for c in results if c.chapter_id == chapter_id]
    return results
