#!/usr/bin/env python3
"""autonovel-phase1-smoke runner.

Phase 1 minimum-viable autonovel: produce one paragraph of BG3 fanfic in
the autonovel voice, write it to disk, score it with evaluate.py, return
PASS/FAIL.

Bead: bd-b5p.4 · Parent: bd-b5p

Design (per spec §4.1 and the autonovel-on-hermes research):

- We invoke the LLM via a direct HTTP POST to the OpenAI-compatible
  endpoint Hermes is already configured for (read from
  ~/.hermes/config.yaml). This is simpler than scripting
  `delegate_task` from skill-side Python — that API is meant to be
  driven by the agent during a conversation turn, not from a child
  process. Phase 2 will move to a true delegate_task pattern.

- Brief is hardcoded (Phase 1 simplicity). Phase 2 reads briefs/*.json.

- We reuse `write/prompts.py::build_draft_system` and `build_draft_user`
  unchanged — the persona-suppression frame (`_PROSE_FRAME`) is the
  contract that keeps the LLM from emitting "Here is the paragraph"
  preamble. Do not paraphrase the frame.

- Output goes to write/runs/phase1-smoke/draft-<UTC-ISO>.md so the cron
  job and operator can find each run by timestamp.

- evaluate.py::slop_score is the post-generation gate. We use a
  threshold of slop_penalty < 5.0 for Phase 1 (looser than the canonical
  3.0 in evaluate_fanfic.evaluate_gate — Phase 1 is about proving the
  pipeline, not hitting full production quality).

Environment overrides (all optional):
- AUTONOVEL_BASE_URL — defaults to value from ~/.hermes/config.yaml
- AUTONOVEL_MODEL — defaults to value from ~/.hermes/config.yaml
- AUTONOVEL_ROOT — defaults to /home/ubuntu/explore/autonovel
- AUTONOVEL_SLOP_THRESHOLD — defaults to 5.0
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Hardcoded Phase 1 brief
# ---------------------------------------------------------------------------

PHASE1_BRIEF_TEXT = """\
Post-Act 3, post-elven-ritual. Astarion and Karlach are at an inn somewhere
outside Baldur's Gate. It is the kind of summer night where the windows
have been left open and the moths keep finding the lamp. They share the
garden bench. Neither of them is good at sitting still with something
that isn't a threat.

POV: Karlach, close third-person, past tense.
Length: one paragraph (3-5 sentences). No section break. No epigraph.

Constraint: Karlach's engine is quiet for once. Astarion is awake. They
are not talking about anything important. The paragraph is the silence
between two people who have spent a year expecting to die.
"""

PHASE1_FANDOM_CONTEXT = """\
Baldur's Gate 3 (Larian, 2023). Karlach Cliffgate: tiefling barbarian,
infernal engine in her chest, ten years in Avernus as Zariel's enforcer,
freed in Act 1, the engine kept her alive but is killing her. Direct,
loud, generous, terrified of being alone, gets blackout-furious. Calls
people "soldier".

Astarion Ancunin: pale elf rogue, two-hundred-year vampire spawn of
Cazador, freed in Act 1. Sharp-tongued, vain, deflects with theatrics,
underneath it is a survivor who never expected to live past the next
hour. After the ritual (Cazador dead, Astarion not Ascended), still
vampire spawn, still can't be in sunlight. Performs disdain. Means
about half of it.

