---
name: write
description: Execute the write loop to draft, evaluate, and revise a story from a brief. Orchestrator-driven; in-harness subagents do the prose generation.
argument-hint: "[brief-path] [bead-id]"
---

## Execution

This is an in-session skill. The orchestrator runs every step directly using Read, Write, Edit, Bash, and the Agent tool (for prose-generation subagents). **Do not add a Python tool that calls the Anthropic API for /write** — that's exactly what the bd-75p migration retired. The Python helpers in `write/` are now pure: prompt builders, evaluation, prepare, state. The orchestrator is the runtime; in-harness subagents generate the prose.

If you find yourself wanting to write `write/api.py` or any Python file that imports `anthropic`, stop. Read `refs/api-vs-harness.md` and `write/prompts.py` first — every prompt expression already lives there.

# /write — Draft a Story

Drive a story brief through BRIEF → CONTEXT → (MUSE) → DRAFT → EVALUATE → (REVISE) → PREPARE → QUEUE → DONE. Each prose step is a subagent dispatch wrapped in the persona-suppression frame from `write/prompts.py:wrap_for_subagent`.

## Prerequisites

- Story brief exists: `briefs/{slug}.json` (from `/conceive` or manual)
- Experiment bead exists for this story (created by `/conceive`, or create one first)
- `identity/`, `ANTI-SLOP.md`, fandom context files in place

## Pipeline

### Step 1 — BRIEF: validate + setup

```python
import json
from write.brief import StoryBrief, validate_brief
from write.loop import setup_run

brief_data = json.loads(open("briefs/{slug}.json").read())
brief = StoryBrief(**brief_data)
validate_brief(brief)
state = setup_run(brief, brief_path="briefs/{slug}.json")
print(state.run_id)
```

Run via `uv run python -c "..."`. Capture the `run_id`. State file is at `write/runs/{run_id}/state.json`.

### Step 2 — CONTEXT: assemble identity + fandom + anti-slop

```python
from identity.schema import load_identity
from write.context import assemble_context
from write.config import load_config
from write.loop import load_soul

identity = load_identity()
context = assemble_context(brief=brief, identity=identity)
soul = load_soul()
config = load_config()
```

`context` is a dict with keys `identity`, `anti_slop_rules`, `fandom_context`, `brief_text`, `token_counts`. The orchestrator passes this dict into prompt builders.

### Step 3 — MUSE (optional, pre-draft seeds)

If `config.muse_enabled`, dispatch a structured subagent for creative seeds:

```python
from write.prompts import (
    build_muse_seeds_system,
    build_muse_seeds_user,
    parse_seeds,
    wrap_for_subagent_structured,
)

seed_count = config.muse_seed_count
sys_p = build_muse_seeds_system(seed_count)
usr_p = build_muse_seeds_user(soul, context["brief_text"], context["fandom_context"], seed_count)
prompt = wrap_for_subagent_structured(
    system=sys_p,
    user=usr_p,
    output_kind=f"a numbered list of {seed_count} creative seeds, one per line, no preamble",
)
```

Dispatch with `Agent` tool, `subagent_type: "general-purpose"`, no worktree isolation:

```
Agent({
  description: "Muse seeds for {slug}",
  subagent_type: "general-purpose",
  prompt: <prompt>,
})
```

When the agent returns, parse: `seeds = parse_seeds(response_text, seed_count)`. Save to `write/runs/{run_id}/seeds.txt` for resumability.

Muse failure is non-fatal — if the agent returns junk, log it, set `seeds = []`, continue.

### Step 4 — DRAFT: one chapter or N chapters

For one-shot (`brief.format != "multi_chapter"`):

```python
from write.prompts import build_draft_system, build_draft_user, wrap_for_subagent

sys_p = build_draft_system(context, soul)
usr_p = build_draft_user(
    brief=brief,
    context=context,
    chapter_num=1,
    total_chapters=1,
    seeds=seeds,
    length_enforcement=config.length_enforcement,
)
prompt = wrap_for_subagent(sys_p, usr_p)
```

Dispatch a general-purpose subagent with this prompt. The agent returns prose. Write to `write/runs/{run_id}/ch1.md`.

For multi-chapter, loop chapters 1..N. For chapter `i > 1`, feed `previous_chapter_tail = open("ch{i-1}.md").read()[-2000:]`. Only pass `seeds` to chapter 1.

