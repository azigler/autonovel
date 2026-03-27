---
name: beads
description: Task tracking with beads-rust (br) for managing development work
argument-hint: "[list|create|close|show|update|sync]"
---

# /beads - Task Tracking

Track development tasks using `br` ([beads-rust](https://github.com/Dicklesworthstone/beads_rust)).

## Quick Reference

```bash
br list                                  # List all open beads
br create -p 2 "scope: title"           # Create a new bead
br update <id> --description "..."       # Add description (ALWAYS do this)
br show <id>                             # Show bead details
br update <id> --status=in_progress      # Claim a bead
br close <id>                            # Close a completed bead
br delete <id>                           # Tombstone a bead (wrong/invalid)
br sync --flush-only                     # Export to JSONL for git tracking
br sync --import-only                    # Import JSONL changes from other agents
```

## Core Principle: One Bead = One Commit

- Close beads BEFORE committing (so JSONL reflects closed state in the diff)
- Every commit message includes a `Bead: <id>` trailer (see `/commit`)
- Never batch multiple bead closures into one commit
- The pre-commit hook warns if the `Bead:` trailer is missing

## Priority Levels

| Priority | Flag | Use For |
|----------|------|---------|
| P1 | `-p 1` | Critical -- production issues, security, blockers |
| P2 | `-p 2` | Important -- current sprint work, active features |
| P3 | `-p 3` | Backlog -- nice-to-have, future work, tech debt |

## Bead Titles

Use a scope prefix matching the area of work:

```bash
br create -p 2 "auth: add JWT token refresh"
br create -p 1 "api: fix rate limit bypass"
br create -p 3 "tests: add integration coverage for payments"
```

## Bead Descriptions

Every bead MUST have a description. Add it immediately after creation:

```bash
br update <id> --description "$(cat <<'EOF'
## Context
Brief background on why this work is needed.

## Task
What specifically needs to be done.

## Acceptance Criteria
- [ ] Concrete deliverable
- [ ] Another deliverable
EOF
)"
```

## Agent Protocol

### At Start
Claim the bead from your task prompt:
```bash
br update <bead-id> --status=in_progress
```

If no bead ID was provided, create one yourself.

### At Completion
```bash
br close <id>                  # Close BEFORE committing
br sync --flush-only           # Export to JSONL
git add .beads/issues.jsonl    # Stage the closed-state JSONL
# Then commit with Bead: <id> trailer and push (see /commit)
```

## Feedback → Fix Beads → Evaluators

When stakeholder feedback arrives (from Phoenix annotations, Google Doc comments,
Slack messages, or any other channel), the standard pattern is:

1. **Create a fix bead** for each discrete piece of feedback:
   ```bash
   br create -p 1 "fix: accounts — [what the feedback says to change]"
   ```

2. **Each fix bead produces an evaluator** — the fix isn't done until there's a
   code evaluator in `factory/eval/evaluators.py` that checks for the issue.
   This ensures the problem doesn't regress.

3. **Close the fix bead** after the prompt/code change AND the evaluator are both
   committed.

This pattern turns every piece of human feedback into a permanent quality gate.

## Atomic Sizing

**Before creating a bead, ask: can one agent complete this in one session?**

- 1-3 acceptance criteria, 1-3 files = good atomic bead
- 4+ criteria or 4+ files = split into multiple beads
- Multiple "and then..." = definitely split