Post-Act 3 setting: the Heroes of Baldur's Gate have just saved the
city. Both characters are alive in the canonical "good" ending. The
Netherbrain is dead. Karlach is on borrowed weeks before the engine
gives out (unless she goes to Avernus — choice unresolved here). They
are processing surviving.
"""


# ---------------------------------------------------------------------------
# Phase 1 minimal StoryBrief stand-in
# ---------------------------------------------------------------------------


class _Brief:
    """Minimal stand-in for write.brief.StoryBrief.

    `build_draft_user` only reads `target_length`, so we don't need the
    full StoryBrief schema for Phase 1.
    """

    target_length = 120  # one paragraph; ~3-5 sentences in this voice


# ---------------------------------------------------------------------------
# Config / paths
# ---------------------------------------------------------------------------


def _autonovel_root() -> Path:
    return Path(
        os.environ.get("AUTONOVEL_ROOT", "/home/ubuntu/explore/autonovel")
    )


def _load_hermes_config() -> dict:
    """Read ~/.hermes/config.yaml and return its `model` block as a dict.

    We intentionally don't import PyYAML to keep this runner dependency-free
    (Hermes provides PyYAML, but the runner may also be invoked from a
    naked python3). Falls back to defaults if the file isn't readable.
    """
    cfg_path = Path.home() / ".hermes" / "config.yaml"
    base_url = "http://localhost:11434/v1"
    model = "qwen3-coder:30b"
    if cfg_path.exists():
        try:
            import yaml  # type: ignore

            cfg = yaml.safe_load(cfg_path.read_text()) or {}
            model_cfg = cfg.get("model", {}) or {}
            base_url = model_cfg.get("base_url", base_url) or base_url
            model = model_cfg.get("default", model) or model
        except ImportError:
            # Naive line parser for the model: block — enough for Phase 1.
            in_model = False
            for raw in cfg_path.read_text().splitlines():
                line = raw.rstrip()
                if line == "model:":
                    in_model = True
                    continue
                if in_model:
                    if line and not line.startswith(" "):
                        break
                    stripped = line.strip()
                    if stripped.startswith("base_url:"):
                        base_url = stripped.split(":", 1)[1].strip()
                    elif stripped.startswith("default:"):
                        model = stripped.split(":", 1)[1].strip()
    base_url = os.environ.get("AUTONOVEL_BASE_URL", base_url)
    model = os.environ.get("AUTONOVEL_MODEL", model)
    return {"base_url": base_url, "model": model}


# ---------------------------------------------------------------------------
# Identity loading (Phase 1: best-effort, never fail)
# ---------------------------------------------------------------------------


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return ""


def _load_identity_context(root: Path) -> dict:
    """Build the `context` dict that `build_draft_system` expects.

    Reads identity files if they exist; returns sane empty defaults if
    they don't. OQ-1 (does the child inherit the parent system prompt?)
    is sidestepped: we always pass identity explicitly inside the prompt
    frame.
    """
    self_md = _read_text(root / "identity" / "self.md")
    voice_priors_path = root / "identity" / "voice_priors.json"
    few_shot_bank = _read_text(root / "identity" / "few_shot_bank.md")

    voice_priors_text = ""
    if voice_priors_path.exists():
        try:
            vp = json.loads(voice_priors_path.read_text())
            # Render as a short prose block — the existing
            # build_draft_system expects identity to be a string, not a
            # nested dict, so we flatten.
            voice_priors_text = "\nVOICE PRIORS (autonovel):\n" + json.dumps(
                vp, indent=2
            )
        except json.JSONDecodeError:
            voice_priors_text = ""

    # Minimal anti-slop rules — the production write loop assembles a
    # richer block from evaluate.TIER1_BANNED + STRUCTURAL_AI_TICS but
    # for Phase 1 we only need enough that the prompt frame isn't empty.
    anti_slop_rules = (
        "Do not use these words: delve, utilize, leverage, facilitate, "
        "elucidate, tapestry, paradigm, synergy, holistic, myriad, plethora. "
        "Do not use rhetorical formulas like 'It wasn't X, it was Y'. "
        "Vary sentence length. No more than 8 em-dashes per 1000 words. "
        "No section breaks (---) as rhythm crutches."
    )

    identity_block = self_md
    if voice_priors_text:
        identity_block = identity_block + "\n" + voice_priors_text
    if few_shot_bank:
        # Few-shot bank can be very long; trim to first ~3K chars for
        # Phase 1 to keep the prompt under qwen3-coder's effective
        # context budget.
        identity_block = (
            identity_block
            + "\n\nVOICE ANCHORS (recent successful samples — match this register):\n"
            + few_shot_bank[:3000]
        )

    return {
        "identity": identity_block,
        "anti_slop_rules": anti_slop_rules,
        "brief_text": PHASE1_BRIEF_TEXT,
        "fandom_context": PHASE1_FANDOM_CONTEXT,
    }


# ---------------------------------------------------------------------------
# LLM call — direct HTTP to the OpenAI-compatible endpoint
# ---------------------------------------------------------------------------


def _call_llm(base_url: str, model: str, prompt: str) -> str:
    """POST a single-message chat completion. Returns the assistant text.

    Why direct HTTP rather than `delegate_task`: per the autonovel-on-hermes
    research §4 (Phase 1 design), the minimum-viable demo just needs to
    prove the pipeline works. `delegate_task` is the parent-agent → child
    seam and isn't meant to be invoked from skill-side Python. The same
    base_url Hermes posts to (qwen3-coder:30b on Ollama at pico) accepts
    our direct POST.
    """
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        # Phase 1: tight generation. One paragraph is ~150-200 tokens;
        # 800 tokens is a generous ceiling that still cuts off runaway
        # rambles. No temperature override — let the provider default
        # apply (Ollama uses 0.8 by default which matches our needs).
        "max_tokens": 800,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    # 300s timeout — qwen3-coder:30b cold-start on pico can be slow when
    # the model isn't already in Ollama's resident set; warm-path is ~10s.
    timeout_s = float(os.environ.get("AUTONOVEL_LLM_TIMEOUT", "300"))
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        raise SystemExit(
            f"runner.py: LLM call to {url} failed: {e}\n"
            f"  Hint: is Hermes' base_url reachable? Check ~/.hermes/config.yaml."
        ) from e
    parsed = json.loads(body)
    choices = parsed.get("choices", [])
    if not choices:
        raise SystemExit(
            f"runner.py: LLM returned no choices. Body: {body[:500]}"
        )
    return choices[0]["message"]["content"]


# ---------------------------------------------------------------------------
# Slop scoring
# ---------------------------------------------------------------------------


def _slop_score(root: Path, prose: str) -> dict:
    """Import evaluate.py from the autonovel root and run slop_score.

    We add the root to sys.path lazily so the runner stays usable from
    anywhere on disk (it lives under ~/.hermes/skills/, not under the
    autonovel checkout).
    """
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import evaluate  # type: ignore

    return evaluate.slop_score(prose)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    root = _autonovel_root()
    if not (root / "write" / "prompts.py").exists():
        print(
            f"runner.py: autonovel root not found at {root}; "
            f"set AUTONOVEL_ROOT to override.",
            file=sys.stderr,
        )
        return 2

    # Add the autonovel root to sys.path so we can import write.prompts.
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from write.prompts import (  # type: ignore
        build_draft_system,
        build_draft_user,
        wrap_for_subagent,
    )

    context = _load_identity_context(root)
    soul = _read_text(root / "identity" / "soul.md")

    system_p = build_draft_system(context, soul)
    user_p = build_draft_user(
        brief=_Brief(),
        context=context,
        chapter_num=1,
        total_chapters=1,
        previous_chapter_tail="",
        seeds=None,
        length_retry=False,
        previous_word_count=0,
        length_enforcement="prompt",
    )
    prompt = wrap_for_subagent(system_p, user_p)

    cfg = _load_hermes_config()
    print(
        f"runner.py: calling {cfg['model']} at {cfg['base_url']} "
        f"(prompt {len(prompt)} chars)",
        file=sys.stderr,
    )
    started = time.time()
    prose = _call_llm(cfg["base_url"], cfg["model"], prompt)
    elapsed = time.time() - started

    # Write the draft. Timestamp is UTC so cron-from-anywhere produces
    # comparable filenames.
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = root / "write" / "runs" / "phase1-smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"draft-{ts}.md"

    # Score the prose (not the footer) so the metric reflects the actual
    # generation, not the runner's own annotations.
    score = _slop_score(root, prose)

    threshold = float(os.environ.get("AUTONOVEL_SLOP_THRESHOLD", "5.0"))
    slop_penalty = float(score.get("slop_penalty", 99.0))
    status = "PASS" if slop_penalty < threshold else "FAIL"

    footer = (
        f"\n\n---\n"
        f"<!-- autonovel-phase1-smoke metadata\n"
        f"timestamp_utc: {ts}\n"
        f"model: {cfg['model']}\n"
        f"base_url: {cfg['base_url']}\n"
        f"elapsed_s: {round(elapsed, 2)}\n"
        f"slop_penalty: {slop_penalty}\n"
        f"slop_threshold: {threshold}\n"
        f"status: {status}\n"
        f"bead: bd-b5p.4\n"
        f"-->\n"
    )
    out_path.write_text(prose + footer, encoding="utf-8")

    # Single-line summary for the cron delivery channel.
    rel = out_path.relative_to(root)
    print(f"slop_score={slop_penalty} file={rel} status={status}")

    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
