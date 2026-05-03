---
name: daily
description: One iteration of the autonovel agent's daily rhythm. Self-paced via ScheduleWakeup ~24h. Protects deep work by handling only the noise around it — drafting, conceiving, and learning are NEVER on this loop.
---

## Execution

This is an in-session skill. The orchestrator runs every step directly using Read, Bash, the AO3 client, and (rarely) the Agent tool. **Do not add a Python tool that calls the Anthropic API for /daily** — the rituals here are file reads, light synthesis, and one small write. The orchestrator is the runtime.

If you find yourself wanting to write `daily.py`, stop. The skill is the spec.

# /daily — Daily rhythm

A real writer doesn't draft a chapter every day. The day has a rhythm: small, ritual work surrounds the rare bursts of substantive creative output. /daily handles the small ritual work. The substantive work — drafting, conceiving, learning — stays human-triggered or gradient-triggered, never clock-triggered.

Run once per iteration. Each iteration is small (≤25 minutes total of orchestrator work). Sleep ~24h. Repeat.

## Step 0 — Sanity check + today-already-done short-circuit (≤30 sec)

Verify you're in the right tree:

```bash
pwd  # must be /home/ubuntu/autonovel
git branch --show-current  # must be master, not worktree-agent-*
test -f identity/self.md || { echo "Wrong tree, aborting"; exit 1; }
```

If anything is off — wrong cwd, on a worktree branch, identity files missing — surface to user and skip the rest of the loop. The /loop driver handles re-scheduling.

### Today-already-done short-circuit (LOAD-BEARING)

Because `ScheduleWakeup` clamps to ≤1h, `/loop /daily` wakes hourly — but the rituals are designed to fire ONCE per UTC day. Without this short-circuit, every wake re-runs Steps 1-4 (including a fresh AO3 scrape on every iteration), which would burn AO3 quota and produce 24+ daily-log lines per day.

```bash
TODAY=$(date -u +%Y-%m-%d)
if test -f feedback/daily-log.md && grep -q "^${TODAY}" feedback/daily-log.md; then
  echo "today's rituals already done; skipping Steps 1-4"
  # If running standalone (not under /loop), still call ScheduleWakeup at Step 5.
  # If running under /loop /daily, /loop handles the next ScheduleWakeup — exit cleanly.
  exit 0
fi
```

Today is "already done" if `feedback/daily-log.md` has a line whose first 10 chars are today's `YYYY-MM-DD` (the EOD-note format from Step 4). The line gets written at the END of an iteration, so an iteration that crashes mid-flight will retry on the next wake.

If today's not done, proceed with Steps 1-4.

## Step 1 — Morning pages (≤5 min)

Orient. What changed since yesterday?

```bash
git log --oneline -10
br stats
br ready --limit 5
```

Read the most recent commit's message. Glance at MEMORY.md (the index, not every memory file). One sentence to the conversation: "Yesterday's headline was X. Today the open beads are Y."

No work yet. This is just orientation.

## Step 2 — Mail (≤10 min)

Pull AO3 stats and comments for every published work. Diff against the last digest.

```bash
# Find every digest file (one per published work)
ls feedback/*_digest.json 2>/dev/null
```

For each work id `{wid}` with a digest:

1. Fetch fresh metrics + comments via `api/ao3_client.py` (httpx, NOT anthropic).
2. Compare to `feedback/{wid}_digest.json`. New comments? New kudos? Subscribers up?
3. **New comment(s):**
   - Read the new comment(s) verbatim.
   - Draft a reply matching the pen-name's voice (no em dashes, no AI tells, see `feedback_no_em_dashes` in memory).
   - Save to `publish/replies_queue/{wid}_{comment_id}.md` for human review.
   - Surface to user: "New comment on {title} ({wid}). Reply queued at {path}. Read it before posting."
4. **No new comment:** note the metric delta in one line, move on.
5. **Engagement spike worth flagging** (kudos jumped, subs up, comment is high-signal): surface to user as something to investigate. Do NOT auto-fire `/learn`.

