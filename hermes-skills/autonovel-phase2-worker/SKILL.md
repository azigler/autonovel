---
name: autonovel-phase2-worker
description: Kanban-worker skill for autonovel's daily fanfic draft. One card on the `autonovel-writer` board per UTC day → orient via `kanban_show()`, load identity, wrap prompt, generate, score, stage to `publish_queue/`.
version: 1.0.0
related_skills: [kanban-worker, autonovel-phase1-smoke]
metadata:
  hermes:
    tags: [kanban, kanban-worker, autonovel, fanfic, phase2, bg3]
---

# autonovel-phase2-worker

> You're seeing this because the kanban dispatcher spawned you against a
> `draft daily fanfic YYYY-MM-DD` card on the `autonovel-writer` board.
> The **lifecycle** (orient → work → heartbeat → block/complete) is
> auto-injected into your system prompt as `KANBAN_GUIDANCE`
> (`agent/prompt_builder.py:188-257`). This skill is the WHAT of the
> work: identity inputs, the `delegate_task` shape, the scoring + staging
> contract, the structured handoff metadata, and the anti-patterns.

**Bead:** `bd-b5p.7` · **Parent epic:** `bd-b5p` · **Spec walk:** `bd-b5p.7.1` (closed) · **Rewrite bead:** `bd-b2p`

## What the work is

The worker drafts one daily fanfic chapter (Baldur's Gate 3, POV typically
Karlach) from the autonovel identity bundle, scores the prose for slop +
voice match, and stages a PASS to `publish_queue/<queue_id>.json`. A FAIL
is a legitimate outcome (the firewall did its job) — not a worker crash.

One card → one worker run → one staged draft (PASS) **or** one recorded
firewall-rejection (FAIL).

## Pre-flight — check the pico exclusive-access lock

Pico inference (Ollama qwen3-coder:30b) is a shared resource. The
bench-matrix and any future heavy bench/training holds it exclusively
during a run; this worker must NOT contend with it (contention OOMs
pico's ~30GB Metal cliff and corrupts the matrix's measurements —
empirically caught 2026-05-30).

**Before any pico-bound LLM call**, source the lock helper and check:

```bash
source /home/ubuntu/dotfiles/local-models/lib/pico_lock.sh
if ! pico_acquire autonovel-phase2-worker 1800 "drafting daily fanfic"; then
    # Pico is held by another consumer. Block this task with the holder's
    # reason as the block message; the dispatcher will retry per cron.
    kanban_block <task_id> "pico held by another consumer; will retry next cron"
    exit 0
fi
trap 'pico_release autonovel-phase2-worker 2>/dev/null || true' EXIT
```

The lock auto-expires (1800s = 30m, matches our max-runtime). If pico is
free, you take the lock + proceed. If not, you block cleanly and exit;
the next cron tick reattempts.

## Workspace — orient FIRST, before any file read

`dir:/home/ubuntu/explore/autonovel` — the autonovel repo root, set by the
enqueue script's `--workspace`. Hermes exports the absolute path in the
env var `$HERMES_KANBAN_WORKSPACE` and surfaces it again in the
`Workspace:` line of `kanban_show()`'s `worker_context`. The dispatcher
also sets the spawned worker's cwd to this directory
(`kanban_db.py:5800`, `subprocess.Popen(cwd=workspace, ...)`).

**However**, empirical worker logs (run `t_41f4bb8f` on 2026-05-30, 4
failed attempts) show the worker's effective cwd at first tool turn is
sometimes NOT the workspace — the agent walks relative paths from
`/home/ubuntu` (or another parent) and burns 5–10 minutes on
`find . -name "identity"`. Treat the cwd as **unknown** and orient
explicitly:

```bash
# After `kanban_show()` (Step 1), before any read_file / execute_code:
cd "$HERMES_KANBAN_WORKSPACE"   # or use the absolute path the Workspace: line names
pwd                              # confirm you're in /home/ubuntu/explore/autonovel
```

Every relative path in this skill (`identity/self.md`,
`publish_queue/<queue_id>.json`, `autonovel_phase2/runner.py`) is
**workspace-relative** — equivalent to
`/home/ubuntu/explore/autonovel/<path>` or
`$HERMES_KANBAN_WORKSPACE/<path>`. If you skip the `cd`, prefix every
read with the absolute workspace path; do NOT walk relative paths
against an unknown cwd.

Because the dispatcher's intended cwd IS this workspace,
`prompt_builder._inject_claude_md()` has already auto-injected the
workspace `CLAUDE.md` / `AGENTS.md` into the system prompt at startup
(per OQ-K-1). Do NOT re-read `CLAUDE.md` or `AGENTS.md` — that wastes
tool turns and creates confusion about which is canonical.

