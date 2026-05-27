---
name: autonovel-phase2
description: "Phase 2 autonovel — Hermes-native delegate_task generation with POV-aware voice anchors, staged to publish_queue/ for AO3 review (no live posting). Bead bd-b5p.5."
version: "0.2.0"
author: "autonovel"
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [autonovel, fanfic, phase2, delegate-task, voice-anchors, ao3-staging, bg3]
    related_skills: [autonovel-phase1-smoke]
    category: creative
---

# autonovel-phase2

Phase 2 autonovel: Hermes-native `delegate_task` generation +
POV-aware voice anchors + AO3 staging. Coexists with Phase 1 (rollback
target); does NOT replace it.

**Bead:** `bd-b5p.5` · **Parent epic:** `bd-b5p` · **Predecessor:**
`bd-b5p.4` (Phase 1, closed)

## What this skill does

1. Loads autonovel identity via direct `Path.read_text` —
   `identity/self.md`, `identity/voice_priors.json`,
   `identity/few_shot_bank.md`, `identity/soul.md`. **Not** via
   the Hermes skill loader (OQ-2 ACCEPT — the loader prepends
   attribution noise that contaminates the voice context).
2. Selects POV-appropriate voice anchors from `few_shot_bank.md`
   via `anchor_selector.select_anchors(pov, max_anchors=2)`.
3. Builds the `_PROSE_FRAME`-wrapped prompt via
   `write.prompts.wrap_for_subagent(build_draft_system(...),
   build_draft_user(...))`.
4. Calls Hermes' native `delegate_task(goal=<frame>, context="",
   toolsets=[], role="leaf")`. The parent agent invokes the
   skill from a conversation turn; `delegate_task` returns the
   child's prose as the `results[0].summary` field of a JSON
   string.
5. Scores the prose: `evaluate.slop_score` (production threshold
   3.0) and `voice_match.voice_match_score` (advisory, threshold
   0.5).
6. On PASS, constructs `api.models.PublishRequest` from the prose
   + Phase-2 brief metadata and calls `api.queue.enqueue` to
   stage at `publish_queue/<queue_id>.json` with
   `status=PENDING`. The `author_notes` block is an HTML comment
   containing the bead ID, model, slop_penalty, voice_match score
   — visible to operators reviewing the queue, hidden on AO3.
7. Returns a single-line summary:
   `slop_penalty=<f> voice_match=<f> queue_id=<hex|none>
   status=<PASS|FAIL>`.

## How to invoke

The skill's parent-agent body calls `run_phase2()` from
`hermes_skills.autonovel_phase2.runner` — typically via the
shipped `runner.py` CLI:

```bash
cd /home/ubuntu/explore/autonovel
python3 ~/.hermes/skills/autonovel-phase2/runner.py
```

Exit code: `0` on PASS, `1` on FAIL (slop firewall). The cron
`--deliver local` channel captures stdout into
`~/.hermes/cron/output/autonovel-phase2/*`.

## Brief (hardcoded for Phase 2 — same as Phase 1)

> Post-Act 3, post-elven-ritual. Astarion and Karlach share a
> wordless moment in the garden of an inn somewhere outside
> Baldur's Gate. Neither of them is good at sitting still with
> something that isn't a threat. One paragraph (3–5 sentences).
> Close third-person, past tense. POV: Karlach.

Hardcoded into `identity_loader.PHASE2_BRIEF_TEXT` for
direct A/B comparability with Phase 1. Phase 3 reads briefs from
`briefs/<slug>.json` (OQ-6 DEFER).

## Output contract

* File: `publish_queue/<queue_id>.json` (12-char hex id from
  `api.queue.enqueue`).
* Content: a `QueueItem` JSON shape — `queue_id`,
  `publish_request`, `status` ("pending"), `created_at`,
  `published_at` (null), `ao3_work_id` (null).
* `publish_request.body` is the raw prose (no footer, no
  metadata — those go in `author_notes` so the prose stays
  parseable for the slop scorer).
* `publish_request.summary` ≤ 250 chars (AO3 server limit).

## Cron registration

Coexists with `autonovel-phase1-smoke` — does NOT replace it:

```bash
hermes cron create \
    --name autonovel-phase2 \
    --skill autonovel-phase2 \
    --workdir /home/ubuntu/explore/autonovel \
    --deliver local \
    '0 9 * * *' \
    'Run the autonovel-phase2 skill: generate one paragraph and stage it for AO3 review.'
```

Phase 1's `autonovel-phase1-smoke` cron stays operational for
one observation week (operator A/B's Phase 1 vs Phase 2 output
side-by-side); then the Phase 1 cron is removed (skill files
stay as rollback artifact).

## Rollback

Rollback is operational, not source-level — Phase 2 skill files
stay on disk; rollback means stopping the cron schedule. Per
spec OQ-7 ACCEPT, in-flight queue items persist on rollback
(no automatic purge of the human-review queue).

To roll back Phase 2:

```bash
hermes cron pause autonovel-phase2
hermes cron resume autonovel-phase1-smoke
```

To enumerate Phase-2-authored items in `publish_queue/` for
operator review:

```bash
cd /home/ubuntu/explore/autonovel
grep -l bd-b5p.5 publish_queue/*.json
```

For each enumerated item, the operator decides per-item: delete
(`api/queue.py::delete_item`), retain for manual posting, or
carry forward.

## Acceptance criteria

See spec bd-b5p.5 §5 for the full test matrix (T-D-1 through
T-D-4, T-V-1 through T-V-5, T-A-1 through T-A-5, T-E-1 through
T-E-3). Coverage lives at
`hermes-skills/autonovel-phase2/tests/`.

## See also

* `runner.py` — CLI entry-point + `run_phase2()` programmatic API
* `identity_loader.py` — direct-read identity helper (OQ-2)
* `anchor_selector.py` — POV-aware few-shot bank selector
* `voice_match.py` — heuristic voice-match score + advisory gate
* `staging.py` — `PublishRequest` builder + slop firewall
* `tests/` — pytest coverage for the contract above
* `hermes-skills/autonovel-phase1-smoke/` — Phase 1 (rollback target)
* spec: `br show bd-b5p.5`
* parent epic: `br show bd-b5p`
* Hermes primer:
  `~/explore/local-coding-models/refs/research/research-hermes-primer.md`
