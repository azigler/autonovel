---
name: autonovel-phase2-worker
description: "autonovel Phase 2 fanfic generator as a Hermes kanban worker. Dispatched by the gateway-embedded kanban dispatcher when an enqueue cron fires `hermes kanban create --skill autonovel-phase2-worker`. Lifecycle: kanban_show() orient, read identity files, generate prose, score, stage to publish_queue/, kanban_complete with metadata + artifacts. Bead bd-b5p.7."
version: "0.4.0"
author: "autonovel"
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [autonovel, fanfic, phase2, kanban-worker, delegate-task, voice-anchors, ao3-staging, bg3]
    related_skills: [kanban-worker, autonovel-phase1-smoke]
    category: creative
---

# autonovel-phase2-worker

Hermes kanban worker for the daily fanfic draft pipeline. The dispatcher
spawns this worker with `KANBAN_GUIDANCE` auto-injected into the system
prompt; that guidance covers the generic 6-step lifecycle (orient →
work → heartbeat → block → complete → spawn). This SKILL body covers
the autonovel-specific recipe layered on top.

**Bead:** `bd-b5p.7` · **Parent epic:** `bd-b5p` · **Supersedes
(architecturally):** `bd-b5p.5` / `bd-b5p.5.6` Pattern 5 ·
**Research:** `~/explore/local-coding-models/refs/research/research-hermes-conformance.md`

## When you receive this task

You were dispatched by the gateway-embedded kanban dispatcher
(per OQ-K-5 of bd-b5p.7.1 — `hermes-gateway.service` embeds the
dispatcher; there is no separate `hermes kanban daemon` in v0.14.0+).
The cron-fired enqueue script created your card with something like:

```
hermes kanban create "draft daily fanfic <YYYY-MM-DD>" \
  --assignee autonovel-writer \
  --skill autonovel-phase2-worker \
  --workspace dir:/home/ubuntu/explore/autonovel \
  --max-runtime 30m \
  --idempotency-key autonovel-phase2-<YYYY-MM-DD>
```

Environment available to you:

- `$HERMES_KANBAN_TASK` — your task id
- `$HERMES_KANBAN_WORKSPACE` — `/home/ubuntu/explore/autonovel`
- Working directory — your CWD is `$HERMES_KANBAN_WORKSPACE`, so the
  agent's `prompt_builder` cwd-scan (per
  `agent/prompt_builder.py:1365-1390`, OQ-K-1) has ALREADY
  auto-injected `/home/ubuntu/explore/autonovel/CLAUDE.md` into your
  system prompt as a context file. You do NOT need to read it
  explicitly.

## What this worker does

The generic kanban lifecycle (orient → work → heartbeat → block →
complete → spawn) is already in your system prompt as
`KANBAN_GUIDANCE` (`agent/prompt_builder.py:188-257`); don't restate
or contradict it. The autonovel-specific work layered on top, in order:

