"""POV-aware voice-anchor selector for autonovel-phase2.

Spec bd-b5p.5 §3.4 + §4.3: parse ``identity/few_shot_bank.md`` into
entries (split on ``^## Entry``), match each entry's ``**POV:**`` line
case-insensitively against the brief's POV character. Cap at
``max_anchors``. If zero entries match, fall back to the
most-recently-dated entries by ``**Source:**`` date.

This replaces Phase 1's ``few_shot_bank[:3000]`` blind trim with a
structured selector that gives the prompt POV-appropriate exemplars.

Bead: bd-b5p.5
"""

from __future__ import annotations

import re
from datetime import date

# Header that starts each entry. Multi-line; anchored at start-of-line.
_ENTRY_SPLIT = re.compile(r"^## Entry\b", flags=re.MULTILINE)

# Per-entry POV extractor. Bank shape: ``**POV:** Karlach (with Dammon...)``.
_POV_LINE = re.compile(r"^\*\*POV:\*\*\s*(.+)$", flags=re.MULTILINE)

# Per-entry Source extractor. We want the embedded date (YYYY-MM-DD) for
# the fallback "most-recently-dated entries" path.
_SOURCE_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _parse_entries(bank_text: str) -> list[str]:
    """Split the bank text into individual entry blocks.

    The leading section before "## Entry 001" (the bank's own preamble)
    is discarded. Each returned block is the raw markdown for one entry,
    starting at "## Entry N" through to the next entry or EOF.
    """
    if not bank_text or not bank_text.strip():
        return []
    parts = _ENTRY_SPLIT.split(bank_text)
    # parts[0] is the bank preamble (no Entry header). Skip it.
    entries: list[str] = []
    for part in parts[1:]:
        # Re-attach the "## Entry" header the split stripped, so the
        # returned block is a self-contained markdown chunk.
        entries.append("## Entry" + part.rstrip() + "\n")
    return entries


def _entry_pov(entry: str) -> str:
    """Return the entry's POV line value (empty string if not found)."""
    match = _POV_LINE.search(entry)
    return match.group(1).strip() if match else ""


def _entry_date(entry: str) -> date | None:
    """Extract the latest YYYY-MM-DD from the entry's first 1000 chars.

    The Source line is at the top of each entry. We look there for the
    publication/draft date to drive the fallback sort.
    """
    # Search just the head of the entry to avoid grabbing dates from
    # the body of long passages.
    head = entry[:1000]
    matches = _SOURCE_DATE.findall(head)
    if not matches:
        return None
    # Convert the first match (Source line is the earliest date in the
    # head) to a date object.
    y, m, d = matches[0]
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def select_anchors(
    bank_text: str,
    pov_character: str,
    max_anchors: int = 2,
) -> list[str]:
    """Select up to ``max_anchors`` voice-anchor entry blocks.

    Matching rule (spec §3.4):
      1. Parse entries via the ``## Entry`` header split.
      2. Extract each entry's ``**POV:**`` line.
      3. Keep entries whose POV value case-insensitively contains
         ``pov_character`` (substring match — "Karlach" matches
         "Karlach (with Dammon in dialogue)").
      4. Cap the list at ``max_anchors``, in entry order.
      5. Fallback: if zero entries match, return up to ``max_anchors``
         most-recently-dated entries by the **Source:** date.
      6. If the bank text is empty, return ``[]`` (no fallback).

    Args:
        bank_text: Raw markdown of identity/few_shot_bank.md.
        pov_character: First name of the brief's POV character.
        max_anchors: Cap on returned entries. Default 2 per spec §3.4.

    Returns:
        List of raw entry-block markdown strings, length <= max_anchors.
    """
    entries = _parse_entries(bank_text)
    if not entries:
        return []

    needle = (pov_character or "").strip().lower()

    matched: list[str] = []
    if needle:
        for entry in entries:
            pov = _entry_pov(entry).lower()
            if needle in pov:
                matched.append(entry)
                if len(matched) >= max_anchors:
                    break

    if matched:
        return matched

    # Fallback: most-recently-dated entries. Stable sort so entries with
    # identical (or missing) dates preserve their bank order.
    dated = [(idx, _entry_date(e), e) for idx, e in enumerate(entries)]
    # Entries without a date sort to the end (treat as the epoch).
    dated.sort(
        key=lambda triple: (
            triple[1] is None,
            -(triple[1].toordinal() if triple[1] else 0),
            triple[0],
        )
    )
    return [e for _, _, e in dated[:max_anchors]]
