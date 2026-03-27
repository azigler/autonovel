"""FastAPI server — local AO3 API proxy.

Run:
    uv run python -m api.server           # real mode
    uv run python -m api.server --mock    # mock mode (no AO3 requests)

Or set MOCK_MODE=true in the environment.
"""

from __future__ import annotations

import os
import sys
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from api.models import (
    Comment,
    PublishRequest,
    QueueItem,
    QueuePatchRequest,
    UserStats,
    WorkDetail,
    WorkStats,
    WorkSummary,
)
from api.queue import delete_item, enqueue, get_item, list_items, mark_published

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

TagList = Annotated[list[str], Query()]

MOCK_MODE = os.getenv("MOCK_MODE", "").lower() in ("1", "true", "yes") or (
    "--mock" in sys.argv
)

app = FastAPI(
    title="AO3 Local Proxy",
    description="Local API proxy for AO3 — decouples agent code from AO3 scraping.",
    version="0.1.0",
)


def _client():
    """Return the appropriate backend (mock or real ao3_client)."""
    if MOCK_MODE:
        from api import mock

        return mock
    from api import ao3_client

    return ao3_client


# ---------------------------------------------------------------------------
# Browse & Search
# ---------------------------------------------------------------------------


@app.get("/fandoms/{fandom_name}/works", response_model=list[WorkSummary])
def fandom_works(
    fandom_name: str,
    sort: str = "kudos",
    tags: TagList = (),
    page: int = 1,
) -> list[WorkSummary]:
    """List works in a fandom, sortable and filterable by tags."""
    client = _client()
    if MOCK_MODE:
        return client.list_works(fandom=fandom_name, sort=sort, page=page)
    return client.list_works_by_fandom(
        fandom_name, sort=sort, tags=list(tags) or None, page=page
    )


@app.get("/tags/{tag_name}/works", response_model=list[WorkSummary])
def tag_works(
    tag_name: str,
    sort: str = "kudos",
    page: int = 1,
) -> list[WorkSummary]:
    """List works with a specific tag."""
    client = _client()
    if MOCK_MODE:
        return client.list_works(tag=tag_name, sort=sort, page=page)
    return client.list_works_by_tag(tag_name, sort=sort, page=page)


@app.get("/works/{work_id}", response_model=WorkDetail)
def work_detail(work_id: int) -> WorkDetail:
    """Get a single work's metadata and text."""
    client = _client()
    work = client.get_work(work_id)
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    return work


@app.get("/search", response_model=list[WorkSummary])
def search(
    query: str = "",
    fandom: str = "",
    tags: TagList = (),
    sort: str = "kudos",
    page: int = 1,
) -> list[WorkSummary]:
    """Search works by query, fandom, tags, and sort."""
    client = _client()
    tag_list = list(tags)
    if MOCK_MODE:
        return client.list_works(
            query=query or None,
            fandom=fandom or None,
            tag=tag_list[0] if tag_list else None,
            sort=sort,
            page=page,
        )
    return client.search_works(
        query=query,
        fandom=fandom,
        tags=tag_list or None,
        sort=sort,
        page=page,
    )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


@app.get("/works/{work_id}/stats", response_model=WorkStats)
def work_stats(work_id: int) -> WorkStats:
    """Get stats for a work: kudos, hits, bookmarks, subscriptions, comments."""
    client = _client()
    stats = client.get_work_stats(work_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="Work not found")
    return stats


@app.get("/users/{username}/stats", response_model=UserStats)
def user_stats(username: str) -> UserStats:
    """Aggregate stats across all of a user's works."""
    client = _client()
    stats = client.get_user_stats(username)
    if stats is None:
        raise HTTPException(status_code=404, detail="User not found")
    return stats


@app.get("/users/{username}/works", response_model=list[WorkSummary])
def user_works(username: str) -> list[WorkSummary]:
    """List a user's works with stats."""
    client = _client()
    if MOCK_MODE:
        return client.list_works(author=username)
    return client.get_user_works(username)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


@app.get("/works/{work_id}/comments", response_model=list[Comment])
def work_comments(work_id: int) -> list[Comment]:
    """All comments on a work."""
    client = _client()
    return client.get_comments(work_id)


@app.get(
    "/works/{work_id}/chapters/{chapter_id}/comments",
    response_model=list[Comment],
)
def chapter_comments(work_id: int, chapter_id: int) -> list[Comment]:
    """Comments on a specific chapter."""
    client = _client()
    return client.get_comments(work_id, chapter_id=chapter_id)


# ---------------------------------------------------------------------------
# Publish queue (human-reviewed, NOT auto-posted)
# ---------------------------------------------------------------------------


@app.post("/works", response_model=QueueItem, status_code=201)
def create_work(request: PublishRequest) -> QueueItem:
    """Queue a work for human review. Returns a queue_id."""
    return enqueue(request)


@app.get("/queue", response_model=list[QueueItem])
def list_queue() -> list[QueueItem]:
    """List all pending publications."""
    return list_items()


@app.get("/queue/{queue_id}", response_model=QueueItem)
def get_queue_item(queue_id: str) -> QueueItem:
    """Get a specific queued publication."""
    item = get_item(queue_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return item


@app.delete("/queue/{queue_id}", status_code=204)
def delete_queue_item(queue_id: str) -> None:
    """Remove a publication from the queue."""
    if not delete_item(queue_id):
        raise HTTPException(status_code=404, detail="Queue item not found")


@app.patch("/queue/{queue_id}", response_model=QueueItem)
def patch_queue_item(queue_id: str, body: QueuePatchRequest) -> QueueItem:
    """Mark a queued publication as published with its AO3 work ID."""
    item = mark_published(queue_id, body.ao3_work_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return item


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    mode = "MOCK" if MOCK_MODE else "LIVE"
    print(f"Starting AO3 proxy in {mode} mode...")
    uvicorn.run("api.server:app", host="127.0.0.1", port=8000, reload=True)
