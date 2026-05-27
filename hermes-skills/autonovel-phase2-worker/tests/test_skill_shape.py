"""SKILL.md doc-tests for the bd-b5p.7 kanban-worker shape.

Per spec §3.1 and §4.1, the new ``autonovel-phase2-worker/SKILL.md``
body is a **kanban-worker shape** that complements (not duplicates) the
auto-injected ``KANBAN_GUIDANCE``. These tests assert the body contains
the right autonovel-specific recipe layered on top of the generic
6-step lifecycle, and DOES NOT regress into the bd-b5p.5.6 Pattern 5
shape.

These tests will FAIL at runtime (skipped via the conftest fixture)
until the /impl wave writes ``hermes-skills/autonovel-phase2-worker/SKILL.md``.
That's correct TDD.

Covers spec test cases T-K-3, T-K-4, T-K-5, T-K-6, T-K-7, T-K-8, T-K-9.
"""

from __future__ import annotations

import re

import pytest

# ---------------------------------------------------------------------------
# T-K-2 — SKILL.md frontmatter declares the kanban-worker shape
# ---------------------------------------------------------------------------


def test_skill_md_frontmatter_name(worker_skill_body: str):
    """T-K-2: frontmatter must declare the new skill name.

    Drift in ``name:`` breaks the dispatcher's ``--skill
    autonovel-phase2-worker`` lookup (per spec §4.4).
    """
    assert "name: autonovel-phase2-worker" in worker_skill_body, (
        "SKILL.md frontmatter must declare `name: autonovel-phase2-worker` "
        "so the kanban dispatcher can load it via --skill flag (spec §3.1)."
    )


def test_skill_md_frontmatter_related_skills_kanban_worker(
    worker_skill_body: str,
):
    """T-K-2: frontmatter must list ``kanban-worker`` in related_skills.

    The dispatcher composes the worker's skill list with the built-in
    ``devops/kanban-worker`` skill body — declaring the relationship
    is the introspection contract Hermes uses to surface "load me too".
    """
    # The related_skills block can be on one line or formatted as a list
    # across multiple lines; assert the membership pattern flexibly.
    assert "kanban-worker" in worker_skill_body, (
        "SKILL.md frontmatter must reference `kanban-worker` (built-in "
        "skill) in related_skills (spec §4.1)."
    )
    assert "related_skills:" in worker_skill_body, (
        "SKILL.md frontmatter must include a `related_skills:` block."
    )


def test_skill_md_frontmatter_tags_include_kanban_worker(
    worker_skill_body: str,
):
    """T-K-2: ``metadata.hermes.tags`` must include ``kanban-worker``.

    Tag-based discovery uses this; missing it means the skill is
    invisible to "find all kanban-worker skills" queries.
    """
    assert "kanban-worker" in worker_skill_body
    # Frontmatter tags appear under a `tags:` key inside metadata.hermes
    assert re.search(
        r"tags:\s*\[.*kanban-worker", worker_skill_body
    ) or re.search(r"-\s*kanban-worker", worker_skill_body), (
        "SKILL.md frontmatter `metadata.hermes.tags` must include "
        "`kanban-worker` as a discoverable tag (spec §4.1)."
    )


# ---------------------------------------------------------------------------
# T-K-3 — SKILL.md instructs kanban_show() FIRST (before other tool calls)
# ---------------------------------------------------------------------------


def test_skill_md_mentions_kanban_show(worker_skill_body: str):
    """T-K-3: SKILL body must mention ``kanban_show()`` as the orient call.

    The KANBAN_GUIDANCE lifecycle requires orient-first; the SKILL body
    must reinforce, not contradict.
    """
    assert "kanban_show()" in worker_skill_body, (
        "SKILL.md must explicitly mention `kanban_show()` as the "
        "orient call (per spec §4.1 'When you receive this task' / "
        "KANBAN_GUIDANCE Step 1)."
    )


def test_skill_md_kanban_show_appears_before_delegate_task(
    worker_skill_body: str,
):
    """T-K-3 (ordering): ``kanban_show()`` must appear BEFORE
    ``delegate_task`` in the body. Workers that delegate before
    orienting skip the parent-handoff metadata they need.
    """
    show_pos = worker_skill_body.find("kanban_show()")
    delegate_pos = worker_skill_body.find("delegate_task")
    assert show_pos != -1, "kanban_show() missing entirely"
    assert delegate_pos != -1, "delegate_task missing entirely"
    assert show_pos < delegate_pos, (
        "kanban_show() must appear BEFORE delegate_task in SKILL.md — "
        "the lifecycle is orient-first (KANBAN_GUIDANCE Step 1, "
        "spec §4.1 Step 1)."
    )