Writes land at workspace-relative `publish_queue/<queue_id>.json` via
the `staging.stage_draft` helper. Nothing else gets written.

## Profile + tools available

Profile `autonovel-writer`, dispatched against board `autonovel-writer`
(per the Wave-19 Rule-2 workload partition; the default board is for
other Hermes work). Tools this work uses:

| Tool | What |
|---|---|
| `kanban_show` | Orient on the dispatched card (title, body, prior attempts, parent handoffs) — your first action via `kanban_show()` |
| `read_file` | Direct identity-file reads (NOT `skill_view`, which prepends an attribution preamble per bd-b5p.5 OQ-2 that poisons voice anchors) |
| `execute_code` | Run the helpers that wrap the prompt, parse the delegate return value, score the prose, and call `staging.stage_draft` |
| `delegate_task` | Generate the prose itself via qwen3-coder:30b on pico (tailnet 100.72.47.4:11434) through Ollama — the wrapped goal goes here, role=`leaf`, no tools |
| `kanban_heartbeat` | Mandatory before `delegate_task` and at progress milestones during the 3–20 min generation |
| `kanban_complete` / `kanban_block` | Structured terminal handoff (success / firewall-reject) or escalation (error path) |

## Identity bundle — the curation source-of-truth

The autonovel identity bundle lives in the workspace, at workspace-relative
paths (resolve against `$HERMES_KANBAN_WORKSPACE` =
`/home/ubuntu/explore/autonovel/`):

- `identity/self.md` — POV character + scope
- `identity/voice_priors.json` — voice register priors
- `identity/few_shot_bank.md` — recent successful samples; the anchor selector picks 2 by POV
- `identity/soul.md` — long-form persona context

These four files inform voice + scope. Read them with `read_file` AFTER
the Workspace-orient `cd` (or with the absolute prefix
`/home/ubuntu/explore/autonovel/identity/...` if you opted to skip the
`cd`). Do NOT route them through `skill_view`. Do NOT duplicate or
paraphrase their content in this skill — they are the source of truth,
this file is the worker's instruction layer.

Order of operations: `kanban_show()` to orient (KANBAN_GUIDANCE Step 1)
→ `cd "$HERMES_KANBAN_WORKSPACE"` to anchor the cwd (Workspace section
above) → `read_file` each of the four identity paths.

## Generation contract — `delegate_task`

The prose itself is generated by Hermes's `delegate_task` tool, used in
its canonical inside-one-run sense (a short reasoning subtask inside
YOUR run — NOT a board substitute; for cross-job handoffs use
`kanban_create`). The wrapped goal is assembled inside `execute_code`
from `autonovel_phase2/runner.py` helpers (`_wrap_prompt`,
`build_draft_system`, `build_draft_user`, `select_anchors`,
`load_identity`); the call shape is:

```
delegate_task(goal=<wrapped goal>, context="", toolsets=[], role="leaf", max_iterations=10)
```

`role="leaf"` keeps the child single-shot (non-leaf roles can recursively
dispatch). `toolsets=[]` is deliberate: a prose-generation child does
not need tools, and passing tools risks tangents. `max_iterations=10` is
the Pattern-5-validated bound.

The return value is a JSON string of shape
`{"results": [{"summary": "...", "child_session_id": "..."}]}` — parse
via `runner._extract_summary` and `runner._check_preamble` (the latter
raises on preamble leakage, a known model regression mode).

## Scoring + staging

After extracting the prose, score and stage inside `execute_code`:

- `evaluate.slop_score(prose)["slop_penalty"]` → float (production
  threshold 3.0; the firewall is internal to `stage_draft`)
- `voice_match.voice_match_score(prose, anchors)` → float (POV-aware)
- `staging.stage_draft(prose, slop_penalty, voice_match_score)` → returns
  an item with `queue_id` + `file_path`, OR `None` when the slop
  firewall trips (legitimate FAIL — no file written)

The output file at `publish_queue/<queue_id>.json` is what the future
Phase-5 publisher consumes; do NOT call `kanban_complete` referencing a
`queue_id` whose file isn't on disk.

## Heartbeats

Generation runs 3–20 minutes on qwen3-coder. **Call `kanban_heartbeat`
BEFORE `delegate_task`** so the dispatcher's `dispatch_stale` clock
re-arms from the heartbeat (not from worker startup) — long generation
without a heartbeat is the path to mid-generation reclaim. During very
long generations (>10 minutes), heartbeat at meaningful progress points;
name what's happening (`"delegate child returned, scoring prose"`), not
`"still working"`.

