"""Write loop state machine orchestrator.

The core loop that takes a story brief from idea to publication-ready fanfic.
States: BRIEF -> CONTEXT -> DRAFT -> EVALUATE -> PREPARE -> QUEUE -> DONE
With REVISE loop between EVALUATE and back, and ERROR for failures.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Re-export for patching in tests
from identity.schema import load_identity
from write.brief import StoryBrief, validate_brief
from write.context import assemble_context
from write.evaluate_fanfic import evaluate_draft as _default_evaluate_draft
from write.evaluate_fanfic import evaluate_gate
from write.experiment import (
    close_experiment as _default_close_experiment,
)
from write.experiment import (
    create_experiment_bead as _default_create_experiment_bead,
)
from write.prepare import prepare_publish_request as _default_prepare
from write.revision import generate_revision as _default_generate_revision
from write.revision import (
    generate_revision_brief as _default_generate_revision_brief,
)
from write.state import WriteLoopState, load_state, save_state

# Maximum revision cycles before giving up
MAX_REVISIONS = 3
MAX_ERROR_RETRIES = 3

# Default runs directory
DEFAULT_RUNS_DIR = Path("write/runs")


# ---------------------------------------------------------------------------
# Functions that tests patch on write.loop.*
# ---------------------------------------------------------------------------


def create_experiment_bead(
    fandom: str, title: str, hypothesis: str | None = None
) -> str:
    """Create experiment bead (patchable entry point)."""
    return _default_create_experiment_bead(
        fandom=fandom, title=title, hypothesis=hypothesis
    )


def close_experiment(
    bead_id: str,
    scores: dict | None = None,
    revision_count: int = 0,
    outcome: str = "completed",
) -> None:
    """Close experiment bead (patchable entry point)."""
    _default_close_experiment(
        bead_id=bead_id,
        scores=scores,
        revision_count=revision_count,
        outcome=outcome,
    )


def draft_chapter(
    brief: StoryBrief,
    context: dict[str, Any],
    chapter_num: int = 1,
    total_chapters: int = 1,
    previous_chapter_tail: str = "",
) -> str:
    """Draft a chapter using the Claude API.

    Builds a system prompt from the identity voice and anti-slop rules,
    and a user prompt from the brief, fandom context, and chapter position.
    """
    from write.api import call_claude

    # --- System prompt: set the writer's voice and constraints ---
    identity_block = context.get("identity", "")
    anti_slop_rules = context.get("anti_slop_rules", "")

    system = f"""You are writing fanfiction. Write in close third-person, past tense.

VOICE:
{identity_block}

ANTI-SLOP RULES (violating these is a hard failure):
{anti_slop_rules}

STRUCTURAL ANTI-PATTERNS (avoid all of these):
- NO groups or lists of three ("X, Y, and Z"). Combine two, cut one, or restructure.
- NO sarcastic quips or performative self-awareness from the narrator.
- NO balanced "not X, but Y" sentence structures more than once per chapter.
- NO over-explaining after showing. If a scene demonstrates something, do not restate it.
- NO "He did not [verb]" more than once. Convert negatives to active alternatives.
- NO "He thought about [X]" constructions. Use the thought itself as a fragment, a physical action, or dialogue.
- NO "the way [X] did [Y]" as a simile connector more than twice. Vary simile structures.
- NO section breaks (---) as rhythm crutches. Max 2 per chapter, for genuine time/location jumps.
- VARY paragraph length deliberately. Never 3+ consecutive paragraphs of similar length.
- DIALOGUE should sound like speech, not prose. Characters stumble, interrupt, trail off.
- 70%+ of the chapter should be in-scene (moment by moment) rather than summary.
- Include at least one moment that surprises -- a beat arriving early, late, or sideways.

Write the FULL chapter. Do not truncate, summarize, or skip ahead."""

    # --- User prompt: the specific writing task ---
    fandom_context = context.get("fandom_context", "")
    brief_text = context.get("brief_text", "")

    chapter_position = ""
    if total_chapters > 1:
        chapter_position = (
            f"This is chapter {chapter_num} of {total_chapters}.\n"
        )
        if previous_chapter_tail:
            chapter_position += (
                f"\nPREVIOUS CHAPTER'S ENDING (continue from here):\n"
                f"{previous_chapter_tail}\n"
            )

    prompt = f"""{chapter_position}STORY BRIEF:
{brief_text}

FANDOM CONTEXT AND CHARACTER VOICES:
{fandom_context}

TARGET LENGTH: {brief.target_length} words.

