---
description: Spec creation workflow for writing formal specification documents
---

# Spec Creation Workflow

You are a spec-writing agent. Your job is to produce a single, complete specification
document for a specific subsystem or feature. The spec must be grounded in primary
sources, and include testable acceptance criteria.

## Your Inputs

You will receive:
1. **Spec name** -- which spec you are writing (e.g., "Auth System Spec")
2. **Bead ID** -- your tracking ID, include as `Bead: <id>` in commit trailers (see `/beads` and `/commit`)
3. **Scope description** -- what the spec covers and what it does NOT cover

## Step 1: Load Context

Before writing anything, read these materials in order:

### Required Reading (every spec agent)
1. **Project CLAUDE.md** -- project definition, conventions, architecture
2. **Design decisions** -- any existing design docs, ADRs, or decision records
3. **Existing specs** -- read specs for subsystems this one depends on or interacts with

### Scope-Specific Reading
Identify and read the primary sources for your spec's domain:
- Existing implementation code (if any)
- Related specs in the project
- External references (RFCs, library docs, prior art)
- User stories or requirements documents

## Step 2: Understand the Baseline

For your subsystem, identify what already exists (code, docs, prior design).
Document the current state as the baseline that this spec formalizes or extends.

Key question: *What does the current system do (or intend to do) for this subsystem,
in concrete detail?*

## Step 3: Apply Design Decisions

Layer the project's locked design decisions on top of the baseline. For each
decision that affects your subsystem, document:
- **What changes** from the baseline
- **Why** (reference the decision ID or source)
- **How** (concrete specification of the new behavior)

## Step 4: Write the Spec Document

### Document Structure

Every spec document MUST follow this structure:

```markdown
# Spec: [Subsystem Name]

## 1. Overview
- What this subsystem does
- Its role in the overall system
- Dependencies on other subsystems
- What is NOT covered (explicit scope boundaries)

### 1.1 Sources and Provenance
- Table mapping each source document to the insight it contributes
- Format: `| Source | Insight applied to this spec |`

## 2. Current State / Baseline
- Summary of what currently exists for this area
- Key behaviors, data structures, APIs
- References to existing code or documentation

## 3. Changes and Decisions
- Each change from the baseline, with explicit markers:
  - **Change:** -- what is different
  - **Decision:** -- which design decision(s) drive this change
  - **Rationale:** -- WHY this change was made

## 4. Formal Specification
- Data structures (with type sketches where helpful)
- Algorithms in pseudocode
- API contracts (inputs, outputs, errors)
- State machines or protocol diagrams where appropriate
- Error conditions and their handling

## 5. Test Cases
- Testable examples with expected outputs
- Edge cases and error cases
- Each test case formatted as:

      TEST: [descriptive name]
      INPUT: [code or API call]
      EXPECTED: [output or behavior]
      RATIONALE: [what this tests]

## 6. Implementation Notes
- Suggested types, modules, and structure
- Language-specific considerations
- Performance-critical sections
- Security considerations

## 7. Open Questions
- Anything discovered during spec-writing that needs resolution
- Cross-references to other specs that must align

## 8. Future Considerations
- How this subsystem might evolve
- Forward-compatibility requirements for the current version
```

### Writing Guidelines

1. **Be concrete, not abstract.** Pseudocode > prose. Data structure layouts >
   descriptions. Actual code examples > hand-waving.

2. **Every claim needs a source.** Reference design docs, existing code, or
   external specs.

3. **Test cases are mandatory.** Minimum 10 test cases per spec. Include both
   happy-path and error cases.

4. **Type sketches, not final code.** The spec shows suggested layouts, but is
   not the implementation. Use `// sketch` comments.

5. **Cross-reference other specs.** If your spec depends on or interacts with
   another subsystem, name it explicitly and describe the interface.

6. **Current version only unless stated otherwise.** Spec the current behavior.
   Put future features in Section 8 only.

7. **Forward-compatibility.** When making design choices, note where they must
   be forward-compatible with known future plans.

## Step 5: Self-Review Checklist

Before committing, verify:

- [ ] Section 1.1 Sources and Provenance table lists all informing documents
- [ ] All project design decisions are reflected (or explicitly noted as n/a)
- [ ] Current state baseline is documented with specific references
- [ ] Every modification has Change:/Decision:/Rationale: markers
- [ ] At least 10 test cases with INPUT/EXPECTED/RATIONALE format
- [ ] Implementation notes include language-appropriate type sketches
- [ ] Current-version scope is clear -- no future features in the main spec body
- [ ] Future considerations section exists
- [ ] Open questions section exists (even if empty)
- [ ] Cross-references to dependent specs are noted

## Step 6: Output

Write the spec document to the project's spec directory (e.g., `specs/[NN]-[kebab-case-name].md`).

Commit with:
```
:page_facing_up: spec: [subsystem name]

Bead: <your-bead-id>
```
