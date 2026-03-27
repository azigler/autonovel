---
name: write
description: Execute the write loop to draft, evaluate, and revise a story from a brief
argument-hint: "[brief-path] [bead-id]"
---

# /write - Draft a Story

Execute the write loop state machine on a story brief. Drafts, evaluates (anti-slop
hard gate), revises if needed, and prepares the post package.

## Prerequisites
- A story brief exists (from `/conceive` or manual creation)
- An experiment bead exists for this story
- `.env` has `ANTHROPIC_API_KEY` set

## Process

1. **Load brief and validate:**
   ```bash
   cat briefs/{slug}.json
   ```

2. **Run the write loop:**
   ```bash
   uv run python -c "
   from write.loop import run
   from write.brief import StoryBrief
   import json
   brief_data = json.loads(open('briefs/{slug}.json').read())
   brief = StoryBrief(**brief_data)
   result = run(brief)
   print(result)
   "
   ```

3. **Monitor state transitions:**
   - BRIEF → CONTEXT → DRAFT → EVALUATE → (REVISE loop) → PREPARE → QUEUE → DONE
   - State is saved to `write/runs/{run_id}/state.json` after every transition
   - If interrupted, resume with `resume(run_id)`

4. **Review output:**
   - Check `write/runs/{run_id}/` for draft text, evaluation scores, post package
   - Read the draft. Does it sound human? Does the voice hold?
   - Check slop scores — did the anti-slop gate catch anything?

5. **Update experiment bead:**
   ```bash
   br update {bead-id} -d "Draft complete. Slop score: X. Quality: Y.
   Voice notes: [observations about the draft]"
   ```

## Calibration Mode

For pre-publication calibration, run `/write` but don't proceed to `/publish`.
Instead, read the output, note what works and what doesn't, and feed that into
`/learn` manually. The goal is voice development, not publication.

## Output
- Draft text in `write/runs/{run_id}/`
- Evaluation scores
- Post package (if PREPARE/QUEUE stages complete)
- Experiment bead updated with scores
