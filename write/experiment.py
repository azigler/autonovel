"""Experiment bead tracking for write loop runs.

Creates and closes experiment beads via the br CLI tool.
"""

from __future__ import annotations

import re
import subprocess


def create_experiment_bead(
    fandom: str,
    title: str,
    hypothesis: str | None = None,
) -> str:
    """Create an experiment bead and return its ID.

    Args:
        fandom: The fandom being written for.
        title: The story/experiment title.
        hypothesis: What we're testing (optional).

    Returns:
        The bead ID string (e.g. "bd-exp-001").
    """
    bead_title = f"experiment: {title} ({fandom})"
    result = subprocess.run(
        ["br", "create", "-p", "3", bead_title],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # Fallback: return a placeholder if br is not available
        return "bd-experiment-unknown"

    # Parse bead ID from output like "Created bead bd-exp-001"
    match = re.search(r"(bd-\S+)", result.stdout)
    if match:
        return match.group(1)
    return "bd-experiment-unknown"


def close_experiment(
    bead_id: str,
    scores: dict | None = None,
    revision_count: int = 0,
    outcome: str = "completed",
) -> None:
    """Close an experiment bead with results.

    Args:
        bead_id: The bead ID to close.
        scores: Final evaluation scores.
        revision_count: Number of revision cycles used.
        outcome: "completed", "published", or "rejected".
    """
    description_parts = [
        f"Outcome: {outcome}",
        f"Revision cycles: {revision_count}",
    ]
    if scores:
        slop = scores.get("slop_penalty", "N/A")
        overall = scores.get("overall_score", "N/A")
        description_parts.append(f"Final slop penalty: {slop}")
        description_parts.append(f"Final overall score: {overall}")

    description = "\n".join(description_parts)

    subprocess.run(
        ["br", "update", bead_id, "--description", description],
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["br", "close", bead_id],
        capture_output=True,
        text=True,
    )
