# autonovel-phase2

Phase 2 Hermes-autonovel pipeline. Hermes-native `delegate_task`
generation with POV-aware voice anchors, staged to `publish_queue/`
for AO3 review (no live posting yet).

**Bead:** `bd-b5p.5` · **Parent epic:** `bd-b5p` · **Predecessor:**
`bd-b5p.4` (Phase 1, closed)
**Spec:** `br show bd-b5p.5`

## What this delivers

A Hermes skill at `~/.hermes/skills/autonovel-phase2/` whose
parent-agent body calls `hermes_skills.autonovel_phase2.runner.run_phase2()`:

1. Loads autonovel identity via direct `Path.read_text` (OQ-2 ACCEPT:
   the Hermes skill loader's attribution preamble is bypassed so it
   cannot contaminate the voice context).
2. Selects POV-appropriate voice anchors from `identity/few_shot_bank.md`
   (POV-aware, replaces Phase 1's blind 3K-char trim).
3. Builds the `_PROSE_FRAME`-wrapped prompt via
   `write.prompts.wrap_for_subagent(build_draft_system(...),
   build_draft_user(...))`.
4. Calls Hermes' native `delegate_task(goal=<frame>, context="",
   toolsets=[], role="leaf")` — pure prose generator, no tools, no
   nested delegation.
5. Scores: `evaluate.slop_score` (PROD threshold 3.0) +
   `voice_match.voice_match_score` (advisory threshold 0.5).
6. On PASS, builds `api.models.PublishRequest` and calls
   `api.queue.enqueue` to land at
   `publish_queue/<queue_id>.json` with `status=PENDING`.
7. Returns the single-line summary
   (`slop_penalty=... voice_match=... queue_id=... status=PASS|FAIL`).

A daily cron (registered via `hermes cron create`) invokes this skill
at 09:00 local time alongside `autonovel-phase1-smoke` for one
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

Coexists with Phase 1 — does NOT replace it:

```bash
hermes cron create \
    --name autonovel-phase2 \
    --skill autonovel-phase2 \
    --workdir /home/ubuntu/explore/autonovel \
    --deliver local \
    '0 9 * * *' \
    'Run the autonovel-phase2 skill: generate one paragraph and stage it for AO3 review.'
```

Verify:

```bash
hermes cron list | grep autonovel
# Expect BOTH autonovel-phase1-smoke AND autonovel-phase2 listed.
```

## Run the tests

```bash
cd /home/ubuntu/explore/autonovel
.venv/bin/python3 -m pytest hermes-skills/autonovel-phase2/tests/ -v
```

The pytest suite covers all spec test cases (T-D-1 through T-E-3)
plus 10 edge/boundary tests beyond the spec. 59 cases total
(including the 9 parametrized preamble-leakage variants of T-D-3).

## File layout

```
hermes-skills/autonovel-phase2/
├── SKILL.md                # Hermes skill body (YAML frontmatter + agent guidance)
├── README.md               # This file
├── runner.py               # CLI entry + run_phase2() + run_delegate()
├── identity_loader.py      # Direct-read identity helper (OQ-2)
├── anchor_selector.py      # POV-aware few-shot bank selector (§3.4)
├── voice_match.py          # Heuristic voice-match score + advisory gate (§3.5)
├── staging.py              # PublishRequest builder + slop firewall (§3.6)
└── tests/                  # 59 pytest cases (test contract; do not modify)
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
* Phase 1 (rollback target): `hermes-skills/autonovel-phase1-smoke/`
* `~/explore/local-coding-models/refs/research/research-hermes-primer.md`
* `~/explore/local-coding-models/refs/research/research-autonovel-on-hermes.md`
