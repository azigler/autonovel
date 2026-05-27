---
name: autonovel-phase2
description: "Phase 2 autonovel — Hermes-native delegate_task generation with POV-aware voice anchors, staged to publish_queue/ for AO3 review (no live posting). Bead bd-b5p.5."
version: "0.3.0"
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
`bd-b5p.4` (Phase 1, closed) · **Architecture revision:** `bd-b5p.5.6`
(Pattern 5 — agent-recipe, not executable runner)

## How to invoke

**This skill is a PROCEDURAL RECIPE the parent agent executes
IN-CONVERSATION.** When the Hermes runtime loads this SKILL body as a
prompt prefix (via `hermes cron run <id>` or any path that constructs
an `AIAgent` and calls `run_conversation`), the agent walks through the
five steps below using its own tools (`read_file`, `execute_code`,
`delegate_task`). Steps 1, 2, 4 use Python helpers imported from this
skill's `runner.py` library; Step 3 is the parent agent's own
`delegate_task` tool call.

**WARNING — NEVER invoke `python3 runner.py` standalone.** `runner.py`
is a HELPER LIBRARY, not an executable. `delegate_task` requires the
parent agent's in-process AIAgent context (`parent_agent=self` is
injected only at `run_agent.py:_dispatch_delegate_task`); subprocesses
have no path to acquire it. See bd-b5p.5.5 research at
`~/explore/local-coding-models/refs/research/research-phase2-invocation.md`
for the full Pattern 5 verdict + per-line citations.

### Step 1: agent uses `read_file` to load identity bundle

The parent agent reads the four identity files directly (NOT via
`skill_view`, which would prepend attribution preamble per OQ-2):

- `/home/ubuntu/explore/autonovel/identity/self.md`
- `/home/ubuntu/explore/autonovel/identity/voice_priors.json`
- `/home/ubuntu/explore/autonovel/identity/few_shot_bank.md`
- `/home/ubuntu/explore/autonovel/identity/soul.md`

Hold the contents in the conversation context for Step 2's
`execute_code` snippet to reference (the snippet may also re-read them
via `identity_loader.load_identity` for ergonomics — either path
works).

### Step 2: agent uses `execute_code` to build the wrapped goal

The parent agent emits an `execute_code` tool call that imports
`hermes_skills.autonovel_phase2.runner._wrap_prompt`, calls it with the
system + user prompt pair, and prints the wrapped goal string. The
snippet shape:

```python
import sys
sys.path.insert(0, "/home/ubuntu/explore/autonovel")
sys.path.insert(0, "/home/ubuntu/explore/autonovel/hermes-skills")

# Synthetic namespace so hermes_skills.autonovel_phase2 resolves to the
# hyphenated on-disk directory.
import types, importlib.util
spec = importlib.util.spec_from_file_location(
    "hermes_skills.autonovel_phase2.runner",
    "/home/ubuntu/explore/autonovel/hermes-skills/autonovel-phase2/runner.py",
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

from hermes_skills.autonovel_phase2.identity_loader import load_identity
from hermes_skills.autonovel_phase2.anchor_selector import select_anchors
from write.prompts import build_draft_system, build_draft_user

ctx = load_identity()
pov = ctx.get("pov_character", "Karlach")
anchors = select_anchors(
    ctx.get("few_shot_bank", ""), pov_character=pov, max_anchors=2
)
if anchors:
    block = (
        "\n\nVOICE ANCHORS (recent successful samples — match this register):\n"
        + "\n\n".join(anchors)
    )
    ctx["identity"] = ctx.get("identity", "") + block

class _Brief:
    target_length = 120

system_p = build_draft_system(ctx, ctx.get("soul", ""))
user_p = build_draft_user(
    brief=_Brief(), context=ctx, chapter_num=1, total_chapters=1,
    previous_chapter_tail="", seeds=None, length_retry=False,
    previous_word_count=0, length_enforcement="prompt",
)
wrapped = runner._wrap_prompt(system_p, user_p)
print("__WRAPPED_GOAL_BEGIN__")
print(wrapped)
print("__WRAPPED_GOAL_END__")
# Also stash the anchors so Step 4 can pass them to voice_match_score
import json as _json
print("__ANCHORS_JSON_BEGIN__")
print(_json.dumps(anchors))
print("__ANCHORS_JSON_END__")
```

Capture the text between `__WRAPPED_GOAL_BEGIN__` and
`__WRAPPED_GOAL_END__` as the wrapped goal; the anchors JSON between
`__ANCHORS_JSON_BEGIN__` / `__ANCHORS_JSON_END__` carries forward to
Step 4.

### Step 3: agent EMITS `delegate_task` tool call directly

The parent agent now emits a NATIVE `delegate_task` tool call (NOT
inside `execute_code`, NOT via `terminal_tool`). This is the canonical
Pattern 5 step — `delegate_task` is in the default `hermes-cli`
toolset, and the AIAgent's tool-dispatch path injects `parent_agent=self`
transparently. The call shape:

```
delegate_task(
    goal=<wrapped goal string from Step 2>,
    context="",
    toolsets=[],
    role="leaf",
    max_iterations=10
)
```

The return value is a JSON string of shape
`{"results": [{"summary": "...", "child_session_id": "..."}]}`.

### Step 4: agent uses `execute_code` to extract, score, and stage

The parent agent emits a second `execute_code` snippet that imports
the runner's `_check_preamble` + `_extract_summary` helpers, the
`staging.stage_draft` helper, plus the scoring helpers, and persists
the result. Pass the delegate result JSON + the anchors JSON from
Step 2 in via stdin or as inline string literals (the agent decides
based on prose length). Snippet shape:

