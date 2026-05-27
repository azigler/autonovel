# autonovel-phase2-worker

Phase 2 Hermes-autonovel pipeline as a **Hermes kanban-worker skill**.
Replaces the bd-b5p.5 / bd-b5p.5.6 Pattern 5 cron-LLM design with
Hermes's native autonomous-agent substrate: a cron `--no-agent
--script` wrapper enqueues one kanban card per UTC day, and the
gateway-embedded kanban dispatcher spawns a worker that loads this
SKILL body alongside the built-in `devops/kanban-worker` reference.

**Bead:** `bd-b5p.7` · **Parent epic:** `bd-b5p` ·
**Supersedes (architecturally):** `bd-b5p.5` / `bd-b5p.5.6` (Pattern 5,
docs-only retained) · **Spec:** `br show bd-b5p.7`

## What this delivers

A Hermes skill at `~/.hermes/skills/autonovel-phase2-worker/` whose
body is a **kanban-worker recipe** the dispatcher loads into the
worker's system prompt when it spawns the worker for an
`autonovel-phase2-worker` card. The generic 6-step kanban lifecycle
(orient → work → heartbeat → block → complete → spawn) lives in the
auto-injected `KANBAN_GUIDANCE` block; this SKILL body covers the
autonovel-specific recipe layered on top:

1. **Step 1** (`kanban_show`): orient on the dispatched task (per
   `KANBAN_GUIDANCE` Step 1).
2. **Step 2** (`read_file` x4): load `identity/self.md`,
   `identity/voice_priors.json`, `identity/few_shot_bank.md`,
   `identity/soul.md` directly (bd-b5p.5 OQ-2 ACCEPT: bypass
   `skill_view` attribution preamble). The workspace `CLAUDE.md` is
   auto-injected by `prompt_builder` per OQ-K-1 — do NOT re-read it.
3. **Step 3** (`execute_code`): import `anchor_selector.select_anchors`,
   `identity_loader.load_identity`, `runner._wrap_prompt`,
   `write.prompts.{build_draft_system, build_draft_user}`; emit the
   `_PROSE_FRAME`-wrapped goal + anchors JSON.
4. **Step 4** (`kanban_heartbeat` then `delegate_task`): call Hermes's
   native `delegate_task(goal=<frame>, context="", toolsets=[],
   role="leaf", max_iterations=10)`. The heartbeat starts the
   `dispatch_stale` clock from the right point for long (3-20min)
   generations.
5. **Step 5** (`execute_code`): import `runner._extract_summary` +
   `runner._check_preamble` + `voice_match.voice_match_score` +
   `evaluate.slop_score` + `staging.stage_draft`. Parse, score, stage
   to `publish_queue/<queue_id>.json`.
6. **Step 6** (`kanban_complete` OR `kanban_block`): emit the
   structured handoff with metadata + artifacts list. The
   `kanban_complete(metadata=..., artifacts=[file_path])` shape IS
   the verification gate — workers that exit without it are marked
   `dispatch_stale` by the dispatcher (per OQ-K-3 — replaces the
   bd-b5p.5.8 ad-hoc verify-queue-file guard with a substrate-level
   invariant).

The pure-Python helpers (`runner.py`, `staging.py`, `voice_match.py`,
`anchor_selector.py`, `identity_loader.py`) ship UNCHANGED from the
bd-b5p.5.6 Pattern 5 sibling at
`hermes-skills/autonovel-phase2/` (per bd-b5p.7 §3.7). The worker
imports them via `importlib.util.spec_from_file_location` from
`execute_code` snippets.

A daily cron registered via `hermes cron create --no-agent --script`
fires the enqueue wrapper at 21:00 UTC; the wrapper has ZERO LLM on
its path, so it cannot confabulate (per bd-b5p.5.7 root cause).

## Install

```bash
# 1. Symlink the skill into ~/.hermes/skills/ (kanban dispatcher
#    picks up by name when an enqueued card has --skill
#    autonovel-phase2-worker).
mkdir -p ~/.hermes/skills
ln -sfn /home/ubuntu/explore/autonovel/hermes-skills/autonovel-phase2-worker \
    ~/.hermes/skills/autonovel-phase2-worker

