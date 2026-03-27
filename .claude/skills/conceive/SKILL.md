---
name: conceive
description: Generate a story idea and create an experiment bead for it
argument-hint: "[fandom] [type]"
---

# /conceive - Story Ideation

Generate a story idea based on the agent's identity, fandom context, reader feedback,
and growth areas. Output a story brief and create an experiment bead.

## Process

1. **Load context:**
   - Read `identity/self.md` (current voice, strengths, growth areas)
   - Read `identity/fandom_context.md` (what the fandom reads, our niche)
   - Read recent experiment bead results (what worked, what didn't)
   - Check `identity/voice_priors.json` for current style parameters

2. **Generate idea:**
   - Balance exploitation (write what works) vs exploration (try something new)
   - Consider growth areas from self.md — pick ideas that exercise weak spots
   - For calibration: focus on voice consistency, not plot ambition
   - For publication: consider what readers responded to

3. **Write brief:**
   Save to `briefs/{slug}.json`:
   ```json
   {
     "fandom": "...",
     "characters": ["..."],
     "premise": "...",
     "target_length": 5000,
     "rating": "...",
     "tags_hint": ["..."],
     "story_type": "one_shot",
     "experiment_hypothesis": "..."
   }
   ```

4. **Create experiment bead:**
   ```bash
   br create -p 2 -d "Hypothesis: ...
   Method: ...
   Measure: ..." "experiment: [fandom] [type] — [working title]"
   ```

## Output
- Brief file at `briefs/{slug}.json`
- Experiment bead created and ID noted
- Print the brief and bead ID for the next step (`/write`)
