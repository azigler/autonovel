# autonovel-phase1-smoke

Phase 1 minimum-viable Hermes-autonovel pipeline. Proves the autonovel
voice + slop-gate path runs end-to-end on Hermes Agent without Claude
Code as orchestrator.

**Bead:** `bd-b5p.4` · **Parent epic:** `bd-b5p`
**Spec:** `br show bd-b5p.4`

## What this delivers

A Hermes skill at `~/.hermes/skills/autonovel-phase1-smoke/` whose
`runner.py`:

1. Builds a hardcoded brief (post-Act-3 BG3 character study, Karlach
   POV).
2. Loads autonovel voice from `identity/self.md` + `voice_priors.json`
   + (optional) `few_shot_bank.md`.
3. Constructs the persona-suppressed prompt via
   `write/prompts.py::wrap_for_subagent(build_draft_system(...),
   build_draft_user(...))`.
4. POSTs to the same OpenAI-compatible endpoint Hermes is configured to
   use (read from `~/.hermes/config.yaml`, defaults
   `http://100.72.47.4:11434/v1` qwen3-coder:30b on the pico tailnet).
5. Writes the response to
   `write/runs/phase1-smoke/draft-<UTC-ISO>.md`.
6. Runs `evaluate.py::slop_score` on the prose and returns
   `slop_score=… status=PASS|FAIL`.

A daily cron (registered with `hermes cron create`) invokes this skill
at 09:00 local time.

## Install

```bash
# 1. From the autonovel repo root, symlink the skill into ~/.hermes/skills/
mkdir -p ~/.hermes/skills
ln -sfn "$(pwd)/hermes-skills/autonovel-phase1-smoke" \
    ~/.hermes/skills/autonovel-phase1-smoke

# 2. Verify the symlink resolves
ls -L ~/.hermes/skills/autonovel-phase1-smoke/SKILL.md

# 3. Make sure the runs output directory exists
mkdir -p write/runs/phase1-smoke
```

The skill loader scans `~/.hermes/skills/` recursively on agent start
(see Hermes primer §2.1) so no other registration is needed.

## Register the cron

```bash
# Note: --name/--skill/--workdir/--deliver MUST come before the
# positional `schedule` and `prompt` args, otherwise argparse mis-routes
# the prompt as an unrecognized flag.
hermes cron create \
    --name autonovel-phase1-smoke \
    --skill autonovel-phase1-smoke \
    --workdir /home/ubuntu/explore/autonovel \
    --deliver local \
    '0 9 * * *' \
    'Use the autonovel-phase1-smoke skill: run runner.py and report the slop_score line it prints.'
```

Confirmed working — produces output like:

```
Created job: 314830bae64a
  Name: autonovel-phase1-smoke
  Schedule: 0 9 * * *
  Skills: autonovel-phase1-smoke
  Workdir: /home/ubuntu/explore/autonovel
  Next run: 2026-05-26T09:00:00+00:00
```

After creation, Hermes warns that the gateway must be running for the
cron to actually fire on schedule (`hermes gateway install` for
systemd). For Phase 1 smoke we just need the registration; the
gateway-up next-firing test is **T5** (operator).

Verify it registered:

```bash
hermes cron list | grep autonovel-phase1-smoke
```

### Why `--deliver local`?

OQ-4 resolution: `local` writes cron output to
`~/.hermes/cron/output/autonovel-phase1-smoke/*.md` — simplest path, no
external auth, easy operator review. Phase 2 may add `--deliver
telegram` for "draft ready" pings; Phase 1 doesn't need it.

### Why `--workdir`?

Per the primer §1.7, `--workdir` injects the project's `CLAUDE.md` /
`AGENTS.md` as project context and uses it as cwd for `terminal` tool
calls. The runner reads `~/.hermes/config.yaml` for its model config
regardless, but `--workdir` keeps `evaluate.py` and the `write/runs/`
output tree on the agent's working path.

## Smoke test

```bash
# Run the deterministic smoke (no LLM call)
./hermes-skills/autonovel-phase1-smoke/smoke-test.sh
```

The smoke script automates T1–T4 + T6 from the spec:

| Test | What it checks | Auto |
|------|----------------|------|
| T1 | `SKILL.md` discoverable at `~/.hermes/skills/autonovel-phase1-smoke/` | yes |
| T2 | Runner produces `slop_score=...` line | yes (via runner.py) |
| T3 | `write/runs/phase1-smoke/draft-*.md` exists | yes |
| T4 | `hermes cron list` shows the job | yes (skip if not registered) |
| T5 | Next 09:00 firing succeeds | **operator** (wait for tomorrow) |
| T6 | `slop_score < 5.0` on most recent draft | yes |
| T7 | Human blind-rate ≥3/5 voice match | **operator** (manual) |

