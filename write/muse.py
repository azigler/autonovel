"""Muse system -- documentation stub.

The muse used to live here as three direct-API callers
(``generate_creative_seeds``, ``generate_depth_notes``,
``generate_soul_evolution``). They were retired in the bd-75p migration.

The orchestrator (running ``/write`` or ``/learn``) now drives the muse
through in-harness subagents. The prompt content lives in
:mod:`write.prompts`:

* :func:`write.prompts.build_muse_seeds_system` /
  :func:`write.prompts.build_muse_seeds_user` -- pre-draft (creative seeds)
* :func:`write.prompts.build_muse_depth_system` /
  :func:`write.prompts.build_muse_depth_user` -- mid-revision (soul notes)
* :func:`write.prompts.build_muse_evolution_system` /
  :func:`write.prompts.build_muse_evolution_user` -- post-feedback (SOUL.md edits)

Output parsing lives there too: :func:`write.prompts.parse_seeds`.

This file is intentionally near-empty -- removing it outright would break
import-time references in legacy briefs / configs that mention
``write.muse``. The shim re-exports :func:`parse_seeds` so any caller
still doing ``from write.muse import parse_seeds`` continues to work.
"""

from __future__ import annotations

from write.prompts import parse_seeds

__all__ = ["parse_seeds"]