def test_skill_md_kanban_show_appears_before_read_file(
    worker_skill_body: str,
):
    """T-K-3 (ordering): ``kanban_show()`` must appear BEFORE the
    identity ``read_file`` block. Reading identity before orienting
    means you don't yet know the task's parent handoff state.
    """
    show_pos = worker_skill_body.find("kanban_show()")
    read_pos = worker_skill_body.find("read_file")
    assert show_pos != -1
    if read_pos != -1:
        assert show_pos < read_pos, (
            "kanban_show() must appear before read_file invocations in "
            "SKILL.md (spec §4.1 Step 1 → Step 2)."
        )


# ---------------------------------------------------------------------------
# T-K-4 — identity files via read_file (NOT via skill_view, NOT CLAUDE.md)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "identity_path",
    [
        "identity/self.md",
        "identity/voice_priors.json",
        "identity/few_shot_bank.md",
        "identity/soul.md",
    ],
)
def test_skill_md_references_identity_file(
    worker_skill_body: str, identity_path: str
):
    """T-K-4: each of the 4 identity files must be referenced in SKILL.md.

    These are the tool-context reads the worker actively uses (POV,
    voice priors, anchor bank, soul). Dropping any one regresses the
    Pattern 5 voice-injection that bd-b5p.5.6 validated.
    """
    assert identity_path in worker_skill_body, (
        f"SKILL.md must reference identity file `{identity_path}` "
        f"(spec §4.1 Step 2)."
    )


def test_skill_md_uses_read_file_not_skill_view_for_identity(
    worker_skill_body: str,
):
    """T-K-4: identity reads must use ``read_file``, NOT ``skill_view``.

    Per bd-b5p.5 OQ-2: ``skill_view`` prepends an attribution preamble
    that poisons the voice anchors. The SKILL body must use ``read_file``.
    """
    assert "read_file" in worker_skill_body, (
        "SKILL.md must instruct `read_file` (not `skill_view`) for "
        "identity reads (spec §4.1 Step 2, OQ-2 of bd-b5p.5)."
    )
    # Defensive: if skill_view IS mentioned, it should be in a "do NOT"
    # context. We don't strictly forbid the substring (e.g., a `Do NOT
    # use skill_view` line is valid), but we DO require read_file.


def test_skill_md_does_not_instruct_rereading_claude_md(
    worker_skill_body: str,
):
    """T-K-4 (OQ-K-1 amendment): SKILL.md must NOT instruct re-reading
    CLAUDE.md / AGENTS.md from the workspace.

    Per the bd-b5p.7.1 OQ-K-1 walk: ``prompt_builder._inject_claude_md()``
    auto-injects the workspace's CLAUDE.md into the worker's system
    prompt at startup since the worker's cwd IS the workspace.
    Instructing a re-read wastes tool turns AND can confuse the agent
    about which CLAUDE.md is canonical.
    """
    # Look for "Do NOT" + CLAUDE.md/AGENTS.md or an explicit auto-injected note
    has_do_not_claude = bool(
        re.search(
            r"(?i)(do\s*not|never).{0,80}(re-?read|read).{0,80}(CLAUDE\.md|AGENTS\.md)",
            worker_skill_body,
        )
    ) or bool(
        re.search(
            r"(?i)(CLAUDE\.md|AGENTS\.md).{0,80}auto[\s\-]?inject",
            worker_skill_body,
        )
    )
    assert has_do_not_claude, (
        "SKILL.md must either (a) explicitly forbid re-reading "
        "CLAUDE.md / AGENTS.md, or (b) note that prompt_builder "
        "auto-injects them. Per OQ-K-1 amendment, the worker receives "
        "these automatically; instructing a re-read is wasteful."
    )


# ---------------------------------------------------------------------------
# T-K-5 — delegate_task call shape (wrapped goal, leaf, no toolsets)
# ---------------------------------------------------------------------------


