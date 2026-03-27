---
name: lint
description: Code quality policy and linter reference for Python (ruff)
---

# /lint - Code Quality

## What's Automatic

A post-write hook runs on every file you write or edit. It silently auto-fixes formatting, import sorting, and safe lint issues. You do not need to run these manually:

| Extension | Hook runs | What it fixes |
|-----------|----------|---------------|
| `.py` | `ruff check --fix` + `ruff format` | Formatting, imports, safe lint fixes |

If the hook encounters an unfixable error, it feeds the error back to you. Fix the code and re-write the file.

## What's Automatic at Commit Time

A Claude Code PreToolUse hook intercepts `git commit` commands and runs deep linters on staged files before allowing the commit through. It only runs linters for languages that have staged changes:

| Staged files | Hook runs | What it catches |
|-------------|----------|-----------------|
| `.py` | `ruff check` | Final lint verification |

If the hook fails, it **blocks the commit** and feeds the errors back to you. Fix the issues, re-stage, and try the commit again.

### When Investigating Issues

Use check mode to audit without modifying files:

```bash
ruff check .                            # Lint check
ruff format --check .                   # Format check
```

Exit code `0` = clean. Non-zero = issues remain.

## Rules

- **Do not ignore lint errors** to unblock yourself. Fix them or ask for help.
- **Do not disable rules inline** (`# noqa`) unless the rule is genuinely wrong for that line, and leave a comment explaining why.
- **Do not run lint on files you did not modify.** Scope to changed files or directories.

## Known Gaps

These are things the linter cannot catch. Be vigilant about them manually:

- **Type checking** -- Ruff does not do type checking. If the project uses mypy or pyright, run those separately.
- **Unsafe fixes** -- Auto-fix only applies safe fixes. For unsafe fixes (renames, behavior-changing rewrites), run manually with `ruff check --fix --unsafe-fixes` and review the diff.

## Command Reference

### Ruff (Python)

```bash
ruff check --fix . && ruff format .     # Fix all (lint + format)
ruff check .                            # Check only
ruff check --fix --unsafe-fixes .       # Fix including unsafe fixes
ruff format --check .                   # Check formatting only
```
