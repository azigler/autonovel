#!/usr/bin/env python3
"""Inspect-only CLI for the write loop.

Since bd-75p, the write loop's runtime is the orchestrator (running the
``/write`` skill), not a Python state machine. There is no
``run brief.json`` command here anymore -- that work moved to the
orchestrator. What this CLI keeps:

* ``--list`` -- enumerate runs in ``write/runs/`` with their state.
* ``--show RUN_ID`` -- print details of a single run.

Both commands operate on persisted ``state.json`` files; they do not
write or generate. To start a run, invoke ``/write`` from a Claude Code
session.

Usage::

    uv run python -m write --list
    uv run python -m write --show <run-id>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from write.loop import DEFAULT_RUNS_DIR
from write.state import load_state


def cmd_list() -> None:
    """List all runs in the runs directory."""
    runs_dir = Path(DEFAULT_RUNS_DIR)
    if not runs_dir.exists():
        print("No runs yet.")
        return

    for run_dir in sorted(runs_dir.iterdir()):
        state_file = run_dir / "state.json"
        if state_file.exists():
            state = load_state(str(state_file))
            words = (
                sum(len(ch.split()) for ch in state.draft_chapters)
                if state.draft_chapters
                else 0
            )
            print(
                f"  {run_dir.name}  state={state.state}  "
                f"words={words}  revisions={state.revision_count}"
            )


def cmd_show(run_id: str) -> None:
    """Show details of a single run."""
    state = load_state(str(DEFAULT_RUNS_DIR / run_id / "state.json"))
    print(f"Run: {state.run_id}")
    print(f"State: {state.state}")
    print(f"Created: {state.created_at}")
    print(f"Updated: {state.updated_at}")
    print(f"Revisions: {state.revision_count}")
    if state.draft_chapters:
        for i, ch in enumerate(state.draft_chapters):
            print(f"Chapter {i + 1}: {len(ch.split())} words")
    if state.evaluation_history:
        print(f"Evaluations: {len(state.evaluation_history)}")
        for ev in state.evaluation_history:
            print(
                f"  slop={ev.get('slop_penalty', '?')} "
                f"overall={ev.get('overall_score', '?')}"
            )
    if state.warnings:
        print(f"Warnings: {state.warnings}")
    if state.queue_id:
        print(f"Queue ID: {state.queue_id}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect persisted write-loop runs. To start a run, invoke "
            "the /write skill from a Claude Code session."
        ),
    )
    parser.add_argument("--list", action="store_true", help="List all runs")
    parser.add_argument("--show", metavar="RUN_ID", help="Show run details")
    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.show:
        cmd_show(args.show)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