- Generate one paragraph of BG3 (Baldur's Gate 3) fanfic via the
  agent's own `delegate_task` tool, with the wrapped goal built from
  `runner._wrap_prompt`.
- Score the prose via `voice_match.voice_match_score` (POV-aware) and
  `evaluate.slop_score` (production threshold 3.0).
- Stage the result via `staging.stage_draft` to
  `publish_queue/<queue_id>.json` (the slop-gate firewall is internal
  to `stage_draft` — FAIL returns `None`, no file written).
- Complete via `kanban_complete(summary, metadata, artifacts)` per
  OQ-K-3 — the `artifacts=[...]` list carries the
  `publish_queue/<id>.json` path so the gateway notifier hooks
  native attachment upload.

The steps that follow walk this in order, but the first thing you do
on dispatch is always `kanban_show()` (per `KANBAN_GUIDANCE` Step 1).

## Step 1 — Orient

Call `kanban_show()` first (per `KANBAN_GUIDANCE` Step 1). The
response includes your task title, body, prior attempts (retries),
and the workspace path. If `kanban_show` reports
`status in {blocked, archived}`, stop — you shouldn't be running.

## Step 2 — Read identity files

The four identity files inform voice + scope. Read them directly with
`read_file` (NOT via `skill_view`, which prepends an attribution
preamble per bd-b5p.5 OQ-2 that poisons the voice anchors). These are
tool-context reads (content the worker actively uses), distinct from
the cwd-auto-injected `CLAUDE.md` (which is ambient project
guidance — already in your system prompt, per OQ-K-1; do NOT re-read
it).

- `$HERMES_KANBAN_WORKSPACE/identity/self.md`
- `$HERMES_KANBAN_WORKSPACE/identity/voice_priors.json`
- `$HERMES_KANBAN_WORKSPACE/identity/few_shot_bank.md`
- `$HERMES_KANBAN_WORKSPACE/identity/soul.md`

## Step 3 — Wrap the draft prompt (`execute_code`)

Run the Phase 2 helpers via `execute_code` to assemble the wrapped
goal string + extract the POV anchors. The snippet (verbatim from
bd-b5p.5.6 Step 2 with workspace-relative paths):

```python
import sys
sys.path.insert(0, "/home/ubuntu/explore/autonovel")
sys.path.insert(0, "/home/ubuntu/explore/autonovel/hermes-skills")

import importlib.util
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
import json as _json
print("__ANCHORS_JSON_BEGIN__")
print(_json.dumps(anchors))
print("__ANCHORS_JSON_END__")
```

Capture the wrapped goal between `__WRAPPED_GOAL_BEGIN__` /
`__WRAPPED_GOAL_END__`; the anchors JSON between
`__ANCHORS_JSON_BEGIN__` / `__ANCHORS_JSON_END__` carries forward to
Step 5.

## Step 4 — Generate via `delegate_task`

This is the canonical inside-one-run use of `delegate_task` (NOT a
board substitute — that's what `kanban_create` is for; per
`KANBAN_GUIDANCE` §Do NOT — this is a short reasoning subtask inside
YOUR run).

Generation runs typically 3-20 minutes on qwen3-coder. **Before** the
call, emit `kanban_heartbeat(note="generating draft via delegate_task")`
so the dispatcher's `dispatch_stale` clock starts from the heartbeat,
not from worker startup. A long generation without a heartbeat is the
path to `dispatch_stale` reclaim mid-generation; heartbeats every few
minutes during long ops are the documented best practice.

```
delegate_task(
    goal=<wrapped goal from Step 3>,
    context="",
    toolsets=[],
    role="leaf",
    max_iterations=10,
)
```

Capture the JSON-string return value. Shape:

```json
{"results": [{"summary": "...", "child_session_id": "..."}]}
```

**Two timeout clocks apply** (per OQ-K-2 of bd-b5p.7.1):

- **`delegate_task` per-child timeout** —
  `delegation.child_timeout_seconds` in `~/.hermes/config.yaml`. The
  Hermes default is **600s** (10min); for this worker the operator
  has bumped it to **1800s** (30min) so it aligns with the worker's
  `--max-runtime 30m` budget (see §3.2 of bd-b5p.7 spec). If the
  delegate child stalls past 1800s, `delegate_task` returns a
  timeout result and YOU REMAIN ALIVE — handle it via `kanban_block`
  (not `kanban_complete`).
- **Worker `--max-runtime 30m`** — enforced by the dispatcher
  (`kanban_db.py:4343-4421 enforce_max_runtime`). On overrun the
  whole worker process is SIGTERMed then SIGKILLed; the task
  re-queues. Nothing you can do from inside.

## Step 5 — Extract, score, stage (`execute_code`)

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

DELEGATE_JSON = """<paste Step 4 delegate_task return value>"""
ANCHORS_JSON = """<paste Step 3 anchors JSON>"""

prose = runner._extract_summary(DELEGATE_JSON)
runner._check_preamble(prose)  # raises on preamble leakage (bd-b5p.5.6 T-D-3)
anchors = json.loads(ANCHORS_JSON)
slop = float(evaluate.slop_score(prose).get("slop_penalty", 99.0))
vm = voice_match_score(prose=prose, anchor_passages=anchors)
item = stage_draft(prose=prose, slop_penalty=slop, voice_match_score=vm)

queue_id = item.queue_id if item is not None else None
file_path = str(item.file_path) if item is not None else None
print("__STAGE_RESULT_BEGIN__")
print(json.dumps({
    "queue_id": queue_id,
    "slop_penalty": slop,
    "voice_match": vm,
    "file_path": file_path,
    "draft_excerpt": prose[:240],
    "status": "PASS" if item is not None else "FAIL",
}))
print("__STAGE_RESULT_END__")
```

`stage_draft` returns `None` when the slop firewall trips (high
`slop_penalty`) — that's a legitimate FAIL outcome, NOT a worker
crash. Continue to Step 6 with `queue_id=None` + `status=FAIL` +
empty artifacts.

## Step 6 — Complete

Call `kanban_complete(summary=..., metadata=..., artifacts=...)` with
the captured result. The metadata schema + artifacts list are FIXED
(downstream parsers + future Phase 5 publisher depend on the shape):

```python
kanban_complete(
    summary=f"drafted {queue_id[:8] if queue_id else 'none'}... slop={slop:.2f} voice_match={vm:.2f} status={status}",
    metadata={
        "queue_id": queue_id,        # hex string when PASS; None on FAIL
        "slop_penalty": slop,        # float; evaluate.slop_score result
        "voice_match": vm,           # float; voice_match_score result
        "draft_excerpt": prose[:240],  # first 240 chars of prose
        "status": status,            # "PASS" | "FAIL"
    },
    artifacts=[file_path] if file_path else [],
)
```

The `artifacts=[file_path]` parameter is the canonical way to
reference produced files (per OQ-K-3 of bd-b5p.7.1 /
`tools/kanban_tools.py:392-460`) — the gateway notifier auto-attaches
the file, and `kanban_show` lists it visibly. Do NOT also stuff
`file_path` into the `metadata` dict; it belongs in `artifacts`.
`worker_session_id` is auto-stamped by
`tools/kanban_tools.py:118-129` — never set it yourself.

**Do NOT** call `kanban_complete` if Step 5 raised, if `prose` was
empty, or if `delegate_task` returned an error. In those cases call
`kanban_block(reason="<one-line diagnosis>")` instead — the dispatcher
surfaces blocks for human triage rather than recording fabricated
success.

## Failure modes

| Symptom | Action |
|---|---|
| `delegate_task` returned `{"error": ...}` | `kanban_block(reason="delegate_task failed: <error>")`. Do NOT retry blindly. |
| `delegate_task` returned a TIMEOUT result (per-child 1800s budget per OQ-K-2) | `kanban_block(reason="delegate_task child timeout — model stalled past 1800s")`. This is distinct from the 30m worker SIGTERM. |
| `_check_preamble(prose)` raised (preamble leakage) | `kanban_block(reason="prose contained delegate preamble — likely model regression")`; comment with the offending excerpt. |
| `stage_draft` returned `None` (slop / voice firewall) | `kanban_complete(... status=FAIL, queue_id=None, artifacts=[] ...)` — this IS a real result; the firewall did its job. Don't block. |
| `kanban_heartbeat` raised | Continue silently; the dispatcher's grace window is the safety net. |
| Worker crashes between Step 4 and Step 6 | Dispatcher marks the run `crashed`; next dispatch tick reclaims (subject to `--max-retries`). No special action — exiting without `kanban_complete` triggers `dispatch_stale` re-queue at the substrate level. |
| Worker SIGTERMed at 30m (`--max-runtime`) by dispatcher | Whole worker pid dies; task re-queues `ready`. Nothing the worker can do. |

Exiting without `kanban_complete` or `kanban_block` means the task is
marked `dispatch_stale` after `kanban.dispatch_stale_timeout_seconds`
(default 4h) and re-queues as `ready`. This is the substrate-level
"no completion = no success" invariant (per `kanban-worker/SKILL.md`)
and replaces the bd-b5p.5.8 ad-hoc verify-queue-file guard with a
uniformly-applied gate.

## Do NOT

- Do NOT invoke `terminal_tool` for kanban board operations — use the
  `kanban_*` tools (per built-in `kanban-worker/SKILL.md`; the CLI
  fails in containerized backends).
- Do NOT call `kanban_complete` with fabricated metadata (the
  dispatcher logs the run row durably; downstream readers will catch
  invented `queue_id`s on the next read — that was the bd-b5p.5.7
  confabulation bug pattern at a different layer).
- Do NOT call `delegate_task` recursively or as a board substitute
  (per `KANBAN_GUIDANCE` §Do NOT).
- Do NOT invoke `python3 runner.py` standalone via `terminal_tool` —
  `runner.py` is a HELPER LIBRARY, not an executable. That was the
  bd-b5p.5.5 broken-invocation pattern this kanban shape supersedes.
  Use `delegate_task` (Step 4) instead.
- Do NOT call `kanban_complete` if `publish_queue/<queue_id>.json`
  doesn't exist on disk (the staging helper writes-then-returns; if
  `item is None`, the file isn't there).
- Do NOT re-read `CLAUDE.md` / `AGENTS.md` from the workspace — the
  agent's `prompt_builder` cwd-scan already auto-injected them at
  worker startup (per OQ-K-1 of bd-b5p.7.1). Re-reading wastes tool
  turns and can confuse the agent about which `CLAUDE.md` is
  canonical.
