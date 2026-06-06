# autonovel — Agentic Fanfiction Author

An autonomous fanfiction-writing agent that develops its own voice, publishes
under a pen name on AO3, collects reader feedback, and learns from it. Built
on top of the autonovel pipeline (novel-writing tools), extended with identity,
feedback, and learning systems.

**Topline goal:** Create a fanfiction agent with its own style that grows its
own fanbase, using a pen name, WITHOUT looking like AI writing.

## Directory Structure

```
.beads/              — Task tracking (beads-rust)
.claude/             — Claude Code config (project-local skills + hooks)
  skills/            — Project-local skills: conceive, write, feedback, learn, daily
hooks/               — Claude Code hook scripts
refs/                — Reference docs (PLAN.md, api-vs-harness.md, etc.)

# --- agentic author (the active fanfic loop) ---
write/               — Pure prompt builders + thin coordinator (post bd-75p)
  prompts.py         — Every prose / muse / revision prompt builder; no API calls
  loop.py            — setup_run, draft.md export; no state machine, no API
  brief.py, context.py, evaluate_fanfic.py, prepare.py, state.py, revision.py, muse.py
identity/            — self.md, soul.md, voice priors, fandom_context, few_shot_bank
publish/             — AO3 post preparation packages
feedback/            — Metrics, comments, digests
api/                 — AO3 client (httpx, NOT anthropic) + proxy
tests/               — pytest suite covering write/, identity/, api/

# --- shared craft / slop references ---
evaluate.py          — Mechanical slop detection (slop_score + tier banks)
CRAFT.md             — Narrative craft frameworks
ANTI-SLOP.md         — AI tell detection (word-level)
ANTI-PATTERNS.md     — AI tell detection (structural)
typeset/             — LaTeX typesetting
```

## Tech Stack

- **Runtime:** Python (uv for dependency management)
- **AI:** Claude Code in-harness subagents (no direct Anthropic SDK calls;
  see API Token Usage below)
- **Platform:** AO3 (Archive of Our Own) — human-in-the-loop posting
- **Task Tracking:** beads-rust (`br`)
- **Hooks:** Claude Code hooks for lint, commit checks, session management

## Development Workflow

Global skills are at `~/.claude/skills/` (commit, beads, lint, impl, spec,
test, check, fix, triage, housekeeping, dispatch, handoff, orchestrator,
loop, schedule, ssot, zig-voice, etc.). Project-local skills under
`.claude/skills/` are the agentic-author rituals:

- `/conceive` — Story ideation; writes `briefs/{slug}.json`, opens experiment bead
- `/write` — Drive draft → eval → revise → prepare via in-harness subagents
- `/feedback` — Scrape AO3 metrics + comments; write digest
- `/learn` — Process digest into identity-file updates; close experiment bead
- `/daily` — One iteration of the autonomous rhythm loop (morning pages,
  mail, one small task, EOD note). Self-paced; deep work NOT on the loop.

See `refs/methodology.md` for the two-loop methodology (engineering vs creative).

## Key Commands

```bash
br list                    # View open beads
br show <id>               # Bead details
br create -p 2 "scope: title"  # Create bead
uv sync                    # Install Python deps
uv run python <script>.py  # Run any tool
```

## Critical Constraints

1. **Anti-AI detection is the #1 priority.** If readers suspect AI, the project
   is dead. Every piece of writing must pass mechanical slop detection AND read
   as human-written. The ANTI-SLOP.md and ANTI-PATTERNS.md databases are sacred.

2. **Human-in-the-loop for publishing.** The agent prepares, the human posts.
   AO3 TOS prohibits automated posting. This also serves as a quality gate.

3. **One-way doors.** Published work can't be unpublished without consequences.
   Reputation accumulates. Early decisions (pen name, fandom, first work) are
   high-stakes. Err on the side of caution.

4. **The agent learns from real readers, not from itself.** Self-evaluation is
   a bootstrap. The real gradient comes from AO3 engagement metrics and comments.

## API Token Usage

As of bd-75p (2026-04-26), the fanfic loop has **zero direct Anthropic SDK
consumers**. Every skill runs in-harness through the Claude Code session:

- `/conceive` — read identity files, write a brief. No API call.
- `/write` — orchestrator dispatches in-harness subagents for draft / muse /
  revision using the prompt builders in `write/prompts.py`. The
  persona-suppression wrappers (`wrap_for_subagent`,
  `wrap_for_subagent_structured`) keep Claude Code's assistant persona from
  leaking into the prose. No direct API call.
- `/feedback` — scrape AO3 metrics (httpx, not Anthropic), parse comments,
  write digest. No API call.
- `/learn` — read digest, edit identity files in place. No API call.

If you're tempted to add a Python tool that imports `anthropic` for any of
these, you're recreating costly shadow infrastructure that the harness
already provides for free on the Max plan. Update the SKILL.md instead, or
add a builder to `write/prompts.py` and dispatch a subagent.

As of bd-pqb (2026-04-26), the 26 dormant autonovel novel-pipeline scripts
(gen_*.py, build_*.py, run_pipeline.py, etc.) have been deleted. Only
`evaluate.py` remains at the root — its `slop_score` is shared across
loops. See `refs/api-vs-harness.md` for the historical audit.

## Hermes substrate — deprecated / paused (2026-06-06)

The `hermes-skills/` subtree (`autonovel-phase1-smoke/`,
`autonovel-phase2/`, `autonovel-phase2-worker/`) was the kanban-substrate
implementation of the bd-b5p re-architecture epic. The Hermes runtime
was fully uninstalled in the 2026-06 cleanup session (`~/.hermes` and
`~/explore/hermes-agent-trial` deleted; Phase 1 + Phase 2 crons paused).

Status:
- All bd-b5p tree beads (epic + 6 children) are **deferred**, not closed
  — preserves the research record for a future refactor week.
- The `hermes-skills/` code is **retained on disk** as reference for
  whatever substrate comes next. Don't delete; don't run.
- Phase 1 daily smoke drafts produced over the arc live in
  `write/runs/phase1-smoke/draft-*.md` (kept per user request). The
  `.gitignore` now excludes that pattern so any future automated draft
  producer doesn't repollute git status.
- No active development on the Hermes integration. Refactor week is the
  next inflection point — at which time either revive Hermes from the
  deferred beads, replace the substrate with something else, or
  formally close the bd-b5p tree.

Anything tagged `Hermes Agent` / `Claude Hermes` in `typeset/` or
`landing/` is the **novel's published author identity** (the pen name
on AO3) — different "Hermes" entirely, unaffected by the substrate
cleanup.
