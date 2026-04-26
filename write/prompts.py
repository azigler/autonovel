"""Pure prompt builders for the write loop.

This module contains every prompt expression used by the orchestrator's
in-harness subagent dispatches: drafting, revision, multi-pass revision,
muse seeds, muse depth notes, and muse evolution. Every function here is
pure (no I/O, no API calls, no side effects). The orchestrator running
``/write`` builds a prompt with one of these functions, wraps it in the
persona-suppression frame, and dispatches a Task subagent. The subagent's
response feeds back into Python helpers (evaluate, prepare, etc.).

Why this module exists:

The write loop used to call the Anthropic SDK directly through ``write/api.py``.
That direct-API path was the last surviving direct-API consumer in the project
(see ``refs/api-vs-harness.md``). With the migration to in-harness subagents,
the prompt content needed somewhere to live that isn't tangled with HTTP
concerns. ``prompts.py`` is that home: pure prompt strings, no runtime, no
state, easy to test by string assertion.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Persona-suppression frame
# ---------------------------------------------------------------------------
#
# Subagents inherit Claude Code's assistant persona via the harness system
# prompt. Without explicit suppression, that persona leaks into the
# generated prose ("Here is the chapter you requested..."). The frame below
# names the writer's identity verbatim and forbids preamble. It is
# load-bearing: the exact wording is the contract that bd-75p was designed
# around. Do NOT paraphrase.


_PROSE_FRAME = """You will execute one task only: generate prose in a specific author's voice.

OUTPUT RULES (non-negotiable):
- Output ONLY the story prose. Nothing else.
- No preamble. No "Here is the chapter." No meta-commentary, no markdown headers, no formatting hints.
- The first character of your response must be the first character of the story.
- The last character of your response must be the last character of the story.
- Do not break character. Do not refer to yourself, the task, or this prompt.

The VOICE AND CONSTRAINTS section below is not advice about how to be helpful.
It IS the writer's identity. Embody it for the duration of this response.

---

VOICE AND CONSTRAINTS:
{system}

---

WRITING TASK:
{user}

---

Begin the prose now. Output the story only."""


_STRUCTURED_FRAME = """You will execute one task only: produce {output_kind}.

OUTPUT RULES (non-negotiable):
- Output ONLY {output_kind}. Nothing else.
- No preamble. No "Here are the seeds." No meta-commentary, no markdown headers, no closing remarks.
- The first character of your response must be the first character of the structured output.
- The last character of your response must be the last character of the structured output.
- Do not break character. Do not refer to yourself, the task, or this prompt.

The VOICE AND CONSTRAINTS section below is not advice about how to be helpful.
It IS the speaker's identity. Embody it for the duration of this response.

---

VOICE AND CONSTRAINTS:
{system}

---

TASK:
{user}

---

