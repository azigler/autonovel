"""Write loop helpers (thin coordinator).

The full state machine that used to live here has been retired. After
the bd-75p migration the orchestrator (running ``/write``) is the
runtime: it loads identity, builds prompts via :mod:`write.prompts`,
dispatches in-harness subagents, and feeds responses back into the
evaluation / preparation helpers.

What remains here is the small set of file-system and identity helpers
that the orchestrator still calls from Python:

* :func:`setup_run` -- create the run directory and seed a fresh
  :class:`WriteLoopState`.
* :func:`_get_state_path` -- locate ``state.json`` for a run.
* :func:`_unique_run_name` -- avoid clobbering an existing run dir.
* :func:`_write_draft_md` -- export the final prose to ``draft.md``
  with YAML frontmatter once a run is complete.
* :func:`load_soul` -- read ``identity/soul.md`` (returns empty string
  if missing).

No function in this module makes a direct API call or imports an
external SDK client. The orchestrator handles all model dispatches.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from write.brief import StoryBrief
from write.state import WriteLoopState

logger = logging.getLogger(__name__)

# Default runs directory
DEFAULT_RUNS_DIR = Path("write/runs")

# Path to SOUL.md (overridable in tests)
_SOUL_PATH = Path("identity/soul.md")


def load_soul(path: Path | None = None) -> str:
    """Load SOUL.md text. Returns empty string if missing.

    Args:
        path: Optional override for the SOUL.md location. Defaults to
            ``identity/soul.md``.

    Returns:
        The full text of SOUL.md, or an empty string if the file is absent.
    """
    p = path or _SOUL_PATH
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("SOUL.md not found at %s, continuing without it.", p)
        return ""


# ---------------------------------------------------------------------------
# Run directory helpers
# ---------------------------------------------------------------------------


def _unique_run_name(base: str, runs_dir: Path = DEFAULT_RUNS_DIR) -> str:
    """Return ``base`` if no directory exists, otherwise append ``_v2``, ``_v3`` ..."""
    if not (runs_dir / base).exists():
        return base
    for n in range(2, 1000):
        candidate = f"{base}_v{n}"
        if not (runs_dir / candidate).exists():
            return candidate
    return f"{base}_{uuid.uuid4().hex[:6]}"


def _get_state_path(run_id: str, runs_dir: Path = DEFAULT_RUNS_DIR) -> Path:
    """Return ``runs_dir/<run_id>/state.json``, creating parent dirs."""
    path = runs_dir / run_id / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def setup_run(
    brief: StoryBrief,
    *,
    run_name: str | None = None,
    brief_path: str | None = None,
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
) -> WriteLoopState:
    """Create a fresh ``WriteLoopState`` for a new run.

    The orchestrator calls this at the start of ``/write``. After this
    returns, the orchestrator drives the rest of the pipeline (context
    assembly, draft, evaluate, revise, prepare, queue) using helpers from
    sibling modules and subagent dispatches built from
    :mod:`write.prompts`.

    Args:
        brief: The validated story brief.
        run_name: Human-readable run directory name. If ``None``, derived
            from ``brief_path`` (its stem) or a fresh UUID.
        brief_path: Path to the brief JSON file (stored in state for
            provenance).
        runs_dir: Directory for run state persistence (default:
            ``write/runs``).

    Returns:
        A new ``WriteLoopState`` at state ``"BRIEF"``, with run directory
        and ``state.json`` already created on disk.
    """
    if run_name is None and brief_path is not None:
        run_name = Path(brief_path).stem
    if run_name is not None:
        run_name = _unique_run_name(run_name, Path(runs_dir))
    else:
        run_name = str(uuid.uuid4())

    now = datetime.now(UTC).isoformat()
    state = WriteLoopState(
        run_id=run_name,
        state="BRIEF",
        brief=brief,
        created_at=now,
        updated_at=now,
        run_name=run_name,
        brief_path=brief_path,
    )

    # Eagerly create the run dir + state.json so the orchestrator has a
    # canonical place to persist progress.
    _get_state_path(state.run_id, runs_dir=Path(runs_dir))

    return state


# ---------------------------------------------------------------------------
# Final markdown export
# ---------------------------------------------------------------------------


def _write_draft_md(
    state: WriteLoopState, runs_dir: Path = DEFAULT_RUNS_DIR
) -> None:
    """Extract prose from a completed run into ``draft.md`` with YAML frontmatter.

    The orchestrator calls this at the end of a successful run. It collects
    the draft chapters (joined with blank lines), counts words, and writes
    a frontmatter header recording the experiment bead, brief path, run
    name, word count, slop score, and timestamp.

    Args:
        state: The completed run's state.
        runs_dir: Directory containing run subdirectories.
    """
    if not state.draft_chapters:
        return

    run_dir = runs_dir / state.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    prose = "\n\n".join(state.draft_chapters)
    word_count = len(prose.split())

    slop_score: float | str = "n/a"
    if state.final_scores is not None:
        slop_score = state.final_scores.get("slop_penalty", "n/a")

    bead_id = state.experiment_bead or state.experiment_bead_id or "none"
    brief_path = state.brief_path or "unknown"
    run_name = state.run_name or state.run_id
    created = state.updated_at or datetime.now(UTC).isoformat()

    frontmatter = (
        "---\n"
        f"experiment: {bead_id}\n"
        f"brief: {brief_path}\n"
        f"run: {run_name}\n"
        f'title: "TBD"\n'
        f"words: {word_count}\n"
        f"slop_score: {slop_score}\n"
        f"created: {created}\n"
        "---\n"
    )

    draft_path = run_dir / "draft.md"
    draft_path.write_text(frontmatter + "\n" + prose, encoding="utf-8")
    logger.info("Wrote draft.md to %s (%d words)", draft_path, word_count)
