"""autonovel-phase2 runner.

Phase 2 pipeline — Hermes-native ``delegate_task`` generation with
POV-aware voice anchors, staged to ``publish_queue/`` for AO3 review
(no live AO3 POST).

Bead: bd-b5p.5 · Parent epic: bd-b5p · Predecessor: bd-b5p.4 (Phase 1)

Two entry points:

* ``run_delegate(prompt=..., system=..., user=..., strict_preamble_check=...)``
  — wraps the prompt in the ``_PROSE_FRAME`` envelope (via
  ``write.prompts.wrap_for_subagent``) and calls Hermes'
  ``delegate_task``. Returns the child's raw prose. Raises on a
  malformed delegate response or detected preamble leakage.

* ``run_phase2()`` — the canonical Phase 2 pipeline. Loads identity,
  selects POV-appropriate voice anchors, runs ``run_delegate``, scores
  the prose with ``evaluate.slop_score`` + ``voice_match``, calls
  ``stage_draft``, returns the single-line summary
  (``slop_penalty=... voice_match=... queue_id=... status=PASS|FAIL``).

``delegate_task`` is imported at module level so tests can monkeypatch
it via the ``fake_delegate_task`` fixture per /test SKILL Step 3.5.
When Hermes isn't installed (test env, naked CLI), a sentinel stub
keeps the module importable; calling it without monkeypatching raises
a clear error.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# delegate_task import (module-level symbol for monkeypatch per /test §3.5)
# ---------------------------------------------------------------------------
#
# Production: imported from Hermes Agent (``tools.delegate_tool``). The
# `parent_agent` argument is required when invoked for real; this
# module is invoked from a parent-agent conversation turn that supplies
# it transparently. In test environments without Hermes, the spy fixture
# overrides this symbol entirely (`monkeypatch.setattr(runner,
# "delegate_task", _spy)`).
try:
    from tools.delegate_tool import (
        delegate_task,  # type: ignore[import-not-found]
    )
except ImportError:

    def delegate_task(**kwargs: Any) -> str:  # type: ignore[no-redef]
        """Stub: real delegate_task is unavailable in this environment.

        Tests monkeypatch this symbol via the ``fake_delegate_task``
        fixture. Calling it without monkeypatching raises a clear
        error so a forgotten patch doesn't silently produce garbage.
        """
        raise RuntimeError(
            "delegate_task not available — Hermes Agent's "
            "tools.delegate_tool is not importable. In production, "
            "the parent agent invokes this module with delegate_task "
            "wired through tools.delegate_tool; in tests, the "
            "fake_delegate_task fixture overrides this symbol."
        )


# ---------------------------------------------------------------------------
# Prompt assembly via write.prompts (unchanged from Phase 1's contract)
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


class _Brief:
    """Minimal stand-in for ``write.brief.StoryBrief``.

    ``build_draft_user`` only reads ``target_length``; the rest of the
    StoryBrief schema isn't needed for Phase 2's one-paragraph output.
    Phase 3 will swap this for the brief-file reader.
    """

    target_length = 120  # one paragraph, ~3-5 sentences in this voice


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
    we want to fail loud so staging.skip the enqueue. Phase 2 ships
    with this gate behind ``strict_preamble_check=True``; callers can
    opt out for diagnostic runs.
    """
    head = prose[:100]
    for pattern in _PREAMBLE_PATTERNS:
        if head.startswith(pattern):
            raise ValueError(
                f"run_delegate: preamble leakage detected — first 100 "
                f"chars start with {pattern!r}: {head!r}. Failing per "
                f"spec bd-b5p.5 T-D-3 / OQ-3 contingency."
            )


