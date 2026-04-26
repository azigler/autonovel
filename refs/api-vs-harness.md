# API vs Harness: Where the Anthropic SDK Belongs

Why some autonovel loops call the Anthropic API directly and others run inside
the Claude Code session. Read this before adding a new Python tool that imports
`anthropic`, or before "moving everything into subagents."

## TL;DR (post-bd-75p)

- **Zero direct-API consumers in the active fanfic loop.** The write loop
  migrated to in-harness subagents on 2026-04-26 (bd-75p). Every prose,
  revision, and muse dispatch now goes through the orchestrator's Task
  tool, framed by the persona-suppression wrappers in
  [`write/prompts.py`](../write/prompts.py).
- **Four already-in-harness skills:** `/conceive`, `/feedback`, `/learn`,
  `/write`. They read files, edit files, dispatch subagents, and call `br`.
  No direct SDK imports. Each SKILL.md is the spec; the orchestrator is the
  runtime.
- **Seventeen dormant scripts** from the original autonovel novel pipeline
  still import `anthropic` but are never reached by the fanfic loop. Slated
  for cleanup in Phase 3.

The boundary used to be: "direct API is justified only when the harness's
persona overlay would corrupt the output." After the bd-75p pilot showed
that a strong persona-suppression frame can keep "I'll help you..."-style
preamble out of subagent prose, that boundary collapses to: **direct API
is never justified for the fanfic loop.** The harness handles
prose-generation just as cleanly, with the cost absorbed by the Max
subscription rather than billed per token.

## Migration record (2026-04-26, bd-75p)

| Before | After |
|--------|-------|
| `write/api.py` (httpx wrapper around Anthropic Messages API) | Deleted. |
| `write/loop.py` state machine calling `call_claude` | Reduced to `setup_run` + `_write_draft_md` + `load_soul`. The state machine is gone; the orchestrator drives the loop. |
| `write/muse.py:_call_muse` + three muse generators | Deleted. Prompt content moved to `write/prompts.py:build_muse_*`. The shim re-exports `parse_seeds`. |
| `write/revision.py:call_revision_model`, `run_revision_passes`, `_build_pass_system_prompt` | Deleted. Pass-system prompts moved to `write/prompts.py:build_revision_pass_system`. `generate_revision_brief` (pure) stays. |
| `tests/test_write_loop.py` mocking `write.loop.draft_chapter`, `write.loop.queue_work`, etc. | Replaced by tests for the surviving helpers (`setup_run`, `_write_draft_md`) plus pure-function tests for evaluate_gate, validate_brief, prepare, etc. |
| `tests/test_soul_muse.py` mocking `write.muse.call_muse` | Replaced by string-assertion tests on `write/prompts.py` builders. |

The persona-suppression frame contract (see `write/prompts.py`'s docstring
and the `_PROSE_FRAME` / `_STRUCTURED_FRAME` constants) is load-bearing.
The wrappers `wrap_for_subagent` and `wrap_for_subagent_structured`
embed `system` and `user` strings into a single user-message that
suppresses Claude Code's assistant persona. Do not paraphrase the
OUTPUT RULES block -- it's the contract bd-75p was designed around.

## Audit: anthropic-importing files

Verify with:

```bash
grep -rln "anthropic\|Anthropic" --include="*.py" . \
  | grep -v ".venv\|__pycache__\|tests/\|.claude/worktrees"
```

### ACTIVE (legitimate direct-API consumers) — 0 files

The fanfic write loop no longer reaches the SDK. There are no active
direct-API consumers.

### ALREADY IN-HARNESS — 4 skills

These skills exist as `.claude/skills/{name}/SKILL.md` and are executed by
the orchestrator using Read, Write, Edit, Bash, and (for `/write`) Task.

