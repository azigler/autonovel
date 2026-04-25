# API vs Harness: Where the Anthropic SDK Belongs

Why some autonovel loops call the Anthropic API directly and others run inside
the Claude Code session. Read this before adding a new Python tool that imports
`anthropic`, or before "moving everything into subagents."

## TL;DR

- **One legitimate direct-API consumer:** the unattended prose-generation loop
  in `write/` (draft, muse seeds, revision passes). It needs a clean system
  prompt to embody the pen-name voice without the Claude Code assistant persona
  leaking into prose.
- **Three already-in-harness skills:** `/conceive`, `/feedback`, `/learn`. They
  read files, edit files, and call `br`. No prose generation, no API token
  required. Their SKILL.md files are the spec; the orchestrator is the runtime.
- **Seventeen dormant scripts** from the original autonovel novel pipeline still
  import `anthropic` but are never reached by the fanfic loop. Slated for
  cleanup in Phase 3.

The boundary: **direct API is justified only when the harness's persona overlay
would corrupt the output.** Drafting prose in a pen-name voice is the only
place that's actually true today.

## Audit: All 19 anthropic-importing files

Verify with:

```bash
grep -rln "anthropic\|Anthropic" --include="*.py" . \
  | grep -v ".venv\|__pycache__\|tests/\|.claude/worktrees"
```

Should return exactly 19 files.

### ACTIVE (legitimate direct-API consumers) — 1 file directly, 3 transitively

These are reached every time the fanfic write loop runs. They produce prose,
not control flow, and the harness persona would pollute the output.

| File | Role | Why direct API |
|------|------|----------------|
| `write/api.py` | Thin `call_claude(system, prompt)` wrapper around the Anthropic HTTP API. Sole entrypoint for the active loop. | Centralizes auth, retries, model selection. Imports `anthropic`. |
| `write/loop.py` | State machine: BRIEF → CONTEXT → DRAFT → EVALUATE → PREPARE → QUEUE → DONE. Calls `call_claude` for the DRAFT step. | Drafting needs the pen-name system prompt verbatim, not "I'll help you write a story." |
| `write/muse.py` | Generates oblique creative seeds (pre-draft, mid-revision, post-feedback) used to perturb the writer model out of safe defaults. | Embodiment-style task; persona overlay would flatten it. |
| `write/revision.py` | Multi-pass revision (structure, depth, voice, cut). Calls `call_claude` for each pass. | Same reason as draft — clean voice required. |

`write/loop.py`, `write/muse.py`, and `write/revision.py` do not themselves
`import anthropic`; they reach the SDK through `write/api.py`. The grep hits
them because they reference `from write.api import call_claude`.

### ALREADY IN-HARNESS (no Python tool, runs in-session today) — 0 files

These skills exist as `.claude/skills/{name}/SKILL.md` and are executed by the
orchestrator using Read, Write, Edit, and Bash. They do not appear in the grep
because no file calls the SDK on their behalf.

| Skill | What it does | Why no API call |
|-------|--------------|-----------------|
| `/conceive` | Reads `identity/self.md`, `identity/fandom_context.md`, `identity/voice_priors.json`, recent experiment bead results. Writes a brief to `briefs/{slug}.json`. Creates an experiment bead. | All inputs are on disk, all outputs are JSON. The orchestrator's reasoning IS the generation step. Round-tripping it through a separate API call adds cost and a translation layer that loses fidelity. |
| `/feedback` | Calls `api/ao3_client.py` (httpx, NOT anthropic) to scrape AO3 metrics and comments. Parses comments into a digest. Updates the experiment bead. | Network I/O against AO3 is httpx. Comment parsing into a digest is in-session synthesis — the orchestrator reads the raw comments and writes the digest directly. |
| `/learn` | Reads digest, edits `identity/self.md`, `identity/voice_priors.json`, `identity/inspirations.md`, few-shot bank. Closes the experiment bead. | Identity-file edits are surgical in-place edits, not generated prose. The orchestrator's reasoning about feedback is the learning step. |

The SKILL.md for each now contains an explicit "Execution" section warning
against adding a Python tool that calls the SDK.

### DORMANT (old autonovel novel pipeline, unused by fanfic loop) — 18 files

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

## The Decision Rule

When you're tempted to add a new Python tool that imports `anthropic`, ask:

1. **Does this generate prose in the pen-name voice?**
   - Yes: probably belongs in `write/` alongside the existing loop. Direct API
     is justified.
   - No: continue.
2. **Does this need a separate model context window from the orchestrator's
   session?** (e.g. parallel evaluation of many candidates)
   - Yes: justify it in writing first; the harness can dispatch subagents and
     that's usually cheaper and more debuggable.
   - No: continue.
3. **Does this just read files, transform them, and write files back?**
   - Yes: it belongs as a SKILL.md, not a Python tool. The orchestrator is the
     runtime.

If the answer is "I want a separate API call so I can iterate on the prompt
independently" — that's prompt engineering scaffolding, not production
infrastructure. Keep it in a notebook, not in `*.py`.

## Phases

This document is the deliverable of Phase 1 of bd-5lv. Two followup beads cover
the remaining work:

- **Phase 2 (bd-rno): pilot subagent-based prose generation for `/write`.**
  Run one calibration draft through an in-session subagent using the current
  `write/loop.py` system prompt. Compare against the API baseline on slop
  score, voice consistency, em-dash incidence (must be zero per the no-em-dashes
  rule), and length. Specifically test whether the Claude Code system-prompt
  overlay leaks "I'll help you..."-style framing into the prose, or whether a
  strong pen-name system prompt suppresses it. Decision doc at the end:
  keep direct API for `/write`, or migrate. **Do not migrate before the pilot.**

- **Phase 3 (bd-pqb): delete or archive the dormant novel pipeline.**
  After user confirmation, remove or move to `legacy/` the 17 dormant
  root-level scripts plus `run_pipeline.py`. Strip novel-pipeline content from
  `WORKFLOW.md` / `PIPELINE.md` / `program.md` (or delete them entirely). Drop
  `evaluate.py:call_judge` if no fanfic loop reaches it. Update the project
  layout section of `CLAUDE.md` to remove the "27 Python tools" claim.
