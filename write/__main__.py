#!/usr/bin/env python3
"""CLI entrypoint for the write loop.

Usage:
  uv run python -m write briefs/first_story.json          # new run from brief
  uv run python -m write --resume <run-id>                 # resume interrupted run
  uv run python -m write --list                            # list runs
  uv run python -m write --show <run-id>                   # show run state
"""

import argparse
import json
import sys
from pathlib import Path

from write.brief import StoryBrief, validate_brief
from write.loop import DEFAULT_RUNS_DIR, resume, run
from write.state import load_state


def cmd_run(brief_path: str) -> None:
    """Run the write loop on a brief."""
    path = Path(brief_path)
    if not path.exists():
        print(f"Brief not found: {path}", file=sys.stderr)
        sys.exit(1)

    with open(path) as f:
        data = json.load(f)

    brief = StoryBrief(**data)
    validate_brief(brief)

    run_name = path.stem

    print("Starting write loop")
    print(f"  Brief: {path}")
    print(f"  Run name: {run_name}")
    print(f"  Fandom: {brief.fandom}")
    print(f"  Characters: {brief.characters}")
    print(f"  Target: {brief.target_length} words")
    print(f"  Format: {brief.format}")
    print()

    state = run(brief, run_name=run_name, brief_path=str(path))

    print()
    print("=== DONE ===")
    print(f"  Run ID: {state.run_id}")
    print(f"  Final state: {state.state}")
    print(f"  Revision cycles: {state.revision_count}")
    if state.draft_chapters:
        total_words = sum(len(ch.split()) for ch in state.draft_chapters)
        print(f"  Total words: {total_words}")
    if state.warnings:
        print(f"  Warnings: {state.warnings}")
    print(f"  Output: {DEFAULT_RUNS_DIR / state.run_id}/")


def cmd_resume(run_id: str) -> None:
    """Resume an interrupted run."""
    state = resume(run_id)
    print(f"Resumed run {run_id}")
    print(f"  Final state: {state.state}")


def cmd_list() -> None:
    """List all runs."""
    runs_dir = Path(DEFAULT_RUNS_DIR)
    if not runs_dir.exists():
        print("No runs yet.")
        return

    for run_dir in sorted(runs_dir.iterdir()):
        state_file = run_dir / "state.json"
        if state_file.exists():
            state = load_state(str(run_dir / "state.json"))
            words = (
                sum(len(ch.split()) for ch in state.draft_chapters)
                if state.draft_chapters
                else 0
            )
            print(
                f"  {run_dir.name}  state={state.state}  words={words}  revisions={state.revision_count}"
            )


def cmd_show(run_id: str) -> None:
    """Show details of a run."""
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
                f"  slop={ev.get('slop_penalty', '?')} overall={ev.get('overall_score', '?')}"
            )
    if state.warnings:
        print(f"Warnings: {state.warnings}")
    if state.queue_id:
        print(f"Queue ID: {state.queue_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Write loop CLI")
    parser.add_argument("brief", nargs="?", help="Path to story brief JSON")
    parser.add_argument(
        "--resume", metavar="RUN_ID", help="Resume an interrupted run"
    )
    parser.add_argument("--list", action="store_true", help="List all runs")
    parser.add_argument("--show", metavar="RUN_ID", help="Show run details")
    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.show:
        cmd_show(args.show)
    elif args.resume:
        cmd_resume(args.resume)
    elif args.brief:
        cmd_run(args.brief)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
