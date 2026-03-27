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
.claude/             — Claude Code config, skills, hooks, refs
  skills/            — Development skills (commit, beads, lint, impl, etc.)
  refs/              — PLAN.md and reference documents
hooks/               — Claude Code hook scripts

# --- autonovel core (novel-writing pipeline) ---
*.py                 — 27 Python tools (drafting, evaluation, revision, etc.)
CRAFT.md             — Narrative craft frameworks
ANTI-SLOP.md         — AI tell detection (word-level)
ANTI-PATTERNS.md     — AI tell detection (structural)
voice.md             — Voice guardrails template
program.md           — Agent instructions per phase
PIPELINE.md          — Full pipeline specification
WORKFLOW.md          — Human-friendly step-by-step guide
typeset/             — LaTeX typesetting

# --- agentic author (new, being built) ---
identity/            — self.md, pen name, voice priors, inspirations
publish/             — AO3 post preparation, formatting, tag generation
feedback/            — Metrics scraping, comment parsing, engagement tracking
learning/            — Prompt evolution, few-shot bank, eval weight adjustment
strategy/            — What to write next, series planning, fandom analysis
```

## Tech Stack

- **Runtime:** Python (uv for dependency management)
- **AI:** Claude API (Anthropic) — Sonnet for writing, Opus for evaluation
- **Platform:** AO3 (Archive of Our Own) — human-in-the-loop posting
- **Task Tracking:** beads-rust (`br`)
- **Hooks:** Claude Code hooks for lint, commit checks, session management

## Development Workflow

This project uses lb-skills methodology. See `.claude/skills/` for:
- `/commit` — Gitmoji commit conventions with bead trailers
- `/beads` — Task tracking (one bead = one commit)
- `/lint` — Code quality (ruff for Python)
- `/impl` — Implementation orchestration
- `/branch` — Branch and release strategy

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
