"""SKILL.md doc-tests for the bd-b5p.5.6 Pattern 5 agent recipe.

Per bd-b5p.5.5 research (research-phase2-invocation.md), Phase 2's
SKILL.md is now a procedural recipe the parent agent executes
in-conversation. There is no executable ``run_phase2()`` to integration-
test against; the recipe shape IS the executable surface.

These tests are intentionally weak coverage — they assert that the
canonical recipe markers (5 steps, the warning against standalone
runner.py invocation, the cron operational path) are present in the
shipped SKILL.md body. Their job is to prevent silent prose-rot of the
recipe; the substantive validation is operational
(``hermes cron run <id>`` smoke runs).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SKILL_PATH = Path(__file__).resolve().parent.parent / "SKILL.md"


@pytest.fixture(scope="module")
def skill_body() -> str:
    """Read the shipped SKILL.md body once for the module."""
    assert _SKILL_PATH.exists(), f"SKILL.md missing at {_SKILL_PATH}"
    return _SKILL_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# DOC-1: the five-step recipe is present
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "step_marker",
    [
        "### Step 1: agent uses `read_file`",
        "### Step 2: agent uses `execute_code` to build the wrapped goal",
        "### Step 3: agent EMITS `delegate_task` tool call directly",
        "### Step 4: agent uses `execute_code` to extract, score, and stage",
        "### Step 5: agent reports the canonical single-line summary",
    ],
)
def test_skill_md_contains_recipe_step(skill_body: str, step_marker: str):
    """DOC-1: SKILL.md must include each of the 5 canonical recipe step
    headers. Missing a step breaks the Pattern 5 agent walk-through.
    """
    assert step_marker in skill_body, (
        f"SKILL.md missing recipe marker: {step_marker!r}. "
        "Pattern 5 requires all 5 steps to be present (bd-b5p.5.6)."
    )


# ---------------------------------------------------------------------------
# DOC-2: explicit warning against standalone runner.py invocation
# ---------------------------------------------------------------------------


def test_skill_md_warns_against_standalone_runner_py(skill_body: str):
    """DOC-2: SKILL.md must contain an explicit "NEVER invoke
    python3 runner.py" warning, with the rationale referencing the
    in-process parent_agent requirement. This is the load-bearing
    anti-pattern the bd-b5p.5.6 rewrite eliminates.
    """
    assert "NEVER invoke `python3 runner.py`" in skill_body, (
        "SKILL.md must contain the canonical 'NEVER invoke python3 "
        "runner.py standalone' warning so agents don't regress to the "
        "broken subprocess pattern (bd-b5p.5.5 / bd-b5p.5.6)."
    )
    assert "parent_agent" in skill_body, (
        "SKILL.md warning must reference the parent_agent in-process "
        "requirement so the rationale is visible at the warning site."
    )


def test_skill_md_warns_against_terminal_tool_subprocess_pattern(
    skill_body: str,
):
    """DOC-2: SKILL.md must warn against the legacy
    ``terminal_tool``-via-subprocess pattern that confabulated success
    summaries (bd-b5p.5.7). Operators reading SKILL.md should know
    BOTH the broken patterns by name.
    """
    assert "terminal_tool" in skill_body, (
        "SKILL.md must reference terminal_tool by name in the warning "
        "against the legacy broken subprocess invocation pattern."
    )


# ---------------------------------------------------------------------------
# DOC-3: canonical operational invocation (hermes cron)
# ---------------------------------------------------------------------------


def test_skill_md_documents_hermes_cron_create_invocation(skill_body: str):
    """DOC-3: SKILL.md must document the canonical
    ``hermes cron create '<schedule>' '/skill:autonovel-phase2 run'
    --deliver local`` registration. This is the only invocation path
    that supplies the parent_agent context the recipe needs.
    """
    assert "hermes cron create" in skill_body, (
        "SKILL.md must document the canonical hermes cron create "
        "registration path (Pattern 5 operational entrypoint)."
    )
    assert "/skill:autonovel-phase2 run" in skill_body, (
        "SKILL.md must reference the /skill: dispatch token cron uses "
        "to load this SKILL body."
    )
    assert "--deliver local" in skill_body, (
        "SKILL.md must reference --deliver local so the single-line "
        "summary lands in ~/.hermes/cron/output/."
    )


def test_skill_md_documents_hermes_cron_run_smoke_path(skill_body: str):
    """DOC-3: SKILL.md must document ``hermes cron run <job-id>`` as
    the manual smoke path for re-firing a registered cron job.
    """
    assert "hermes cron run" in skill_body, (
        "SKILL.md must document hermes cron run <id> as the manual "
        "smoke re-fire path."
    )


# ---------------------------------------------------------------------------
# DOC-4: recipe references the pure-helper module surface
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "helper_ref",
    [
        "_wrap_prompt",
        "_check_preamble",
        "_extract_summary",
        "stage_draft",
        "voice_match_score",
    ],
)
def test_skill_md_references_pure_helper(skill_body: str, helper_ref: str):
    """DOC-4: SKILL.md recipe steps must reference each pure helper
    by name. If the recipe drops a helper reference, the agent will
    skip the corresponding pipeline step.
    """
    assert helper_ref in skill_body, (
        f"SKILL.md recipe must reference helper {helper_ref!r} so the "
        "agent's execute_code snippet imports + calls it."
    )


# ---------------------------------------------------------------------------
# DOC-5: canonical single-line summary format is documented
# ---------------------------------------------------------------------------


def test_skill_md_documents_single_line_summary_format(skill_body: str):
    """DOC-5: SKILL.md must show the canonical single-line summary
    shape so operators (and the agent) know what Step 5 reports.
    """
    assert "slop_penalty=" in skill_body
    assert "voice_match=" in skill_body
    assert "queue_id=" in skill_body
    assert "status=" in skill_body