```python
chapters = []
for i in range(1, num_chapters + 1):
    prev_tail = chapters[-1][-2000:] if chapters else ""
    sys_p = build_draft_system(context, soul)
    usr_p = build_draft_user(
        brief=brief,
        context=context,
        chapter_num=i,
        total_chapters=num_chapters,
        previous_chapter_tail=prev_tail,
        seeds=seeds if i == 1 else None,
        length_enforcement=config.length_enforcement,
    )
    prompt = wrap_for_subagent(sys_p, usr_p)
    # Dispatch subagent here, capture response_text as chapter_text
    chapters.append(chapter_text)
    open(f"write/runs/{run_id}/ch{i}.md", "w").write(chapter_text)
```

Persist `state.draft_chapters = chapters` and `state.draft_word_count = sum(...)` via `write.state.save_state(state, ...)`.

#### Length retry (one-shot only)

If `config.length_enforcement == "retry"` and total word count is below `brief.target_length * (1 - tolerance)`:

```python
sys_p = build_draft_system(context, soul)
usr_p = build_draft_user(
    brief=brief, context=context, chapter_num=1, total_chapters=1,
    seeds=seeds, length_retry=True, previous_word_count=total_wc,
    length_enforcement="retry",
)
# Dispatch again; replace ch1.md
```

Only retry once. If still short, append a warning to `state.warnings` and proceed.

### Step 5 — EVALUATE: mechanical gate

```python
from write.evaluate_fanfic import evaluate_draft, evaluate_gate

full_text = "\n\n".join(chapters)
scores = evaluate_draft(draft_text=full_text, brief=brief, context=context)
state.evaluation_history.append(scores)
passed, reason = evaluate_gate(scores)
state.gate_result = reason
```

`evaluate_draft` is mechanical (slop_score, em-dash count, structural patterns). No subagent needed.

If `passed`: `state.final_scores = scores`, jump to PREPARE.

If `state.revision_count >= config.max_revision_cycles`: append a warning, set `final_scores`, jump to PREPARE anyway.

Otherwise: → REVISE.

#### Mid-revision muse (optional, after first eval)

If `config.muse_enabled` and this is the first eval (`len(state.evaluation_history) == 1`):

```python
from write.prompts import build_muse_depth_system, build_muse_depth_user

sys_p = build_muse_depth_system(config.muse_seed_count)
usr_p = build_muse_depth_user(soul, scores, full_text)
prompt = wrap_for_subagent_structured(
    system=sys_p, user=usr_p,
    output_kind=f"a numbered list of {config.muse_seed_count} soul notes, one per line",
)
# Dispatch; parse_seeds the response into state.mid_revision_notes
```

Muse failure non-fatal.

### Step 6 — REVISE: multi-pass or single

`state.revision_count += 1`.

**Multi-pass** (recommended, follows `revision._PASS_SUBSETS` selection by `config.revision_passes`):

```python
from write.revision import _PASS_SUBSETS, GATE_FAILURE_PASSES
from write.prompts import (
    build_revision_pass_system,
    build_revision_pass_user,
    wrap_for_subagent,
)

# Pick passes: gate failure type takes precedence, else use config count
passes = GATE_FAILURE_PASSES.get(state.gate_result) or _PASS_SUBSETS[config.revision_passes]

current = full_text
for pass_name in passes:
    sys_p = build_revision_pass_system(
        pass_name=pass_name,
        context=context,
        muse_notes=state.mid_revision_notes if pass_name == "depth" else None,
        soul=soul if pass_name == "cut" else "",
    )
    usr_p = build_revision_pass_user(current)
    prompt = wrap_for_subagent(sys_p, usr_p)
    # Dispatch; capture response as current
    state.revision_pass_log.append(... pass log ...)

state.draft_chapters = [current]
state.draft_word_count = len(current.split())
```

**Single-shot revision** (alternate, when a tightly-scoped brief is preferred):

```python
from write.revision import generate_revision_brief
from write.prompts import (
    build_simple_revision_system,
    build_simple_revision_user,
    wrap_for_subagent,
)

rev_brief = generate_revision_brief(
    scores=state.evaluation_history[-1],
    gate_result=state.gate_result,
    draft_text=full_text,
    fandom_context=context.get("fandom_context", ""),
)
sys_p = build_simple_revision_system()
usr_p = build_simple_revision_user(full_text, brief, context, rev_brief)
prompt = wrap_for_subagent(sys_p, usr_p)
# Dispatch; capture response as revised text
```

