"""T-D-* coverage: delegate_task migration + identity loader.

Spec: bd-b5p.5 §5 (test cases T-D-1, T-D-2, T-D-3, T-D-4)
Sub-spec: §3.2 (delegate_task contract) + §3.3 (skill_view vs direct read)

These tests verify the substrate migration from Phase 1's HTTP shim to
Hermes' native delegate_task primitive, and that identity files are
loaded via Path.read_text rather than skill_view (which would prepend
attribution noise per cron/scheduler.py:1145-1162).
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest

# Planned module imports — fail at runtime (correct TDD) if impl wave
# hasn't built these yet.
from hermes_skills.autonovel_phase2 import runner as runner_mod
from hermes_skills.autonovel_phase2.identity_loader import load_identity
from hermes_skills.autonovel_phase2.runner import run_delegate

# ---------------------------------------------------------------------------
# T-D-1: delegate_task is invoked (no HTTP fallback)
# ---------------------------------------------------------------------------


def test_run_delegate_invokes_delegate_task(
    monkeypatch: pytest.MonkeyPatch, fake_delegate_task
):
    """TEST: T-D-1 (spec bd-b5p.5, delegate basic) — verify run_delegate
    invokes the Hermes delegate_task primitive at least once.

    Delegation-assertion pattern per /test SKILL Step 3.5: spy on the
    real dependency, assert call args. If run_delegate is a stub body
    that returns the right shape but never calls delegate_task, this
    test fails immediately.
    """
    monkeypatch.setattr(runner_mod, "delegate_task", fake_delegate_task.spy)
    run_delegate(prompt="A wrapped _PROSE_FRAME goal string for testing.")
    assert len(fake_delegate_task.calls) == 1, (
        f"Expected exactly 1 delegate_task call, got "
        f"{len(fake_delegate_task.calls)}"
    )


def test_run_delegate_passes_wrapped_prompt_as_goal(
    monkeypatch: pytest.MonkeyPatch, fake_delegate_task
):
    """TEST: T-D-1 (spec bd-b5p.5, delegate arg contract) — the wrapped
    _PROSE_FRAME prompt MUST land in delegate_task's ``goal`` arg, not
    ``context``. Per §3.2 the frame is self-contained and context="".
    """
    monkeypatch.setattr(runner_mod, "delegate_task", fake_delegate_task.spy)
    canary = "CANARY_PROSE_FRAME_GOAL_PAYLOAD_8675309"
    run_delegate(prompt=canary)
    call = fake_delegate_task.calls[0]
    assert canary in call["goal"], "Wrapped prompt must be passed as goal="
    assert call["context"] == "", (
        "Phase 2 spec §3.2 mandates context='' (frame is self-contained)"
    )


def test_run_delegate_uses_empty_toolsets_and_leaf_role(
    monkeypatch: pytest.MonkeyPatch, fake_delegate_task
):
    """TEST: T-D-1 (spec bd-b5p.5, delegate role/toolsets) — child must
    be a pure generator: toolsets=[] and role='leaf'. Per §3.2 design
    decisions (no nested delegation; no tool latency).
    """
    monkeypatch.setattr(runner_mod, "delegate_task", fake_delegate_task.spy)
    run_delegate(prompt="x")
    call = fake_delegate_task.calls[0]
    assert call["toolsets"] == [], "Phase 2 §3.2: toolsets=[] (pure generator)"
    assert call["role"] == "leaf", "Phase 2 §3.2: role='leaf' (no nesting)"


def test_run_delegate_does_not_issue_outbound_http(
    monkeypatch: pytest.MonkeyPatch, fake_delegate_task
):
    """TEST: T-D-1 (spec bd-b5p.5, no HTTP shim) — confirm run_delegate
    does NOT call urllib.request.urlopen or httpx.post directly.
    Substantive evidence the Phase 1 shim path is gone.
    """
    import urllib.request

    blocked_calls: list[str] = []

    def _block_urlopen(*args, **kwargs):
        blocked_calls.append(f"urlopen({args!r}, {kwargs!r})")
        raise AssertionError(
            "Phase 2 must not POST directly; use delegate_task."
        )

    monkeypatch.setattr(urllib.request, "urlopen", _block_urlopen)
    monkeypatch.setattr(runner_mod, "delegate_task", fake_delegate_task.spy)

    # Block httpx too if it's been wired in.
    try:
        import httpx

        def _block_post(*args, **kwargs):
            blocked_calls.append(f"httpx.post({args!r}, {kwargs!r})")
            raise AssertionError(
                "Phase 2 must not POST directly; use delegate_task."
            )

        monkeypatch.setattr(httpx, "post", _block_post, raising=False)
    except ImportError:
        pass

    run_delegate(prompt="goal payload")
    assert not blocked_calls, (
        f"Phase 2 must not issue outbound HTTP from skill code; "
        f"got: {blocked_calls}"
    )


# ---------------------------------------------------------------------------
# T-D-2: child receives the wrapped prompt as `goal`
# ---------------------------------------------------------------------------


def test_run_delegate_wraps_prompt_with_prose_frame(
    monkeypatch: pytest.MonkeyPatch, fake_delegate_task
):
    """TEST: T-D-2 (spec bd-b5p.5, OQ-1 resolution evidence) — the
    ``goal`` passed to delegate_task must contain the verbatim
    _PROSE_FRAME contract language so the child's effective system
    prompt embeds the persona-suppression rules.

    Per spec §4.2 the parent builds the wrapped frame via
    write.prompts.wrap_for_subagent before calling delegate_task.
    """
    monkeypatch.setattr(runner_mod, "delegate_task", fake_delegate_task.spy)
    # run_delegate accepts EITHER a pre-wrapped prompt or builds one from
    # context. We pass a system+user combo and check the wrapping happens.
    run_delegate(
        system="VOICE: be Karlach.",
        user="Write one paragraph.",
    )
    call = fake_delegate_task.calls[0]
    goal = call["goal"]
    # Load-bearing fragments of _PROSE_FRAME (verbatim from write/prompts.py)
    assert "OUTPUT RULES" in goal, (
        "_PROSE_FRAME's OUTPUT RULES header must be in the goal"
    )
    assert "Do not break character" in goal, (
        "_PROSE_FRAME's persona-suppression clause must be in the goal"
    )
    assert "VOICE AND CONSTRAINTS" in goal, (
        "_PROSE_FRAME's VOICE block marker must be in the goal"
    )


# ---------------------------------------------------------------------------
# T-D-3: no preamble leakage in child response
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
def test_run_delegate_rejects_preamble_in_first_100_chars(
    monkeypatch: pytest.MonkeyPatch, preamble: str
):
    """TEST: T-D-3 (spec bd-b5p.5, preamble leakage gate) — if the
    child returns prose whose first 100 chars contain known preamble
    patterns, run_delegate MUST raise / return an error sentinel so
    the staging step skips queue enqueue.
    """
    import json

    def _bad_child(**kwargs) -> str:
        return json.dumps(
            {
                "results": [
                    {
                        "summary": (
                            f"{preamble} the paragraph you requested: "
                            "She sat. The moths circled. He was quiet."
                        )
                    }
                ]
            }
        )

    monkeypatch.setattr(runner_mod, "delegate_task", _bad_child)
    with pytest.raises((ValueError, RuntimeError, AssertionError)):
        run_delegate(prompt="x", strict_preamble_check=True)


def test_run_delegate_accepts_clean_prose(
    monkeypatch: pytest.MonkeyPatch, fake_delegate_task
):
    """TEST: T-D-3 (spec bd-b5p.5, clean-prose happy path) — when the
    child returns prose without preamble, run_delegate returns the
    prose verbatim.
    """
    monkeypatch.setattr(runner_mod, "delegate_task", fake_delegate_task.spy)
    prose = run_delegate(prompt="x")
    assert isinstance(prose, str), "run_delegate must return a str"
    assert prose, "run_delegate must not return an empty string on success"
    # No preamble in the spy's canned response (set in conftest)
    first_100 = prose[:100]
    for bad in _PREAMBLE_PATTERNS:
        assert not first_100.startswith(bad), (
            f"Clean prose path leaked preamble {bad!r}: {first_100!r}"
        )


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
