"""T-E-* coverage: full Phase 2 pipeline + Phase 1 coexistence + rollback.

Spec: bd-b5p.5 §5 (test cases T-E-1, T-E-2, T-E-3)
Sub-spec: §3.1 (new skill, NOT replacement) + §3.7 (cron registration)

End-to-end smoke that ties the delegate → slop gate → voice gate →
staging pipeline together, plus invariants that prove Phase 1 stays
operational as the rollback target.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# T-E-1: end-to-end smoke (canonical Phase 2 acceptance run)
# ---------------------------------------------------------------------------


def test_run_phase2_end_to_end_lands_pending_queue_item(
    monkeypatch: pytest.MonkeyPatch,
    clean_publish_queue: Path,
    fake_delegate_task,
):
    """TEST: T-E-1 (spec bd-b5p.5, canonical acceptance) — invoking
    the Phase 2 skill entrypoint (run_phase2) produces a
    publish_queue/<id>.json with status=pending. Single-line summary
    is returned. slop_penalty < 3.0 in this happy path.

    The fake_delegate_task fixture returns clean canned prose so the
    full pipeline can run without an actual LLM.
    """
    runner_mod = importlib.import_module(
        "hermes_skills.autonovel_phase2.runner"
    )
    monkeypatch.setattr(runner_mod, "delegate_task", fake_delegate_task.spy)

    run_phase2 = runner_mod.run_phase2
    summary = run_phase2()

    # Assert exactly one queue file landed
    files = list(clean_publish_queue.glob("*.json"))
    assert len(files) == 1, (
        f"Expected exactly 1 queue file; got {len(files)}: {files}"
    )
    data = json.loads(files[0].read_text())
    assert data["status"] == "pending"

    # Assert delegate_task was invoked
    assert len(fake_delegate_task.calls) >= 1, (
        "run_phase2 must call delegate_task at least once"
    )

    # Assert summary is single-line + contains required signals
    assert isinstance(summary, str)
    assert "\n" not in summary.strip(), (
        f"Summary must be single-line; got: {summary!r}"
    )
    for token in ("slop_penalty=", "voice_match=", "queue_id=", "status="):
        assert token in summary, f"Summary missing required token: {token}"


def test_run_phase2_exit_code_zero_on_pass(
    monkeypatch: pytest.MonkeyPatch,
    clean_publish_queue: Path,
    fake_delegate_task,
):
    """TEST: T-E-1 (spec bd-b5p.5, exit code contract) — on success
    (slop_penalty < 3.0), the runner returns/exits 0. Per §4.6 the
    single-line summary line says status=PASS in this case.
    """
    runner_mod = importlib.import_module(
        "hermes_skills.autonovel_phase2.runner"
    )
    monkeypatch.setattr(runner_mod, "delegate_task", fake_delegate_task.spy)

    summary = runner_mod.run_phase2()
    assert "status=PASS" in summary, (
        f"Happy-path summary must say status=PASS; got: {summary!r}"
    )


def test_run_phase2_emits_fail_summary_when_slop_high(
    monkeypatch: pytest.MonkeyPatch,
    clean_publish_queue: Path,
):
    """TEST: T-E-1 (spec bd-b5p.5, fail-path summary) — when the
    delegate returns slop-heavy prose triggering slop_penalty >= 3.0,
    the summary contains status=FAIL and NO queue file lands.
    """
    runner_mod = importlib.import_module(
        "hermes_skills.autonovel_phase2.runner"
    )

    # Return prose laced with TIER1_BANNED words so evaluate.slop_score
    # produces a high penalty. Use words from the Phase 1 list.
    bad_prose = (
        "She delved into the tapestry. The synergy was holistic. "
        "She utilized the paradigm to leverage the myriad of options. "
        "Her plethora of feelings facilitated a delve into the bench."
    )

    def _bad_delegate(**kwargs) -> str:
        return json.dumps({"results": [{"summary": bad_prose}]})

    monkeypatch.setattr(runner_mod, "delegate_task", _bad_delegate)

    summary = runner_mod.run_phase2()
    assert "status=FAIL" in summary, (
        f"High-slop path must say status=FAIL; got: {summary!r}"
    )
    files = list(clean_publish_queue.glob("*.json"))
    assert files == [], (
        "FAIL path must NOT add to publish_queue (slop firewall)"
    )


# ---------------------------------------------------------------------------
# T-E-2: Phase 1 + Phase 2 coexistence (disjoint output paths)
# ---------------------------------------------------------------------------


def test_phase1_skill_dir_still_exists(autonovel_root: Path):
    """TEST: T-E-2 (spec bd-b5p.5, Phase 1 coexists) — Phase 2 is a NEW
    skill, NOT a replacement of autonovel-phase1-smoke. Phase 1's
    skill directory and runner.py must remain present untouched as
    the rollback target.
    """
    phase1_dir = autonovel_root / "hermes-skills" / "autonovel-phase1-smoke"
    assert phase1_dir.is_dir(), "Phase 1 skill dir must remain"
    runner = phase1_dir / "runner.py"
    assert runner.is_file(), "Phase 1 runner.py must remain unmodified"
    skill_md = phase1_dir / "SKILL.md"
    assert skill_md.is_file(), "Phase 1 SKILL.md must remain"


def test_phase2_output_path_disjoint_from_phase1(autonovel_root: Path):
    """TEST: T-E-2 (spec bd-b5p.5, output-path isolation) — Phase 1
    writes to write/runs/phase1-smoke/; Phase 2 writes to
    publish_queue/. These must be disjoint paths so the two cron
    jobs cannot collide on shared mutable state.
    """
    phase1_out = autonovel_root / "write" / "runs" / "phase1-smoke"
    phase2_out = autonovel_root / "publish_queue"
    # Disjointness check: neither path is an ancestor or descendant of the
    # other; the LAST path components differ.
    try:
        phase1_out.relative_to(phase2_out)
        raise AssertionError(
            "Phase 1 output path must not be inside Phase 2 publish_queue"
        )
    except ValueError:
        pass
    try:
        phase2_out.relative_to(phase1_out)
        raise AssertionError(
            "Phase 2 publish_queue must not be inside Phase 1 output dir"
        )
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# T-E-3: rollback path is one-command (cron pause/resume)
# ---------------------------------------------------------------------------


def test_rollback_does_not_require_phase2_source_deletion(
    autonovel_root: Path,
):
    """TEST: T-E-3 (spec bd-b5p.5, rollback semantics) — rollback is
    operational, not source-level. Phase 2 skill files can stay on
    disk; rollback is purely about which cron schedule fires. This
    test confirms the rollback contract is documented in SKILL.md
    body rather than requiring file deletion.
    """
    skill_md = (
        autonovel_root / "hermes-skills" / "autonovel-phase2" / "SKILL.md"
    )
    assert skill_md.exists(), (
        "Phase 2 SKILL.md must exist for rollback documentation"
    )
    body = skill_md.read_text(encoding="utf-8")
    # Per OQ-7 ACCEPT amendment in --notes: SKILL.md must include the
    # grep enumeration recipe so operators can locate Phase 2 queue items
    # without consulting external docs.
    assert "rollback" in body.lower() or "Rollback" in body, (
        "Phase 2 SKILL.md must document rollback (OQ-7 amendment)"
    )
    assert "publish_queue" in body, (
        "SKILL.md rollback section must reference publish_queue enumeration"
    )


def test_phase2_rollback_keeps_existing_queue_items(
    clean_publish_queue: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_delegate_task,
):
    """TEST: T-E-3 (spec bd-b5p.5, queue persistence on rollback) —
    per OQ-7 ACCEPT, in-flight queue items stay on rollback. We
    simulate this by enqueuing a Phase 2 item, then asserting it
    persists even if the runner is never invoked again.
    """
    runner_mod = importlib.import_module(
        "hermes_skills.autonovel_phase2.runner"
    )
    monkeypatch.setattr(runner_mod, "delegate_task", fake_delegate_task.spy)
    runner_mod.run_phase2()
    files_after_run = list(clean_publish_queue.glob("*.json"))
    assert len(files_after_run) == 1

    # Simulate "rollback": stop scheduling Phase 2. The queue file MUST
    # remain on disk untouched — no automatic purge.
    file_path = files_after_run[0]
    content_before = file_path.read_text()
    # ... time passes ... no further action ...
    assert file_path.exists(), "Queue file must survive rollback"
    assert file_path.read_text() == content_before, (
        "Queue file must not be mutated by rollback"
    )
    # The operator's enumeration recipe per OQ-7 amendment:
    # grep -l bd-b5p.5 publish_queue/*.json
    assert "bd-b5p.5" in content_before, (
        "Queue file must contain bead ID so OQ-7 grep enumeration works"
    )


# ---------------------------------------------------------------------------
# REGRESSION: bd-ylg / bd-b5p.5.3 /scrutinize FIX-FIRST 2026-05-27
# ---------------------------------------------------------------------------


def test_run_phase2_passes_strict_preamble_check_true_to_run_delegate(
    clean_publish_queue: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """REGRESSION (bd-ylg, /scrutinize FIX-FIRST 2026-05-27):

    Verify run_phase2 invokes run_delegate with strict_preamble_check=True
    in the production end-to-end path. Without this kwarg, child-model
    preamble like "Here is the paragraph:" would land in
    publish_request.body — exactly the failure mode spec §3 said to skip.

    The /scrutinize gate caught that the impl's tests passed (59/59) but
    the production call site at runner.py:333 was missing the kwarg.

    Spy on run_delegate (the SUT's call site, not on delegate_task) and
    assert the kwarg is set on every invocation.
    """
    runner_mod = importlib.import_module(
        "hermes_skills.autonovel_phase2.runner"
    )

    captured_calls: list[dict] = []

    def spy(*args, **kwargs):
        captured_calls.append(dict(kwargs))
        # Return clean prose so the rest of run_phase2 doesn't crash
        return (
            "She sat on the bench. The moths kept finding the lamp. "
            "Astarion was quiet for once."
        )

    monkeypatch.setattr(runner_mod, "run_delegate", spy)

    runner_mod.run_phase2()

    assert len(captured_calls) >= 1, "run_phase2 must invoke run_delegate"
    for i, call in enumerate(captured_calls):
        assert call.get("strict_preamble_check") is True, (
            f"run_phase2 call {i} must invoke run_delegate with "
            f"strict_preamble_check=True (got {call.get('strict_preamble_check')!r}). "
            "T-D-3 preamble gate must be enforced at production runtime, "
            "not only in unit tests. Bug surfaced by /scrutinize on bd-b5p.5.3."
        )


# ---------------------------------------------------------------------------
# REGRESSION: bd-hmm 2026-05-27 — namespace bootstrap for standalone runner.py
# ---------------------------------------------------------------------------


def test_runner_bootstraps_namespace_for_standalone_invocation():
    """REGRESSION (bd-hmm): runner.py must self-bootstrap the synthetic
    `hermes_skills.autonovel_phase2` namespace + autonovel project root on
    sys.path so that the lazy imports inside run_phase2 work when invoked
    directly via `python3 ~/.hermes/skills/autonovel-phase2/runner.py`.

    Without this, run_phase2's first lazy import raises ModuleNotFoundError
    and the deployment never gets far enough to surface real runtime issues.

    This test exercises the bootstrap path by invoking the script as a
    subprocess with PATH stripped (NOT via pytest's existing namespace
    install — that hides the bug). The script will fail later somewhere
    downstream of the bootstrap (delegate_task parent-context error in
    production-equivalent venvs, or a missing-third-party-dep
    ImportError like pydantic in this PATH-stripped env using
    /usr/bin/python3) — both are acceptable; the ONLY thing the bd-hmm
    regression guards is that the `hermes_skills` and `api`
    ModuleNotFoundError classes do NOT appear, since those are the two
    bootstrap stanzas we own.
    """
    import subprocess

    skill_runner = Path(__file__).resolve().parent.parent / "runner.py"
    assert skill_runner.exists(), f"runner.py missing at {skill_runner}"

    # Clean env so PYTHONPATH from pytest doesn't mask the bug
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/tmp",  # avoid leaking pytest user state
    }
    result = subprocess.run(
        ["python3", str(skill_runner)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    assert (
        "ModuleNotFoundError: No module named 'hermes_skills'" not in combined
    ), (
        "runner.py failed at namespace import — the bd-hmm bootstrap "
        f"regressed. Output:\n{combined}"
    )
    assert "ModuleNotFoundError: No module named 'api'" not in combined, (
        "runner.py failed at autonovel project import — the bd-hmm "
        f"sys.path bootstrap regressed. Output:\n{combined}"
    )
