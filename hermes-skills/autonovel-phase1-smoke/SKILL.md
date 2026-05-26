---
name: autonovel-phase1-smoke
description: "Phase 1 minimum-viable autonovel — generate one paragraph of BG3 fanfic in the autonovel voice via runner.py, write it to write/runs/phase1-smoke/draft-<ts>.md, run evaluate.py to score it, and return slop_score. Bead bd-b5p.4. Hardcoded brief: post-Act-3 BG3 character study."
version: "0.1.0"
author: "autonovel"
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [autonovel, fanfic, phase1, smoke, bg3, voice]
    related_skills: []
    category: creative
---

# autonovel-phase1-smoke

Phase 1 minimum-viable autonovel: prove the pipeline runs end-to-end on
Hermes Agent without Claude Code as orchestrator. One skill, one
delegate, one paragraph, daily via cron.

**Bead:** bd-b5p.4 · **Parent epic:** bd-b5p

## What this skill does

1. Builds a brief (hardcoded scene: post-Act-3 BG3 character study).
2. Loads autonovel voice — `identity/self.md`, `identity/voice_priors.json`,
   `identity/few_shot_bank.md` if present — as system context.
3. Calls `write/prompts.py::build_draft_system` + `build_draft_user` to
   construct the persona-suppressed prompt frame.
4. Generates one paragraph (3–5 sentences) of BG3 fanfic via Hermes'
   underlying model (qwen3-coder:30b via the `custom` provider) — the
   parent agent invokes runner.py through the `terminal` tool, which
   POSTs to the configured `base_url/v1/chat/completions` endpoint.
5. Writes output to `write/runs/phase1-smoke/draft-<ISO-timestamp>.md`.
6. Runs `evaluate.py` slop-scoring on the output; returns the slop_score
   as a Pass/Fail (Pass = slop_penalty < 5.0).

## How to invoke

The skill ships with a single Python runner that does the work. The
agent should call it via the `terminal` tool:

```bash
cd /home/ubuntu/explore/autonovel
python3 ~/.hermes/skills/autonovel-phase1-smoke/runner.py
```

The runner prints a single line to stdout:

```
slop_score=2.3 file=write/runs/phase1-smoke/draft-20260526T091500Z.md status=PASS
```

Exit code 0 = pass (slop_penalty < 5.0), 1 = fail. The cron `--deliver
local` channel saves the full stdout into
`~/.hermes/cron/output/autonovel-phase1-smoke/*.md`.

## Brief (hardcoded for Phase 1)

> Post-Act 3, post-elven-ritual. Astarion and Karlach share a wordless
> moment in the garden of an inn somewhere outside Baldur's Gate.
> Neither of them is good at sitting still with something that isn't a
> threat. One paragraph (3–5 sentences). Close third-person, past tense.
> POV: Karlach.

The brief is hardcoded into `runner.py` for Phase 1 simplicity. Phase 2
will read briefs from `briefs/*.json`.

## Output contract

- File path: `write/runs/phase1-smoke/draft-<ISO-timestamp>.md`
  (timestamp is UTC, format `%Y%m%dT%H%M%SZ`)
- Content: raw prose only (no YAML frontmatter, no headers — matches
  the `_PROSE_FRAME` contract in `write/prompts.py`)
- The runner adds a small footer with the slop score for log review,
  separated by `\n\n---\n` so the prose stays parseable for evaluate.py

## Acceptance criteria (T1–T7 from the spec)

- T1: `hermes skills list` (or `find ~/.hermes/skills/autonovel-phase1-smoke`)
  shows the skill is discoverable
- T2: `hermes -z 'use the autonovel-phase1-smoke skill: run runner.py' --yolo`
  produces a paragraph
- T3: `ls write/runs/phase1-smoke/draft-*.md` shows at least one file
- T4: `hermes cron list` shows the registered job after running
  the cron create command in the README
- T5: next 09:00 firing — manual operator check (out of scope for
  smoke-test.sh)
- T6: `evaluate.py` slop_score < 5.0
- T7: human blind-rate — operator task, out of scope

## See also

- README.md — install + cron registration + smoke-test instructions
- smoke-test.sh — automates T1–T4 + T6
- runner.py — the actual implementation
- bd-b5p.4 — Phase 1 spec
- bd-b5p — parent epic
- `~/explore/local-coding-models/refs/research/research-hermes-primer.md`
- `~/explore/local-coding-models/refs/research/research-autonovel-on-hermes.md`
