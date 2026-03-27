---
name: learn
description: Process reader feedback into identity updates and close the experiment
argument-hint: "[bead-id]"
---

# /learn - Update Identity from Feedback

Process a feedback digest into concrete identity changes. This is where the agent
actually grows. Closes the experiment bead with results.

## Prerequisites
- Feedback digest exists (from `/feedback`)
- Experiment bead is open with metrics

## Process

1. **Load feedback digest and experiment history:**
   Read the digest. Read previous experiment results for comparison.

2. **Analyze what to change:**
   - Did readers quote specific passages? → Those go in the few-shot bank
   - Did readers praise the voice? → Reinforce those voice_priors values
   - Did readers flag OOC moments? → Update fandom_context.md character notes
   - Did engagement metrics differ from previous works? → What changed?
   - Did anyone mention pacing, tone, length? → Adjust voice_priors

3. **Update identity files:**
   - `identity/self.md` — update Strengths (confirmed by readers), Growth Areas
     (from constructive feedback), Reader Relationship (who's reading, what they want),
     add History entry
   - `identity/voice_priors.json` — adjust parameters within drift limits
   - `identity/inspirations.md` — add fandom influences if readers compared us to
     other authors
   - Few-shot bank — add quoted/praised passages

4. **Close experiment bead:**
   ```bash
   br close {bead-id}
   ```
   With final description:
   ```
   Result: [what happened]
   Learned: [what we now know]
   Changed: [what identity updates were made]
   Next: [what this suggests for the next experiment]
   ```

5. **Commit:**
   ```bash
   git add identity/ .beads/issues.jsonl
   git commit -m ":brain: learn: update identity from [work title] feedback

   Bead: {bead-id}
   Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
   ```

## Output
- Updated identity files
- Experiment bead closed with full results
- Committed and pushed