After revision, save the new draft to `write/runs/{run_id}/ch1.md` (or per-chapter), update state, return to **Step 5** (EVALUATE).

### Step 7 — PREPARE: AO3 post package

```python
from write.prepare import prepare_publish_request

publish_req = prepare_publish_request(state=state, identity=identity)
state.publish_request = publish_req.model_dump()
```

No subagent. Mechanical: title, summary, tags, formatting.

### Step 8 — QUEUE: surface for human posting

```python
import uuid
state.queue_id = f"q-{uuid.uuid4().hex[:8]}"
```

The human posts to AO3 manually (TOS — see CLAUDE.md). Record the queue ID for traceability.

### Step 9 — Close experiment bead + export draft.md

```python
from write.experiment import close_experiment
from write.loop import _write_draft_md

close_experiment(
    bead_id=state.experiment_bead_id,
    scores=state.final_scores,
    revision_count=state.revision_count,
    outcome="queued",
)
state.state = "DONE"
write.state.save_state(state, _get_state_path(state.run_id))
_write_draft_md(state)
```

Final artifact: `write/runs/{run_id}/draft.md` with YAML frontmatter (experiment bead, brief path, word count, slop score).

## Subagent dispatch checklist (every prose call)

1. Build `system` and `user` from `write.prompts` builders
2. Wrap: `prompt = wrap_for_subagent(system, user)` (or `wrap_for_subagent_structured(...)` for muse seeds / depth notes / evolution)
3. Dispatch:
   - `subagent_type: "general-purpose"` (no worktree — we don't need code-writing hooks for prose)
   - `description`: short string like `"Draft ch3 of {slug}"`
   - `prompt`: the wrapped string from step 2
4. Save the response verbatim to `write/runs/{run_id}/{filename}.md` BEFORE doing anything else with it. The persona-suppression frame should yield clean prose; if you see "I'll help you..." or any preamble, that's a tell — log it, surface to user, do NOT silently strip and pretend it's clean.

## Resumability

Every step writes `state.json` and the relevant prose file. To resume after interruption:

```python
from write.state import load_state
state = load_state(f"write/runs/{run_id}/state.json")
# Inspect state.state and state.draft_chapters to determine what's done
```

The orchestrator decides where to pick up by reading what files exist in the run dir and what `state.state` says.

## Calibration mode

For pre-publication calibration, run /write but stop after Step 6. Read the prose, note what works and what doesn't, feed observations into `/learn` manually. The goal is voice development, not publication.

## Anti-patterns

- ❌ **Calling the Anthropic API directly** — the migration retired this. All prose generation goes through subagents.
- ❌ **Using `subagent_type: "subagent"` with worktree isolation for prose** — that creates a 796MB worktree per chapter. Use `general-purpose` without isolation; we don't need linting hooks for fiction.
- ❌ **Skipping `wrap_for_subagent`** — the persona-suppression frame is the contract. Without it, "Here is the chapter..." preamble leaks into prose.
- ❌ **Stripping subagent preamble silently** — if a draft comes back with assistant-persona artifacts, surface it. Don't paper over a voice-leak by post-processing; that hides the regression.
- ❌ **Multiple length retries** — one retry per draft. If a second retry would still undershoot, accept the warning and let the human decide.
- ❌ **Auto-publishing** — humans post to AO3, always (TOS + quality gate).

## Output

- Draft text in `write/runs/{run_id}/` (per-chapter `.md` files plus final `draft.md` with frontmatter)
- Evaluation scores in `state.evaluation_history`
- Post package (`state.publish_request`) for human-driven AO3 posting
- Experiment bead closed with scores

## See also

- `write/prompts.py` — every prompt builder (read this before adjusting any prose-gen prompt content)
- `write/loop.py` — `setup_run`, `load_soul`, `_write_draft_md`
- `write/evaluate_fanfic.py` — mechanical evaluation gate
- `write/revision.py` — `generate_revision_brief`, `_PASS_SUBSETS`, `GATE_FAILURE_PASSES`
- `refs/api-vs-harness.md` — the why behind in-harness dispatch
- `/conceive` — produces the brief this skill consumes
- `/feedback` — runs after publication; surfaces signal for `/learn`
- `/learn` — updates identity from feedback digest
