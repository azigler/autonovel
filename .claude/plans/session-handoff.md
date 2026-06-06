# Session handoff — 2026-06-06 (triage + housekeeping)

## State at offboard
- Current branch: master (orchestrator merges worktree-agent-dotfiles in)
- Last commit at handoff write: 97dc7aa — `:card_file_box: beads: defer all Hermes-arc beads (bd-b5p tree)`
- Open beads (ready to claim):
  - `bd-3kw` P1 — learning: prompt evolution loop (gated on more reader signal)
  - `bd-3qd` P2 — engine adaptation research program (in pieces; tracked in bd-49j)
  - `bd-y3a` P2 — fandom analysis + story planning (gated on bd-pc8)
  - `bd-pc8` P1 — multi-chapter experiment (demoted in_progress→open this session; gated on foundation-phase design)
- Deferred (Hermes substrate arc, 7 beads):
  - `bd-b5p` (epic) + `bd-b5p.1`, `bd-b5p.5`, `bd-b5p.5.2`, `bd-b5p.5.7`, `bd-b5p.5.8`, `bd-b5p.7`
  - Also `bd-13y` (voiceover/podfic brainstorm), `bd-1p2` (cover-image brainstorm)
- In-flight subagents: none
- Open epics close-eligible: none

## What happened this session (triage + housekeeping)

### Beads
- Verified all 7 Hermes-arc beads are correctly DEFERRED (not accidentally closed). The deferral preserves the research record for a future refactor week — when Hermes-or-substrate comes back, the spec walks, study, and bug beads are already there.
- Demoted `bd-pc8` `in_progress` → `open`. The bead had been "in_progress" since 2026-04-26 with no active session work; gated on foundation-phase design (outline + foreshadowing ledger + character arcs adapted for fanfic) before any multi-chapter run is dispatchable. `open` more honestly reflects the queue state.
- Other open beads (bd-3kw, bd-y3a, bd-3qd) are real autonovel forward-work — left alone. Each has clear gating notes in their bodies.
- `br orphans`: clean. `br epic close-eligible`: none.

### Hermes deprecation
- Added a "Hermes substrate — deprecated / paused" section to `CLAUDE.md` documenting: the `hermes-skills/` subtree is retained on disk but not running; Phase 1 + Phase 2 crons are paused (Hermes runtime uninstalled); all bd-b5p tree beads are deferred; refactor week is the next inflection point. Also clarified that `Hermes Agent` / `Claude Hermes` in `typeset/` + `landing/` are the **novel's pen name**, a different "Hermes" entirely, unaffected.

### .gitignore
- Added `write/runs/phase1-smoke/draft-*.md` and `write/runs/*/draft-*.md` patterns so the 13 existing daily drafts (and any future automated drafts) stay on disk as creative artifacts but don't pollute `git status`. Existing untracked drafts are preserved per user request — they just disappear from `git status` going forward.

### Research content
- Committed the `refs/pi-dev-gap-audit.md` modification from the 2026-05-25 evening research arc — confirms the pi.dev tool-use gap on Qwen3 Ollama is empirically real even though all the wire-layer components are theoretically present (pi.dev injects structured tools, has harmony-recovery, but the integration is flaky). HIGH severity stands.

## What's next

1. **Refactor week (TBD)** — the cohort of choices about Hermes-vs-substrate-replacement. Reopen bd-b5p tree or close-superseded depending on the call.
2. **`bd-pc8` foundation-phase design** — the gate on multi-chapter fic. Engine adaptation work in `bd-3qd` / `bd-49j` is the upstream design pass; once stable, dispatch ch01.
3. **`bd-3kw` prompt evolution** — still gated on >1 published piece with feedback (currently n=1: TheIcyQueen-quoted entry 001).
4. **`bd-y3a` strategy system** — still gated on bd-pc8 producing more data points.

## Warnings / watch-outs

- The 13 daily smoke drafts in `write/runs/phase1-smoke/` are untracked output, not creative deliverables — they were the Phase 1 smoke-test producer's outputs. Now ignored by `.gitignore`. If user wants any specific draft published / sourced into the fic, surface it manually.
- `write/karlach_infernal_engine_scene.md` is untracked creative output from a prior session — left alone (per user choice).
- `.beads/issues.jsonl` will land in the merge commit reflecting bd-pc8 status demotion + appended note. No bead closures.
- Hermes substrate code under `hermes-skills/` is **not deleted** — the orchestrator may want to do a deliberate `:fire:` removal later if the refactor week decides Hermes is not coming back. For now, retained as reference.
