"""Write loop state machine orchestrator.

The core loop that takes a story brief from idea to publication-ready fanfic.
States: BRIEF -> CONTEXT -> DRAFT -> EVALUATE -> PREPARE -> QUEUE -> DONE
With REVISE loop between EVALUATE and back, and ERROR for failures.
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

# Maximum revision cycles before giving up
MAX_REVISIONS = 3
MAX_ERROR_RETRIES = 3

# Default runs directory
DEFAULT_RUNS_DIR = Path("write/runs")

# Path to SOUL.md
_SOUL_PATH = Path("identity/soul.md")


def load_soul(path: Path | None = None) -> str:
    """Load SOUL.md text. Returns empty string if missing."""
    p = path or _SOUL_PATH
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning("SOUL.md not found at %s, continuing without it.", p)
        return ""


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
    soul: str = "",
    seeds: list[str] | None = None,
    config: Any = None,
    length_retry: bool = False,
    previous_word_count: int = 0,
) -> str:
    """Draft a chapter using the Claude API.

    Builds a system prompt from the identity voice and anti-slop rules,
    and a user prompt from the brief, fandom context, and chapter position.

    Args:
        brief: The story brief.
        context: Assembled context dict.
        chapter_num: Current chapter number (1-indexed).
        total_chapters: Total chapters in this work.
        previous_chapter_tail: Ending text from previous chapter.
        soul: SOUL.md text to include in the system prompt.
        seeds: Creative seeds from the muse to include in the user prompt.
        config: WriteConfig instance (optional).
        length_retry: If True, this is a retry after length undershoot.
        previous_word_count: Word count from the previous attempt (for retry).
    """
    from write.api import call_claude

    # --- System prompt: set the writer's voice and constraints ---
    identity_block = context.get("identity", "")
    anti_slop_rules = context.get("anti_slop_rules", "")

    soul_block = ""
    if soul:
        soul_block = f"\nTHEMATIC DNA (what this writer cares about):\n{soul}\n"

    system = f"""You are writing fanfiction. Write in close third-person, past tense.

VOICE:
{identity_block}
{soul_block}
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
- VARY observation verbs. Do not use "He/She looked at" more than 3 times per chapter. Use alternatives or restructure as action.
- WATCH em-dash density. No more than 8 em-dashes per 1000 words.

Write the FULL chapter. Do not truncate, summarize, or skip ahead.

OUTPUT RULES:
- Output ONLY the story prose. No title, no headers, no content warnings, no author's notes, no epigraphs, no italicized summary at the top or bottom.
- Start with the first sentence of the story. End with the last sentence of the story. Nothing else."""

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

    # Creative seeds from the muse
    seeds_block = ""
    if seeds:
        formatted = "\n".join(f"- {s}" for s in seeds)
        seeds_block = (
            f"\nCREATIVE SEEDS (from the muse -- use or ignore as "
            f"inspiration):\n{formatted}\n"
        )

    # Length instruction per config
    length_enforcement = "prompt"
    if config is not None:
        length_enforcement = getattr(config, "length_enforcement", "prompt")

    length_instruction = ""
    if length_enforcement == "none":
        length_instruction = ""
    elif length_retry:
        length_instruction = (
            f"\nCRITICAL: Your previous draft was {previous_word_count} words. "
            f"The MINIMUM is {brief.target_length} words. You MUST write at "
            f"least {brief.target_length} words. Expand scenes, add interiority, "
            f"let dialogue breathe. Do not compress.\n"
        )
    else:
        length_instruction = (
            f"\nMINIMUM LENGTH: {brief.target_length} words. Write at least "
            f"{brief.target_length} words. The piece should feel complete and "
            f"unhurried at this length, not truncated or compressed. Allow "
            f"scenes to breathe. Do not self-edit for brevity during drafting "
            f"-- that is what revision is for.\n"
        )

    prompt = f"""{chapter_position}STORY BRIEF:
{brief_text}

FANDOM CONTEXT AND CHARACTER VOICES:
{fandom_context}
{seeds_block}{length_instruction}
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


def muse_creative_seeds(
    soul: str,
    brief: str,
    fandom_context: str,
    config: Any,
) -> list[str]:
    """Pre-draft muse (patchable entry point)."""
    from write.muse import generate_creative_seeds as _impl

    return _impl(
        soul=soul, brief=brief, fandom_context=fandom_context, config=config
    )


def muse_depth_notes(
    draft: str,
    soul: str,
    scores: dict[str, Any],
    config: Any,
) -> list[str]:
    """Mid-revision muse (patchable entry point)."""
    from write.muse import generate_depth_notes as _impl

    return _impl(draft=draft, soul=soul, scores=scores, config=config)


# ---------------------------------------------------------------------------
# State machine runner
# ---------------------------------------------------------------------------


