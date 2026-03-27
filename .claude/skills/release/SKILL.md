---
name: release
description: Cut a new release -- bump versions, update changelog, tag, and create GitHub release
argument-hint: "<version> [--dry-run]"
---

# /release - Release Process

Cut a new release by bumping versions, updating the changelog, creating a git tag,
and publishing a GitHub release. Ensures all quality gates pass before release.

## Usage

```bash
/release v1.2.0                 # Full release workflow
/release v1.2.1 --dry-run       # Preview what would happen without making changes
/release patch                  # Auto-bump patch version
/release minor                  # Auto-bump minor version
```

## Workflow

### Step 1: Validate

Before doing anything, check that the release is safe:

```bash
# Must be on main branch (or the project's release branch)
git branch --show-current

# Must be clean
git status --porcelain     # expect: empty

# Must be up to date
git pull --ff-only

# No open P1 beads
br list | grep "P1"        # expect: none
```

### Step 2: Run Quality Gates

All gates must pass. Abort the release if any fail. Run whatever quality checks
the project uses:

```bash
# Examples -- adapt to your project:
# Node/Bun:  bun run typecheck && bun test
# Rust:      cargo check && cargo test && cargo clippy -- -D warnings
# Python:    mypy . && pytest
# Go:        go vet ./... && go test ./...
```

### Step 3: Determine Version

If a specific version was provided (e.g., `v1.2.0`), use it. Otherwise:

- `patch` -- Increment the patch number (1.2.0 -> 1.2.1)
- `minor` -- Increment the minor number (1.2.0 -> 1.3.0)
- `major` -- Increment the major number (1.2.0 -> 2.0.0)

Read the current version from the project's version source (package.json, Cargo.toml,
pyproject.toml, etc.).

### Step 4: Bump Versions

Update version strings in all relevant files. Common locations:

- `package.json` (and workspace member package.json files)
- `Cargo.toml` (workspace and member crates)
- `pyproject.toml`
- `version.go` or constants files
- Any other files that embed the version string

Verify the bump:
```bash
# Check that all version references are consistent
grep -r '"version"' */package.json package.json 2>/dev/null | head -20
grep 'version =' */Cargo.toml Cargo.toml 2>/dev/null | head -20
```

### Step 5: Update PLAN.md

Check off any items in `PLAN.md` that were completed in this release. Compare the
work included in the release (commits, merged branches, closed beads) against the
plan's checklist items. Change `- [ ]` to `- [x]` for completed items.

```bash
# Review what's being released
git log --oneline $(git describe --tags --abbrev=0 HEAD~1)..HEAD

# Edit PLAN.md to check off completed items
# Stage it with the other release files in Step 7
```

If PLAN.md has no unchecked items relevant to this release, skip this step.

### Step 6: Update CHANGELOG.md

Move entries from `[Unreleased]` to the new version section. Add the release date.

**Before:**

```markdown
## [Unreleased]

### Added
- New webhook endpoint for file uploads
```

**After:**

```markdown
## [Unreleased]

## [v1.2.0] - 2026-03-05

### Added
- New webhook endpoint for file uploads
```

If there is no CHANGELOG.md yet, create one following [Keep a Changelog](https://keepachangelog.com/) format.

### Step 7: Commit

```bash
git add <version-files> PLAN.md CHANGELOG.md
git commit -m "$(cat <<'EOF'
:rocket: release v1.2.0

<milestone summary>

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

### Step 8: Tag

```bash
git tag -a v1.2.0 -m "<milestone name>"
```

### Step 9: Push

```bash
git push && git push --tags
```

### Step 10: GitHub Release

```bash
gh release create v1.2.0 \
  --title "v1.2.0 - <milestone name>" \
  --notes-file CHANGELOG.md
```

### Step 11: Verify

```bash
# Confirm tag exists
git tag -l "v1.2.*"

# Confirm GitHub release
gh release view v1.2.0

# Confirm version bump
# (use project-appropriate version check)
```

## Dry Run

When `--dry-run` is specified, perform all validation and gate checks but do NOT:

- Modify any files
- Create commits
- Create tags
- Push anything
- Create GitHub releases

Instead, print what would happen:

```
[dry-run] Would bump version: 1.2.0 -> 1.2.1
[dry-run] Would update 3 package.json files
[dry-run] Would update CHANGELOG.md (move 2 unreleased entries)
[dry-run] Would create commit: ":rocket: release v1.2.1"
[dry-run] Would create tag: v1.2.1
[dry-run] Would push to origin
[dry-run] Would create GitHub release: v1.2.1 - Hotfix: ...
```

## Safety Checks

- **Never release from a dirty working tree** -- all changes must be committed first
- **Never release with failing quality gates** -- fix issues before releasing
- **Never release with open P1 beads** -- critical issues block releases
- **Never release a MAJOR version without human approval** -- breaking changes need explicit confirmation
- **Always push tags immediately** -- do not leave tags local-only