T2 + T6 require a live LLM endpoint; if the configured `base_url` is
unreachable, the runner exits 1 with a clear error.

### End-to-end via Hermes (manual)

```bash
# This actually drives the skill through Hermes' agent loop
hermes -z 'use the autonovel-phase1-smoke skill: invoke runner.py via terminal and surface the slop_score' --yolo
```

Expected: the agent reads the SKILL.md, runs `python3
~/.hermes/skills/autonovel-phase1-smoke/runner.py`, prints the
`slop_score=...` line.

## File layout

```
hermes-skills/autonovel-phase1-smoke/
├── SKILL.md          # Hermes skill body (YAML frontmatter + agent guidance)
├── runner.py         # The actual pipeline: brief → prompt → LLM → file → score
├── smoke-test.sh     # Automates T1-T4 + T6
└── README.md         # This file
```

Plus, on the autonovel side:

```
write/runs/phase1-smoke/
├── draft-20260526T090000Z.md   # one file per cron firing
├── draft-20260527T090000Z.md
└── ...
```

## OQ resolutions (from the spec)

| OQ | Question | Phase 1 resolution |
|----|----------|--------------------|
| OQ-1 | Do Hermes child agents inherit the parent system prompt? | **Sidestepped.** The runner passes identity context inline in the prompt frame, so it doesn't matter whether the child inherits or not. To be re-tested in Phase 2 when we move to true `delegate_task`. |
| OQ-2 | Does `skill_view` poison voice files? | **Not exercised.** Runner does not load voice files via `skill_view` — it reads them directly from `identity/*.md`, so no skill-loader header is prepended. Phase 2 (which uses the `autonovel-voice` skill pattern) needs the empirical answer. |
| OQ-3 | Does `WriteLoopState` survive across cron firings? | **Sidestepped.** Phase 1 writes one file per firing under a UTC-timestamped name; no shared state. Filesystem state confirmed working via smoke-test.sh. |
| OQ-4 | Cron delivery — local-file vs telegram? | **Decided: `--deliver local`.** Simplest path; no auth; operator reviews `~/.hermes/cron/output/autonovel-phase1-smoke/*.md`. Telegram considered Phase 2 quality-of-life. |
| OQ-5 | Does the cron prompt-injection scanner interfere? | **Not observed.** Skill body contains no flagged tokens (no "ignore previous instructions" / no obvious injection). Operator should watch first cron firing's stderr/log for `CronPromptInjectionBlocked` and downgrade SKILL.md wording if seen. |
| OQ-6 | Are Hermes' iteration_budget defaults sufficient? | **Yes.** Runner is a single-shot HTTP POST — no recursive tool use, no subagent spawning, well within the parent-90 / subagent-50 budgets. |

## Acceptance criteria mapping (T1–T7)

T1–T6 are checked by `smoke-test.sh`. T5 + T7 are operator tasks:

- **T5** — register the cron, wait for the next 09:00 firing, confirm
  the file in `~/.hermes/cron/output/autonovel-phase1-smoke/` records
  a successful invocation.
- **T7** — read the most recent draft alongside Entry 002 from
  `identity/few_shot_bank.md`; rate voice match 1–5. Phase 1 exits
  cleanly at ≥3/5.

## Limits + Phase 2 prerequisites

- Brief is hardcoded; Phase 2 reads from `briefs/*.json`.
- LLM call is direct HTTP, not `delegate_task`. Phase 2 wraps via
  `delegate_task` so iteration budget + observability hooks fire.
- No revision pass, no muse seeds, no AO3 staging — by design.
- Slop threshold is loose (5.0 vs production 3.0) so the smoke is
  forgiving while the pipeline stabilizes.

## See also

- `br show bd-b5p.4` — full Phase 1 spec
- `br show bd-b5p` — parent epic
- `~/explore/local-coding-models/refs/research/research-hermes-primer.md`
- `~/explore/local-coding-models/refs/research/research-autonovel-on-hermes.md`
- `~/explore/local-coding-models/refs/research/research-hermes-plugin-deepdive.md`
- `write/prompts.py` — `_PROSE_FRAME`, `build_draft_system`,
  `build_draft_user`, `wrap_for_subagent`
- `evaluate.py` — `slop_score`
