---
description: Session entrypoint -- discover state, classify work, route to sub-skill
---

# Orient

Entry point for every session. Discovers current state dynamically, classifies
remaining work by skill domain, and routes to the appropriate sub-skill.

**No hardcoded references.** Everything is discovered fresh from live state.

## Step 1: Read Foundation

Read **every** item below before taking any action. Do not skip any, and do not
proceed to Step 2 until all have been read and absorbed.

1. **`CLAUDE.md`** (root) -- project definition for autonovel (autonomous
   fanfiction author agent). Covers directory layout, tech stack (Python/uv,
   Claude API, AO3), anti-AI-detection priorities, and development conventions.
2. **`~/.claude/CLAUDE.md`** (global) -- user's private global instructions.
   These override defaults and contain delegation patterns, bead lifecycle,
   and worktree protocols.
3. **`.claude/refs/PLAN.md`** -- the project plan covering the core loop
   (identity, writing, publishing, feedback, learning), milestones (M0-M6),
   one-way doors, and architecture. This is the roadmap.
4. **`.claude/refs/methodology.md`** -- the two-loop methodology (engineering
   loop vs creative loop). Defines how experiment beads, calibration beads,
   and feedback beads work. Required reading for classifying work correctly.
5. **`MEMORY.md`** -- user preferences, operational lessons, feedback from
   prior sessions. Failing to read this causes repeated mistakes.
6. **Every skill file** in `.claude/skills/*/SKILL.md` -- read each one fully.
   These define the workflows, conventions, and guardrails for all operations
   (commit format, linting policy, bead tracking, branching, TDD, spec
   writing, orchestration, creative loop, etc.). Skipping a skill means
   missing best practices that apply to the current session.

## Step 2: Discover Live State

```bash
git tag --sort=-v:refname | head -5         # current version
git log --oneline -5                        # recent work
git branch -a | grep -v worktree            # active branches
br list                                     # open beads
git status --short                          # dirty files
```

From this, determine:
- **Version**: latest tag (e.g., v0.2.3)
- **Active branch**: any version branch means work in flight
- **Open beads**: any in-progress beads mean interrupted work
- **Experiment beads**: any experiment/calibration beads indicate creative loop state
- **Dirty files**: uncommitted changes need attention first

## Step 3: Find Current Position

Locate the project plan. For autonovel:
- `.claude/refs/PLAN.md` -- milestones M0-M6, architecture, one-way doors
- `CLAUDE.md` -- directory layout and constraints

Walk the plan milestones. Find the first incomplete item -- that's where we are.
Check off completed items against git history and live state.

## Step 4: Classify Work by Skill Domain

This project has two loop types (see `.claude/refs/methodology.md`). Determine
which loop the current work belongs to before routing.

### Engineering Loop

Builds the harness. Beads are deterministic with greppable acceptance criteria.

```
spec -> review -> test -> impl -> eval -> housekeeping -> release
        ^                                                    |
        +------- (new OQs discovered) ----------------------+
```

| Domain | Skill | When |
|--------|-------|------|
| **Spec** | `/spec` | Writing or amending a specification |
| **Review** | `/review` | Deciding open questions, resolving conflicts |
| **Test** | `/test` | Writing tests before implementation (TDD) |
| **Impl** | `/impl` | Building code until tests pass |
| **Eval** | `/eval` | Evaluating agent quality, harvesting feedback, running experiments |
| **Housekeeping** | `/housekeeping` | Deletions, deprecation markers, doc updates, AD rewrites |
| **Release** | `/release` | Merge branch to main, tag, GitHub release (uses `/branch` internally) |

**Route to `/eval` when:**
- Human left annotations on Phoenix traces that need harvesting
- Agent output quality needs verification after prompt or logic changes
- Prompt changes were made and need validation before release

### Creative Loop

Develops the author. Beads are experimental with hypotheses and results.

```
conceive -> write -> evaluate -> publish -> feedback -> learn
    ^                                                    |
    +----------------------------------------------------+
```

| Domain | Skill | When |
|--------|-------|------|
| **Conceive** | `/conceive` | Generating a story idea, creating experiment beads |
| **Write** | `/write` | Drafting, evaluating, revising a story from a brief |
| **Feedback** | `/feedback` | Collecting AO3 metrics and parsing reader comments |
| **Learn** | `/learn` | Processing feedback into identity updates, closing experiments |

**Pre-launch (calibration):** The loop is `conceive -> write -> evaluate -> learn`
(no publish/feedback). Calibration beads develop the voice before going live.

**Post-launch:** The full loop runs including publish and feedback stages.

**Route to creative loop when:**
- Open experiment or calibration beads need advancing
- Voice calibration is in progress
- Reader feedback has arrived and needs processing
- The agent's identity files need updating from results

## Step 5: Check Blockers

Before routing, verify:

1. **Open P1 questions** affecting target work? -> Route to `/review` first
2. **Prior branch not merged?** -> Can't start dependent work
3. **Pending human feedback?** -> Route to `/eval harvest` to capture it first
4. **Pending reader feedback?** -> Route to `/feedback` then `/learn`
5. **Calibration in progress?** -> Continue creative loop before starting new engineering work
6. **Dirty git state?** -> Clean up first
7. **Beads from interrupted session?** -> Assess whether to resume or close (check experiment beads too)

If blockers exist, present them and ask the user before proceeding.

## Step 6: Present and Route

Show the user:

```
## Orientation Report

**Version**: vN.M.R
**Position**: [description of where we are in the plan]
**Active plan**: [plan file path, if any]
**Phase**: [which phase is current]
**Loop**: [engineering / creative]
**Skill domain**: [spec / review / test / impl / eval / housekeeping / release / conceive / write / feedback / learn]
**Calibration status**: [not started / in progress / complete]
**Blockers**: [none / list]

**Recommended action**: [what to do next]
```

Then invoke the appropriate skill.

## Post-Compaction Recovery

If you're resuming after context compaction:

1. **Do NOT immediately create branches or beads.** Orient first.
2. **Read the active plan file** if one exists. It has the phase breakdown.
3. **Check what's already done** by comparing the plan against git history and
   live state. Don't redo completed work.
4. **Present your findings** before taking any action. The user may have context
   you don't.

The most common post-compaction mistake is jumping straight to `/impl` when the
current phase actually needs `/spec` or `/review`. Always classify the work first.
