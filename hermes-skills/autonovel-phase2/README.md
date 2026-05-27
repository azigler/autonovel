# autonovel-phase2

Phase 2 Hermes-autonovel pipeline. Hermes-native `delegate_task`
generation with POV-aware voice anchors, staged to `publish_queue/`
for AO3 review (no live posting yet).

**Bead:** `bd-b5p.5` · **Parent epic:** `bd-b5p` · **Predecessor:**
`bd-b5p.4` (Phase 1, closed) · **Architecture revision:** `bd-b5p.5.6`
(Pattern 5 — agent-recipe SKILL, not executable runner)
**Spec:** `br show bd-b5p.5`

## What this delivers

A Hermes skill at `~/.hermes/skills/autonovel-phase2/` whose body is a
PROCEDURAL RECIPE the parent Hermes agent executes IN-CONVERSATION.
The recipe walks 5 steps using the agent's own tools (`read_file`,
`execute_code`, `delegate_task`) — the pure-Python helpers in
`runner.py` / `staging.py` / `voice_match.py` / `anchor_selector.py` /
`identity_loader.py` are imported from `execute_code` snippets the
agent emits:

1. **Step 1** (`read_file`): load `identity/self.md`,
   `identity/voice_priors.json`, `identity/few_shot_bank.md`,
   `identity/soul.md` directly (OQ-2 ACCEPT: the Hermes skill loader's
   attribution preamble is bypassed so it cannot contaminate the voice
   context).