## Handoff — `kanban_complete` shape

```python
kanban_complete(
    summary=f"drafted {queue_id[:8] if queue_id else 'none'}... slop={slop:.2f} voice_match={vm:.2f} status={status}",
    metadata={
        "queue_id": queue_id,        # hex string on PASS; None on FAIL
        "slop_penalty": slop,        # float — evaluate.slop_score
        "voice_match": vm,           # float — voice_match_score
        "draft_excerpt": prose[:240],
        "status": status,            # "PASS" | "FAIL"
    },
    artifacts=[file_path] if file_path else [],
)
```

The `artifacts=[file_path]` parameter is the canonical way to surface
produced files (per OQ-K-3 / `tools/kanban_tools.py:392-460`); the
gateway notifier auto-attaches and `kanban_show` lists it visibly. Do
NOT stuff `file_path` into the `metadata` dict — that bypasses the
notifier. `worker_session_id` is auto-stamped by the substrate
(`tools/kanban_tools.py:118-129`); never set it yourself.

## Failure modes

| Symptom | Action |
|---|---|
| `read_file identity/self.md` → `File not found` (cwd drift) | `cd "$HERMES_KANBAN_WORKSPACE"` and retry; do NOT `find . -name "identity"` — that wastes the runtime budget. If cwd is unreachable, prefix the absolute path `/home/ubuntu/explore/autonovel/identity/self.md` |
| `delegate_task` returned `{"error": ...}` | `kanban_block(reason="delegate_task failed: <error>")` — do not retry blindly |
| `delegate_task` child timed out (per-child 1800s budget per OQ-K-2 / `delegation.child_timeout_seconds`) | `kanban_block(reason="delegate_task child timeout — model stalled past 1800s")` — distinct from the worker SIGTERM below |
| `_check_preamble(prose)` raised (preamble leakage) | `kanban_block(reason="prose contained delegate preamble — likely model regression")` + `kanban_comment` with the offending excerpt |
| `stage_draft` returned `None` (slop / voice firewall) | `kanban_complete(... status="FAIL", queue_id=None, artifacts=[])` — this IS a real outcome; the firewall did its job |
| Worker SIGTERMed at 30m (`--max-runtime`, enforced by `kanban_db.py:4343-4421`) | Whole process dies; task re-queues. Nothing you can do from inside |

Two timeout clocks: the `delegate_task` per-child (1800s, recoverable
via `kanban_block`) and the worker `--max-runtime 30m` SIGTERM
(substrate-enforced, unrecoverable). Conflating them mishandles a
recoverable delegate timeout as fatal, or vice-versa.

Exiting without `kanban_complete` or `kanban_block` causes the task to
be marked `dispatch_stale` after `kanban.dispatch_stale_timeout_seconds`
(default 4h) and re-queued as `ready`. The structured handoff IS the
verification gate.

## Block reasons that get answered fast

Bad: `"stuck"`. Good: one sentence naming the specific decision /
missing input.

- `kanban_block(reason="delegate_task child timeout — model stalled past 1800s")`
- `kanban_block(reason="identity file missing: identity/voice_priors.json")`
- `kanban_block(reason="Ollama at 100.72.47.4:11434 unreachable")`

## Do NOT

- **Do NOT invoke `terminal_tool` for kanban board operations** — use the
  `kanban_*` tools (the CLI fails in containerized backends; per the
  built-in `kanban-worker/SKILL.md`).
- **Do NOT call `delegate_task` recursively or as a board substitute** —
  for cross-job handoffs use `kanban_create` (per `KANBAN_GUIDANCE` §Do NOT).
- **Do NOT invoke `python3 runner.py` standalone via `terminal_tool`** —
  `runner.py` is a helper library, not an executable. That was the
  bd-b5p.5.5 broken-invocation pattern this worker shape supersedes.
- **Do NOT modify the `identity/*` files** mid-run — they are the
  read-only curation source-of-truth.
- **Do NOT call `kanban_complete` with fabricated `queue_id`** — the
  staging helper is the only thing that writes to `publish_queue/`; if
  `stage_draft` returned `None`, use the FAIL envelope
  (`status="FAIL"`, `queue_id=None`, `artifacts=[]`).
- **Do NOT list `created_cards`** on `kanban_complete` — this worker
  spawns no child cards.
- **Do NOT re-state the `KANBAN_GUIDANCE` lifecycle** — it's already in
  your system prompt; this skill is the autonovel-specific layer on top.
