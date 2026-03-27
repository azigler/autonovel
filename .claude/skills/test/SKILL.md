---
description: Test creation workflow converting spec test cases into executable tests
---

# Test Creation Workflow

You are a test-writing agent. Your job is to convert a spec document's test cases
into executable tests, plus add additional edge-case and integration tests discovered
during analysis.

## Your Inputs

1. **Spec number and name** -- which spec you're writing tests for
2. **Bead ID** -- include as `Bead: <id>` in commit trailers (see `/beads` and `/commit`)
3. **Dependencies** -- which modules must exist before these tests can run

## Step 1: Load Context

### Required Reading
1. The spec document you're testing
2. Project design decisions -- especially any resolved open questions
3. The `/spec` skill -- understand the spec format

Also read the specs for any subsystems your tests depend on, so you understand
the interfaces you'll be calling.

## CRITICAL: Test Agents Write ONLY Test Files

**You must NEVER create or modify implementation source files.** Your output is
exclusively test files.

### Import from real module paths, not stubs

**Always import from the real module paths where the implementation will live.**
The tests will fail until implementation lands -- that is expected and correct.
The impl agent's job is to make the tests pass without modifying them.

```typescript
// CORRECT -- import from the real path (module doesn't exist yet, that's fine)
import { loadAgentConfig } from "../loader.js";
import type { AgentConfig } from "../types.js";

// WRONG -- do NOT write inline stubs, mocks, or placeholder implementations
const loadAgentConfig = () => { throw new Error("not implemented"); };
```

Why: If you write stubs, the impl agent will rewrite your test file to replace
them with real imports, causing merge conflicts and defeating the purpose of TDD.
The tests define the contract; the implementation must match the tests.

### When to use skip markers

Use `test.skip()` or `test.todo()` ONLY for tests that genuinely cannot run even
after implementation lands (e.g., needs a running server, external service, or
integration environment):

- **Rust**: `#[ignore = "needs running server"]`
- **TypeScript/JS**: `test.skip("needs Next.js runtime", () => { ... })`
- **Python**: `@pytest.mark.skip(reason="needs running server")`
- **Go**: `t.Skip("needs running server")`

Do NOT skip tests just because the implementation doesn't exist yet. Write them
as active tests with real imports -- they will fail now and pass after impl.

Do NOT write stubs, scaffolding, or placeholder implementations in source files
to make tests compile. The impl agents handle all source code.

## Step 2: Extract Test Cases from Spec

Read the spec's Section 5 (Test Cases). Each test case has:
```
TEST: [name]
INPUT: [code or API call]
EXPECTED: [output or behavior]
RATIONALE: [what this tests]
```

Convert each to a test. The test should:
1. Set up the necessary state
2. Execute the operation described in INPUT
3. Assert the EXPECTED output
4. Include the RATIONALE as a doc comment

## Step 3: Add Edge Cases and Error Tests

For every spec test case, consider:
- **Boundary values**: empty collections, zero, MAX_INT, nil/null/undefined
- **Error paths**: what happens on invalid input? Does it throw or return error?
- **Concurrency** (if applicable): what if two operations run simultaneously?
- **Persistence** (if applicable): does this survive save/restore?

Add at minimum 5 additional tests beyond what the spec provides.

## Step 4: Write the Test File

### Naming Conventions

These conventions apply regardless of implementation language:

- Test function: `snake_case` matching the spec test name (or `camelCase` per language convention)
- Spec tests: direct from spec, no prefix
- Edge cases: prefix function name with `edge_`
- Error paths: prefix function name with `error_`
- Integration: prefix function name with `integration_`
- Doc comment: always include `TEST:` or `EDGE:` or `ERROR:` label

### Test Structure Example (language-agnostic pattern)

```
// Spec Test Cases
// Each maps 1:1 to a spec Section 5 test case

/// TEST: basic-create (Spec NN, Test Case 01)
/// Verifies that creating an entity returns expected fields.
test basic_create() {
    // setup
    // execute
    // assert
}

// Edge Case Tests
// Additional coverage beyond the spec

/// EDGE: empty-input
/// Tests behavior when input is empty/null.
test edge_empty_input() {
    // setup
    // execute
    // assert
}

// Error Path Tests

/// ERROR: invalid-id
/// Tests that invalid IDs produce a clear error, not a crash.
test error_invalid_id() {
    // setup
    // execute
    // assert error
}
```

### Handling Unimplemented Dependencies

Most tests should import from real module paths and be written as active tests.
They will fail until implementation lands -- this is correct TDD behavior.

Only use skip markers for tests that need **external infrastructure** (running
servers, cloud services, integration environments) that won't exist even after
the module is implemented:

```
# Rust:    #[ignore = "needs running database"]
# JS/TS:  test.skip("needs Next.js runtime", () => { ... })
# Python:  @pytest.mark.skip(reason="needs running Redis")
# Go:      t.Skip("needs running database")
```

Do NOT skip tests just because the imported module doesn't exist yet.

## Step 5: Self-Review Checklist

Before committing, verify:

- [ ] Every spec test case (Section 5) has a corresponding test
- [ ] At least 5 additional edge-case/error tests beyond the spec
- [ ] Each test has a doc comment with TEST/EDGE/ERROR label and spec reference
- [ ] Tests parse as valid syntax (imports from real module paths, even if modules don't exist yet)
- [ ] No inline stubs or placeholder implementations -- only real imports
- [ ] Naming follows conventions (prefixes, language-appropriate case)
- [ ] Integration tests are separated from unit tests
- [ ] **NO implementation source files were created or modified**

## Step 6: Output

Write the test file to its appropriate location per project conventions.

Commit with:
```
:white_check_mark: tests: spec NN [subsystem name]

Bead: <your-bead-id>
```
