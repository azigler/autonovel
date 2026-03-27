"""Filesystem-based publish queue for human-reviewed AO3 posting."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from api.models import PublishRequest, QueueItem, QueueStatus

QUEUE_DIR = Path("publish_queue")


def _ensure_dir() -> None:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)


def enqueue(request: PublishRequest) -> QueueItem:
    """Create a new queue item and persist it to disk."""
    _ensure_dir()
    item = QueueItem(
        queue_id=uuid.uuid4().hex[:12],
        publish_request=request,
        status=QueueStatus.PENDING,
        created_at=datetime.now(UTC),
    )
    path = QUEUE_DIR / f"{item.queue_id}.json"
    path.write_text(item.model_dump_json(indent=2))
    return item


def list_items() -> list[QueueItem]:
    """Return all queue items sorted by created_at descending."""
    _ensure_dir()
    items: list[QueueItem] = []
    for path in QUEUE_DIR.glob("*.json"):
        data = json.loads(path.read_text())
        items.append(QueueItem.model_validate(data))
    items.sort(key=lambda i: i.created_at, reverse=True)
    return items


def get_item(queue_id: str) -> QueueItem | None:
    """Get a single queue item by ID."""
    path = QUEUE_DIR / f"{queue_id}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return QueueItem.model_validate(data)


def delete_item(queue_id: str) -> bool:
    """Remove a queue item from disk. Returns True if it existed."""
    path = QUEUE_DIR / f"{queue_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


def mark_published(queue_id: str, ao3_work_id: int) -> QueueItem | None:
    """Mark a queue item as published with the real AO3 work ID."""
    item = get_item(queue_id)
    if item is None:
        return None
    item.status = QueueStatus.PUBLISHED
    item.published_at = datetime.now(UTC)
    item.ao3_work_id = ao3_work_id
    path = QUEUE_DIR / f"{queue_id}.json"
    path.write_text(item.model_dump_json(indent=2))
    return item
