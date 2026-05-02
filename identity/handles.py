"""Self-recognition guard for the heartbeat / mail loop.

Spec bd-49j Section 3.2 + 4.5. Prevents the loop from treating Maren's
own AO3 replies as new fanmail (the 2026-04-26 incident, in which
``maren_eurynome``'s reply to TheIcyQueen was nearly drafted as if it
were fresh inbound mail).

Public surface:

- :data:`_PATH` -- module-level constant pointing at ``handles.json``.
  Tests monkeypatch this to redirect reads to a tmp file.
- :func:`is_self` -- predicate ``author -> bool`` answering "is this
  author one of our own handles?"

Design notes:

- ``is_self`` reads ``handles.json`` on every call. Hand-edits to the
  file (the only sanctioned way to add a handle, per spec) are picked
  up immediately on the next call -- no stale-cache foot-guns.
- Comparisons against ``ao3_handles`` are case-sensitive. AO3 usernames
  are case-sensitive in the API; loosening this would let an attacker
  spoof the pen name with a casing variant.
- Only ``ao3_handles`` is consulted. ``display_names`` is descriptive
  metadata, not an identity check -- a reader could legitimately set
  their AO3 handle to "Maren Solaire" and we must not treat them as
  self.
- This module imports nothing from ``identity/`` -- it is foundational
  and other identity files may import it, but it imports none of them.
"""

from __future__ import annotations

import json
from pathlib import Path

# Path to the handles data file. Tests monkeypatch this to redirect
# reads to a tmp_path; production code reads the file shipped in
# ``identity/handles.json``.
_PATH = Path(__file__).resolve().parent / "handles.json"


def _load_handles() -> dict:
    """Read and parse ``handles.json`` from :data:`_PATH`.

    Raises:
        FileNotFoundError: if the file is absent. Surfacing this loudly
            is intentional -- a missing file would otherwise silently
            treat everyone as not-self, re-opening the 2026-04-26
            incident.
        json.JSONDecodeError: if the file is malformed. Hand-editing is
            the supported workflow; corrupted JSON must fail fast so the
            operator notices.
    """
    with open(_PATH, encoding="utf-8") as f:
        return json.load(f)


def is_self(author: str | None) -> bool:
    """Return True iff ``author`` is one of our own AO3 handles.

    Args:
        author: An AO3 username, or ``None`` / empty string for guest /
            deleted-user comments.

    Returns:
        True if ``author`` matches an entry in ``ao3_handles`` exactly
        (case-sensitive). False for ``None``, empty string, unknown
        handles, or casing variants of a known handle.

    Raises:
        FileNotFoundError: if ``handles.json`` is missing.
        json.JSONDecodeError: if ``handles.json`` is malformed.
    """
    if not author:
        return False

    data = _load_handles()
    ao3_handles = data.get("ao3_handles", [])
    return author in ao3_handles
