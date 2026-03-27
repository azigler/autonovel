"""Write loop state persistence.

Defines WriteLoopState and save/load functions for JSON serialization.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from write.brief import StoryBrief


@dataclass
class WriteLoopState:
    """Full state of a write loop run, persisted to JSON."""

    run_id: str = ""
    state: str = "BRIEF"
    brief: StoryBrief | None = None
    created_at: str = ""
    updated_at: str = ""

    # Context
    context_assembled: bool = False
    context_token_counts: dict[str, int] = field(default_factory=dict)

    # Draft
    draft_chapters: list[str] = field(default_factory=list)
    draft_word_count: int = 0

    # Evaluation
    evaluation_history: list[dict[str, Any]] = field(default_factory=list)
    gate_result: str = ""
    revision_count: int = 0
    max_revisions_reached: bool = False

    # Prepare / Queue
    queue_id: str | None = None
    publish_request: dict | None = None

    # Experiment tracking
    experiment_bead_id: str | None = None
    final_scores: dict[str, Any] | None = None

    # Error handling
    error_from: str | None = None
    error_detail: str | None = None
    error_attempt_count: int = 0

    # Warnings
    warnings: list[str] = field(default_factory=list)


def save_state(state: WriteLoopState, path: str | Path) -> None:
    """Persist WriteLoopState to a JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _state_to_dict(state)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def load_state(path: str | Path) -> WriteLoopState:
    """Load WriteLoopState from a JSON file."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return _dict_to_state(data)


def _state_to_dict(state: WriteLoopState) -> dict:
    """Convert state to a JSON-serializable dict."""
    data = {}
    for fld in state.__dataclass_fields__:
        val = getattr(state, fld)
        if isinstance(val, StoryBrief):
            val = asdict(val)
        data[fld] = val
    return data


def _dict_to_state(data: dict) -> WriteLoopState:
    """Reconstruct WriteLoopState from a dict."""
    brief_data = data.pop("brief", None)
    state = WriteLoopState(**data)
    if brief_data and isinstance(brief_data, dict):
        state.brief = StoryBrief(**brief_data)
    return state
