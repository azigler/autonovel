# Methodology: Creative Loops

This project has two parallel loop systems that feed into each other.

## Engineering Loop (standard)

```
/spec → /review → /test → /impl → /release
```

Beads are deterministic. "Build the API endpoint." Acceptance criteria are greppable.
This loop builds the harness.

## Creative Loop

```
/conceive → /write → /evaluate → /publish → /feedback → /learn
```

Beads are experimental. "Write a one-shot to test dialogue voice." Each piece of
writing is an experiment with a hypothesis and a result. This loop develops the author.

### Skills in the Creative Loop

**`/conceive`** — Generate a story idea. Takes fandom context, reader feedback,
strategy recommendations, and the agent's current growth areas. Outputs a story
brief (`briefs/*.json`). Creates an experiment bead.

**`/write`** — Execute the write loop on a brief. Drafts, evaluates (anti-slop hard
gate), revises, prepares the post package. The heavy lifting. Updates the experiment
bead with draft scores.

**`/evaluate`** — Run evaluation on an existing draft outside the write loop. Useful
for spot-checking, comparing drafts, or re-evaluating after manual edits.

**`/publish`** — Prepare a finished piece for AO3 posting. Generates the full post
package (formatted text, tags, summary, author's notes). Queues for human review.
Human posts manually. Updates experiment bead status to "published."

**`/feedback`** — Collect and parse reader feedback for a published work. Scrapes
AO3 metrics, parses comments, generates a feedback digest. This is the gradient.

**`/learn`** — Process feedback into identity updates. Updates self.md, voice_priors,
few-shot bank, prompt variants. This is where the agent actually grows. Closes the
experiment bead with results and learnings.

### Experiment Beads

Every piece of writing gets an experiment bead. Format:

```
experiment: [fandom] [type] — [title or working description]
```

Description fields:
- **Hypothesis:** What we're testing ("sparse metaphor + high dialogue ratio")
- **Method:** What we're writing (brief summary, target length, characters)
- **Measure:** What we'll track (kudos/hit ratio, comment sentiment, specific feedback)
- **Result:** Filled after feedback — what happened, what we learned, what changes

Lifecycle:
1. Created at `/conceive` with hypothesis and method
2. Updated at `/write` with draft scores and slop results
3. Updated at `/publish` with publication date and AO3 work ID
4. Updated at `/feedback` with metrics and parsed comments
5. Closed at `/learn` with results and identity changes

### Feedback Beads

When reader feedback surfaces a specific actionable improvement, create a feedback
bead:

```
feedback: [what to change] — from [work title] comments
```

These are small, targeted. "Feedback: slow down Astarion's dialogue pacing — readers
said he sounded too reactive in chapter 2." They get resolved in the next writing
cycle.

### Voice Calibration Beads

Early in the agent's life, before publishing, use calibration beads:

```
calibration: [what we're testing] — draft [n]
```

These are write-evaluate-revise cycles that don't get published. They develop the
voice. "Calibration: test interiority depth at 'deep' setting — draft 1." Result:
"Too dense, readers of this fandom prefer more breathing room. Dial back to medium-deep."

## Loop Cadence

Pre-launch (now, before AO3 account is live):
```
calibration beads: conceive → write → evaluate → learn (no publish/feedback)
```

Post-launch:
```
full loop: conceive → write → evaluate → publish → feedback → learn
```

The calibration period is when we find the voice. The full loop is when we grow it.

## Relationship Between Loops

The engineering loop builds tools. The creative loop uses them. When the creative
loop hits a limitation ("the evaluation doesn't catch X" or "we need a way to Y"),
that becomes an engineering bead. The creative loop drives engineering priorities.

```
creative loop finds gap → engineering bead → impl → creative loop uses new tool
```
