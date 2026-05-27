"""T-D-* coverage: pure-helper tests (_wrap_prompt, _check_preamble,
_extract_summary, load_identity).

Spec: bd-b5p.5 §5 (test cases T-D-2, T-D-3, T-D-4)
Sub-spec: §3.2 (delegate_task contract — the wrap-prompt half) +
§3.3 (skill_view vs direct read)

bd-b5p.5.6 rewrite: the historical `run_delegate(prompt=...)` wrapper
was removed when Pattern 5 moved `delegate_task` invocation from
``runner.py`` to the SKILL.md agent recipe. Tests that asserted on
the wrapper's call semantics (T-D-1) are gone; the substantive
assertions migrated to direct tests of the pure helpers below.

T-D-1 (delegate_task is invoked, args + role correct) is now a
SKILL.md doc test (see ``test_skill_recipe.py``) — the agent calls
``delegate_task`` as its own tool per the recipe.
"""

from __future__ import annotations

import importlib
import inspect
import json
from pathlib import Path

import pytest
from hermes_skills.autonovel_phase2.identity_loader import load_identity
from hermes_skills.autonovel_phase2.runner import (
    _check_preamble,
    _extract_summary,
    _wrap_prompt,
)

# ---------------------------------------------------------------------------
# T-D-2: _wrap_prompt embeds the _PROSE_FRAME envelope
# ---------------------------------------------------------------------------


def test_wrap_prompt_embeds_prose_frame_output_rules():
    """TEST: T-D-2 (spec bd-b5p.5, OQ-1 resolution evidence) — the goal
    string built by ``_wrap_prompt`` must contain the verbatim
    _PROSE_FRAME contract language so the child's effective system
    prompt embeds the persona-suppression rules.

    Per spec §4.2 the parent agent invokes ``_wrap_prompt`` (via
    ``execute_code`` in SKILL.md Step 2) before passing the result as
    ``goal=`` to its own ``delegate_task`` tool call (Step 3).
    """
    goal = _wrap_prompt("VOICE: be Karlach.", "Write one paragraph.")
    # Load-bearing fragments of _PROSE_FRAME (verbatim from write/prompts.py)
    assert "OUTPUT RULES" in goal, (
        "_PROSE_FRAME's OUTPUT RULES header must be in the wrapped goal"
    )
    assert "Do not break character" in goal, (
        "_PROSE_FRAME's persona-suppression clause must be in the wrapped goal"
    )
    assert "VOICE AND CONSTRAINTS" in goal, (
        "_PROSE_FRAME's VOICE block marker must be in the wrapped goal"
    )


def test_wrap_prompt_carries_caller_system_and_user_payloads():
    """TEST: T-D-2 (spec bd-b5p.5, payload pass-through) — the caller's
    system + user strings must be visible verbatim inside the wrapped
    goal (the wrapper is a frame, not a paraphraser).
    """
    canary_sys = "SYS_CANARY_PHRASE_8675309_LOAD_BEARING"
    canary_user = "USR_CANARY_PHRASE_4842300_LOAD_BEARING"
    goal = _wrap_prompt(canary_sys, canary_user)
    assert canary_sys in goal, "system payload must survive wrap_for_subagent"
    assert canary_user in goal, "user payload must survive wrap_for_subagent"


# ---------------------------------------------------------------------------
# T-D-3: _check_preamble rejects LLM preamble patterns
# ---------------------------------------------------------------------------

_PREAMBLE_PATTERNS = [
    "Here is",
    "Here's",
    "I'll",
    "Sure,",
    "The following",
    "Below is",
    "Certainly,",
    "Of course",
    "As an AI",
]


@pytest.mark.parametrize("preamble", _PREAMBLE_PATTERNS)
def test_check_preamble_rejects_known_patterns(preamble: str):
    """TEST: T-D-3 (spec bd-b5p.5, preamble leakage gate) — if prose's
    first 100 chars contain known preamble patterns, ``_check_preamble``
    MUST raise ValueError so the SKILL.md Step 4 recipe skips queue
    enqueue.
    """
    leaking_prose = (
        f"{preamble} the paragraph you requested: "
        "She sat. The moths circled. He was quiet."
    )
    with pytest.raises(ValueError, match="preamble leakage"):
        _check_preamble(leaking_prose)


