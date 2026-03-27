"""Shared fixtures for AO3 API proxy tests."""

from __future__ import annotations

import os
import shutil
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _mock_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure MOCK_MODE is enabled for every test."""
    monkeypatch.setenv("MOCK_MODE", "true")


@pytest.fixture()
def _clean_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path]:
    """Redirect the publish queue to a temporary directory and clean up after."""
    queue_dir = tmp_path / "publish_queue"
    queue_dir.mkdir()
    monkeypatch.setattr("api.queue.QUEUE_DIR", queue_dir)
    yield queue_dir
    if queue_dir.exists():
        shutil.rmtree(queue_dir)


@pytest.fixture()
def client(_clean_queue: Path) -> TestClient:
    """TestClient wired to the FastAPI app in mock mode.

    The _clean_queue fixture ensures every test gets an isolated publish queue.
    We must force-reload the module so MOCK_MODE picks up the env var.
    """
    # Force re-evaluation of MOCK_MODE from the environment
    os.environ["MOCK_MODE"] = "true"

    import importlib

    import api.server

    importlib.reload(api.server)

    return TestClient(api.server.app)