```python
import sys, json
sys.path.insert(0, "/home/ubuntu/explore/autonovel")
sys.path.insert(0, "/home/ubuntu/explore/autonovel/hermes-skills")

import importlib.util
spec = importlib.util.spec_from_file_location(
    "hermes_skills.autonovel_phase2.runner",
    "/home/ubuntu/explore/autonovel/hermes-skills/autonovel-phase2/runner.py",
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

from hermes_skills.autonovel_phase2.staging import stage_draft
from hermes_skills.autonovel_phase2.voice_match import voice_match_score
import evaluate

DELEGATE_JSON = """<paste delegate JSON return from Step 3>"""
ANCHORS_JSON = """<paste anchors JSON from Step 2>"""

prose = runner._extract_summary(DELEGATE_JSON)
runner._check_preamble(prose)  # raises on T-D-3 preamble leakage
anchors = json.loads(ANCHORS_JSON)
slop = float(evaluate.slop_score(prose).get("slop_penalty", 99.0))
vm = voice_match_score(prose=prose, anchor_passages=anchors)
item = stage_draft(prose=prose, slop_penalty=slop, voice_match_score=vm)

queue_id = item.queue_id if item is not None else "none"
status = "PASS" if item is not None else "FAIL"
print(f"slop_penalty={slop} voice_match={vm} queue_id={queue_id} status={status}")
```

### Step 5: agent reports the canonical single-line summary

The parent agent surfaces the single-line summary verbatim as its
final reply to the conversation:

```
slop_penalty=<f> voice_match=<f> queue_id=<hex|none> status=<PASS|FAIL>
```

The `hermes cron --deliver local` channel captures this stdout line
into `~/.hermes/cron/output/autonovel-phase2/*`. Operators inspect the
file to confirm PASS / FAIL + the queue_id for AO3 review.

## Canonical operational invocation

**Scheduled (daily cron, parent-context supplied by Hermes daemon):**

```bash
hermes cron create '0 21 * * *' '/skill:autonovel-phase2 run' --deliver local
```

**Manual smoke (re-fires the registered cron with the same AIAgent path):**

```bash
hermes cron run <job-id>
```

Both paths construct an `AIAgent`, call `run_conversation(prompt)` with
this SKILL body as the prompt prefix (per
`cron/scheduler.py:_build_job_prompt`), and the LLM follows the 5-step
recipe above. The cron daemon is THE parent context — there is no
separate Python-process invocation pathway.

**DO NOT** use these patterns — they all fail:

- `python3 ~/.hermes/skills/autonovel-phase2/runner.py` — there is no
  `main()`. `runner.py` is a library.
- `hermes -z 'use the autonovel-phase2 skill: invoke run_phase2 …
  via terminal_tool'` — `terminal_tool` runs a subprocess; subprocess
  has no `parent_agent`; `delegate_task` errors; under `--yolo` the
  agent fabricates a success summary (the confabulation bug — see
  bd-b5p.5.7).

## What this skill does

The Step 1-5 recipe above performs the full Phase 2 pipeline:

1. **Identity load** (Step 1) — direct `read_file` of `self.md`,
   `voice_priors.json`, `few_shot_bank.md`, `soul.md`. **Not** via the
   Hermes skill loader (OQ-2 ACCEPT — the loader's attribution preamble
   contaminates the voice context).
2. **Anchor selection + prompt wrap** (Step 2) — `anchor_selector` picks
   POV-appropriate anchors from `few_shot_bank.md`;
   `write.prompts.wrap_for_subagent` builds the `_PROSE_FRAME` envelope.
3. **delegate_task** (Step 3) — native parent-agent tool call;
   `goal=<frame>`, `context=""`, `toolsets=[]`, `role="leaf"`.
4. **Scoring + staging** (Step 4) — `evaluate.slop_score` (production
   threshold 3.0), `voice_match.voice_match_score` (advisory 0.5),
   `staging.stage_draft` → `publish_queue/<queue_id>.json` with
   `status=PENDING`. Slop-gate firewall is internal to `stage_draft` —
   FAIL path returns `None` and skips enqueue. The `author_notes` block
   is an HTML comment containing the bead ID, model, slop_penalty,
   voice_match score — visible to operators reviewing the queue, hidden
   on AO3.
5. **Summary** (Step 5) — single-line
   `slop_penalty=<f> voice_match=<f> queue_id=<hex|none> status=<PASS|FAIL>`.

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
T-D-4, T-V-1 through T-V-5, T-A-1 through T-A-5). Coverage lives at
`hermes-skills/autonovel-phase2/tests/`. T-E-1/2/3 (the end-to-end
pipeline tests) were retired in bd-b5p.5.6 because the executable
`run_phase2` function they exercised no longer exists; the SKILL.md
recipe is now the executable surface and is validated via
`hermes cron run <id>` smoke runs.

## See also

* `runner.py` — pure-Python helpers (`_wrap_prompt`, `_check_preamble`,
  `_extract_summary`). Library only — NOT invokable standalone.
* `identity_loader.py` — direct-read identity helper (OQ-2)
* `anchor_selector.py` — POV-aware few-shot bank selector
* `voice_match.py` — heuristic voice-match score + advisory gate
* `staging.py` — `PublishRequest` builder + slop firewall
* `tests/` — pytest coverage for the helpers above + SKILL recipe doc tests
* `hermes-skills/autonovel-phase1-smoke/` — Phase 1 (rollback target)
* spec: `br show bd-b5p.5`
* parent epic: `br show bd-b5p`
* Pattern 5 research: `~/explore/local-coding-models/refs/research/research-phase2-invocation.md`
* Hermes primer:
  `~/explore/local-coding-models/refs/research/research-hermes-primer.md`
