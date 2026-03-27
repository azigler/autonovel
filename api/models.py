"""Pydantic v2 models for AO3 API proxy request/response schemas."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Rating(StrEnum):
    NOT_RATED = "Not Rated"
    GENERAL = "General Audiences"
    TEEN = "Teen And Up Audiences"
    MATURE = "Mature"
    EXPLICIT = "Explicit"


class SortField(StrEnum):
    KUDOS = "kudos"
    HITS = "hits"
    DATE_POSTED = "date_posted"
    DATE_UPDATED = "date_updated"
    WORD_COUNT = "word_count"
    BOOKMARKS = "bookmarks"
    COMMENTS = "comments"


class QueueStatus(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"


# ---------------------------------------------------------------------------
# Work models
# ---------------------------------------------------------------------------


class WorkStats(BaseModel):
    kudos: int = 0
    hits: int = 0
    bookmarks: int = 0
    subscriptions: int = 0
    comment_count: int = 0
    by_date: dict[str, int] | None = None


class WorkSummary(BaseModel):
    id: int
    title: str
    authors: list[str] = Field(default_factory=list)
    fandoms: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    rating: str = ""
    summary: str = ""
    word_count: int = 0
    chapter_count: int = 1
    date_posted: date | None = None
    date_updated: date | None = None
    stats: WorkStats = Field(default_factory=WorkStats)


class ChapterDetail(BaseModel):
    id: int
    number: int
    title: str = ""
    body: str = ""
    word_count: int = 0


class WorkDetail(WorkSummary):
    chapters: list[ChapterDetail] = Field(default_factory=list)
    body: str = ""


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


class Comment(BaseModel):
    id: int
    author: str = ""
    date: datetime | None = None
    chapter_id: int | None = None
    body: str = ""
    is_reply: bool = False
    parent_id: int | None = None


# ---------------------------------------------------------------------------
# Publish / Queue
# ---------------------------------------------------------------------------


class PublishRequest(BaseModel):
    title: str
    fandom: str
    rating: Rating = Rating.NOT_RATED
    tags: list[str] = Field(default_factory=list)
    summary: str = ""
    body: str
    author_notes: str = ""


class QueueItem(BaseModel):
    queue_id: str
    publish_request: PublishRequest
    status: QueueStatus = QueueStatus.PENDING
    created_at: datetime
    published_at: datetime | None = None
    ao3_work_id: int | None = None


class QueuePatchRequest(BaseModel):
    """PATCH body for marking a queue item as published."""

    ao3_work_id: int


# ---------------------------------------------------------------------------
# User stats
# ---------------------------------------------------------------------------


class UserStats(BaseModel):
    username: str
    total_works: int = 0
    total_kudos: int = 0
    total_hits: int = 0
    total_bookmarks: int = 0
    total_subscriptions: int = 0
    total_comments: int = 0
    total_word_count: int = 0


# ---------------------------------------------------------------------------
# Search / filter helpers
# ---------------------------------------------------------------------------


class SearchParams(BaseModel):
    query: str = ""
    fandom: str = ""
    tags: list[str] = Field(default_factory=list)
    rating: Rating | None = None
    sort: SortField = SortField.KUDOS
    page: int = 1
    per_page: int = 20