def _extract_summary(result_json: str) -> str:
    """Parse the delegate_task return value and pull the child's summary.

    Hermes' ``delegate_task`` returns a JSON string of the shape
    ``{"results": [{"summary": "...", "child_session_id": "..."}]}``.
    Empty / malformed responses raise so the caller fails loud rather
    than silently produces empty prose (per spec EDGE 7 + EDGE 8).
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


def run_delegate(
    prompt: str | None = None,
    *,
    system: str | None = None,
    user: str | None = None,
    strict_preamble_check: bool = False,
) -> str:
    """Invoke ``delegate_task`` with a ``_PROSE_FRAME``-wrapped goal.

    Two calling conventions:
      - ``run_delegate(prompt=already_wrapped)`` — the caller supplies a
        pre-wrapped goal string. Used in tests that don't need the
        full prompt-builder shape.
      - ``run_delegate(system=..., user=...)`` — the runner wraps the
        (system, user) pair via ``write.prompts.wrap_for_subagent``
        before passing it as ``goal=``. This is the production path
        called by ``run_phase2``.

    The wrapped goal goes in via ``goal=``; ``context=""`` (the frame
    is self-contained); ``toolsets=[]`` (pure generator, no tools);
    ``role="leaf"`` (no nested delegation). Per spec §3.2 design
    decisions.

    Args:
        prompt: Pre-wrapped goal string (mutually exclusive with
            ``system``+``user``).
        system: System prompt section for the wrapper.
        user: User-task section for the wrapper.
        strict_preamble_check: If True, raise on detected preamble
            leakage in the first 100 chars (spec T-D-3 gate).

    Returns:
        The child's prose (the ``results[0]["summary"]`` field).

    Raises:
        ValueError: on malformed delegate response OR detected preamble
            leakage when ``strict_preamble_check=True``.
    """
    if prompt is None:
        # Build the wrapped goal from (system, user). Supply benign
        # defaults so callers passing just one half still get a sane
        # frame — tests exercise both paths.
        goal = _wrap_prompt(system or "", user or "")
    elif system is None and user is None:
        # Pre-wrapped goal — but if the caller passed a bare string
        # without the _PROSE_FRAME envelope, wrap it anyway so the
        # child still sees the persona-suppression rules. Detection
        # heuristic: an already-wrapped prompt contains "OUTPUT RULES".
        goal = prompt if "OUTPUT RULES" in prompt else _wrap_prompt("", prompt)
    else:
        # Caller passed prompt AND system/user — unusual but tolerated.
        # Wrap the system+user pair and append the bare prompt as
        # extra context inside the user slot.
        goal = _wrap_prompt(system or "", (user or "") + "\n\n" + prompt)

    result_json = delegate_task(
        goal=goal,
        context="",
        toolsets=[],
        role="leaf",
        max_iterations=None,
    )
    prose = _extract_summary(result_json)
    if strict_preamble_check:
        _check_preamble(prose)
    return prose


# ---------------------------------------------------------------------------
# Phase 2 end-to-end pipeline
# ---------------------------------------------------------------------------


def _slop_penalty(prose: str) -> float:
    """Run ``evaluate.slop_score`` and return the numeric penalty.

    Lazy-imports evaluate so a bare ``import runner`` doesn't pull the
    entire autonovel module graph when the caller only wants
    ``run_delegate``.
    """
    _add_autonovel_to_path()
    import evaluate  # type: ignore[import-not-found]

    score = evaluate.slop_score(prose)
    return float(score.get("slop_penalty", 99.0))


def run_phase2() -> str:
    """Run the full Phase 2 pipeline; return the single-line summary.

    Pipeline (per spec §4.1 SKILL body):
      1. Load identity (identity_loader.load_identity).
      2. Select POV-appropriate voice anchors (anchor_selector).
      3. Build the system + user prompts via write.prompts; inject the
         selected anchors into the system block.
      4. Call ``run_delegate`` to produce prose.
      5. Run ``evaluate.slop_score`` and ``voice_match_score``.
      6. Call ``stage_draft`` — slop-gates internally; FAIL path skips
         enqueue.
      7. Emit single-line summary line:
         ``slop_penalty=<f> voice_match=<f> queue_id=<hex|none> status=<PASS|FAIL>``.

    The summary is the return value AND the only thing this function
    writes to its caller's stdout (the caller picks the destination).
    """
    # Lazy imports keep ``run_delegate`` callable without paying for
    # the whole module graph until ``run_phase2`` is actually invoked.
    # Local imports must NOT prefix with the synthetic package path —
    # the conftest's namespace install means siblings can be imported
    # by their bare names when this module is loaded via
    # hermes_skills.autonovel_phase2.runner.
    from hermes_skills.autonovel_phase2.anchor_selector import select_anchors
    from hermes_skills.autonovel_phase2.identity_loader import load_identity
    from hermes_skills.autonovel_phase2.staging import stage_draft
    from hermes_skills.autonovel_phase2.voice_match import voice_match_score

    root = _add_autonovel_to_path()
    from write.prompts import (  # type: ignore[import-not-found]
        build_draft_system,
        build_draft_user,
    )

    context = load_identity(root=root)
    pov = context.get("pov_character", "Karlach")

    anchors = select_anchors(
        context.get("few_shot_bank", ""), pov_character=pov, max_anchors=2
    )

    # Inject selected anchors into the identity block under a labeled
    # header (mirrors Phase 1 runner.py's shape, but POV-aware).
    if anchors:
        anchor_block = (
            "\n\nVOICE ANCHORS (recent successful samples — "
            "match this register):\n" + "\n\n".join(anchors)
        )
        context["identity"] = context.get("identity", "") + anchor_block

    system_p = build_draft_system(context, context.get("soul", ""))
    user_p = build_draft_user(
        brief=_Brief(),
        context=context,
        chapter_num=1,
        total_chapters=1,
        previous_chapter_tail="",
        seeds=None,
        length_retry=False,
        previous_word_count=0,
        length_enforcement="prompt",
    )

    # FIX (bd-b5p.5.3 /scrutinize FIX-FIRST 2026-05-27): enable
    # strict_preamble_check so T-D-3 preamble-gate is enforced at
    # production runtime (not only in tests). Without this, child-model
    # preamble like "Here is the paragraph:" would land in
    # publish_request.body — exactly what spec §3 told us to skip.
    prose = run_delegate(
        system=system_p, user=user_p, strict_preamble_check=True
    )

    slop = _slop_penalty(prose)
    vm_score = voice_match_score(prose=prose, anchor_passages=anchors)

    item = stage_draft(
        prose=prose,
        slop_penalty=slop,
        voice_match_score=vm_score,
    )

    if item is None:
        queue_id = "none"
        status = "FAIL"
    else:
        queue_id = item.queue_id
        status = "PASS"

    return (
        f"slop_penalty={slop} voice_match={vm_score} "
        f"queue_id={queue_id} status={status}"
    )


# ---------------------------------------------------------------------------
# CLI entry-point (mirrors Phase 1 runner.py shape)
# ---------------------------------------------------------------------------


def main() -> int:
    """CLI: invoke ``run_phase2`` and print the summary line; exit 0/1.

    Exit code is 0 on PASS, 1 on FAIL (slop gate firewall). The
    cron ``--deliver local`` channel captures stdout into
    ``~/.hermes/cron/output/autonovel-phase2/*``.
    """
    summary = run_phase2()
    print(summary)
    return 0 if "status=PASS" in summary else 1


if __name__ == "__main__":
    raise SystemExit(main())