# 2. Verify
ls -L ~/.hermes/skills/autonovel-phase2-worker/SKILL.md
```

## Bump the delegate_task child timeout (one-time, per OQ-K-2)

The worker uses `--max-runtime 30m`; the Hermes default
`delegation.child_timeout_seconds: 600` (10min) would clip
generations that run 12-20min on slow Ollama days. Bump to 1800s
(30min) in `~/.hermes/config.yaml`:

```yaml
delegation:
  child_timeout_seconds: 1800  # was 600 default; align with worker --max-runtime 30m
```

Restart the gateway to pick up the bump:

```bash
systemctl --user restart hermes-gateway.service
```

## Gateway-embedded dispatcher (no separate daemon)

Per OQ-K-5 of bd-b5p.7.1: `hermes kanban daemon` is DEPRECATED in
Hermes v0.14.0; the dispatcher loop is embedded inside
`hermes-gateway.service` via `kanban.dispatch_in_gateway: true`
(default; already set in `~/.hermes/config.yaml`). No separate
install — just confirm the gateway is up:

```bash
systemctl --user status hermes-gateway.service
grep -E '^\s*dispatch_in_gateway:\s*true' ~/.hermes/config.yaml
```

## Register the cron

The cron-fired wrapper at `~/.hermes/scripts/enqueue-autonovel-phase2.sh`
runs `hermes kanban create ...` to enqueue one card per UTC day.
Register it with `--no-agent --script` (the same shape Wave 1 uses
for Phase 1):

```bash
hermes cron create '0 21 * * *' \
  --no-agent \
  --script enqueue-autonovel-phase2.sh \
  --workdir /home/ubuntu/explore/autonovel \
  --deliver local \
  --name autonovel-phase2-enqueue
```

Verify:

```bash
hermes cron list | grep autonovel
# Expect autonovel-phase1-smoke (Wave 1) AND autonovel-phase2-enqueue.
```

## Manual smoke

To verify end-to-end without waiting for cron:

```bash
# 1. Fire the enqueue wrapper directly (creates one kanban card).
bash ~/.hermes/scripts/enqueue-autonovel-phase2.sh

# 2. Confirm the task landed on the board.
hermes kanban list | grep autonovel-writer

# 3. The gateway-embedded dispatcher polls every
#    `kanban.dispatch_interval_seconds` (default 60s) and will spawn
#    the worker. Wait up to ~35 minutes (max-runtime + slack), then:
hermes kanban list | grep autonovel-writer
hermes kanban show <task_id>

# Expect status=done with the §4.5 metadata schema populated:
#   queue_id, slop_penalty, voice_match, draft_excerpt, status
# AND the publish_queue/<id>.json path in the artifacts list.

# 4. Verify the staged draft is on disk:
ls -lt /home/ubuntu/explore/autonovel/write/runs/phase2/publish_queue/ | head
```

**Do NOT** try to invoke the worker any of these ways — they all fail
per bd-b5p.5.5 / bd-b5p.5.7 root cause:

```bash
# WRONG — runner.py is a library, not an executable. No main() exists.
python3 ~/.hermes/skills/autonovel-phase2/runner.py

# WRONG — terminal_tool subprocess has no parent_agent context;
# delegate_task errors; under --yolo the agent fabricates a success
# summary (the confabulation bug, bd-b5p.5.7).
hermes -z 'use the autonovel-phase2-worker skill: invoke runner.py via terminal_tool' --yolo