Write the chapter now. Full text, beginning to end."""

    max_tokens = int(brief.target_length * 1.5)
    # Clamp to reasonable bounds
    max_tokens = max(4000, min(max_tokens, 32000))

    return call_claude(system=system, prompt=prompt, max_tokens=max_tokens)


def evaluate_draft(
    draft_text: str,
    brief: Any = None,
    context: dict | None = None,
) -> dict[str, Any]:
    """Evaluate a draft (patchable entry point)."""
    return _default_evaluate_draft(draft_text, brief, context)


def generate_revision(
    draft_text: str,
    revision_brief: str,
    context: dict[str, Any] | None = None,
) -> str:
    """Generate revision (patchable entry point)."""
    return _default_generate_revision(draft_text, revision_brief, context)


def generate_revision_brief(
    scores: dict[str, Any],
    gate_result: str,
    draft_text: str,
    fandom_context: str,
) -> str:
    """Generate revision brief (patchable entry point)."""
    return _default_generate_revision_brief(
        scores, gate_result, draft_text, fandom_context
    )


def prepare_publish_request(
    state: WriteLoopState,
    identity: dict[str, Any],
) -> Any:
    """Prepare publish request (patchable entry point)."""
    return _default_prepare(state=state, identity=identity)


def queue_work(publish_request: Any) -> str:
    """Queue a work for human review (patchable entry point -- stub).

    Will POST to API proxy in real implementation.
    Returns a queue_id.
    """
    return f"q-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# State machine runner
# ---------------------------------------------------------------------------


def run(brief: StoryBrief) -> WriteLoopState:
    """Run the full write loop from a story brief.

    Creates a new run, progresses through all states, and returns
    the final state.

    Args:
        brief: The story brief describing what to write.

    Returns:
        The final WriteLoopState.
    """
    now = datetime.now(UTC).isoformat()
    state = WriteLoopState(
        run_id=str(uuid.uuid4()),
        state="BRIEF",
        brief=brief,
        created_at=now,
        updated_at=now,
    )

    return _run_from_state(state)


def resume(
    run_id: str,
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
) -> WriteLoopState:
    """Resume a write loop from saved state.

    Args:
        run_id: The UUID of the run to resume.
        runs_dir: Directory containing run subdirectories.

    Returns:
        The final WriteLoopState after resuming.
    """
    state_path = Path(runs_dir) / run_id / "state.json"
    state = load_state(state_path)

    # Handle ERROR state: retry from error_from
    if state.state == "ERROR":
        if state.error_attempt_count >= MAX_ERROR_RETRIES:
            return state
        state.error_attempt_count += 1
        state.state = state.error_from or "BRIEF"
        state.error_from = None
        state.error_detail = None

    return _run_from_state(state)


def _run_from_state(state: WriteLoopState) -> WriteLoopState:
    """Execute the state machine from the current state until completion or error."""
    state_path = _get_state_path(state.run_id)
    context: dict[str, Any] = {}
    identity: dict[str, Any] = {}

    while state.state not in ("DONE", "ERROR"):
        try:
            if state.state == "BRIEF":
                state = _step_brief(state)
            elif state.state == "CONTEXT":
                state, identity, context = _step_context(state)
            elif state.state == "DRAFT":
                state = _step_draft(state, context)
            elif state.state == "EVALUATE":
                state = _step_evaluate(state, context)
            elif state.state == "REVISE":
                state = _step_revise(state, context)
            elif state.state == "PREPARE":
                state, identity = _step_prepare(state, identity)
            elif state.state == "QUEUE":
                state = _step_queue(state)
            else:
                state.state = "ERROR"
                state.error_detail = f"Unknown state: {state.state}"
                break
        except Exception as exc:
            prev_state = state.state
            state.state = "ERROR"
            state.error_from = prev_state
            state.error_detail = str(exc)
            save_state(state, state_path)
            return state

        state.updated_at = datetime.now(UTC).isoformat()
        save_state(state, state_path)

    return state


def _get_state_path(run_id: str) -> Path:
    """Get the state file path for a run."""
    path = DEFAULT_RUNS_DIR / run_id / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# State step functions
# ---------------------------------------------------------------------------


def _step_brief(state: WriteLoopState) -> WriteLoopState:
    """BRIEF state: validate brief and create experiment bead."""
    brief = state.brief
    if brief is None:
        state.state = "ERROR"
        state.error_detail = "No brief provided"
        state.error_from = "BRIEF"
        return state

    try:
        validate_brief(brief)
    except (ValueError, Exception) as exc:
        state.state = "ERROR"
        state.error_detail = str(exc)
        state.error_from = "BRIEF"
        return state

    # Create experiment bead
    hypothesis = brief.experiment_hypothesis or (
        f"Standard {brief.genre} {brief.fandom} {brief.format}"
    )
    bead_id = create_experiment_bead(
        fandom=brief.fandom,
        title=brief.title or "Untitled",
        hypothesis=hypothesis,
    )
    state.experiment_bead_id = bead_id

    state.state = "CONTEXT"
    return state


def _step_context(
    state: WriteLoopState,
) -> tuple[WriteLoopState, dict[str, Any], dict[str, Any]]:
    """CONTEXT state: load identity and assemble context."""
    identity = load_identity()

    context = assemble_context(
        brief=state.brief,  # type: ignore[arg-type]
        identity=identity,
    )

    state.context_assembled = True
    state.context_token_counts = context.get("token_counts", {})
    state.state = "DRAFT"
    return state, identity, context


def _step_draft(
    state: WriteLoopState,
    context: dict[str, Any],
) -> WriteLoopState:
    """DRAFT state: draft one or more chapters."""
    brief = state.brief
    if brief is None:
        state.state = "ERROR"
        state.error_detail = "No brief in state"
        state.error_from = "DRAFT"
        return state

    chapters: list[str] = []

    if brief.format == "multi_chapter":
        num_chapters = brief.chapter_count or max(
            2, min(brief.target_length // 4000, 20)
        )
        for i in range(1, num_chapters + 1):
            prev_tail = chapters[-1][-2000:] if chapters else ""
            chapter_text = draft_chapter(
                brief=brief,
                context=context,
                chapter_num=i,
                total_chapters=num_chapters,
                previous_chapter_tail=prev_tail,
            )
            chapters.append(chapter_text)
    else:
        # One-shot
        chapter_text = draft_chapter(
            brief=brief,
            context=context,
            chapter_num=1,
            total_chapters=1,
        )
        chapters.append(chapter_text)

    state.draft_chapters = chapters
    state.draft_word_count = sum(len(c.split()) for c in chapters)
    state.state = "EVALUATE"
    return state


def _step_evaluate(
    state: WriteLoopState,
    context: dict[str, Any],
) -> WriteLoopState:
    """EVALUATE state: run evaluation gates on the draft."""
    full_text = "\n\n".join(state.draft_chapters)
    scores = evaluate_draft(
        draft_text=full_text,
        brief=state.brief,
        context=context,
    )

    state.evaluation_history.append(scores)
    passed, reason = evaluate_gate(scores)
    state.gate_result = reason

    if passed:
        state.final_scores = scores
        state.state = "PREPARE"
    elif state.revision_count >= MAX_REVISIONS:
        state.max_revisions_reached = True
        state.warnings.append(
            f"Max revisions ({MAX_REVISIONS}) reached. "
            f"Last gate result: {reason}. Proceeding to PREPARE."
        )
        state.final_scores = scores
        state.state = "PREPARE"
    else:
        state.state = "REVISE"

    return state


def _step_revise(
    state: WriteLoopState,
    context: dict[str, Any],
) -> WriteLoopState:
    """REVISE state: generate revision brief and revise the draft."""
    state.revision_count += 1

    full_text = "\n\n".join(state.draft_chapters)
    fandom_context = context.get("fandom_context", "")

    last_scores = (
        state.evaluation_history[-1] if state.evaluation_history else {}
    )
    brief = generate_revision_brief(
        scores=last_scores,
        gate_result=state.gate_result,
        draft_text=full_text,
        fandom_context=fandom_context,
    )

    revised_text = generate_revision(
        draft_text=full_text,
        revision_brief=brief,
        context=context,
    )

    # Replace draft chapters with revised text
    state.draft_chapters = [revised_text]
    state.draft_word_count = len(revised_text.split())
    state.state = "EVALUATE"
    return state


def _step_prepare(
    state: WriteLoopState,
    identity: dict[str, Any],
) -> tuple[WriteLoopState, dict[str, Any]]:
    """PREPARE state: format for AO3 and generate metadata."""
    # If identity is empty (e.g. resumed from a later state), reload it
    if not identity:
        identity = load_identity()

    publish_req = prepare_publish_request(state=state, identity=identity)
    state.publish_request = publish_req.model_dump()
    state.state = "QUEUE"
    return state, identity


def _step_queue(state: WriteLoopState) -> WriteLoopState:
    """QUEUE state: submit to the API proxy for human review."""
    from api.models import PublishRequest

    publish_data = state.publish_request
    if publish_data is None:
        state.state = "ERROR"
        state.error_detail = "No publish request in state"
        state.error_from = "QUEUE"
        return state

    req = PublishRequest(**publish_data)
    queue_id = queue_work(req)
    state.queue_id = queue_id

    # Close experiment bead
    if state.experiment_bead_id:
        close_experiment(
            bead_id=state.experiment_bead_id,
            scores=state.final_scores,
            revision_count=state.revision_count,
            outcome="queued",
        )

    state.state = "DONE"
    return state
