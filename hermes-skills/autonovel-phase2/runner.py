"""autonovel-phase2 helpers (library-only — NOT invokable standalone).

Pure-Python helpers for the Phase 2 agent-recipe. **This module is a
library, not an executable.** The ``autonovel-phase2`` SKILL drives a
Hermes parent agent to call these helpers via ``execute_code`` inside
its own conversation turn; the parent agent emits ``delegate_task`` as
its own tool (NOT from this module — ``delegate_task`` strictly
requires the in-process AIAgent parent context per
``run_agent.py:_dispatch_delegate_task`` injecting ``parent_agent=self``).

Bead: bd-b5p.5.6 (rewrite per bd-b5p.5.5 Pattern 5 research)
Parent epic: bd-b5p · Spec: bd-b5p.5 · Predecessor: bd-b5p.4 (Phase 1)

Exported helpers (all pure string / JSON manipulation, no side effects):

* ``_wrap_prompt(system, user)`` — builds the ``_PROSE_FRAME``-wrapped
  goal string via ``write.prompts.wrap_for_subagent``. The Phase 2
  SKILL recipe invokes this from an ``execute_code`` snippet in Step 2
  and passes the return value to its own ``delegate_task`` tool call
  in Step 3.

* ``_check_preamble(prose)`` — raises ``ValueError`` if the first 100
  chars of prose look like LLM preamble (T-D-3 / OQ-3 contingency
  gate). The SKILL recipe invokes this from an ``execute_code`` snippet
  in Step 4 against the prose extracted from the delegate result.

* ``_extract_summary(result_json)`` — parses the JSON-string Hermes'
  ``delegate_task`` returns and surfaces ``results[0].summary``. Raises
  on malformed shapes so the recipe fails loud rather than silently
  enqueuing empty prose (spec EDGE 7 + EDGE 8).

Companion modules (also library-only, unchanged):

* ``staging.stage_draft`` — builds ``PublishRequest`` + ``api.queue.enqueue``
* ``voice_match.voice_match_score`` / ``passes_voice_gate`` — heuristic gate
* ``anchor_selector.select_anchors`` — POV-aware few-shot selector
* ``identity_loader.load_identity`` — direct-read identity bundle

There is no ``run_phase2()`` and no CLI entry point. The historical
``runner.py`` was an executable pipeline; bd-b5p.5.5 research
(``research-phase2-invocation.md``) proved standalone invocation
cannot work because ``delegate_task`` requires the live AIAgent
``parent_agent`` and there is no env-var / re-lookup path. Pattern 5
moves orchestration into the SKILL.md recipe and leaves only the
helpers below.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Prompt assembly via write.prompts (Phase 1's contract — unchanged)
# ---------------------------------------------------------------------------


_PREAMBLE_PATTERNS = (
    "Here is",
    "Here's",
    "I'll",
    "Sure,",
    "The following",
    "Below is",
    "Certainly,",
    "Of course",
    "As an AI",
)


def _add_autonovel_to_path() -> Path:
    """Ensure the autonovel repo root is importable for write.prompts / evaluate.

    Returns the resolved root path. This module lives at
    ``autonovel/hermes-skills/autonovel-phase2/runner.py``; the repo
    root is two parents up from ``Path(__file__).resolve().parent``.
    """
    here = Path(__file__).resolve()
    # parents[1] == hermes-skills, parents[2] == autonovel
    root = here.parents[2]
    if not (root / "write" / "prompts.py").exists():
        # Fallback: env-override or canonical pi.dev path.
        env = os.environ.get("AUTONOVEL_ROOT")
        root = Path(env) if env else Path("/home/ubuntu/explore/autonovel")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def _wrap_prompt(system: str, user: str) -> str:
    """Build the ``_PROSE_FRAME``-wrapped goal string.

    Imports ``write.prompts.wrap_for_subagent`` lazily so the runner
    module stays importable from environments where the autonovel root
    hasn't been pushed onto ``sys.path`` yet (e.g., a bare ``pytest``
    invocation from a different cwd).

    Called by the SKILL.md Step 2 ``execute_code`` snippet — the parent
    agent passes the return value as ``goal=`` to its own ``delegate_task``
    tool call in Step 3.
    """
    _add_autonovel_to_path()
    from write.prompts import (
        wrap_for_subagent,  # type: ignore[import-not-found]
    )

    return wrap_for_subagent(system, user)


def _check_preamble(prose: str) -> None:
    """Raise ValueError if the first 100 chars of prose look like preamble.

    Per spec §5 T-D-3 + OQ-3 contingency: if the child slipped a
    "Here is the paragraph:" line past the ``_PROSE_FRAME`` contract,
    we want to fail loud so staging skips the enqueue.

    Called by the SKILL.md Step 4 ``execute_code`` snippet against the
    prose extracted from the delegate result.
    """
    head = prose[:100]
    for pattern in _PREAMBLE_PATTERNS:
        if head.startswith(pattern):
            raise ValueError(
                f"_check_preamble: preamble leakage detected — first 100 "
                f"chars start with {pattern!r}: {head!r}. Failing per "
                f"spec bd-b5p.5 T-D-3 / OQ-3 contingency."
            )


def _extract_summary(result_json: str) -> str:
    """Parse the delegate_task return value and pull the child's summary.

    Hermes' ``delegate_task`` returns a JSON string of the shape
    ``{"results": [{"summary": "...", "child_session_id": "..."}]}``.
    Empty / malformed responses raise so the caller fails loud rather
    than silently produces empty prose (per spec EDGE 7 + EDGE 8).

    Called by the SKILL.md Step 4 ``execute_code`` snippet on the JSON
    string returned by the parent agent's ``delegate_task`` tool call in
    Step 3.
    """
    if not isinstance(result_json, str):
        raise ValueError(
            f"delegate_task must return a JSON string, got {type(result_json)!r}"
        )
    try:
        parsed = json.loads(result_json)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"delegate_task returned non-JSON: {result_json[:200]!r}"
        ) from e
    results = parsed.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError(f"delegate_task returned no results: {parsed!r}")
    summary = results[0].get("summary")
    if not summary:
        raise ValueError(
            f"delegate_task returned empty summary: {results[0]!r}"
        )
    return summary