2. **Step 2** (`execute_code`): import `anchor_selector.select_anchors`
   (POV-aware, replaces Phase 1's blind 3K-char trim) +
   `write.prompts.wrap_for_subagent` + `runner._wrap_prompt`; emit the
   `_PROSE_FRAME`-wrapped goal string.
3. **Step 3** (`delegate_task` as the agent's OWN tool): call Hermes'
   native `delegate_task(goal=<frame>, context="", toolsets=[],
   role="leaf", max_iterations=10)`. The AIAgent's dispatcher injects
   `parent_agent=self` transparently (`run_agent.py:_dispatch_delegate_task`).
4. **Step 4** (`execute_code`): import `runner._extract_summary` +
   `runner._check_preamble` + `voice_match.voice_match_score` +
   `evaluate.slop_score` + `staging.stage_draft`. Parse the delegate
   result, score (production threshold 3.0 slop, advisory 0.5 voice),
   and persist to `publish_queue/<queue_id>.json` with `status=PENDING`.
5. **Step 5**: report the single-line summary
   `slop_penalty=<f> voice_match=<f> queue_id=<hex|none> status=PASS|FAIL`.

A daily cron registered via `hermes cron create` invokes this skill
at 21:00 local time alongside `autonovel-phase1-smoke` for one
observation week.

## Install

```bash
# 1. Symlink the skill into ~/.hermes/skills/ (Phase 1 stays
#    independently installed — Phase 2 coexists, NOT a replacement)
mkdir -p ~/.hermes/skills
ln -sfn "$(pwd)/hermes-skills/autonovel-phase2" \
    ~/.hermes/skills/autonovel-phase2

# 2. Verify
ls -L ~/.hermes/skills/autonovel-phase2/SKILL.md

# 3. publish_queue/ already exists from the AO3 API proxy work; no
#    setup needed.
```

## Register the cron

The canonical Pattern 5 registration. The `/skill:` token tells the
Hermes cron daemon to load this SKILL body as the prompt prefix when
the AIAgent starts the conversation:

```bash
hermes cron create '0 21 * * *' '/skill:autonovel-phase2 run' --deliver local
```

Verify:

```bash
hermes cron list | grep autonovel
# Expect BOTH autonovel-phase1-smoke AND autonovel-phase2 listed.
```

## Manual smoke

To re-fire a registered cron job on demand (uses the same AIAgent
path as the scheduled run — same parent_agent context, same SKILL
body loading):

```bash
hermes cron list                              # find the job-id
hermes cron run <job-id>                      # fire it
ls ~/.hermes/cron/output/autonovel-phase2/    # inspect captured summary
```

**Do NOT** try to invoke the skill any of these ways — they all fail
per bd-b5p.5.5 research:

```bash
# WRONG — runner.py is a library, not an executable. No main() exists.
python3 ~/.hermes/skills/autonovel-phase2/runner.py

# WRONG — terminal_tool subprocess has no parent_agent context;
# delegate_task errors; under --yolo the agent fabricates a success
# summary (the confabulation bug, bd-b5p.5.7).
hermes -z 'use the autonovel-phase2 skill: invoke runner.py via terminal_tool' --yolo
```

## Run the tests

```bash
cd /home/ubuntu/explore/autonovel
.venv/bin/python3 -m pytest hermes-skills/autonovel-phase2/tests/ -v
```

The pytest suite covers the pure-helper surface (anchor selection,
voice match, identity load, AO3 staging, prompt wrap, preamble gate,
extract summary) plus SKILL.md doc tests that guard the 5-step recipe
shape. **65 cases** total as of bd-b5p.5.6 (was 61 pre-rewrite;
deleted the 16 ``run_phase2`` orchestration / regression / bootstrap
tests and added 17 doc tests + direct `_extract_summary` /
`_check_preamble` / `_wrap_prompt` tests).

The bd-b5p.5.6 rewrite deliberately retired the `T-E-*` end-to-end
pipeline tests because the executable surface they exercised
(`run_phase2()`) no longer exists. The substantive validation for the
agent recipe is operational — fire `hermes cron run <id>` and observe
a `publish_queue/<id>.json` materialize.

## File layout

```
hermes-skills/autonovel-phase2/
├── SKILL.md                # Hermes skill body — agent recipe (Pattern 5)
├── README.md               # This file
├── runner.py               # Pure helpers only: _wrap_prompt, _check_preamble,
│                           # _extract_summary. NOT invokable standalone.
├── identity_loader.py      # Direct-read identity helper (OQ-2)
├── anchor_selector.py      # POV-aware few-shot bank selector (§3.4)
├── voice_match.py          # Heuristic voice-match score + advisory gate (§3.5)
├── staging.py              # PublishRequest builder + slop firewall (§3.6)
└── tests/                  # 65 pytest cases (pure helpers + SKILL.md doc tests)
```

## Rollback

Rollback is operational, not source-level. To roll back:

```bash
hermes cron pause autonovel-phase2
hermes cron resume autonovel-phase1-smoke   # if previously paused
```

Phase 2 skill files stay on disk (rollback artifact). In-flight
queue items in `publish_queue/` persist (OQ-7 ACCEPT). To enumerate
Phase 2 items for operator review:

```bash
grep -l bd-b5p.5 publish_queue/*.json
```

## OQ resolutions (from the spec /check walk)

| OQ | Question | Resolution |
|----|----------|------------|
| OQ-1 | Child inherits parent system prompt? | ACCEPT — no inheritance; pass full `_PROSE_FRAME` as `goal`. |
| OQ-2 | Hermes skill loader poisons voice files? | ACCEPT — yes; bypass via direct `Path.read_text` in `identity_loader.py`. |
| OQ-3 | Hermes "summary" boilerplate interferes? | ACCEPT — trust the frame; T-D-3 is the empirical gate. |
| OQ-4 | Voice-match threshold 0.5 calibration? | ACCEPT — start at 0.5, file `study` bead with 7 days of cron data, recalibrate. |
| OQ-5 | Cross-reference `voice_priors.json` in selector? | DEFER to Phase 3 (ranker layer). |
| OQ-6 | Brief-file reading from `briefs/<slug>.json`? | DEFER to Phase 3 (first deliverable). |
| OQ-7 | In-flight queue items on rollback? | ACCEPT — items stay; operator decides per-item via `grep -l bd-b5p.5`. |
| OQ-8 | In-process vs subprocess for `evaluate.py`? | ACCEPT — in-process import (Phase 1 validates). |
| OQ-9 | Hermes SessionDB captures delegate trajectory? | DEFER — sibling `study` bead (bd-b5p.5.2). |
| OQ-10 | Cron prompt-injection scanner false-positives? | ACCEPT — 7-day monitoring + two-strikes protocol. |

## Phase 3 candidates (parking lot)

- Reader feedback loop (`/feedback`, `/mail`).
- Brief reading from `briefs/<slug>.json` (resolves OQ-6).
- Live AO3 POST (the `api/ao3_*` live client invoked from a
  promotion skill).
- Multi-skill orchestration (`/heartbeat` as Hermes cron router).
- `autonovel-voice` skill packaging (gated on Hermes upstream
  raw-mode skill view).
- Voice-match promotion advisory → hard gate (per OQ-4 calibration).
- `voice_priors.json` cross-reference in anchor selection (OQ-5).
- ShareGPT trajectory export hook (OQ-9).

## See also

* spec: `br show bd-b5p.5`
* parent epic: `br show bd-b5p`
* Pattern 5 research: `~/explore/local-coding-models/refs/research/research-phase2-invocation.md`
* Phase 1 (rollback target): `hermes-skills/autonovel-phase1-smoke/`
* `~/explore/local-coding-models/refs/research/research-hermes-primer.md`
* `~/explore/local-coding-models/refs/research/research-autonovel-on-hermes.md`