def test_skill_md_delegate_task_block_present(worker_skill_body: str):
    """T-K-5: SKILL must show a ``delegate_task(`` invocation.

    The wrapped-goal pattern is the bd-b5p.5.6 validated shape; the
    worker's job is to emit this tool call after Step 3.
    """
    assert "delegate_task(" in worker_skill_body, (
        "SKILL.md must show a `delegate_task(` invocation block "
        "(spec §4.1 Step 4)."
    )


def test_skill_md_delegate_task_has_goal_kwarg(worker_skill_body: str):
    """T-K-5: the delegate_task block must show ``goal=`` (the wrapped
    prompt slot the parent agent fills in from Step 3 output)."""
    assert "goal=" in worker_skill_body, (
        "SKILL.md `delegate_task(...)` invocation must show the "
        "`goal=` kwarg (spec §4.1 Step 4)."
    )


def test_skill_md_delegate_task_role_leaf(worker_skill_body: str):
    """T-K-5: delegate_task must use ``role=\"leaf\"``.

    Non-leaf roles can recursively dispatch; we want a single-shot
    child here so the worker stays in control of the lifecycle.
    """
    assert (
        'role="leaf"' in worker_skill_body or "role='leaf'" in worker_skill_body
    ), 'SKILL.md `delegate_task` block must use role="leaf" (spec §4.1 Step 4).'


def test_skill_md_delegate_task_toolsets_empty(worker_skill_body: str):
    """T-K-5: ``toolsets=[]`` — the prose-generation child does not
    need tools; passing tools risks the child going off on a tangent."""
    assert "toolsets=[]" in worker_skill_body, (
        "SKILL.md `delegate_task` block must use toolsets=[] "
        "(spec §4.1 Step 4 — Pattern 5 contract validated by bd-b5p.5.6)."
    )


def test_skill_md_delegate_task_max_iterations_present(
    worker_skill_body: str,
):
    """T-K-5: ``max_iterations=`` must be set (Pattern 5 used 10; we
    don't strictly assert the value but presence is contractual)."""
    assert "max_iterations=" in worker_skill_body, (
        "SKILL.md `delegate_task` block must set `max_iterations=` "
        "(spec §4.1 Step 4)."
    )


# ---------------------------------------------------------------------------
# T-K-6 — kanban_complete schema + artifacts parameter
# ---------------------------------------------------------------------------


def test_skill_md_kanban_complete_block_present(worker_skill_body: str):
    """T-K-6: SKILL must show a ``kanban_complete(`` invocation block."""
    assert "kanban_complete(" in worker_skill_body, (
        "SKILL.md must show the canonical `kanban_complete(...)` "
        "invocation (spec §4.1 Step 6)."
    )


@pytest.mark.parametrize(
    "metadata_key",
    [
        "queue_id",
        "slop_penalty",
        "voice_match",
        "draft_excerpt",
        "status",
    ],
)
def test_skill_md_kanban_complete_metadata_key(
    worker_skill_body: str, metadata_key: str
):
    """T-K-6: each of the 5 metadata keys per §4.5 must appear in
    SKILL.md. Downstream parsers depend on this shape; missing a key
    = silent data loss.
    """
    assert metadata_key in worker_skill_body, (
        f"SKILL.md must reference metadata key `{metadata_key}` in "
        f"the kanban_complete block (spec §4.5)."
    )


def test_skill_md_kanban_complete_uses_artifacts_parameter(
    worker_skill_body: str,
):
    """T-K-6 (OQ-K-3 amendment): SKILL must show ``artifacts=[...]``
    as a separate kwarg (NOT stuffed into metadata).

    Per OQ-K-3: passing the publish_queue file via the ``artifacts``
    parameter hooks the gateway notifier for native attachment upload;
    using ``metadata['file_path']`` instead skips the notifier hook.
    """
    assert "artifacts=" in worker_skill_body, (
        "SKILL.md kanban_complete block must use `artifacts=[...]` "
        "parameter (per OQ-K-3 amendment / spec §4.5). Stuffing the "
        "file path in metadata bypasses the gateway notifier."
    )


def test_skill_md_kanban_complete_references_publish_queue_path(
    worker_skill_body: str,
):
    """T-K-6: the artifacts list must reference the publish_queue file
    path so future operators know which file is being attached."""
    assert (
        "publish_queue" in worker_skill_body or "file_path" in worker_skill_body
    ), (
        "SKILL.md must reference the publish_queue file path (or "
        "file_path variable that holds it) so the artifacts list is "
        "concretely anchored (spec §4.1 Step 6)."
    )


