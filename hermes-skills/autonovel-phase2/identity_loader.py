"""Identity loader for autonovel-phase2.

Replaces Phase 1 runner.py's inline ``_load_identity_context`` with a
reusable helper. Per spec bd-b5p.5 §3.3 (OQ-2 resolution): identity
files are loaded via ``Path.read_text`` directly (the Hermes skill
loader prepends a "The user has invoked the {skill_name} skill"
attribution preamble that would contaminate the voice context the
model sees, so we bypass it).

Returns the same ``context`` dict shape that
``write.prompts.build_draft_system`` and ``build_draft_user`` consume,
plus a ``few_shot_bank`` key carrying the raw bank text so
``anchor_selector`` can parse it (no blind 3K-char trim).

Bead: bd-b5p.5
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Hardcoded Phase 2 brief (same as Phase 1 for direct A/B comparison)
# ---------------------------------------------------------------------------

PHASE2_BRIEF_TEXT = """\
Post-Act 3, post-elven-ritual. Astarion and Karlach are at an inn somewhere
outside Baldur's Gate. It is the kind of summer night where the windows
have been left open and the moths keep finding the lamp. They share the
garden bench. Neither of them is good at sitting still with something
that isn't a threat.

POV: Karlach, close third-person, past tense.
Length: one paragraph (3-5 sentences). No section break. No epigraph.

Constraint: Karlach's engine is quiet for once. Astarion is awake. They
are not talking about anything important. The paragraph is the silence
between two people who have spent a year expecting to die.
"""

PHASE2_FANDOM_CONTEXT = """\
Baldur's Gate 3 (Larian, 2023). Karlach Cliffgate: tiefling barbarian,
infernal engine in her chest, ten years in Avernus as Zariel's enforcer,
freed in Act 1, the engine kept her alive but is killing her. Direct,
loud, generous, terrified of being alone, gets blackout-furious. Calls
people "soldier".

Astarion Ancunin: pale elf rogue, two-hundred-year vampire spawn of
Cazador, freed in Act 1. Sharp-tongued, vain, deflects with theatrics,
underneath it is a survivor who never expected to live past the next
hour. After the ritual (Cazador dead, Astarion not Ascended), still
vampire spawn, still can't be in sunlight. Performs disdain. Means
about half of it.

Post-Act 3 setting: the Heroes of Baldur's Gate have just saved the
city. Both characters are alive in the canonical "good" ending. The
Netherbrain is dead. Karlach is on borrowed weeks before the engine
gives out (unless she goes to Avernus, choice unresolved here). They
are processing surviving.
"""

# Minimal anti-slop block (matches Phase 1 runner.py's shape).
_ANTI_SLOP_RULES = (
    "Do not use these words: delve, utilize, leverage, facilitate, "
    "elucidate, tapestry, paradigm, synergy, holistic, myriad, plethora. "
    "Do not use rhetorical formulas like 'It wasn't X, it was Y'. "
    "Vary sentence length. No more than 8 em-dashes per 1000 words. "
    "No section breaks (---) as rhythm crutches."
)

# Default brief metadata for Phase 2's hardcoded brief (Phase 3 reads briefs/*.json).
PHASE2_BRIEF_META = {
    "pov_character": "Karlach",
    "title": "Garden Bench",
    "fandom": "Baldur's Gate 3 (Video Game)",
    "tags": [
        "Karlach (Baldur's Gate)",
        "Astarion (Baldur's Gate)",
        "Post-Canon",
        "Character Study",
        "Hurt/Comfort",
    ],
}


def _read_text(path: Path) -> str:
    """Read a file as UTF-8, returning empty string on missing/permission.

    Mirrors Phase 1's tolerant read; the loader never fails on a missing
    identity file (we just produce a leaner context).
    """
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return ""


def _default_autonovel_root() -> Path:
    """Compute the autonovel repo root.

    Resolution order:
      1. ``AUTONOVEL_ROOT`` environment variable, if set.
      2. The repo root inferred from this module's file path (works when
         the file lives under hermes-skills/autonovel-phase2/).
      3. Fall back to the canonical /home/ubuntu/explore/autonovel path
         Phase 1 hardcodes.
    """
    env = os.environ.get("AUTONOVEL_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    # .../autonovel/hermes-skills/autonovel-phase2/identity_loader.py
    #  -> parents[2] == .../autonovel
    candidate = here.parents[2] if len(here.parents) >= 3 else None
    if candidate and (candidate / "identity" / "self.md").exists():
        return candidate
    return Path("/home/ubuntu/explore/autonovel")


def load_identity(root: Path | None = None) -> dict[str, str]:
    """Load autonovel identity files into a context dict.

    Spec contract (bd-b5p.5 §3.3, T-D-4): all files are read via
    ``Path.read_text(encoding="utf-8")`` directly — the Hermes skill
    loader is bypassed so its attribution preamble does not contaminate
    the voice context. The returned dict's keys match what
    ``write.prompts.build_draft_system`` /
    ``write.prompts.build_draft_user`` expect, plus extras the Phase 2
    pipeline needs (raw ``few_shot_bank`` text, ``soul`` text, brief
    metadata).

    Args:
        root: Autonovel repo root. Defaults to ``_default_autonovel_root()``.

    Returns:
        Dict with keys:
          - ``identity``: combined identity block (self.md + voice_priors)
          - ``anti_slop_rules``: anti-slop ruleset for the prompt frame
          - ``brief_text``: the Phase 2 hardcoded brief
          - ``fandom_context``: BG3 character context
          - ``few_shot_bank``: raw text of identity/few_shot_bank.md
          - ``soul``: identity/soul.md text (may be empty)
          - ``pov_character``: brief POV for anchor selection
          - ``brief_meta_json``: JSON-serialised brief metadata
    """
    base = root if root is not None else _default_autonovel_root()
    identity_dir = base / "identity"

    self_md = _read_text(identity_dir / "self.md")
    few_shot_bank = _read_text(identity_dir / "few_shot_bank.md")
    soul_md = _read_text(identity_dir / "soul.md")

    voice_priors_path = identity_dir / "voice_priors.json"
    voice_priors_text = ""
    if voice_priors_path.exists():
        try:
            vp = json.loads(voice_priors_path.read_text(encoding="utf-8"))
            voice_priors_text = "\nVOICE PRIORS (autonovel):\n" + json.dumps(
                vp, indent=2
            )
        except json.JSONDecodeError:
            voice_priors_text = ""

    # Combine self.md + voice_priors into the identity block. The
    # few_shot bank stays OUT of this combined block; the parent skill
    # body slots POV-selected anchors back in after anchor_selector
    # runs (see runner.run_phase2).
    identity_block = self_md
    if voice_priors_text:
        identity_block = identity_block + "\n" + voice_priors_text

    return {
        "identity": identity_block,
        "anti_slop_rules": _ANTI_SLOP_RULES,
        "brief_text": PHASE2_BRIEF_TEXT,
        "fandom_context": PHASE2_FANDOM_CONTEXT,
        "few_shot_bank": few_shot_bank,
        "soul": soul_md,
        "pov_character": PHASE2_BRIEF_META["pov_character"],
        "brief_meta_json": json.dumps(PHASE2_BRIEF_META),
    }
