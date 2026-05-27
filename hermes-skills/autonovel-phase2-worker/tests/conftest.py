"""Shared pytest fixtures + sys.path wiring for autonovel-phase2-worker tests.

This conftest mirrors the bd-b5p.5.6 sibling
``hermes-skills/autonovel-phase2/tests/conftest.py`` so the
``hermes_skills.autonovel_phase2.*`` import path resolves for the
helper-coverage re-imports in ``test_helper_coverage.py`` (per
bd-b5p.7 §3.7 — pure helpers ship UNCHANGED into the new worker
context). The worker skill body itself lives one directory up at
``hermes-skills/autonovel-phase2-worker/SKILL.md`` (NEW, not yet on
disk during this /test wave — that's the /impl wave's job).

The SKILL.md doc tests in ``test_skill_shape.py`` will fail at
collection time with a clear FileNotFoundError if the worker SKILL.md
hasn't been written yet — correct TDD failure.

Bead: bd-b5p.7.2 (test wave for bd-b5p.7 kanban-worker spec)
Parent spec: bd-b5p.7 · OQ walk: bd-b5p.7.1 (CLOSED)
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path wiring — same shape as bd-b5p.5.6 sibling conftest
# ---------------------------------------------------------------------------

# This conftest lives at .../autonovel-phase2-worker/tests/conftest.py
_WORKER_TESTS_DIR = Path(__file__).resolve().parent
_WORKER_SKILL_DIR = _WORKER_TESTS_DIR.parent  # .../autonovel-phase2-worker/
_HERMES_SKILLS_DIR = _WORKER_SKILL_DIR.parent  # .../hermes-skills/
_AUTONOVEL_ROOT = _HERMES_SKILLS_DIR.parent  # .../autonovel/

# The Pattern 5 sibling whose pure helpers we re-import (UNCHANGED per §3.7)
_PHASE2_HELPERS_DIR = _HERMES_SKILLS_DIR / "autonovel-phase2"


def _install_hermes_skills_namespace() -> None:
    """Register ``hermes_skills.autonovel_phase2`` as a synthetic namespace
    package pointing at the hyphenated on-disk dir.

    Same trick as the bd-b5p.5.6 sibling conftest. The new worker dir
    (``autonovel-phase2-worker``) does NOT have a corresponding Python
    import path because its only Python content is the test files
    themselves; the SKILL body lives in markdown and is executed by
    the kanban-dispatched worker via ``execute_code`` snippets that
    import from ``hermes_skills.autonovel_phase2`` (the sibling).
    """
    if str(_AUTONOVEL_ROOT) not in sys.path:
        sys.path.insert(0, str(_AUTONOVEL_ROOT))

    if "hermes_skills" not in sys.modules:
        pkg = types.ModuleType("hermes_skills")
        pkg.__path__ = [str(_HERMES_SKILLS_DIR)]
        sys.modules["hermes_skills"] = pkg

    full_name = "hermes_skills.autonovel_phase2"
    if full_name not in sys.modules:
        sub = types.ModuleType(full_name)
        sub.__path__ = [str(_PHASE2_HELPERS_DIR)]
        sys.modules[full_name] = sub
        sys.modules["hermes_skills"].autonovel_phase2 = sub


_install_hermes_skills_namespace()


# ---------------------------------------------------------------------------
# Path fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def autonovel_root() -> Path:
    """Absolute path to the autonovel repo root (parent of hermes-skills/)."""
    return _AUTONOVEL_ROOT


@pytest.fixture()
def worker_skill_dir() -> Path:
    """Absolute path to the NEW autonovel-phase2-worker skill directory.

    The dir exists (this conftest sits inside it); SKILL.md may not yet
    exist during the /test wave — that's correct TDD.
    """
    return _WORKER_SKILL_DIR


@pytest.fixture()
def worker_skill_md_path(worker_skill_dir: Path) -> Path:
    """Path to the worker SKILL.md (NOT guaranteed to exist yet)."""
    return worker_skill_dir / "SKILL.md"


@pytest.fixture()
def phase2_helpers_dir() -> Path:
    """Absolute path to the bd-b5p.5.6 Pattern 5 sibling whose pure helpers
    ship unchanged per bd-b5p.7 §3.7."""
    return _PHASE2_HELPERS_DIR


@pytest.fixture()
def enqueue_script_path() -> Path:
    """Absolute path to the cron-fired enqueue wrapper script.

    Per spec §4.2 the script lives at
    ``/home/ubuntu/.hermes/scripts/enqueue-autonovel-phase2.sh``. The
    /impl wave creates it; tests assert against this fixed path so the
    cron-registration contract (§3.3) stays anchored.
    """
    return Path("/home/ubuntu/.hermes/scripts/enqueue-autonovel-phase2.sh")


@pytest.fixture()
def hermes_config_path() -> Path:
    """Path to the operator's ~/.hermes/config.yaml — sourced for the
    OQ-K-2 delegate child-timeout assertion in test_config_bump.py."""
    return Path.home() / ".hermes" / "config.yaml"


# ---------------------------------------------------------------------------
# Canonical kanban_complete-shape example pulled from spec §4.5
# ---------------------------------------------------------------------------


@pytest.fixture()
def canonical_kanban_complete_example() -> dict:
    """The canonical shape per spec §4.5: ``metadata=`` keys, ``artifacts=``
    list, ``summary`` single-line.

    Per OQ-K-3 amendment: ``file_path`` lives in ``artifacts=[...]``, NOT
    in ``metadata`` (the gateway notifier hooks the artifacts list for
    native attachment upload). ``worker_session_id`` is auto-stamped by
    the substrate per ``tools/kanban_tools.py:118-129`` — workers must
    NOT set it themselves.
    """
    return {
        "summary": "drafted abc12345... slop=0.12 voice_match=0.71",
        "metadata": {
            "queue_id": "abc1234567890def",
            "slop_penalty": 0.12,
            "voice_match": 0.71,
            "draft_excerpt": "Karlach leaned against the bedroll, fire still warm...",
            "status": "PASS",
        },
        "artifacts": [
            "/home/ubuntu/explore/autonovel/write/runs/phase2/publish_queue/abc1234567890def.json",
        ],
    }


@pytest.fixture()
def canonical_kanban_complete_fail_example() -> dict:
    """FAIL-case shape: firewall rejected. ``queue_id=None``,
    ``status=FAIL``, ``artifacts=[]`` (no file to attach)."""
    return {
        "summary": "drafted None... slop=99.00 voice_match=0.10 status=FAIL",
        "metadata": {
            "queue_id": None,
            "slop_penalty": 99.0,
            "voice_match": 0.10,
            "draft_excerpt": "...",
            "status": "FAIL",
        },
        "artifacts": [],
    }


# ---------------------------------------------------------------------------
# SKILL.md body loader — used across all doc-shape tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def worker_skill_body() -> str:
    """Read the SHIPPED worker SKILL.md body once for the session.

    During the /test wave this fixture raises FileNotFoundError —
    that's CORRECT TDD. The /impl wave creates SKILL.md and the
    failures resolve.
    """
    skill_md = _WORKER_SKILL_DIR / "SKILL.md"
    if not skill_md.exists():
        pytest.skip(
            f"worker SKILL.md not yet written at {skill_md} — "
            f"correct TDD failure pending /impl wave"
        )
    return skill_md.read_text(encoding="utf-8")