# ---------------------------------------------------------------------------
# T-K-7 — kanban_heartbeat on long ops
# ---------------------------------------------------------------------------


def test_skill_md_mentions_kanban_heartbeat(worker_skill_body: str):
    """T-K-7: SKILL must mention ``kanban_heartbeat`` for long ops.

    A 30m-budget worker without heartbeat after a stalled delegate_task
    is the path to ``dispatch_stale`` reclaim mid-generation.
    """
    assert "kanban_heartbeat" in worker_skill_body, (
        "SKILL.md must mention `kanban_heartbeat` for the long "
        "generate-via-delegate_task case (spec §4.1 Step 4 + KANBAN_GUIDANCE Step 3)."
    )


def test_skill_md_heartbeat_near_long_op_context(worker_skill_body: str):
    """T-K-7: the heartbeat mention should be NEAR a long-op marker
    (e.g., "long", "minutes", "delegate_task")."""
    body = worker_skill_body
    heartbeat_pos = body.find("kanban_heartbeat")
    assert heartbeat_pos != -1
    # Pull a 240-char window around the heartbeat mention
    window = body[max(0, heartbeat_pos - 120) : heartbeat_pos + 240].lower()
    # At least one long-op indicator in the local context
    indicators = ["long", "minutes", "5 min", "delegate", "generation", "stall"]
    matches = [ind for ind in indicators if ind in window]
    assert matches, (
        "SKILL.md `kanban_heartbeat` mention should be co-located "
        "with a long-op indicator (long / minutes / delegate / "
        "generation / stall). Found none in 240-char window."
    )


# ---------------------------------------------------------------------------
# T-K-8 — failure modes use kanban_block (not kanban_complete) on errors
# ---------------------------------------------------------------------------


def test_skill_md_has_failure_modes_section(worker_skill_body: str):
    """T-K-8: SKILL must have a Failure modes section."""
    assert re.search(r"(?i)#+\s*failure\s*mode", worker_skill_body), (
        "SKILL.md must include a `## Failure modes` (or similar) "
        "section enumerating error-path handling (spec §4.6)."
    )


def test_skill_md_failure_modes_use_kanban_block(worker_skill_body: str):
    """T-K-8: failure modes must call ``kanban_block`` (NOT
    ``kanban_complete``) for error cases.

    Completing on error fabricates success — that's the bd-b5p.5.7
    failure mode at a different layer. Blocking preserves human triage.
    """
    assert "kanban_block" in worker_skill_body, (
        "SKILL.md failure modes must call `kanban_block(...)` for "
        "error cases — NOT `kanban_complete` (spec §4.6)."
    )


def test_skill_md_distinguishes_delegate_timeout_from_worker_sigterm(
    worker_skill_body: str,
):
    """T-K-8 (OQ-K-2 amendment): failure modes must distinguish the
    two timeout clocks — delegate_task per-child (1800s) vs worker
    --max-runtime (30m SIGTERM).

    Per bd-b5p.7.1 OQ-K-2: there ARE two clocks. Conflating them means
    the worker mishandles a recoverable delegate timeout as a fatal
    crash, or vice-versa.
    """
    body = worker_skill_body.lower()
    # Must mention both clocks somewhere
    has_delegate_timeout = ("delegate" in body) and (
        "timeout" in body or "1800" in body
    )
    has_worker_sigterm = (
        ("sigterm" in body)
        or ("30m" in body)
        or ("max-runtime" in body or "max_runtime" in body)
    )
    assert has_delegate_timeout, (
        "SKILL.md failure modes must mention the delegate_task timeout "
        "(per-child 1800s budget per §3.2)."
    )
    assert has_worker_sigterm, (
        "SKILL.md failure modes must mention the worker --max-runtime "
        "SIGTERM at 30m (substrate-enforced per §4.4)."
    )


# ---------------------------------------------------------------------------
# T-K-9 — Do NOT section forbids terminal_tool + fabrication + CLAUDE.md re-read
# ---------------------------------------------------------------------------


def test_skill_md_has_do_not_section(worker_skill_body: str):
    """T-K-9: SKILL must have a 'Do NOT' (or similar) anti-pattern section."""
    assert re.search(r"(?i)#+\s*do\s*not", worker_skill_body), (
        "SKILL.md must include a `## Do NOT` (or similar) anti-pattern "
        "section (spec §4.1)."
    )


