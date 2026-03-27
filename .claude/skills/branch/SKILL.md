---
description: Branching and release strategy for versioned development with worktree agents
---

# Branch & Release Strategy

All development uses a single branching model. Work for any version lives on
a `v0.N/descriptive-name` branch. The descriptive name is a short kebab-case label
describing the scope of work (e.g., `auth-system`, `api-redesign`, `performance`).

**Core rule:** Worktree agents merge into the active branch, never into `main`.
Only the orchestrator merges to `main` and creates tagged releases.

## Branch Structure

```
main                          <- stable, only receives branch merges
+-- v0.2/auth-system          <- all auth-related work
|   +-- worktree-agent-XXX    <- OAuth implementation
|   +-- worktree-agent-YYY    <- session management
+-- v0.2/api-redesign         <- API restructuring (depends on auth)
|   +-- worktree-agent-AAA    <- endpoint migration
+-- v0.3/future-feature       <- future version work
```

## Naming Conventions

| Thing | Pattern | Example |
|-------|---------|---------|
| Branch | `v0.N/descriptive-name` | `v0.2/auth-system` |
| Release tag | `v0.N.R` | `v0.2.1` |
| Git release title | descriptive | `v0.2 Auth System` |
| Worktree branches | `worktree-agent-XXXX` | merge into active branch |

## Branch Lifecycle

### Step 1: Baseline Check

Before creating a branch, verify main is clean. Do not branch from a broken baseline.

```bash
git checkout main
# Run project quality checks (tests, lint, etc.)
```

**If checks fail, stop.** Fix the issue on main before starting new work.

### Step 2: Create Branch

```bash
git checkout -b v0.N/descriptive-name
git push -u origin v0.N/descriptive-name
```

### Step 3: Dispatch Agents

Agents merge into the active branch. Include in every agent prompt:

```
Merge target: v0.N/descriptive-name (NOT main)
```

Orchestrator merges agent work:

```bash
git checkout v0.N/descriptive-name
git merge worktree-agent-XXXX --no-edit
git merge-base --is-ancestor worktree-agent-XXXX HEAD  # safety check
```

Bead lifecycle is unchanged -- orchestrator closes beads and commits bead state
on the branch.

### Step 4: Verify

After all agents are merged, verify on the branch. Two gates must pass:

**Gate 1 -- Build quality:**

```bash
# Run all project quality checks (tests, lint, typecheck, etc.)
```

**Gate 2 -- Plan acceptance criteria:**

If a plan file exists for this branch, check every item in its acceptance criteria
section. These are plan-specific gates beyond generic build quality.

**If either gate fails, do not proceed.** Create fix beads and dispatch cleanup
agents. Re-run verification after fixes are merged.

### Step 5: Merge + Tag

```bash
# Merge to main and tag
git checkout main
git merge v0.N/descriptive-name --no-edit
git tag -a v0.N.R -m "<title> -- <summary>"
git push origin main --tags
```

### Step 6: Create GitHub Release

```bash
gh release create v0.N.R --title "<title>" --notes "$(cat <<'EOF'
## <title>

### Included
- [summary of what was done]

### Verification
- All tests pass
- Linting clean
EOF
)"
```

### Step 7: Cleanup

```bash
git branch -d v0.N/descriptive-name
git push origin --delete v0.N/descriptive-name
```

The branch is preserved in the tag. The branch itself is disposable.

## Version Scheme

```
v0.1.0   <- design complete (checkpoint before any code)
v0.1.1   <- first branch merged (whichever finishes first)
...
v0.1.13  <- all v0.1 work complete
v0.2.0   <- v0.2 design complete
v0.2.1   <- first branch merged
...
```

Tags are **sequential by merge order**, not by branch name. The release title
and tag message always describe the scope so the mapping is unambiguous.

## Parallelization

Branches that share no dependencies can run in parallel. Check the project's
plan files or roadmap for the current dependency graph.

## Rollback

```bash
# Revert a specific release (non-destructive)
git revert --no-commit v0.N.R~1..v0.N.R
git commit -m ":rewind: revert <title>"

# Hard reset to a checkpoint (destructive -- confirm with user first)
git reset --hard v0.N.R
```

## Quick Reference

```bash
# 1. Baseline check (abort if fails)
git checkout main && <run quality checks>

# 2. Create branch
git checkout -b v0.N/descriptive-name

# 3. Merge agent work into branch
git checkout v0.N/descriptive-name && git merge worktree-agent-XXXX --no-edit

# 4. Verify (abort if fails -- fix first)
<run quality checks>

# 5. Merge + tag
git checkout main && git merge v0.N/descriptive-name --no-edit
git tag -a v0.N.R -m "<title>" && git push origin main --tags

# 6. GitHub release
gh release create v0.N.R --title "<title>" --notes "..."

# 7. Cleanup
git branch -d v0.N/descriptive-name && git push origin --delete v0.N/descriptive-name
```