| Skill | What it does | Mechanism |
|-------|--------------|-----------|
| `/conceive` | Reads `identity/self.md`, `identity/fandom_context.md`, `identity/voice_priors.json`, recent experiment bead results. Writes a brief to `briefs/{slug}.json`. Creates an experiment bead. | Direct file I/O; orchestrator's reasoning IS the generation step. |
| `/feedback` | Calls `api/ao3_client.py` (httpx, NOT anthropic) to scrape AO3 metrics and comments. Parses comments into a digest. Updates the experiment bead. | Network I/O against AO3 is httpx; comment-to-digest synthesis is in-session. |
| `/learn` | Reads digest, edits `identity/self.md`, `identity/voice_priors.json`, `identity/inspirations.md`, few-shot bank. Closes the experiment bead. | Surgical in-place edits; orchestrator's reasoning about feedback is the learning step. |
| `/write` *(new in bd-75p)* | Calls `setup_run` to seed state, builds prompts via `write.prompts`, dispatches Task subagents for draft / revision / muse, evaluates output via `write.evaluate_fanfic`, prepares for AO3 via `write.prepare`. | Orchestrator coordinates Python helpers + Task subagents. The subagents inherit the harness persona but the prompt frame suppresses leakage. |

### DORMANT (old autonovel novel pipeline, unused by fanfic loop) — 17 files + 1 partial

These belong to the original "write a full novel from a seed" pipeline that
predates the agentic-fanfic project. The fanfic loop never calls them.

Direct anthropic imports (17 files):

- `gen_world.py`, `gen_canon.py`, `gen_characters.py`
- `gen_outline.py`, `gen_outline_part2.py`
- `build_outline.py`, `build_arc_summary.py`
- `draft_chapter.py`, `gen_revision.py`
- `adversarial_edit.py`, `review.py`, `reader_panel.py`, `compare_chapters.py`
- `gen_audiobook_script.py`, `gen_art.py`, `gen_art_directions.py`
- `seed.py`

Partially dormant (1 file):

- `evaluate.py` — `call_judge` is dormant (LLM-as-judge for the novel
  pipeline). `slop_score` is mechanical, ANTI-SLOP-driven, and **must stay** —
  it's the hard gate the fanfic loop relies on.

Related dormant orchestration (does not import anthropic but is part of the
same dead pipeline, listed for Phase 3 awareness):

- `run_pipeline.py` — top-level novel orchestrator that shells out to the 17
  scripts above
- `WORKFLOW.md`, `PIPELINE.md`, `program.md` — novel-pipeline docs

These 17+1 files will be deleted or archived in Phase 3 once the user confirms
nothing depends on them.

## The Decision Rule (post-bd-75p)

When you're tempted to add a new Python tool that imports `anthropic`, ask:

1. **Does this need to run unattended outside a Claude Code session?**
   - Yes: justify in writing first. The harness is the runtime for
     everything in the fanfic loop today; a non-harness path adds
     infrastructure surface area and bills the API per token instead of
     absorbing into the Max subscription.
   - No: continue.
2. **Does this just read files, transform them, and write files back?**
   - Yes: it belongs as a SKILL.md, not a Python tool. The orchestrator is the
     runtime.
3. **Does this generate prose / structured output?**
   - Yes: the orchestrator dispatches a Task subagent. Build the prompt
     in `write/prompts.py` (or a sibling pure module) and wrap it with
     `wrap_for_subagent` / `wrap_for_subagent_structured`.

If the answer is "I want a separate API call so I can iterate on the prompt
independently" — that's prompt engineering scaffolding, not production
infrastructure. Keep it in a notebook, not in `*.py`.

## Phases

This document is the deliverable of Phase 1 of bd-5lv. Two followup beads
covered the remaining work:

- **Phase 2 (bd-rno → bd-75p): pilot subagent-based prose generation for
  `/write`.** Completed 2026-04-26. The migration record above documents the
  final state. The pilot confirmed that a strong persona-suppression frame
  is sufficient to keep assistant-persona leakage out of the prose.

- **Phase 3 (bd-pqb): delete or archive the dormant novel pipeline.**
  After user confirmation, remove or move to `legacy/` the 17 dormant
  root-level scripts plus `run_pipeline.py`. Strip novel-pipeline content from
  `WORKFLOW.md` / `PIPELINE.md` / `program.md` (or delete them entirely). Drop
  `evaluate.py:call_judge` if no fanfic loop reaches it. Update the project
  layout section of `CLAUDE.md` to remove the "27 Python tools" claim.