def test_skill_md_do_not_forbids_terminal_tool(worker_skill_body: str):
    """T-K-9: anti-pattern section must forbid ``terminal_tool`` for
    board ops (per kanban-worker reference skill)."""
    assert "terminal_tool" in worker_skill_body, (
        "SKILL.md must reference `terminal_tool` by name in the "
        "anti-pattern section — it's the documented Hermes pitfall "
        "for board ops (CLI fails in containerized backends)."
    )


def test_skill_md_do_not_forbids_pattern5_standalone_invocation(
    worker_skill_body: str,
):
    """T-K-9 (regression guard): the new worker shape must NOT
    instruct invoking ``python3 runner.py`` standalone — that was
    the bd-b5p.5.5 broken-invocation pattern the kanban shape supersedes.
    """
    # If the body has "python3 runner.py" it should be in a "do NOT"
    # context. We assert the inverse: the body should NOT contain a
    # bare invocation pattern as a positive instruction.
    bad_pattern = re.search(
        r"(?i)(?<!do not invoke `)(?<!never invoke `)python3\s+runner\.py",
        worker_skill_body,
    )
    if bad_pattern:
        # If it does match, the surrounding context must be a Do NOT
        # warning (not a positive instruction).
        context = worker_skill_body[
            max(0, bad_pattern.start() - 80) : bad_pattern.end() + 40
        ].lower()
        assert "do not" in context or "never" in context, (
            "SKILL.md must not positively instruct `python3 runner.py` "
            "standalone — that was the bd-b5p.5.5 broken pattern; "
            "the kanban worker shape uses delegate_task instead."
        )


# ---------------------------------------------------------------------------
# T-K-8 (additional) — exit without kanban_complete documented expectation
# ---------------------------------------------------------------------------


def test_skill_md_mentions_dispatch_stale_or_exit_expectation(
    worker_skill_body: str,
):
    """T-K-8: SKILL should document the expectation that exiting
    without ``kanban_complete`` causes the task to be marked
    ``dispatch_stale`` (substrate behavior, but workers should know
    they MUST emit kanban_complete or kanban_block to avoid this).
    """
    body = worker_skill_body.lower()
    assert any(
        marker in body
        for marker in [
            "dispatch_stale",
            "dispatch-stale",
            "re-queue",
            "requeue",
            "stale",
        ]
    ), (
        "SKILL.md should mention the substrate's dispatch_stale / "
        "re-queue behavior for workers that exit without "
        "kanban_complete (spec §4.6 + KANBAN_GUIDANCE Step 5)."
    )


# ---------------------------------------------------------------------------
# Spec-anchor sanity: bead id present
# ---------------------------------------------------------------------------


def test_skill_md_references_bead_id(worker_skill_body: str):
    """Sanity: the worker SKILL should reference its bead (bd-b5p.7)
    for provenance — same convention as the bd-b5p.5.6 sibling.
    """
    assert "bd-b5p.7" in worker_skill_body, (
        "SKILL.md should reference bead `bd-b5p.7` for provenance "
        "(spec §4.1 frontmatter)."
    )


# ---------------------------------------------------------------------------
# Reinforcement: NO instructions to re-read CLAUDE.md as a positive step
# ---------------------------------------------------------------------------


def test_skill_md_no_positive_claude_md_read_instruction(
    worker_skill_body: str,
):
    """T-K-4 (inverted): the body should NOT contain a positive
    instruction like "read CLAUDE.md" or "Step N: read CLAUDE.md"
    since prompt_builder auto-injects it.
    """
    # Find any "read CLAUDE.md" mention; if found, surrounding context
    # must be a do-not / auto-injected note.
    matches = re.finditer(
        r"(?i)(read|cat|load)\s+(?:the\s+)?(?:workspace\s+)?CLAUDE\.md",
        worker_skill_body,
    )
    for m in matches:
        context = worker_skill_body[
            max(0, m.start() - 100) : m.end() + 100
        ].lower()
        is_negative = (
            "do not" in context
            or "don't" in context
            or "never" in context
            or "auto-inject" in context
            or "automatically" in context
            or "no need" in context
            or "already" in context
        )
        assert is_negative, (
            f"SKILL.md contains a positive 'read CLAUDE.md' "
            f"instruction at position {m.start()} — per OQ-K-1, the "
            f"worker auto-receives CLAUDE.md via prompt_builder. "
            f"Context: {context!r}"
        )