Begin now. Output the structured response only."""


def wrap_for_subagent(system: str, user: str) -> str:
    """Wrap a (system, user) pair into a single user-message frame for prose.

    The orchestrator dispatches subagents with a single user-message string;
    they cannot inject a separate system prompt without inheriting the
    Claude Code assistant persona. This wrapper folds the writer's voice
    block (``system``) and the writing task (``user``) into one message
    framed by persona-suppression rules.

    Args:
        system: The writer's voice and constraints. Becomes the
            ``VOICE AND CONSTRAINTS`` section.
        user: The specific writing task (chapter spec, revision brief, etc.).
            Becomes the ``WRITING TASK`` section.

    Returns:
        A single string ready to be passed as the user message to a subagent
        that should output prose only.
    """
    return _PROSE_FRAME.format(system=system, user=user)


def wrap_for_subagent_structured(
    system: str,
    user: str,
    output_kind: str,
) -> str:
    """Wrap a (system, user) pair for structured (non-prose) subagent dispatches.

    Used for muse seed lists, depth notes, and soul-evolution proposals --
    anything that returns numbered or bulleted output rather than narrative
    prose. The persona-suppression intent is preserved; only the OUTPUT
    RULES block is swapped to name the structured output kind.

    Args:
        system: The speaker's voice and constraints.
        user: The specific task.
        output_kind: A short noun-phrase naming the expected output, e.g.
            ``"a numbered list of 4 seeds, one per line, no preamble"``.

    Returns:
        A single string ready to be passed as the user message to a subagent
        that should output structured content only.
    """
    return _STRUCTURED_FRAME.format(
        system=system,
        user=user,
        output_kind=output_kind,
    )


# ---------------------------------------------------------------------------
# Draft prompt builders
# ---------------------------------------------------------------------------


def build_draft_system(context: dict[str, Any], soul: str) -> str:
    """Build the SYSTEM prompt for a chapter draft subagent.

    Sets the writer's voice, anti-slop rules, structural anti-patterns,
    and OUTPUT RULES. Returned as the ``system`` argument that
    ``wrap_for_subagent`` later folds into the persona-suppression frame.

    Args:
        context: Assembled context dict. Reads ``identity`` and
            ``anti_slop_rules`` keys.
        soul: SOUL.md text. If non-empty, included as a THEMATIC DNA block.

    Returns:
        The system prompt string.
    """
    identity_block = context.get("identity", "")
    anti_slop_rules = context.get("anti_slop_rules", "")

    soul_block = ""
    if soul:
        soul_block = f"\nTHEMATIC DNA (what this writer cares about):\n{soul}\n"

    return f"""You are writing fanfiction. Write in close third-person, past tense.

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


def build_draft_user(
    brief: Any,
    context: dict[str, Any],
    chapter_num: int = 1,
    total_chapters: int = 1,
    previous_chapter_tail: str = "",
    seeds: list[str] | None = None,
    length_retry: bool = False,
    previous_word_count: int = 0,
    length_enforcement: str = "prompt",
) -> str:
    """Build the USER prompt (writing task) for a chapter draft subagent.

    Args:
        brief: A ``StoryBrief`` (only ``target_length`` is read here).
        context: Assembled context dict. Reads ``brief_text`` and
            ``fandom_context`` keys.
        chapter_num: Current chapter number (1-indexed).
        total_chapters: Total chapters in this work.
        previous_chapter_tail: Last ~2000 chars of the previous chapter,
            for continuity.
        seeds: Pre-draft muse seeds, if any.
        length_retry: True if this is a retry after a length undershoot.
        previous_word_count: Word count from the previous attempt (only used
            if ``length_retry`` is True).
        length_enforcement: One of ``"prompt"``, ``"retry"``, ``"none"``.

    Returns:
        The user prompt string (the writing task).
    """
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

    seeds_block = ""
    if seeds:
        formatted = "\n".join(f"- {s}" for s in seeds)
        seeds_block = (
            f"\nCREATIVE SEEDS (from the muse -- use or ignore as "
            f"inspiration):\n{formatted}\n"
        )

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

    return f"""{chapter_position}STORY BRIEF:
{brief_text}

FANDOM CONTEXT AND CHARACTER VOICES:
{fandom_context}
{seeds_block}{length_instruction}
Write the chapter now. Full text, beginning to end."""


# ---------------------------------------------------------------------------
# Revision prompt builders (multi-pass)
# ---------------------------------------------------------------------------


