"""Shared Claude API client for the write loop.

Centralises the httpx call pattern so that draft_chapter() and
call_revision_model() both go through a single function.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Load .env from repo root (same convention as draft_chapter.py)
_BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(_BASE_DIR / ".env")


def _get_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. "
            "Export it or add it to the .env file."
        )
    return key


def _get_model() -> str:
    return os.environ.get("AUTONOVEL_WRITER_MODEL", "claude-sonnet-4-6")


def _get_api_base() -> str:
    return os.environ.get("AUTONOVEL_API_BASE_URL", "https://api.anthropic.com")


def call_claude(
    system: str,
    prompt: str,
    max_tokens: int = 16000,
    temperature: float = 0.8,
) -> str:
    """Call the Anthropic Messages API and return the assistant text.

    Uses the same httpx pattern as the original ``draft_chapter.py``
    top-level script.

    Args:
        system: System prompt that sets the writer's voice and constraints.
        prompt: User-role message (the specific writing task).
        max_tokens: Maximum tokens in the response.
        temperature: Sampling temperature (0.8 for drafting, 0.7 for revision).

    Returns:
        The text content of the first content block in the response.

    Raises:
        RuntimeError: If ANTHROPIC_API_KEY is missing.
        httpx.HTTPStatusError: If the API returns a non-2xx status.
    """
    api_key = _get_api_key()
    model = _get_model()
    api_base = _get_api_base()

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }

    resp = httpx.post(
        f"{api_base}/v1/messages",
        headers=headers,
        json=payload,
        timeout=600,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]
