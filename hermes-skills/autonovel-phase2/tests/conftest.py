"""Shared pytest fixtures + sys.path wiring for autonovel-phase2 tests.

The on-disk skill directory is ``hermes-skills/autonovel-phase2/``. The
hyphenated path isn't directly importable as a Python package, so this
conftest installs a synthetic ``hermes_skills.autonovel_phase2`` namespace
package that points at the real directory. Impl modules
(identity_loader.py, anchor_selector.py, voice_match.py, staging.py,
runner.py) live as siblings of this ``tests/`` dir and are imported by
real planned module paths::

    from hermes_skills.autonovel_phase2.runner import run_delegate
    from hermes_skills.autonovel_phase2.anchor_selector import select_anchors
    from hermes_skills.autonovel_phase2.voice_match import voice_match_score
    from hermes_skills.autonovel_phase2.staging import stage_draft
    from hermes_skills.autonovel_phase2.identity_loader import load_identity

If the impl modules don't exist yet (correct TDD), the test fails at
runtime with a clear ImportError — NOT at collection time.

The autonovel repo root is also injected into ``sys.path`` so tests can
import ``api.models``, ``api.queue``, ``evaluate`` etc. — these are
production modules the Phase 2 skill consumes unchanged.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path wiring
# ---------------------------------------------------------------------------

# The skill directory (hermes-skills/autonovel-phase2) and the autonovel
# repo root (parent of hermes-skills). We compute these once and stash them
# as session-level constants.

_SKILL_DIR = Path(__file__).resolve().parent.parent  # .../autonovel-phase2/
_HERMES_SKILLS_DIR = _SKILL_DIR.parent  # .../hermes-skills/
_AUTONOVEL_ROOT = _HERMES_SKILLS_DIR.parent  # .../autonovel/


def _install_hermes_skills_namespace() -> None:
    """Register hermes_skills.autonovel_phase2 as a synthetic namespace package.

    The on-disk dir is hyphenated; this glue lets tests use the
    Python-canonical underscored path the spec calls for.
    """
    # Ensure autonovel repo root is importable for api.*, evaluate, etc.
    if str(_AUTONOVEL_ROOT) not in sys.path:
        sys.path.insert(0, str(_AUTONOVEL_ROOT))

    # Create the hermes_skills package
    if "hermes_skills" not in sys.modules:
        pkg = types.ModuleType("hermes_skills")
        pkg.__path__ = [str(_HERMES_SKILLS_DIR)]
        sys.modules["hermes_skills"] = pkg

    # Create the autonovel_phase2 subpackage pointing at the hyphenated dir
    full_name = "hermes_skills.autonovel_phase2"
    if full_name not in sys.modules:
        sub = types.ModuleType(full_name)
        sub.__path__ = [str(_SKILL_DIR)]
        sys.modules[full_name] = sub
        sys.modules["hermes_skills"].autonovel_phase2 = sub


_install_hermes_skills_namespace()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def autonovel_root() -> Path:
    """Absolute path to the autonovel repo root (parent of hermes-skills/)."""
    return _AUTONOVEL_ROOT


@pytest.fixture()
def skill_dir() -> Path:
    """Absolute path to the autonovel-phase2 skill directory."""
    return _SKILL_DIR


@pytest.fixture()
def few_shot_bank_text(autonovel_root: Path) -> str:
    """The real identity/few_shot_bank.md text — anchors source."""
    return (autonovel_root / "identity" / "few_shot_bank.md").read_text(
        encoding="utf-8"
    )


@pytest.fixture()
def clean_publish_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Redirect api.queue.QUEUE_DIR to a tmp dir for the test duration.

    Same pattern as autonovel/tests/conftest.py::_clean_queue. The
    Phase 2 staging tests use this to verify enqueue() lands files
    without polluting the real publish_queue/.
    """
    queue_dir = tmp_path / "publish_queue"
    queue_dir.mkdir()
    # Late import so api.queue can be optional during early TDD passes
    api_queue = importlib.import_module("api.queue")
    monkeypatch.setattr(api_queue, "QUEUE_DIR", queue_dir)
    return queue_dir


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip env vars that could leak production behavior into tests.

    Phase 2 runner.py / staging.py should not pick up AUTONOVEL_ROOT
    from the host shell during a test run.
    """
    for var in (
        "AUTONOVEL_BASE_URL",
        "AUTONOVEL_MODEL",
        "AUTONOVEL_ROOT",
        "AUTONOVEL_SLOP_THRESHOLD",
        "AUTONOVEL_LLM_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)
    # MOCK_MODE controls api/mock.py; keep on for safety during staging tests.
    monkeypatch.setenv("MOCK_MODE", "true")


@pytest.fixture()
def fake_delegate_task(monkeypatch: pytest.MonkeyPatch):
    """Install a spy-able replacement for the Hermes delegate_task primitive.

    The Phase 2 runner.run_delegate should call into delegate_task. Tests
    that need to assert call args (T-D-1, T-D-2) install this spy and
    inspect ``calls`` after invocation.
    """
    import json

    calls: list[dict] = []

    def _spy(
        *,
        goal: str,
        context: str = "",
        toolsets: list | None = None,
        role: str = "leaf",
        max_iterations: int | None = None,
        **kwargs,
    ) -> str:
        calls.append(
            {
                "goal": goal,
                "context": context,
                "toolsets": toolsets or [],
                "role": role,
                "max_iterations": max_iterations,
                "kwargs": kwargs,
            }
        )
        # Return shape mirrors Hermes' delegate_task JSON-string contract.
        return json.dumps(
            {
                "results": [
                    {
                        "summary": (
                            "She sat on the bench. The moths kept finding "
                            "the lamp. Astarion was quiet for once."
                        ),
                        "child_session_id": "test-child-session",
                    }
                ]
            }
        )

    # Install on the planned runner module location. Tests may need to
    # patch in additional locations once the impl lands.
    try:
        runner_mod = importlib.import_module(
            "hermes_skills.autonovel_phase2.runner"
        )
        monkeypatch.setattr(runner_mod, "delegate_task", _spy, raising=False)
    except ImportError:
        # Impl not present yet — the spy is still useful for direct injection
        # via the returned object.
        pass

    return types.SimpleNamespace(spy=_spy, calls=calls)
