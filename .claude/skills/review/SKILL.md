---
description: Walk through open questions, cross-spec conflicts, and dependencies for decision-making
---

# Review Workflow

You are guiding the user through reviewable items that need decisions before
implementation can proceed. There are three item types:

1. **Open Questions (OQs)** -- Design questions needing a decision
2. **Cross-Spec Conflicts** -- Inconsistencies between specs needing alignment
3. **Cross-Spec Dependencies** -- Interface agreements between subsystems needing confirmation

Your job is to present each item with expert analysis, help the user decide, and
record the decision.

## Your Inputs

1. **Mode** -- one of:
   - A specific item: `review OQ-03`, `review conflict 7`, `review dep 14`
   - A batch: `review all P1`, `review all conflicts`, `review all deps`
   - Everything: `review all`
2. **Bead ID** -- include as `Bead: <id>` in commit trailers (see `/beads` and `/commit`)

## Step 1: Load Context

### Required Reading (every review session)
1. **Design decisions document** -- all OQs, conflicts, and dependencies with status
2. **Locked/decided design decisions** -- to understand what's already settled

### Per-Item Reading
For each item being reviewed:
- Read the **source spec(s)** referenced in the item
- Read any **related design docs** or prior art relevant to the question
- Understand the **implementation impact** -- what code/specs would change

## Step 2: Present the Item

### For Open Questions

```
### OQ-NN: [Title]
**Priority:** P1/P2/P3
**Source:** Spec NN, Section X
**Affects:** [which subsystems or specs]

**Question:** [the question verbatim from the decisions doc]

**Current Recommendation:** [the recommendation from the decisions doc]

**Expert Analysis:**
- **Current state:** [what the system does now, or what existing code/docs say]
- **Alternatives:** [concrete pros/cons of each option]
- **Prior art:** [how similar systems handle this, with references]

**Recommendation:** [ACCEPT / MODIFY / DEFER]
[rationale -- 2-3 sentences max]
```

### For Cross-Spec Conflicts

```
### Conflict #N: [Title]
**Specs involved:** Spec NN vs. Spec MM
**Affects:** [which subsystems]

**The inconsistency:** [description from decisions doc]

**Current proposed fix:** [what the decisions doc says should be updated]

**Expert Analysis:**
- **Root cause:** [why the specs diverged]
- **Recommended resolution:** [which spec should change, and how]
- **Impact if left unresolved:** [what breaks during implementation]

**Recommendation:** [ACCEPT proposed fix / MODIFY / DEFER]
```

### For Cross-Spec Dependencies

```
### Dependency #N: [Title]
**Specs involved:** Specs NN, MM, ...
**Affects:** [which subsystems]

**The dependency:** [description from decisions doc]

**Expert Analysis:**
- **Interface contract:** [what these specs must agree on]
- **Implementation ordering:** [which must be done first]
- **Current state:** [are the specs already aligned, or need updates?]

**Recommendation:** [CONFIRMED aligned / NEEDS spec update / DEFER]
```

Keep all analysis concrete. Cite specific docs, code, or external references. No hand-waving.

## Step 3: Record the Decision

### For OQs

When the user decides:

1. Update the OQ entry in the decisions document:
   - Add `**Status: DECIDED (YYYY-MM-DD)**`
   - Add `**Answer:** [the decision, one sentence]`
   - Add `**Rationale:** [brief rationale]`
   - Preserve the original question and recommendation

2. If the decision **contradicts** the recommendation, note this explicitly.

3. If the decision **affects a spec**, add a note:
   ```
   **Spec update needed:** Spec NN Section X must be updated to reflect [change].
   ```
   Do NOT modify specs during review. Record what needs updating.

4. If the decision **unblocks implementation**, note which subsystems.

### Discovering New OQs During Review

Watch for gaps or implicit assumptions not captured by any existing OQ. When
you identify a new gap:
1. Propose it: "This seems like a new OQ -- [brief description]. Want me to add it?"
2. If confirmed, add it with source, question, and recommendation
3. Note it in the session summary
4. Do NOT hold up the review to resolve it -- add and continue

### For Conflicts

1. Update the entry: `**Status: RESOLVED (YYYY-MM-DD)**`
2. Add `**Resolution:** [what was decided]`
3. Note which spec(s) need updates

### For Dependencies

1. Update the entry: `**Status: CONFIRMED (YYYY-MM-DD)**`
2. Add `**Interface agreement:** [one-sentence summary]`

## Step 4: Batch Mode

### OQ batches

When the user says "review all P1" (or P2, P3):
1. List all OQs at that priority with status
2. Skip decided OQs
3. Present open ones sequentially
4. Ask "Continue to next?" between each
5. Summarize all decisions at the end

### Conflict and dependency batches

Same pattern: list, skip resolved, present one at a time, summarize.

### Full review

When the user says "review all":
1. All open P1 OQs first (these block implementation)
2. Then open P2 OQs
3. Then open conflicts
4. Then open dependencies
5. Then P3 OQs (can be deferred)
6. Summarize everything at the end

## Step 5: Output

After each review session:

1. **Commit** the updated decisions document:
   ```
   :memo: decisions: resolve OQ-NN [, conflict N, ...] [, dep N, ...]

   Bead: <bead-id>
   ```

2. **Summarize** what was decided:
   ```
   ## Review Session Summary

   ### Open Questions
   | OQ | Decision | Spec Updates Needed |
   |----|----------|---------------------|
   | OQ-03 | Forbid changes after first instantiation | Spec 01 Section 4.X |

   ### Conflicts Resolved
   | # | Resolution | Spec Updates Needed |
   |---|-----------|---------------------|
   | 7 | Spec 12 references Spec 07 cache flush | Specs 07, 12 |

   ### Dependencies Confirmed
   | # | Agreement | Spec Updates Needed |
   |---|----------|---------------------|
   | 14 | Write barrier covers field-0 uniformly | Spec 01 add note |
   ```

3. **List blockers cleared** -- which subsystems are now unblocked.

4. **Check completeness** -- report:
   - How many OQs remain open
   - How many conflicts remain unresolved
   - How many dependencies remain unconfirmed
   - Whether all P1 OQs are decided (required before implementation)

## Step 6: Generate Implementation Readiness Report

When ALL P1 OQs are decided and ALL conflicts are resolved, generate:

```markdown
## Implementation Readiness Report

**Date:** YYYY-MM-DD
**P1 OQs decided:** N/N
**Conflicts resolved:** N/N
**Dependencies confirmed:** N/N

### Subsystem Readiness
- [Subsystem]: [READY / BLOCKED by OQ-NN, conflict #N]
- Spec updates needed before implementation: [list]

### Recommended Implementation Order
[Based on dependencies and resolved decisions]

### Spec Updates Required
[Consolidated list of all "Spec update needed" notes, grouped by spec number]
```

This report is the handoff artifact from `/review` to `/impl`.