def test_check_preamble_accepts_clean_prose():
    """TEST: T-D-3 (spec bd-b5p.5, clean-prose happy path) — when the
    prose does not start with a preamble pattern, ``_check_preamble``
    returns silently (None).
    """
    clean = (
        "She sat on the bench. The moths kept finding the lamp. "
        "Astarion was quiet for once."
    )
    assert _check_preamble(clean) is None


# ---------------------------------------------------------------------------
# T-D-3 (helper): _extract_summary parses Hermes delegate JSON shape
# ---------------------------------------------------------------------------


def test_extract_summary_returns_results_zero_summary_field():
    """TEST: T-D-3 (spec bd-b5p.5, delegate-result parsing) —
    ``_extract_summary`` must return ``results[0].summary`` from the
    canonical Hermes ``delegate_task`` JSON-string return shape.
    """
    canned = json.dumps(
        {
            "results": [
                {
                    "summary": "She sat on the bench. The moths circled.",
                    "child_session_id": "abc-123",
                }
            ]
        }
    )
    prose = _extract_summary(canned)
    assert prose == "She sat on the bench. The moths circled."


# ---------------------------------------------------------------------------
# T-D-4: identity files loaded via direct read, NOT skill_view
# ---------------------------------------------------------------------------


def test_load_identity_uses_path_read_text_not_skill_view(
    autonovel_root: Path,
):
    """TEST: T-D-4 (spec bd-b5p.5, OQ-2 resolution) — identity_loader.py
    must use Path.read_text for self.md / voice_priors.json /
    few_shot_bank.md. NO skill_view call is allowed (it prepends the
    "The user has invoked the {skill_name} skill" attribution noise per
    cron/scheduler.py:1145-1162).

    Verified via static source inspection: skill_view must not appear
    as a callable reference in identity_loader.py's body.
    """
    src = inspect.getsource(
        importlib.import_module(
            "hermes_skills.autonovel_phase2.identity_loader"
        )
    )
    assert "skill_view" not in src, (
        "identity_loader.py must not call skill_view (OQ-2 resolution); "
        "use Path.read_text instead. Found 'skill_view' in module source."
    )


def test_load_identity_returns_required_keys(autonovel_root: Path):
    """TEST: T-D-4 (spec bd-b5p.5, identity contract) — load_identity
    must return a dict containing the keys build_draft_system reads:
    'identity', 'anti_slop_rules', 'brief_text', 'fandom_context'.
    """
    ctx = load_identity(root=autonovel_root)
    for key in ("identity", "anti_slop_rules", "brief_text", "fandom_context"):
        assert key in ctx, (
            f"load_identity must return key {key!r}; got keys={list(ctx)}"
        )
        assert isinstance(ctx[key], str), f"{key!r} must be a string"


def test_load_identity_reads_few_shot_bank_text(autonovel_root: Path):
    """TEST: T-D-4 (spec bd-b5p.5, anchors source) — load_identity must
    surface the raw few_shot_bank.md text under the 'few_shot_bank' key
    (or similar) so anchor_selector can parse it.

    Per spec §3.3 the helper extracts the same logic Phase 1 runner.py
    used (_load_identity_context) but exposes the few_shot bank
    structured rather than blind-trimmed at 3000 chars.
    """
    ctx = load_identity(root=autonovel_root)
    # The structured field name is part of the load_identity contract;
    # accept either 'few_shot_bank' (preferred) or 'few_shot_bank_text'.
    bank_text = ctx.get("few_shot_bank") or ctx.get("few_shot_bank_text")
    assert bank_text, (
        "load_identity must expose few_shot_bank.md text as a top-level key "
        "for anchor_selector to parse"
    )
    assert "## Entry" in bank_text, (
        "few_shot_bank text must include entry markers"
    )
