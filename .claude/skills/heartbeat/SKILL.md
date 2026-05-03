---
name: heartbeat
description: Top-of-loop router for the autonovel autonomous agent. Fires every ≤1h via /loop, runs the routing table, dispatches at most ONE downstream skill per tick, sleeps. Drives mail / daily / triage / housekeeping AND gradient-driven /learn, /conceive, /write under the rate caps + anti-entropy rules from spec bd-49j.
---

## Execution

This is an in-session skill. The orchestrator runs every step directly using Read, Bash, the Skill tool (to invoke downstream skills), and the Agent tool (only when downstream skills dispatch subagents). **Do not add a Python tool that calls the Anthropic API for /heartbeat** — the routing logic is decision-tree code over on-disk state. The orchestrator is the runtime.

If you find yourself wanting to write `heartbeat.py` that imports `anthropic`, stop. The skill is the spec.

# /heartbeat — Top-of-loop router

Source of truth: spec bead **bd-49j**. Read its `--description` and `--notes` before working in this skill. The routing table, rate caps, anti-entropy clock, and stop conditions are all defined there.

Run via `/loop /heartbeat`. The first iteration runs immediately; each subsequent iteration is scheduled via `ScheduleWakeup` at the end of the previous tick (≤1h cadence).

## Step 0 — Sanity + stop checks

In order. Halt at the first match.

1. **Stop file:** if `.heartbeat-stop` exists in repo root → log halt, do NOT call `ScheduleWakeup`, exit. Human re-arms by deleting the file and re-running `/loop /heartbeat`.
2. **Open P0 STOP bead:** `br list --type human --priority 0 --status open` → if any title matches `^human: STOP` → halt as above.
3. **Error budget:** load `feedback/heartbeat-state.json`. If `consecutive_errors >= 3` → halt. File a P0 human bead `human: STOP — error budget exceeded` if not already present.
4. **Git state:** `git branch --show-current` must be `master`. `git status --short` must NOT show unstaged changes outside `feedback/heartbeat-log.md` and `feedback/heartbeat-state.json`. Anything weird → halt with a P0 human bead.
5. **Identity drift:** quick checksum on `identity/handles.json`, `identity/self.md`, `identity/voice_priors.json`, `identity/soul.md` against the last-seen checksums in heartbeat-state. Mismatch outside a /learn cycle → halt with a P0 human bead `human: STOP — identity-file mutation detected outside /learn`.

If sanity passes, proceed.

## Step 1 — Gather signals

Read these from on-disk state. Side-effect-free:

```python
from feedback.heartbeat_state import load_state
from identity.handles import is_self
from api.ao3_client import get_comments, needs_refetch

state = load_state(Path("feedback/heartbeat-state.json"))
today = utc_today()
daily_done = today.isoformat() in (Path("feedback/daily-log.md").read_text() if exists else "")
```

### 1a — New mail scan (rate-limited)

```python
new_mail = []
ao3_calls_this_tick = 0
for digest_path in glob("feedback/*_digest.json"):
    if ao3_calls_this_tick >= 5: break  # OQ-04 cap per heartbeat
    if not needs_refetch(digest_path): continue  # 30min TTL

    wid = parse_id(digest_path)
    digest = json.loads(Path(digest_path).read_text())
    comments = get_comments(wid)  # filter_self=True default
    ao3_calls_this_tick += 1
    digest["last_fetched_at"] = now().isoformat()

    if not digest.get("baseline_at"):
        # OQ-05 baseline-on-first-scrape: NO /mail fire
        digest["baseline_at"] = now().isoformat()
        digest["comments"] = [comment_to_record(c) for c in comments]
        Path(digest_path).write_text(json.dumps(digest, indent=2))
        continue

    last_seen_ids = {c["id"] for c in digest["comments"]}
    new = [c for c in comments if c.id not in last_seen_ids]
    if new:
        new_mail.extend([(wid, c) for c in new])
    Path(digest_path).write_text(json.dumps(digest, indent=2))
```

### 1b — Other signals

```python
open_human = run("br list --type human --status open --json")  # parse JSON
learn_pending = check_learn_eligibility()  # any work with new mail since last /learn cycle on it
brief_ready = check_brief_ready()  # brief in briefs/ + experiment bead in_progress + no draft.md
conceive_reactive = (
    state.last_learn_at is not None
    and (now - last_publish_at()) >= timedelta(hours=48)
    and no_in_progress_experiment()
)
entropy = compute_entropy(state, now)  # from feedback.heartbeat_state
stale_count = int(run("br stale --days 14 | wc -l").strip())
weekly_due = today.weekday() == 6 and state.housekeeping_done_week != iso_week(today)
```

## Step 2 — Status line (interactive sessions)

If running interactively (a human is reading), open the response with one line:

```
📬 {open_human_count} human · ⏰ next wake in {next_wake_min}m · 🔄 last heartbeat {since_last}m ago
```

If invoked unattended (during a /loop tick with no human present), skip the status line — write to `feedback/heartbeat-log.md` instead (Step 5).

## Step 3 — Route (priority order, AT MOST ONE skill per tick)

