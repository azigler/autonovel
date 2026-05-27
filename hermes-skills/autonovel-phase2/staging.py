"""AO3 staging for autonovel-phase2.

Spec bd-b5p.5 §3.6 + §4.5: after slop_gate passes, construct a
``PublishRequest`` from the generated prose + brief metadata and call
``api.queue.enqueue`` to land it at ``publish_queue/<queue_id>.json``
with ``status=PENDING``. The live AO3 POST is explicitly out of scope
(Phase 3 work) — this module never imports the live-POST client and
never references the AO3 website URL.

Bead: bd-b5p.5
"""

from __future__ import annotations

from datetime import UTC, datetime

from api.models import PublishRequest, QueueItem, Rating
from api.queue import enqueue

# Production slop threshold per spec §4.6. Phase 1 used a relaxed 5.0
# while validating the pipeline; Phase 2 ships at the canonical 3.0.
SLOP_THRESHOLD = 3.0

# AO3 summary field hard limit (server-side validation rejects longer).
SUMMARY_MAX = 250

# Hardcoded brief metadata for the Phase 2 same-as-Phase-1 brief. Phase
# 3 reads briefs/<slug>.json (deferred per OQ-6).
PHASE2_TITLE = "Garden Bench"
PHASE2_FANDOM = "Baldur's Gate 3 (Video Game)"
PHASE2_RATING = Rating.GENERAL
PHASE2_TAGS = (
    "Karlach (Baldur's Gate)",
    "Astarion (Baldur's Gate)",
    "Post-Canon",
    "Character Study",
    "Hurt/Comfort",
)

# Bead ID is load-bearing in author_notes (T-A-3): the operator's
# rollback recipe greps for it across publish_queue/*.json.
_BEAD_ID = "bd-b5p.5"


def _build_summary(prose: str) -> str:
    """Derive AO3 summary from prose per spec §3.6.

    Rule: ``prose.split(".")[0].strip()[:250]``. The first-sentence
    extraction is intentionally simple — a more sophisticated
    sentence-boundary detector would be over-engineered for a
    summary field whose purpose is a teaser line on the AO3 work page.
    """
    first = prose.split(".")[0].strip()
    return first[:SUMMARY_MAX]


def _build_author_notes(
    *,
    slop_penalty: float,
    voice_match: float,
    model: str = "qwen3-coder:30b",
    base_url: str = "",
) -> str:
    """Build the HTML-comment-wrapped metadata block for author_notes.

    Per spec §3.6 T-A-3: must contain the bead ID, the numeric
    slop_penalty, and the numeric voice_match_score, wrapped in
    ``<!-- ... -->`` so it doesn't render on AO3.
    """
    ts = datetime.now(UTC).isoformat()
    return (
        "<!-- autonovel-phase2 metadata\n"
        f"bead: {_BEAD_ID}\n"
        f"model: {model}\n"
        f"base_url: {base_url}\n"
        f"slop_penalty: {slop_penalty}\n"
        f"voice_match_score: {voice_match}\n"
        f"ts: {ts}\n"
        "-->"
    )


def stage_draft(
    prose: str,
    *,
    slop_penalty: float,
    voice_match_score: float,
    model: str = "qwen3-coder:30b",
    base_url: str = "",
    title: str = PHASE2_TITLE,
    fandom: str = PHASE2_FANDOM,
    rating: Rating = PHASE2_RATING,
    tags: list[str] | None = None,
) -> QueueItem | None:
    """Stage a Phase 2 draft to ``publish_queue/<id>.json``.

    Spec §3.6 contract:
      - PASS path: slop_penalty < SLOP_THRESHOLD (3.0). Build
        PublishRequest, call api.queue.enqueue, return the QueueItem.
      - FAIL path: slop_penalty >= 3.0 OR prose is empty. Return None
        (no file is written; the slop gate is the firewall protecting
        publish_queue/ from polluted drafts).
      - voice_match_score is recorded in author_notes but is ADVISORY
        in Phase 2 (does NOT block enqueue per spec §3.5).

    Args:
        prose: The generated paragraph (verbatim; no footer).
        slop_penalty: evaluate.py slop_score's penalty (numeric).
        voice_match_score: voice_match.voice_match_score (numeric).
        model: Model identifier for the metadata block.
        base_url: LLM endpoint URL for the metadata block.
        title: AO3 title (defaults to PHASE2_TITLE).
        fandom: AO3 canonical fandom string.
        rating: AO3 Rating enum.
        tags: Override tag list; defaults to PHASE2_TAGS.

    Returns:
        QueueItem on PASS, None on FAIL. Either way, never raises on
        gate failure (so the runner can emit a single-line summary).
    """
    # Slop firewall — failing prose must not land in the human review
    # queue. Empty prose hits the same gate (body would fail AO3 POST
    # server-side anyway, per EDGE 1).
    if not prose or not prose.strip():
        return None
    if slop_penalty >= SLOP_THRESHOLD:
        return None

    request = PublishRequest(
        title=title,
        fandom=fandom,
        rating=rating,
        tags=list(tags) if tags is not None else list(PHASE2_TAGS),
        summary=_build_summary(prose),
        body=prose,
        author_notes=_build_author_notes(
            slop_penalty=slop_penalty,
            voice_match=voice_match_score,
            model=model,
            base_url=base_url,
        ),
    )
    return enqueue(request)
