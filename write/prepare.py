"""Post preparation for AO3 publishing.

Converts markdown to AO3 HTML, generates tags, summary, and author's notes.
Packages everything into a PublishRequest for the API proxy.
"""

from __future__ import annotations

import re
from typing import Any

from api.models import PublishRequest, Rating
from write.brief import StoryBrief

# Import slop_score for metadata quality checks
try:
    from evaluate import slop_score
except ImportError:

    def slop_score(text: str) -> dict:  # type: ignore[misc]
        return {"slop_penalty": 0.0}


SUMMARY_SLOP_THRESHOLD = 2.0
MAX_SUMMARY_ATTEMPTS = 3


def format_ao3_html(markdown_text: str) -> str:
    """Convert markdown to AO3-compatible HTML.

    Handles: paragraphs, italics, bold, horizontal rules, blockquotes.
    """
    text = markdown_text.strip()

    # Split into paragraphs by double newlines
    paragraphs = re.split(r"\n{2,}", text)

    html_parts: list[str] = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Horizontal rule: --- (or more dashes) on its own
        if re.fullmatch(r"-{3,}", para):
            html_parts.append("<hr />")
            continue

        # Handle blockquotes
        if para.startswith(">"):
            bq_lines = []
            for line in para.split("\n"):
                bq_lines.append(re.sub(r"^>\s?", "", line))
            bq_text = " ".join(bq_lines)
            bq_text = _inline_formatting(bq_text)
            html_parts.append(f"<blockquote>{bq_text}</blockquote>")
            continue

        # Regular paragraph
        para_text = " ".join(para.split("\n"))
        para_text = _inline_formatting(para_text)
        html_parts.append(f"<p>{para_text}</p>")

    return "\n".join(html_parts)


def _inline_formatting(text: str) -> str:
    """Apply inline markdown formatting (bold, italics)."""
    # Bold: **text** -> <strong>text</strong>
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italics: *text* -> <em>text</em>
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    return text


def generate_tags(
    brief: StoryBrief,
    fandom_context: str = "",
) -> list[str]:
    """Generate AO3 tags from the story brief and fandom context.

    Uses an LLM stub that can be mocked in tests.
    """
    base_tags = generate_tags_from_llm(brief, fandom_context)
    return base_tags


def generate_tags_from_llm(
    brief: StoryBrief,
    fandom_context: str = "",
) -> list[str]:
    """LLM-based tag generation (stub).

    Will be replaced with real Claude API call.
    """
    tags = [brief.fandom]
    tags.extend(brief.characters)
    if brief.ship:
        tags.append(brief.ship)
    if brief.genre and brief.genre != "general":
        tags.append(brief.genre.title())
    tags.extend(brief.tags_hint)
    return tags


def generate_summary(
    draft_text: str,
    pen_name_voice: str,
    fandom: str,
) -> str:
    """Generate a hook-style summary under 500 chars.

    Retries up to 3 times if the summary fails slop check.
    """
    for _attempt in range(MAX_SUMMARY_ATTEMPTS):
        summary = generate_summary_text(
            draft_text=draft_text,
            pen_name_voice=pen_name_voice,
            fandom=fandom,
        )
        result = slop_score(summary)
        if result.get("slop_penalty", 0.0) < SUMMARY_SLOP_THRESHOLD:
            return summary

    # All attempts failed -- return last attempt with warning
    return summary  # type: ignore[possibly-undefined]


def generate_summary_text(
    draft_text: str,
    pen_name_voice: str,
    fandom: str,
) -> str:
    """LLM-based summary generation (stub).

    Will be replaced with real Claude API call.
    """
    # Default stub: extract first sentence
    sentences = re.split(r"[.!?]+", draft_text)
    first = sentences[0].strip() if sentences else "A story"
    return first[:497] + "..." if len(first) > 497 else first + "."


def generate_author_notes(
    draft_text: str,
    pen_name_voice: str,
    fandom: str,
) -> str:
    """Generate author's notes in the pen name's voice.

    Retries up to 3 times if notes fail slop check.
    """
    for _attempt in range(MAX_SUMMARY_ATTEMPTS):
        notes = generate_notes_text(
            draft_text=draft_text,
            pen_name_voice=pen_name_voice,
            fandom=fandom,
        )
        result = slop_score(notes)
        if result.get("slop_penalty", 0.0) < SUMMARY_SLOP_THRESHOLD:
            return notes

    return notes  # type: ignore[possibly-undefined]


def generate_notes_text(
    draft_text: str,
    pen_name_voice: str,
    fandom: str,
) -> str:
    """LLM-based author's notes generation (stub).

    Will be replaced with real Claude API call.
    """
    return "Hope you enjoy this one! Comments always welcome."


def prepare_publish_request(
    state: Any,
    identity: dict[str, Any],
) -> PublishRequest:
    """Package a completed draft into a PublishRequest for the API proxy.

    Args:
        state: WriteLoopState with draft and brief.
        identity: Identity context dict.

    Returns:
        A fully populated PublishRequest.
    """
    brief = state.brief
    draft_chapters = state.draft_chapters

    # Format body
    full_text = "\n\n---\n\n".join(draft_chapters)
    body = format_ao3_html(full_text)

    # Generate metadata
    pen_name_voice = identity.get("pen_name", "")
    fandom_context = identity.get("fandom_context", "")

    tags = generate_tags(brief=brief, fandom_context=fandom_context)
    summary = generate_summary(
        draft_text=full_text,
        pen_name_voice=pen_name_voice,
        fandom=brief.fandom,
    )
    author_notes = generate_author_notes(
        draft_text=full_text,
        pen_name_voice=pen_name_voice,
        fandom=brief.fandom,
    )

    title = brief.title or f"Untitled {brief.genre.title()} - {brief.fandom}"

    return PublishRequest(
        title=title,
        fandom=brief.fandom,
        rating=brief.rating
        if isinstance(brief.rating, Rating)
        else Rating.NOT_RATED,
        tags=tags,
        summary=summary,
        body=body,
        author_notes=author_notes,
    )
