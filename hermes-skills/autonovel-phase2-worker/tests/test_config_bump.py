"""Config-state test for the OQ-K-2 delegate_task dual-clock alignment.

Per spec §3.2 (amended via bd-b5p.7.1 OQ-K-2 walk):
    ``delegation.child_timeout_seconds`` MUST be bumped from the
    600s default to **1800s** in ``~/.hermes/config.yaml`` so the
    delegate_task per-child timeout aligns with the worker's
    ``--max-runtime 30m`` budget. Otherwise a 12-min generation would
    hit the delegate_task ceiling before the worker's budget is
    exhausted.

This is a CONFIG-STATE test. On a fresh system it FAILS until the
bd-b5p.6 operationalize bead lands the config bump. That's correct
TDD — the test guards against the operational drift documented in
the OQ-K-2 amendment.

Covers spec test cases T-K-1 (operational prereq), T-K-8 (failure-
mode rationale), spec §3.2.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REQUIRED_CHILD_TIMEOUT_SECONDS = 1800  # 30 min, per OQ-K-2 amendment
HERMES_DEFAULT = 600  # Hermes default (tools/delegate_tool.py:367-391)


# ---------------------------------------------------------------------------
# Pure-text parsing helper (avoid yaml dep — config file is yaml-ish)
# ---------------------------------------------------------------------------


def _extract_child_timeout_from_config(config_text: str) -> int | None:
    """Extract ``delegation.child_timeout_seconds`` from a yaml config.

    Hand-parses (vs. importing pyyaml) so the test stays dependency-free.
    Looks for the ``child_timeout_seconds: <int>`` line under a
    ``delegation:`` block.
    """
    in_delegation_block = False
    for raw_line in config_text.splitlines():
        # Detect block heading (top-level key, no leading whitespace)
        stripped = raw_line.rstrip()
        if re.match(r"^delegation:\s*$", stripped):
            in_delegation_block = True
            continue
        # Detect leaving the block: another top-level key
        if (
            in_delegation_block
            and re.match(r"^[A-Za-z_][\w-]*:\s*", stripped)
            and not raw_line.startswith((" ", "\t"))
        ):
            in_delegation_block = False
        # Match the timeout line inside the block
        if in_delegation_block:
            m = re.match(
                r"^\s+child_timeout_seconds:\s*(\d+)\s*(?:#.*)?$",
                raw_line,
            )
            if m:
                return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Parser sanity (catches bugs in our parser, not the config itself)
# ---------------------------------------------------------------------------


def test_parser_extracts_value_from_minimal_config():
    """Sanity: parser handles a minimal config snippet."""
    snippet = """
delegation:
  child_timeout_seconds: 1800
  max_concurrent_children: 3
"""
    assert _extract_child_timeout_from_config(snippet) == 1800


def test_parser_returns_none_when_key_missing():
    """Sanity: parser returns None when the key isn't set."""
    snippet = """
delegation:
  max_concurrent_children: 3
"""
    assert _extract_child_timeout_from_config(snippet) is None


def test_parser_ignores_key_outside_delegation_block():
    """Sanity: parser only matches the key under delegation:."""
    snippet = """
other:
  child_timeout_seconds: 99
delegation:
  max_concurrent_children: 3
"""
    assert _extract_child_timeout_from_config(snippet) is None


def test_parser_handles_inline_comment():
    """Sanity: parser handles `# was 600 default; align with...` trailing
    comment per the spec §3.2 example."""
    snippet = """
delegation:
  child_timeout_seconds: 1800  # was 600 default; align with worker --max-runtime 30m
"""
    assert _extract_child_timeout_from_config(snippet) == 1800


# ---------------------------------------------------------------------------
# CRITICAL: the actual config bump assertion
# ---------------------------------------------------------------------------


def test_hermes_config_exists(hermes_config_path: Path):
    """Pre-condition: ``~/.hermes/config.yaml`` exists on this host."""
    assert hermes_config_path.exists(), (
        f"~/.hermes/config.yaml missing at {hermes_config_path}. "
        f"Hermes gateway must be installed (it is per bd-b5p.7 §2.2)."
    )


def test_child_timeout_bumped_to_at_least_1800s(hermes_config_path: Path):
    """T-K-2 (OQ-K-2 amendment): ``delegation.child_timeout_seconds`` MUST be
    ≥ 1800s to align with the worker's 30m --max-runtime.

    Otherwise a 12+min generation hits the delegate_task per-child cap
    before the worker budget is exhausted, returning a timeout the
    worker would then have to handle as a recoverable error rather than
    letting generation complete cleanly.

    Per spec §3.2: operator applies once in ``~/.hermes/config.yaml``::

        delegation:
          child_timeout_seconds: 1800  # was 600 default

    This test FAILS on a fresh system; bd-b5p.6 operationalize lands
    the config bump (correct TDD).
    """
    if not hermes_config_path.exists():
        pytest.skip(
            f"~/.hermes/config.yaml not present at {hermes_config_path}"
        )
    text = hermes_config_path.read_text(encoding="utf-8")
    value = _extract_child_timeout_from_config(text)

    assert value is not None, (
        "delegation.child_timeout_seconds key MISSING from "
        f"{hermes_config_path}. Per spec §3.2 (OQ-K-2 amendment), "
        f"this MUST be set to {REQUIRED_CHILD_TIMEOUT_SECONDS}s to "
        f"align with the worker's --max-runtime 30m. "
        f"Default ({HERMES_DEFAULT}s) is too short for autonovel "
        f"generation (3-20min)."
    )
    assert value >= REQUIRED_CHILD_TIMEOUT_SECONDS, (
        f"delegation.child_timeout_seconds = {value}s is below the "
        f"required {REQUIRED_CHILD_TIMEOUT_SECONDS}s. Per spec §3.2 "
        f"(OQ-K-2 amendment), this must be bumped to align with the "
        f"worker's --max-runtime 30m budget. Otherwise a 12+min "
        f"generation hits the delegate_task per-child cap before the "
        f"worker budget is exhausted. Fix: edit "
        f"{hermes_config_path}::delegation.child_timeout_seconds: "
        f"{REQUIRED_CHILD_TIMEOUT_SECONDS}"
    )


def test_child_timeout_not_set_below_hermes_default(hermes_config_path: Path):
    """Defensive: even if the operator de-tunes, never below Hermes's
    own 600s default — that would silently regress the dual-clock
    alignment AND every other delegate_task user on this host."""
    if not hermes_config_path.exists():
        pytest.skip(
            f"~/.hermes/config.yaml not present at {hermes_config_path}"
        )
    text = hermes_config_path.read_text(encoding="utf-8")
    value = _extract_child_timeout_from_config(text)
    if value is None:
        pytest.skip("child_timeout_seconds not explicitly set")
    assert value >= HERMES_DEFAULT, (
        f"delegation.child_timeout_seconds = {value}s is below "
        f"Hermes's own default ({HERMES_DEFAULT}s) — this would "
        f"regress every delegate_task caller on this host."
    )