If the AO3 scrape fails (network, rate limit, AO3 down): log it, set `mail_empty = false` (so we don't burn the slot on a maintenance task), continue.

After mail: set `mail_was_empty = (no new comments AND no metric delta worth noting)`.

## Step 3 — One small maintenance task (≤10 min, ONLY if `mail_was_empty`)

If mail surfaced anything, skip this step. Mail-then-rest is the discipline; back-to-back tasks are how /daily turns into a slop machine.

If mail was empty, pick **ONE** of:

- **Groom one stale bead.** `br stale --days 14 | head -1` → read it → close, defer, or write a one-line `--notes` of current state. ONE bead. Not a triage pass.
- **Mine one calibration passage.** Pick one passage from a calibration draft (`write/runs/calibration_*/draft.md`) that holds up well, copy it into `identity/few_shot_bank.md` with attribution. ONE passage.
- **Sweep em-dashes from one paragraph.** Open the published-or-near-published draft, `grep -n '—'` for em-dashes, fix ONE paragraph by replacing with periods/commas/colons. ONE paragraph.

ONE thing. Not a parade. The point of the loop is to NOT pile up — small daily increments compound; daily marathons collapse.

## Step 4 — End-of-day note (≤2 min)

Write one line to `feedback/daily-log.md` (create if missing):

```
2026-MM-DD — <one-line summary of what happened today and tomorrow's first priority>
```

Examples:

```
2026-04-26 — mail empty; mined one passage (Shadowheart drinking). Tomorrow: check kudos on What the Hands Remember.
2026-04-27 — new comment on What the Hands Remember (id 12345); reply queued. Tomorrow: read it, decide whether to fire /learn.
2026-04-28 — AO3 was down; no mail. Skipped maintenance. Tomorrow: retry mail.
```

Commit if the log changed:

```bash
git add feedback/daily-log.md publish/replies_queue/ 2>/dev/null
git commit -m ":calendar: daily: $(date -I) ritual pass"
```

(Skip the commit on iterations that produced no changes — empty days are fine.)

## Step 5 — Schedule next wake (standalone-mode only)

**If invoked under `/loop /daily`, SKIP this step.** /loop handles the next ScheduleWakeup itself, so /daily calling it would double-schedule. Just exit cleanly.

If invoked standalone (manually, without /loop wrapping), use the `ScheduleWakeup` tool. Aim for ~22-24h forward with a few minutes of jitter so the loop doesn't drift to a perfectly predictable wall-clock time.

```python
# Pseudocode for the call shape:
import secrets
delay = 22 * 3600 + secrets.randbelow(2 * 3600)  # 22-24h
ScheduleWakeup(
    delaySeconds=delay,
    reason=f"daily ritual {date+1}; mail+maintenance+EOD note",
    prompt="/loop /daily",
)
```

The runtime clamps delaySeconds to [60, 3600] though, so for a true 24h sleep we cap at 3600s and accept that /daily will wake repeatedly through the day. For a long-running deployment, swap to `/schedule` with a cron expression instead — see "Long-haul mode" below.

## What's NOT on this loop

These are intentional invocations. /daily must NEVER autonomously fire any of them:

- **Drafting a chapter** (`/write`). Triggered by user or by an explicit "we have a brief, ship it" decision in conversation.
- **Conceiving a new piece** (`/conceive`). Triggered when the human picks a fandom + premise.
- **/learn from a digest.** Triggered when mail surfaces high-signal feedback that warrants identity update — surface the signal to the human; let them say "go." `/learn` writes to identity files; it must be deliberate.
- **Multi-task sprees.** One small thing per day, max. If you finished maintenance early, end the iteration. Do not start a second.
- **Reorganizing things.** Tidying / restructuring / refactoring is `/housekeeping`, not /daily. Different cadence.

The loop's job is to keep the noise down so the human's deep-work time is uncluttered. If /daily ever feels productive in a "I got a lot done" way, it's drifted. Pull it back.

## Long-haul mode (cron via /schedule)

`ScheduleWakeup` clamps to ≤1h, which means a self-paced /daily loop wakes many times per day. For an unattended multi-day deployment, switch to a true daily cadence via `/schedule`:

```
/schedule create --cron "0 14 * * *" --prompt "/daily"
```

(2pm UTC daily, or pick a time that aligns with when AO3 typically has fresh activity in your timezone.)

When using cron mode, /daily becomes single-shot per fire — Step 5 (ScheduleWakeup) is skipped, and `/schedule` handles the cadence.

## Anti-patterns

- ❌ **Putting deep work on the loop.** Drafting at 9am every day is how you get a chapter a day of slop. Deep work is intentional.
- ❌ **Skipping mail to do maintenance "while I'm in here."** Mail first. Mail is the only step that touches the outside world; it's the only one with information that decays.
- ❌ **Auto-firing `/learn` from inside /daily.** Learning rewrites identity. That's a deliberate act, not a daily ritual.
- ❌ **Doing two maintenance tasks "since I had time."** ONE. Banking time for tomorrow doesn't work; the loop spreads work across days on purpose.
- ❌ **Posting AO3 replies automatically.** Queue them for human review. AO3 TOS forbids automated posting and the human's eye is the quality gate.
- ❌ **Letting /daily pile up uncommitted state.** If something changed (queued reply, daily-log line, bead state), commit it. If nothing changed, don't fake a commit.
- ❌ **Cron + ScheduleWakeup at the same time.** Pick one cadence source. Cron via /schedule for unattended; self-paced /loop /daily for active sessions.

## See also

- `api/ao3_client.py` — httpx-based scraper used in Step 2
- `/feedback` — full digest pipeline; /daily's Step 2 is a lighter-weight diff against existing digests
- `/learn` — what to fire when mail surfaces something that warrants identity update (NOT auto)
- `/triage` — full bead triage; /daily's Step 3 grooms ONE bead, not the population
- `/loop`, `/schedule` — the two cadence sources
- `feedback_no_em_dashes` memory — comment replies must avoid em dashes (AI tell)
