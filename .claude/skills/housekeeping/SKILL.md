---
description: Mechanical text work -- deletions, deprecation markers, doc updates, AD rewrites, config cleanup
---

# Housekeeping

Mechanical, non-creative changes that don't introduce new logic or behavior.

## What Housekeeping IS

- Deleting deprecated code (entire directories, files, dead imports)
- Adding deprecation markers to spec documents
- Updating architecture decisions in PLAN.md and CLAUDE.md
- Writing documentation (setup guides, workflow docs)
- Terminology renames (find-and-replace across files)
- Version bumps (pyproject.toml, constants)
- Stale doc/table cleanup (removing hardcoded counts, outdated tables)
- Gitignore updates
- Skill file creation or maintenance
- README/CLAUDE.md updates
- Fixing broken internal links or cross-references
- Removing dead tests for deleted code

All of these are deterministic text transformations. No design judgment required.

## What Housekeeping is NOT

- New features or capabilities (use `/spec` then `/test` then `/impl`)
- Spec amendments (use `/spec`)
- Test writing for new features (use `/test`)
- Open question resolution (use `/review`)
- Refactoring that changes behavior or API surface (use `/impl`)

If you're uncertain whether something is housekeeping, ask: "Does this require
reading a spec or making a design decision?" If yes, it's not housekeeping.

## Workflow

### 1. Inventory

List every file and change needed. Group by type:

| Type | What to check |
|------|---------------|
| **Deletion** | Grep for imports from target paths before deleting |
| **Deprecation** | Read each spec to confirm it's fully superseded |
| **AD update** | Read the current AD text and the spec that changes it |
| **Doc creation** | Read the source material being converted to docs |

```bash
# Example: verify nothing imports from modules being deleted
rg "from.*identity\.old" --type py
rg "import.*identity\.old" --type py
```

### 2. Dependency Check (Critical for Deletions)

Before deleting any directory or file:

1. **Grep for imports** -- search all `.py` files for import paths referencing the target
2. **Check test files** -- tests for deleted code should also be deleted
3. **Check pyproject.toml** -- remove scripts and dependencies that only served deleted code
4. **Check CLAUDE.md** -- update directory layout if it references deleted paths

```bash
# Full dependency scan before deletion
rg "(from|import).*target_module" --type py
```

If anything imports from a deletion target, classify:
- **Also being deleted** -- safe, proceed
- **Not being deleted** -- STOP. This needs code changes, which is `/impl` work

### 3. Apply Changes

Work in this order to avoid broken intermediate states:

1. **Delete code** -- remove deprecated directories and files
2. **Delete tests** -- remove tests for deleted code
3. **Update pyproject.toml** -- remove dead scripts and deps
4. **Add deprecation markers** -- update spec frontmatter
5. **Update architecture decisions** -- rewrite ADs in PLAN.md
6. **Update CLAUDE.md** -- reflect new directory layout and decisions
7. **Write new documentation** -- setup guides, workflow docs

### 4. Verify (Deterministic Quality Gates)

```bash
# Confirm deletions
ls target_dir/ 2>/dev/null && echo "FAIL: target still exists" || echo "OK"

# Confirm no dangling imports
rg "(from|import).*target_module" --type py

# If Python code was touched:
ruff check . 2>&1 | tail -20
uv run pytest 2>&1 | tail -20
```

Skip build/test checks if only documentation files were changed.

**Mass deletions require grep-based quality gates.** After deleting, run
deterministic grep scans for import paths referencing deleted modules. Never
trust a self-reported "done" without independent verification.

### 5. Deprecation Markers for Specs

Add a deprecation notice at the top of each deprecated spec, below the title:

```markdown
> **DEPRECATED by Spec 25 (Singleton Agent Model).** This spec describes
> systems that have been removed. It is retained as historical reference.
> See Spec 25 for the replacement.
```

Do NOT delete deprecated specs. They are historical reference.

### 6. Architecture Decision Updates

When updating ADs in PLAN.md:

- **Deprecated ADs** -- add `**DEPRECATED.**` prefix to the decision text
  and note which spec/AD replaces it
- **Replaced ADs** -- rewrite the decision text and rationale to reflect
  the new model. Preserve the AD number for cross-reference stability
- **New ADs** -- add with the next sequential number

### 7. Commit and Push

Follow `/commit` conventions. Use the gitmoji that best fits:

| Change type | Emoji |
|-------------|-------|
| Remove dead code/files | `:fire:` |
| Doc updates | `:memo:` |
| Config/tooling | `:wrench:` |
| Renames, moves | `:truck:` |
| Structure/formatting | `:art:` |

For large housekeeping passes, split into multiple atomic commits:
1. `:fire:` Deletions first (code + tests + deps)
2. `:memo:` Deprecation markers + AD updates
3. `:memo:` New documentation
4. `:memo:` CLAUDE.md + README.md refresh

Each commit should be independently valid (no broken imports, no dangling refs).

## 8. Project Documentation Refresh

Every housekeeping pass should end with a documentation and memory audit:

### CLAUDE.md
- **Directory Layout** -- does it match the actual filesystem after deletions?
- **Key Commands** -- are all listed commands still valid?
- **Architecture Decisions** -- do they match the ADs in PLAN.md?
- **Conventions** -- any new patterns or deprecated ones to update?

### README.md
- **Version** -- does it match the latest git tag?
- **Phase status** -- does the progress section match PLAN.md?
- **How It Works diagram** -- does it reflect the current architecture?
- **Getting Started** -- are the instructions still correct?
- **Commands** -- are the listed CLI commands still valid?

### Memory (`.claude/projects/.../memory/`)
- **Stale project memories** -- any that describe completed phases or old models?
- **Outdated feedback** -- any feedback that no longer applies?
- **Missing memories** -- anything learned this session worth persisting?
- **MEMORY.md index** -- does it match the actual files?

Audit each, fix what's stale, and commit as a final `:memo:` commit in the pass.