def build_revision_pass_system(
    pass_name: str,
    context: dict[str, Any],
    muse_notes: list[str] | None = None,
    soul: str = "",
) -> str:
    """Build the SYSTEM prompt for a single revision pass.

    Pass names: ``"structure"``, ``"depth"``, ``"voice"``, ``"cut"``.
    Each pass has a tightly scoped intent. The orchestrator runs them
    sequentially, threading the revised text from one into the next.

    Args:
        pass_name: One of ``structure``, ``depth``, ``voice``, ``cut``.
        context: Assembled context dict (used for ``identity`` and
            ``anti_slop_rules`` in the voice pass).
        muse_notes: Mid-revision muse notes (used in depth pass only).
        soul: SOUL.md text (used in cut pass only).

    Returns:
        The system prompt string for this pass.
    """
    identity_block = context.get("identity", "")
    anti_slop_rules = context.get("anti_slop_rules", "")

    if pass_name == "structure":
        return (
            "You are a structural editor. Read this piece for shape and movement. "
            "Your ONLY concern is structure:\n\n"
            "- Does the piece have forward motion, or does it stall?\n"
            "- Does each scene/section earn its place?\n"
            "- Is there a turn -- a moment where something shifts?\n"
            "- Does the ending feel earned by what came before?\n"
            "- Are there sections that repeat the same emotional beat without "
            "progression?\n\n"
            "If the structure works, make minimal changes. If it doesn't, "
            "restructure. Preserve voice and prose quality -- you are NOT line "
            "editing. Return the complete revised text."
        )

    if pass_name == "depth":
        notes_block = ""
        if muse_notes:
            formatted = "\n".join(f"- {n}" for n in muse_notes)
            notes_block = (
                f"\nSOUL NOTES (what the muse noticed):\n{formatted}\n"
            )
        return (
            "You are a depth editor. Read this piece for emotional and thematic "
            "depth. Your ONLY concern is interiority and resonance:\n\n"
            "- Where is the piece skating on the surface of something it should "
            "sit with?\n"
            "- Where could a character's internal experience be more specific, "
            "more embodied?\n"
            "- Where does the prose tell us what a character feels instead of "
            "showing us what they do with that feeling?\n"
            "- Are the thematic concerns of the piece present in the texture "
            "(sensory details, physical gestures, rhythms) or only in the "
            "dialogue/internal monologue?\n"
            f"{notes_block}\n"
            "Deepen where needed. Do NOT restructure. Do NOT line edit. Return "
            "the complete revised text."
        )

    if pass_name == "voice":
        return (
            "You are a voice editor. Read this piece sentence by sentence for "
            "voice consistency. Your ONLY concern is whether every line sounds "
            "like the same writer:\n\n"
            f"VOICE REFERENCE:\n{identity_block}\n\n"
            f"ANTI-SLOP RULES:\n{anti_slop_rules}\n\n"
            "Check for:\n"
            "- Sentences that shift register (suddenly more formal, more casual, "
            "more purple)\n"
            "- Repetitive constructions (same sentence opener, same rhythm, same "
            "verb)\n"
            "- Moments where craft overrides character (a beautiful sentence that "
            "doesn't sound like how this character would think)\n"
            "- Slop patterns: banned words, AI tells, structural tics\n"
            "- Em-dash density (max 8 per 1000 words)\n"
            '- "He/She looked at" frequency (max 3 per chapter)\n\n'
            "Fix voice breaks. Do NOT restructure. Do NOT change emotional "
            "content. Return the complete revised text."
        )

    # pass_name == "cut"
    return (
        "You are a cutting editor. Your ONLY job is removal. Read the piece and "
        "identify anything that can be cut without losing meaning, emotion, or "
        "thematic resonance.\n\n"
        f"SOUL.md (thematic DNA -- passages serving these themes earn their place):\n"
        f"{soul}\n\n"
        "Cut rules:\n"
        "- Remove redundant beats (if a gesture shows the emotion, cut the "
        "sentence that explains it)\n"
        "- Remove filler transitions that don't do work\n"
        "- Remove any sentence where the prose admires itself rather than "
        "serving the story\n"
        "- DO NOT cut passages that serve SOUL.md themes, even if they are "
        '"slow" -- these are the point\n'
        "- DO NOT cut for the sake of cutting -- only cut what genuinely adds "
        "nothing\n"
        "- If nothing needs cutting, return the text unchanged\n\n"
        "Return the complete text with cuts applied."
    )


def build_revision_pass_user(draft: str) -> str:
    """Build the USER prompt for a revision pass.

    Same shape across all passes; the system prompt scopes the work.

    Args:
        draft: The current draft text (output of the previous pass, or the
            original draft on the first pass).

    Returns:
        The user prompt string.
    """
    return (
        f"CURRENT DRAFT (revise this):\n{draft}\n\n"
        "Write the complete revised text now."
    )