def run(
    brief: StoryBrief,
    runs_dir: str | Path = DEFAULT_RUNS_DIR,
) -> WriteLoopState:
    """Run the full write loop from a story brief.

    Creates a new run, progresses through all states, and returns
    the final state.

    Args:
        brief: The story brief describing what to write.
        runs_dir: Directory for run state persistence (default: write/runs).

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

    return _run_from_state(state, runs_dir=Path(runs_dir))


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

    return _run_from_state(state, runs_dir=Path(runs_dir))


def _run_from_state(
    state: WriteLoopState,
    runs_dir: Path = DEFAULT_RUNS_DIR,
) -> WriteLoopState:
    """Execute the state machine from the current state until completion or error."""
    state_path = _get_state_path(state.run_id, runs_dir=runs_dir)
    context: dict[str, Any] = {}
    identity: dict[str, Any] = {}
    soul: str = ""
    config = None

    while state.state not in ("DONE", "ERROR"):
        try:
            if state.state == "BRIEF":
                state = _step_brief(state)
            elif state.state == "CONTEXT":
                state, identity, context, soul, config = _step_context(state)
            elif state.state == "DRAFT":
                state = _step_draft(state, context, soul=soul, config=config)
            elif state.state == "EVALUATE":
                state = _step_evaluate(state, context, soul=soul, config=config)
            elif state.state == "REVISE":
                state = _step_revise(state, context, soul=soul, config=config)
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


def _get_state_path(run_id: str, runs_dir: Path = DEFAULT_RUNS_DIR) -> Path:
    """Get the state file path for a run."""
    path = runs_dir / run_id / "state.json"
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
) -> tuple[WriteLoopState, dict[str, Any], dict[str, Any], str, Any]:
    """CONTEXT state: load identity, soul, config, and assemble context."""
    identity = load_identity()

    context = assemble_context(
        brief=state.brief,  # type: ignore[arg-type]
        identity=identity,
    )

    # Load SOUL.md
    soul = load_soul()

    # Load config (with per-brief overrides if available)
    from write.config import WriteConfig, load_config

    overrides = None
    if state.brief is not None and hasattr(state.brief, "config_overrides"):
        overrides = getattr(state.brief, "config_overrides", None)
    try:
        config = load_config(overrides=overrides)
    except (ValueError, Exception):
        logger.warning("Config load failed, using defaults.")
        config = WriteConfig()

    state.config_snapshot = config.to_dict()
    state.context_assembled = True
    state.context_token_counts = context.get("token_counts", {})
    state.state = "DRAFT"
    return state, identity, context, soul, config


def _step_draft(
    state: WriteLoopState,
    context: dict[str, Any],
    soul: str = "",
    config: Any = None,
) -> WriteLoopState:
    """DRAFT state: fire pre-draft muse (if enabled) and draft chapters."""
    brief = state.brief
    if brief is None:
        state.state = "ERROR"
        state.error_detail = "No brief in state"
        state.error_from = "DRAFT"
        return state

    # Fire pre-draft muse (non-fatal -- if it fails, draft without seeds)
    seeds: list[str] = []
    if config is not None and getattr(config, "muse_enabled", False):
        try:
            seeds = muse_creative_seeds(
                soul=soul,
                brief=context.get("brief_text", ""),
                fandom_context=context.get("fandom_context", ""),
                config=config,
            )
            state.pre_draft_seeds = seeds
        except Exception:
            logger.warning("Pre-draft muse failed, continuing without seeds.")
            seeds = []

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
                soul=soul,
                seeds=seeds if i == 1 else None,
                config=config,
            )
            chapters.append(chapter_text)
    else:
        # One-shot
        chapter_text = draft_chapter(
            brief=brief,
            context=context,
            chapter_num=1,
            total_chapters=1,
            soul=soul,
            seeds=seeds,
            config=config,
        )
        chapters.append(chapter_text)

    # Length retry mode
    total_wc = sum(len(c.split()) for c in chapters)
    length_enforcement = "prompt"
    tolerance = 0.15
    if config is not None:
        length_enforcement = getattr(config, "length_enforcement", "prompt")
        tolerance = getattr(config, "target_length_tolerance", 0.15)

    min_acceptable = brief.target_length * (1 - tolerance)
    if (
        length_enforcement == "retry"
        and total_wc < min_acceptable
        and state.length_retry_count == 0
    ):
        state.length_retry_count += 1
        logger.info(
            "Length undershoot: %d < %d. Retrying with stronger instruction.",
            total_wc,
            int(min_acceptable),
        )
        # Redraft (one-shot only for simplicity)
        if brief.format != "multi_chapter":
            chapter_text = draft_chapter(
                brief=brief,
                context=context,
                chapter_num=1,
                total_chapters=1,
                soul=soul,
                seeds=seeds,
                config=config,
                length_retry=True,
                previous_word_count=total_wc,
            )
            chapters = [chapter_text]
            total_wc = len(chapter_text.split())
            if total_wc < min_acceptable:
                state.warnings.append(
                    f"Length retry still undershooting: {total_wc} < "
                    f"{int(min_acceptable)} words."
                )

    state.draft_chapters = chapters
    state.draft_word_count = total_wc
    state.state = "EVALUATE"
    return state


def _step_evaluate(
    state: WriteLoopState,
    context: dict[str, Any],
    soul: str = "",
    config: Any = None,
) -> WriteLoopState:
    """EVALUATE state: run evaluation gates, fire mid-revision muse."""
    full_text = "\n\n".join(state.draft_chapters)
    scores = evaluate_draft(
        draft_text=full_text,
        brief=state.brief,
        context=context,
    )

    state.evaluation_history.append(scores)
    passed, reason = evaluate_gate(scores)
    state.gate_result = reason

    # Fire mid-revision muse (after first evaluation)
    if (
        config is not None
        and getattr(config, "muse_enabled", False)
        and len(state.evaluation_history) == 1
    ):
        try:
            notes = muse_depth_notes(
                draft=full_text,
                soul=soul,
                scores=scores,
                config=config,
            )
            state.mid_revision_notes = notes
        except Exception:
            logger.warning(
                "Mid-revision muse failed, continuing without notes."
            )

    # Determine max revisions from config
    max_revisions = MAX_REVISIONS
    if config is not None:
        max_revisions = getattr(config, "max_revision_cycles", MAX_REVISIONS)

    if passed:
        state.final_scores = scores
        state.state = "PREPARE"
    elif state.revision_count >= max_revisions:
        state.max_revisions_reached = True
        state.warnings.append(
            f"Max revisions ({max_revisions}) reached. "
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
    soul: str = "",
    config: Any = None,
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