| # | Condition | Action |
|---|---|---|
| 1 | `len(open_human) > 0` | **Surface only** — log "surface: N human beads pending"; no skill fire. The ScheduleWakeup at Step 5 still happens. |
| 2 | `len(new_mail) > 0` | Invoke `/mail` with the `(wid, comment)` list. |
| 3 | `learn_pending` (any work has new comments since last /learn) | Invoke `/learn` for that work. /learn is rate-unrestricted (OQ-19). |
| 4 | `not daily_done` | Invoke `/daily`. |
| 5 | `brief_ready` AND `(now - state.last_write_at) > 48h` | Invoke `/write` with the brief path. (OQ-19 cap.) |
| 6 | `conceive_reactive` AND `(now - state.last_conceive_at) > 24h` | Invoke `/conceive` with mode=reactive. (OQ-19 cap.) |
| 7 | `entropy` AND `(now - state.last_conceive_at) > 24h` | Invoke `/conceive` with mode=entropy. **MANDATORY:** invoke `/ssot` first to force novelty axes (incl. fandom). |
| 8 | `stale_count >= 5` | Invoke `/triage`. |
| 9 | `weekly_due` | Invoke `/housekeeping`. |
| 10 | (else) | Log "idle". |

**Single-skill-per-tick is load-bearing.** If multiple branches match, the higher-priority one fires; lower-priority work re-evaluates next iteration. This caps per-tick cost.

## Step 4 — Invoke (with error capture)

```python
fire = pick_branch_per_table()  # returns (skill_name, payload) or None

if fire:
    try:
        invoke_skill(*fire)  # via Skill tool
        state = record_success(state)
        state = update_last_fire(state, skill=fire[0], ts=now)
    except Exception as e:
        state = record_error(state)
        log_error(e)
```

`record_success` resets `consecutive_errors` to 0. `record_error` increments. Hitting 3 → next iteration's Step 0 halts the loop.

## Step 5 — Persist + schedule next wake

```python
state.last_heartbeat_at = now
write_state(state, Path("feedback/heartbeat-state.json"))
append_heartbeat_log(
    f"{now.isoformat()} → {fire[0] if fire else 'idle'}",
    Path("feedback/heartbeat-log.md"),
)

if state.consecutive_errors < 3:
    delay = clamp(3500 + jitter(±300), 60, 3600)  # ~1h with jitter
    ScheduleWakeup(
        delaySeconds=delay,
        prompt="/loop /heartbeat",
        reason=f"next heartbeat after {fire[0] if fire else 'idle'}",
    )
```

`ScheduleWakeup` clamps to [60s, 3600s]. Hitting the upper bound is fine; the loop wakes hourly. The `/daily` Step 0 short-circuit handles same-day repeats.

## Anti-patterns

- ❌ **Multi-skill ticks** — pick ONE per iteration. If both mail and triage match, mail wins; triage waits.
- ❌ **Auto-firing /learn outside the reactive condition** — /learn must only fire when there's specifically a new non-self comment since the last /learn cycle on that work. Don't fire /learn on stale signal.
- ❌ **Skipping rate-limit gates on /write or /conceive** — those gates are the slop-prevention spine. Hit one autonomous /write per 48h max, one /conceive per 24h max. /learn is unrestricted; /mail is unrestricted (it's reactive to actual new comments).
- ❌ **Calling `br close` on human beads** — heartbeat NEVER closes a human bead. Only Andrew does. Heartbeat surfaces them, that's all.
- ❌ **Identity-file mutation outside /learn** — heartbeat reads `identity/*.md` and `*.json` but NEVER writes. Mutation outside the /learn invocation path is a corruption signal that triggers the Step 0.5 hard halt.
- ❌ **Skipping the baseline-on-first-scrape rule for new digests** — if there's no `baseline_at` field on a digest, the first scrape writes the baseline silently. Any other behavior risks mass-fire on digest wipe.
- ❌ **Forgetting `/ssot` on anti-entropy /conceive** — without /ssot the entropy fire collapses to "another quiet BG3 character study." That's distribution collapse, not exploration.
- ❌ **Auto-publishing** — heartbeat NEVER drafts an AO3 post. Drafts go to runs/ → human bead → human posts.
- ❌ **Long Bash chains for the routing table** — keep it as Python (the helpers above) called from the Bash tool. Each branch should be testable in isolation.

## Stop / re-arm reference

| Mechanism | Effect | Re-arm |
|---|---|---|
| `.heartbeat-stop` file | Step 0 halts; no ScheduleWakeup | `rm .heartbeat-stop && /loop /heartbeat` |
| Open P0 `human: STOP` bead | Step 0 halts | Andrew closes the bead |
| `consecutive_errors >= 3` | Step 0 halts; P0 STOP bead created | Andrew closes the STOP bead AND `rm feedback/heartbeat-state.json` (or zero out the field) |
| Closing the Claude Code session | Loop dies (session-bound per OQ-01) | New session: re-run `/loop /heartbeat` |

## See also

- Spec: `br show bd-49j` (Section 4.1 pseudocode this skill implements)
- `/mail` — invoked from heartbeat row 2
- `/daily` — invoked from heartbeat row 4
- `/conceive`, `/write`, `/learn` — invoked under gradient conditions from rows 3, 5, 6, 7
- `/triage`, `/housekeeping` — invoked from rows 8, 9
- `feedback/heartbeat_state.py` — load/write/compute helpers
- `identity/handles.py` — `is_self` filter (used inside `api.ao3_client.get_comments` by default)
- `api/ao3_client.py` — `needs_refetch`, `get_comments(filter_self=True)`
- `/ssot` — mandatory before anti-entropy /conceive (row 7)
- `/loop` — the cadence source