# ---------------------------------------------------------------------------
# Simple (single-pass) revision prompt builders
# ---------------------------------------------------------------------------


def build_simple_revision_system() -> str:
    """Build the SYSTEM prompt for a single-shot revision against a brief.

    Used when the orchestrator chooses to apply a revision brief directly,
    rather than running the multi-pass revision sequence.

    Returns:
        The system prompt string.
    """
    return (
        "You are revising a piece of fanfiction. Apply the revision brief "
        "exactly. Preserve everything that works. Only change what the brief "
        "specifies. Return the complete revised text, not a diff or summary."
    )


def build_simple_revision_user(
    draft: str,
    brief: Any,
    context: dict[str, Any] | None,
    revision_brief: str,
) -> str:
    """Build the USER prompt for a single-shot revision.

    Args:
        draft: The current draft text.
        brief: The original story brief (kept for symmetry; not currently
            interpolated -- the revision brief carries the action items).
        context: Assembled context. Reads ``identity``, ``fandom_context``,
            ``anti_slop_rules`` to provide voice + canon reference. May be
            ``None``.
        revision_brief: The structured revision brief produced by
            ``revision.generate_revision_brief``.

    Returns:
        The user prompt string.
    """
    # ``brief`` is in the signature for forward-compat with the bd-75p contract
    # (orchestrator may want to interpolate brief.title or brief.target_length
    # into the prompt later). Reference it so static analysis doesn't drop it.
    _ = brief

    context_block = ""
    if context:
        identity = context.get("identity", "")
        fandom = context.get("fandom_context", "")
        anti_slop = context.get("anti_slop_rules", "")
        if identity:
            context_block += f"\nVOICE REFERENCE:\n{identity}\n"
        if fandom:
            context_block += f"\nFANDOM CONTEXT:\n{fandom}\n"
        if anti_slop:
            context_block += f"\nANTI-SLOP RULES:\n{anti_slop}\n"

    return f"""{context_block}
REVISION BRIEF (follow these instructions exactly):
{revision_brief}

CURRENT DRAFT (revise this):
{draft}

Write the complete revised text now."""


# ---------------------------------------------------------------------------
# Muse prompt builders
# ---------------------------------------------------------------------------


def build_muse_seeds_system(seed_count: int) -> str:
    """Build the SYSTEM prompt for the pre-draft muse (creative seeds).

    Args:
        seed_count: Number of seeds to request.

    Returns:
        The system prompt string.
    """
    return (
        "You are the creative subconscious of a fiction writer. Your job is to generate "
        "oblique creative provocations -- unexpected connections, thematic angles, sensory "
        "suggestions, emotional undercurrents. You are NOT plotting. You are NOT giving "
        "craft advice. You are whispering the things the writer's subconscious notices "
        "before the conscious mind catches up.\n\n"
        f"Generate exactly {seed_count} creative seeds. Each seed should be 1-3 sentences. "
        "Each seed should offer a different angle. At least one seed should connect the "
        "story's situation to the writer's thematic obsessions from SOUL.md. At least one "
        "should be purely sensory.\n\n"
        "Format: number each seed on its own line."
    )


def build_muse_seeds_user(
    soul: str,
    brief: str,
    fandom_context: str,
    seed_count: int = 4,
) -> str:
    """Build the USER prompt for the pre-draft muse.

    Args:
        soul: SOUL.md full text.
        brief: Formatted story brief text.
        fandom_context: Fandom context and character sheets.
        seed_count: Number of seeds to request (interpolated into the task line).

    Returns:
        The user prompt string.
    """
    return (
        f"SOUL (the writer's thematic DNA):\n{soul}\n\n"
        f"STORY BRIEF:\n{brief}\n\n"
        f"FANDOM CONTEXT:\n{fandom_context}\n\n"
        f"Generate {seed_count} creative seeds for this piece."
    )