# WRONG — cron `--script` does not load skills; the cron-LLM path is
# what bd-b5p.5.7 confabulated through. ALWAYS go via kanban.
hermes cron create '0 21 * * *' '/skill:autonovel-phase2-worker run' --deliver local
```

## Run the tests

```bash
cd /home/ubuntu/explore/autonovel
.venv/bin/python3 -m pytest hermes-skills/autonovel-phase2-worker/tests/ -v
bash hermes-skills/autonovel-phase2-worker/tests/test_enqueue_script.sh
```

The pytest suite covers (per bd-b5p.7 §5):

- **Doc tests** asserting SKILL.md shape (`kanban_show` first,
  `delegate_task` with the canonical `leaf` + `toolsets=[]` shape,
  `kanban_complete` with the 5-key metadata schema + artifacts list,
  `kanban_heartbeat` on long ops, `kanban_block` on errors, Do NOT
  section forbidding `terminal_tool` for board ops + CLAUDE.md
  re-reads).
- **Contract tests** on the `kanban_complete` shape (per OQ-K-3
  amendment: file_path lives in artifacts, NOT metadata).
- **Helper coverage** sanity-imports of the 5 helper modules
  (`runner`, `staging`, `voice_match`, `anchor_selector`,
  `identity_loader`) — guards against accidental moves under §3.7
  "unchanged" disposition.
- **Config-state test** (`test_config_bump.py`) asserting
  `delegation.child_timeout_seconds >= 1800` per OQ-K-2.
- **Bash test** (`test_enqueue_script.sh`) covering the enqueue
  wrapper's args (kanban create + --skill + --workspace + --assignee
  + --max-runtime + --idempotency-key), idempotency (re-running on
  the same UTC day reuses the key), exit code propagation, JSON
  passthrough, and one-call-per-invocation discipline.

## File layout

```
hermes-skills/autonovel-phase2-worker/
├── SKILL.md   # kanban-worker recipe body (loaded by dispatcher)
├── README.md  # this file
└── tests/     # pytest + bash coverage (9 doc + N contract + N helper + bash)
```

The pure helpers live one directory up at
`hermes-skills/autonovel-phase2/` (bd-b5p.5.6 sibling, unchanged per
§3.7). The worker imports them via `importlib.util` from
`execute_code` snippets.

The cron-fired wrapper at `~/.hermes/scripts/enqueue-autonovel-phase2.sh`
is operator-side state (not in this directory). It contains zero LLM
on its path; `hermes kanban create` is the only command it runs.

## Rollback

Rollback is operational, not source-level. To pause Phase 2:

```bash
hermes cron pause autonovel-phase2-enqueue
```

In-flight kanban cards survive (per bd-b5p.5 OQ-7 ACCEPT — queue
items persist on rollback; operator decides per-item). To enumerate
queued cards:

```bash
hermes kanban list | grep autonovel-writer
```

To enumerate Phase-2-authored items already staged to disk:

```bash
ls /home/ubuntu/explore/autonovel/write/runs/phase2/publish_queue/
```

For each enumerated item, the operator decides per-item: delete
(`api/queue.py::delete_item`), retain for manual posting, or carry
forward.

## OQ resolutions (from the bd-b5p.7.1 /check walk)

| OQ | Question | Resolution (one-line) |
|----|----------|------------------------|
| OQ-K-1 | Does `kanban_show()` auto-inject workspace CLAUDE.md? | MODIFY — kanban_show itself doesn't, but `prompt_builder.py:1365-1390` cwd-scan does; worker auto-receives CLAUDE.md; don't re-read. |
| OQ-K-2 | `delegate_task` vs `--max-runtime` budget? | MODIFY — two clocks: bump `delegation.child_timeout_seconds` 600s→1800s. |
| OQ-K-3 | `kanban_complete` metadata schema? | ACCEPT — free-form dict; PLUS pass file via `artifacts=[...]` for gateway notifier hook. |
| OQ-K-4 | One daemon or per-skill? | ACCEPT (superseded by K-5) — dispatch is skill-agnostic; per-card `--skill` controls body load. |
| OQ-K-5 | New profile or default? | MODIFY (CRITICAL) — `hermes kanban daemon` DEPRECATED in v0.14.0; gateway embeds dispatcher; --assignee is a board label, not a profile. |
| OQ-K-6 | Phase 4+ multi-step support? | ACCEPT — `hermes kanban swarm` covers writer→critic→synthesizer for free. |

## See also

- **Spec:** `br show bd-b5p.7` (AMENDED 2026-05-27)
- **/check walk:** `br show bd-b5p.7.1` (CLOSED, 6/6 decisions)
- **Test bead:** `br show bd-b5p.7.2` (CLOSED, 91 tests)
- **Operationalize:** `br show bd-b5p.6` (config bump + cron register)
- **Parent epic:** `br show bd-b5p`
- **Pattern 5 predecessors (docs-only):** `bd-b5p.5`, `bd-b5p.5.6`
- **Conformance research:** `~/explore/local-coding-models/refs/research/research-hermes-conformance.md` (220 lines, HIGH confidence)
- **Hermes primer:** `~/explore/local-coding-models/refs/research/research-hermes-primer.md`
- **kanban-worker built-in reference:** `~/explore/hermes-agent-trial/.venv/skills/devops/kanban-worker/SKILL.md`
- **Pattern 5 sibling (helpers ship unchanged):** `hermes-skills/autonovel-phase2/`
- **Phase 1 (rollback target):** `hermes-skills/autonovel-phase1-smoke/`