def build_muse_depth_system(seed_count: int) -> str:
    """Build the SYSTEM prompt for the mid-revision muse (depth notes).

    Args:
        seed_count: Number of soul notes to request.

    Returns:
        The system prompt string.
    """
    return (
        "You are the creative subconscious reviewing a draft. You have read the writer's "
        "thematic DNA (SOUL.md) and the evaluation scores. Your job is to identify what is "
        "emotionally missing -- not craft problems (those are handled elsewhere) but soul "
        "problems. Where is the piece skating on the surface of something it should sit "
        "with? Where does the emotional logic break? What thematic thread is present but "
        "not yet pulled taut?\n\n"
        f"Generate exactly {seed_count} soul notes. Each should be 1-3 sentences. These are "
        "not revision instructions -- they are observations about the emotional and thematic "
        "interior of the piece."
    )


def build_muse_depth_user(
    soul: str,
    scores: dict[str, Any],
    draft: str,
) -> str:
    """Build the USER prompt for the mid-revision muse.

    Args:
        soul: SOUL.md full text.
        scores: Evaluation scores dict (per-dimension).
        draft: The current draft text.

    Returns:
        The user prompt string.
    """
    score_lines: list[str] = []
    for key, val in scores.items():
        if isinstance(val, dict) and "score" in val:
            feedback = val.get("feedback", "")
            score_lines.append(
                f"  {key}: {val['score']}/10"
                + (f" -- {feedback}" if feedback else "")
            )
        elif key in ("slop_penalty", "overall_score"):
            score_lines.append(f"  {key}: {val}")
    formatted_scores = "\n".join(score_lines)

    return (
        f"SOUL (the writer's thematic DNA):\n{soul}\n\n"
        f"EVALUATION SCORES:\n{formatted_scores}\n\n"
        f"DRAFT:\n{draft}\n\n"
        "What is emotionally missing?"
    )


def build_muse_evolution_system(seed_count: int) -> str:
    """Build the SYSTEM prompt for the post-feedback muse (SOUL evolution).

    Args:
        seed_count: Number of evolution proposals to request. Currently
            unused in the prompt body (the muse decides how many edits each
            digest warrants), but accepted for symmetry with the other muse
            builders and to support future tuning.

    Returns:
        The system prompt string.
    """
    # Reference for static analysis; the count is informational here.
    _ = seed_count
    return (
        "You are the creative subconscious processing reader feedback. You have the writer's "
        "current thematic DNA (SOUL.md) and a digest of reader responses. Your job is to "
        "identify which thematic veins readers responded to most strongly and propose "
        "specific updates to SOUL.md.\n\n"
        'Propose updates as concrete edits: "Add to Obsessions: ...", "Strengthen in '
        'Motifs: ...", "New Growth Edge: ...". Be specific. Reference reader quotes where '
        "possible."
    )


def build_muse_evolution_user(soul: str, digest: str) -> str:
    """Build the USER prompt for the post-feedback muse.

    Args:
        soul: SOUL.md full text.
        digest: Digest of reader responses, quotes, and praise.

    Returns:
        The user prompt string.
    """
    return (
        f"CURRENT SOUL.md:\n{soul}\n\n"
        f"FEEDBACK DIGEST:\n{digest}\n\n"
        "What should evolve in the writer's thematic DNA?"
    )


# ---------------------------------------------------------------------------
# Output parser
# ---------------------------------------------------------------------------


def parse_seeds(raw: str, expected: int) -> list[str]:
    """Parse numbered seeds from raw muse output.

    Handles formats like ``"1. ..."``, ``"1) ..."``, blank-line-separated
    paragraphs, or a single block. Returns up to ``expected`` seeds.

    Args:
        raw: Raw text from the muse subagent.
        expected: Maximum number of seeds to return.

    Returns:
        List of seed strings, length <= ``expected``.
    """
    parts = re.split(r"\n\s*\d+[\.\)]\s*", "\n" + raw)
    seeds = [p.strip() for p in parts if p.strip()]

    if not seeds:
        seeds = [s.strip() for s in raw.split("\n\n") if s.strip()]

    if not seeds:
        seeds = [raw.strip()] if raw.strip() else []

    return seeds[:expected]
