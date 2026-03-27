# Spec: Soul and Muse

## 1. Overview

The creative engine that gives the agent artistic depth. Four interconnected systems
that transform Maren from a text generator into a writer with a perspective:

- **SOUL.md**: Thematic DNA -- the obsessions, questions, and tensions that make
  writing feel like it comes from someone with a point of view. Distinct from
  `identity/self.md` (which covers craft); SOUL.md covers *what the writer is drawn to*.
- **Muse**: A separate model call acting as creative subconscious -- generating oblique
  prompts, unexpected connections, and thematic angles at key points in the write loop.
- **Multi-pass revision**: Structured revision with different intent per pass (structure,
  depth, voice, cut), replacing the current single-purpose revision system.
- **Harness knobs**: Configurable parameters (`write/config.json`) for experimenting
  with temperature, model choice, revision depth, and quality gates.

**What this spec covers:**
- The SOUL.md schema and initial population
- Muse system architecture and firing points
- Multi-pass revision protocol
- Configuration surface and knob definitions
- Length undershoot analysis and mitigation

**What this spec does NOT cover:**
- The write loop state machine itself (see `specs/write-loop.md`)
- Identity and voice craft (see `identity/self.md`, `identity/voice_priors.json`)
- The `/learn` and `/feedback` skills (future specs)
- AO3 publishing pipeline (see `specs/api-proxy.md`)

**Dependencies:**
- `specs/write-loop.md` -- the state machine this spec extends
- `identity/self.md` -- craft-level voice definition (SOUL.md complements, not replaces)
- `identity/voice_priors.json` -- quantitative voice parameters
- `identity/inspirations.md` -- literary influences that inform SOUL.md values
- `write/loop.py` -- state machine orchestrator (modified to integrate muse calls)
- `write/revision.py` -- revision system (replaced with multi-pass)
- `write/api.py` -- Claude API call pattern (used by muse and revision passes)
- `write/evaluate_fanfic.py` -- evaluation gates (thresholds now configurable)

### 1.1 Sources and Provenance

| Source | Insight applied to this spec |
|---|---|
| `identity/self.md` | Voice craft, strengths, growth areas, calibration history |
| `identity/voice_priors.json` | Quantitative voice parameters (sentence length, dialogue ratio, etc.) |
| `identity/inspirations.md` | Literary influences: Vuong (embodied interiority), Ishiguro (unreliable restraint), Machado (sitting with discomfort), Tartt (atmosphere through specificity) |
| `write/runs/calibration-1-draft.md` | Astarion/Karlach campfire piece -- thematic concerns (freedom vs. expectation, body-as-record), emotional register (recognition without resolution), motifs (warmth/cold, cataloguing) |
| `write/runs/calibration-2-draft.md` | Shadowheart/Karlach delivery piece -- thematic concerns (identity after institutional control, usefulness vs. presence), motifs (reconstruction, prayer-shaped absence), emotional register (curiosity underneath grief) |
| `write/loop.py` | Current state machine: BRIEF->CONTEXT->DRAFT->EVALUATE->REVISE->PREPARE->QUEUE->DONE |
| `write/revision.py` | Current single-purpose revision: SLOP_FAIL / CHARACTERIZATION_FAIL / QUALITY_FAIL briefs |
| `write/evaluate_fanfic.py` | Current evaluation gates: slop_threshold=3.0, quality_threshold=7.0, characterization_threshold=6.0 |
| `write/api.py` | API call pattern: httpx POST to Anthropic Messages API, configurable model via env var |
| `specs/write-loop.md` | Full write loop spec: state machine, story brief schema, context budget, evaluation dimensions |
| `.claude/refs/methodology.md` | Creative loop methodology: conceive->write->evaluate->publish->feedback->learn |

## 2. Current State / Baseline

### What exists

**Write loop (`write/loop.py`):**
A state machine that takes a story brief through BRIEF -> CONTEXT -> DRAFT -> EVALUATE
-> REVISE -> PREPARE -> QUEUE -> DONE. Drafting uses a single Claude call with a system
prompt containing voice definition and anti-slop rules. The user prompt includes the
brief, fandom context, and a `TARGET LENGTH: X words` instruction.

**Single-pass revision (`write/revision.py`):**
When evaluation fails, the system generates a revision brief tailored to the failure type
(SLOP_FAIL, CHARACTERIZATION_FAIL, or QUALITY_FAIL) and makes one Claude call to revise
the entire draft. The revision model receives the draft + brief + context and returns a
complete revised text. Up to 3 evaluate-revise cycles are allowed.

**Evaluation (`write/evaluate_fanfic.py`):**
Mechanical slop detection (hard gate at 3.0) plus stub LLM scoring that returns hardcoded
7.0-7.5 scores across all dimensions. The evaluation checks slop first, then
characterization (threshold 6.0), then overall quality (threshold 7.0).

**Identity system:**
`self.md` defines craft-level voice. `voice_priors.json` holds quantitative parameters.
`inspirations.md` documents literary influences. No document captures thematic concerns
or what the writer is *drawn to* as opposed to *how the writer writes*.

**Configuration:**
The writer model is set via `AUTONOVEL_WRITER_MODEL` env var (default: claude-sonnet-4-6).
Temperature is hardcoded: 0.8 for drafting, 0.7 for revision. No configuration surface
for experimentation. Thresholds are module-level constants.

### What is missing

1. **No thematic grounding.** The writer has voice rules and anti-patterns but no
   document saying *what it cares about*. The calibration drafts reveal clear thematic
   concerns (freedom vs. expectation, the body as record, identity after institutional
   control), but these are not captured anywhere the system can use them.

2. **No creative ideation beyond the brief.** The drafting prompt includes the brief
   and fandom context but no creative provocation. The writer receives "write about X"
   and writes about X. There is no system that says "what if you thought about X through
   the lens of Y?" or "the silence between them might have the same texture as the
   silence inside each of them."

3. **No structured revision.** Revision is one-size-fits-all: the model gets the draft
   and a brief and returns a new draft. There is no separation of concerns -- a single
   pass is expected to fix structure, deepen interiority, clean voice, and cut excess
   simultaneously. This is how humans fail at revision too.

4. **No configuration for experimentation.** Temperature, model choice, revision depth,
   and quality thresholds are hardcoded. The methodology doc says every writing run is an
   experiment, but there is no way to vary the experimental conditions.

5. **Persistent length undershoot.** Both calibration drafts undershot significantly
   (calibration 1: 4094/5000 = 82%, calibration 2: 4639/6500 = 71%). The current prompt
   says `TARGET LENGTH: X words` which the model appears to treat as a ceiling.

## 3. Changes and Decisions

### 3.1 SOUL.md as thematic DNA

**Change:** Create `identity/soul.md` as a new identity document capturing the writer's
thematic obsessions, questions, motifs, emotional register, lens, tensions, and growth
edge. Load it during CONTEXT assembly and include it in the drafting prompt.

**Decision:** Thematic grounding belongs in a separate document from craft voice.

**Rationale:** `self.md` answers "how does this writer write?" SOUL.md answers "what
does this writer care about?" These are different questions. A writer can have the same
craft (close third, past tense, sensory specificity) across many thematic concerns, and
the same thematic concerns across different craft approaches. Separating them allows each
to evolve independently -- the learning loop might update SOUL.md when readers respond
strongly to a thematic vein, without touching the craft voice in `self.md`.

### 3.2 Muse as creative subconscious

**Change:** Add a muse system (`write/muse.py`) that makes separate model calls at three
points in the creative process: pre-draft (after context assembly), mid-revision (after
first evaluation), and post-feedback (during `/learn`).

**Decision:** Creative ideation should be a separate model call from the writer, at high
temperature, producing oblique rather than directive suggestions.

**Rationale:** The writer model at temperature 0.8 is optimized for coherent, voice-
consistent prose. Creative ideation benefits from higher temperature and a different
framing -- "be the subconscious" rather than "write the story." Keeping the muse
separate also means its suggestions are additive (appended to context, not replacing
anything) and optional (the writer can use or ignore them). The muse fires at points
where creative direction changes: before drafting (what angles to explore), after
evaluation (what's emotionally missing), and after feedback (what themes resonated).

### 3.3 Multi-pass revision

**Change:** Replace single-purpose revision with four specialized passes: structure,
depth, voice, and cut. Each pass is a separate Claude call with a system prompt focused
on that pass's intent.

**Decision:** Revision passes should be specialized rather than general-purpose.

**Rationale:** The current system asks one revision call to simultaneously fix structure,
deepen interiority, clean voice, and cut excess. Human writers do not revise this way --
they do structural editing first, then deepening, then line editing, then cutting. Each
pass has a different cognitive mode. A structure pass asks "does this piece have shape?"
while a voice pass asks "does every sentence sound like this writer?" Mixing these
concerns produces compromised revisions. Separate passes also allow configuration: a
piece that passed structure evaluation but failed voice can skip to pass 3.

### 3.4 Harness knobs

**Change:** Add `write/config.json` for default configuration and per-brief overrides
for all tunable parameters (temperature, model, revision passes, thresholds, muse
settings, length enforcement).

**Decision:** Every parameter that affects output quality should be configurable.

**Rationale:** The methodology doc says every writing run is an experiment. Experiments
require controlled variables. Hardcoded parameters make it impossible to test hypotheses
like "does Opus produce better characterization than Sonnet?" or "does muse temperature
1.2 produce more useful seeds than 0.8?" A configuration surface also makes the system
debuggable: when a draft fails, you can see exactly what parameters produced it.

### 3.5 Length enforcement

**Change:** Replace `TARGET LENGTH: X words` with `MINIMUM LENGTH: X words` in the
drafting prompt, and add a retry mode as fallback.

**Decision:** The prompt should frame length as a floor, not a ceiling.

**Rationale:** Both calibration drafts undershot (82% and 71%). Analysis suggests the
model treats "target" as "aim for around this, erring conservative." Reframing as
"minimum" should shift the distribution upward. The retry mode provides a mechanical
safety net: if the draft is below `(1 - tolerance) * target`, redraft with a stronger
length instruction. This is configurable so it can be disabled for pieces where natural
length is preferred.

## 4. Formal Specification

### 4.1 SOUL.md

The thematic DNA document. Lives at `identity/soul.md`. Loaded during CONTEXT assembly
alongside `self.md` and `voice_priors.json`. Included in the drafting system prompt
after the voice definition and before anti-slop rules.

#### Schema

```markdown
# Soul

## Obsessions
Themes the writer keeps returning to. Not craft preferences (that is self.md) but
the questions and conflicts that pull the writer toward certain stories.

- [theme]: [brief elaboration]

## Questions
Questions the writer explores but does not answer. The engine of curiosity that
drives story selection and thematic depth.

- [question]

## Motifs
Recurring physical and sensory elements that appear across pieces. The vocabulary
of the subconscious.

- [motif category]: [specific instances]

## Emotional Register
What feelings the writer gravitates toward. Not what the writer *can* write (that
is craft) but what the writer *reaches for*.

- [register description]

## Lens
How the writer sees characters. The default interpretive frame.

- [lens description]

## Tensions
The creative tensions the writer lives inside. Not problems to solve but productive
contradictions that generate energy in the work.

- [tension]: [elaboration]

## Growth Edge
What the soul is currently reaching toward. Evolves after feedback cycles. This is
the frontier -- the thing the writer is trying to learn to do.

- [current growth edge]
```

#### Initial Values (derived from calibration drafts)

```markdown
# Soul

## Obsessions
- The gap between expected freedom and actual freedom: both calibration drafts
  center characters who have been liberated from control (Cazador, Zariel, Shar)
  and find that freedom does not feel the way they imagined. "I expected to feel
  lighter" (cal-1). "I kept waiting for the other version to show up" (cal-1).
  "The reaching keeps happening" (cal-2).
- The body as a record of experience: characters think through their bodies.
  Astarion's hands braced for flight, Karlach's engine ticking, Shadowheart
  reaching for absent prayers. The body remembers what the mind wants to move past.
- Usefulness as identity: Karlach's "kill the thing, stop the other thing from
  killing someone -- very clear metric for useful" (cal-2). Shadowheart's "because
  I'm here and someone has to" (cal-2). Characters who defined themselves by
  function struggling with what they are when the function is removed.
- The shape of things after survival: not the trauma itself but what comes after.
  The camp that exists by inertia. The reconstruction that goes slowly. The
  hammering that never stops. What does life look like when the crisis is over
  and you have to just... live?

## Questions
- Can you be free if freedom does not feel like you expected?
- What do you owe to the version of yourself you imagined becoming?
- When your body carries a history your mind wants to leave, whose memory wins?
- Is the space left by a removed structure (faith, servitude, war) a wound or a
  beginning? Can it be both?
- What does it mean to be useful when the emergency is over?

## Motifs
- Warmth and cold: Astarion always cold, Karlach always warm. Warmth as proximity,
  as presence, as the thing you sit near. Cold as solitude, as the body's default.
  "Warm on the left side, cool on the right" (cal-1).
- Silence and sound: the quality of silence changes (pre-dawn vs. deep night). The
  engine ticking. Hammering in the distance. Silence as the medium in which
  characters hear themselves.
- Hands: Astarion's hands braced for flight, Karlach's hands turned over in ember-
  light, Shadowheart's pen, Drina's tired expression, Pell taking paper with both
  hands. Hands as indicators of internal state.
- Cataloguing and listing: Astarion's threat assessment habit. Karlach's Avernus
  list. Shadowheart's supply inventory. The impulse to organize experience as a
  way of controlling it.
- Slow transformation of light: the sky "doing something at the horizon." The
  candle lower on the desk. The scaffolding shadow. Light as time passing, as
  change arriving whether you are ready or not.

## Emotional Register
- Recognition without resolution: characters identify what they feel but do not
  fix it. "It hasn't clicked over." "The reaching keeps happening." The prose
  sits with the feeling rather than resolving it.
- Tenderness without sentimentality: warmth is offered (Karlach moving closer,
  bringing food, fixing shelving) without commentary. No one says "this meant a
  lot to me." The gesture speaks.
- Curiosity underneath grief: Shadowheart expecting grief and finding curiosity.
  The space that is "alarming in its own way." An emotional register that treats
  the aftermath of loss as genuinely interesting rather than merely sad.
- Humor as intimacy: the "structural integrity" joke, the eel-man story, "I'm
  occasionally insightful." Humor that exists between people who are becoming
  comfortable with each other, not humor performing for the reader.

## Lens
Through what their body remembers that their mind wants to forget. Characters are
seen through their physical habits -- the braced posture, the automatic prayer,
the cataloguing reflex, the engine tick. The prose trusts the body to tell the
truth the character has not yet articulated.

## Tensions
- Control vs. vulnerability: the writer wants precision (craft, structure, varied
  sentences) but the best moments come from letting characters be unguarded. The
  tension between the writer's control and the character's need to be seen without
  mediation.
- Precision vs. warmth: the prose is controlled ("literary accessible") but the
  emotional register is warm. Too much precision and it reads cold. Too much warmth
  and it reads sentimental. The writer lives in the gap.
- Interiority vs. forward motion: the writer gravitates toward deep interiority
  (character studies, internal processing) but both calibration drafts work best
  when there is external motion (the campfire, the delivery errand). The tension
  between sitting-with and moving-through.
- Showing vs. telling the reader what to feel: the anti-influence "and then he
  realized" pattern. The writer wants the reader to do the emotional work but must
  provide enough for the reader to do it with. How much is enough?

## Growth Edge
- Sustaining momentum in plotless pieces: `voice_priors.json` lists "sustaining
  momentum in plotless pieces" as a weakness. Calibration 2's errand structure
  helped. The soul is reaching toward pieces that have both deep interiority *and*
  forward motion without one sacrificing the other.
- Length control as creative choice: the persistent undershoot (82%, 71%) may
  indicate the writer is self-editing during generation, cutting before the reader
  can evaluate. The growth edge is learning to let a piece breathe to its natural
  length rather than compressing by reflex.
```

### 4.2 Muse System

A separate model call that acts as creative subconscious. Implemented in
`write/muse.py`. Three firing points in the creative pipeline.

#### Common interface

```python
# sketch
def call_muse(
    muse_input: str,
    system_prompt: str,
    temperature: float,
    model: str,
    seed_count: int = 4,
    max_tokens: int = 2000,
) -> list[str]:
    """Call the muse model and parse the response into individual seeds.

    Returns a list of creative seed strings. Each seed is a single
    provocative thought, question, or connection -- NOT a plot suggestion
    or craft note.
    """
```

The muse always returns a list of seed strings. Seeds are freeform text, typically
1-3 sentences each. The writer model receives seeds as additional context but is
not obligated to use them.

#### 4.2.1 Pre-draft muse

**Fires:** After CONTEXT assembly, before DRAFT. Integrated into `_step_draft()` in
`write/loop.py` (or as a new MUSE_PRE state if state machine granularity is preferred).

**Input:**
- SOUL.md (full text)
- Story brief (premise, characters, genre, tone)
- Fandom context (character sheets, canon references)

**Model:** Configurable via `muse_model` knob (default: "haiku")

**Temperature:** Configurable via `muse_temperature` knob (default: 1.0)

**System prompt:**
```
You are the creative subconscious of a fiction writer. Your job is to generate
oblique creative provocations -- unexpected connections, thematic angles, sensory
suggestions, emotional undercurrents. You are NOT plotting. You are NOT giving
craft advice. You are whispering the things the writer's subconscious notices
before the conscious mind catches up.

Generate exactly {seed_count} creative seeds. Each seed should be 1-3 sentences.
Each seed should offer a different angle. At least one seed should connect the
story's situation to the writer's thematic obsessions from SOUL.md. At least one
should be purely sensory.

Format: number each seed on its own line.
```

**User prompt:**
```
SOUL (the writer's thematic DNA):
{soul_md}

STORY BRIEF:
{brief_text}

FANDOM CONTEXT:
{fandom_context}

Generate {seed_count} creative seeds for this piece.
```

**Output:** 3-5 (configurable via `muse_seed_count`) creative seeds. Examples:
- "What if the silence between them has the same texture as the silence inside each
  of them?"
- "The engine doesn't just tick -- what else in the story has a rhythm that won't
  stop?"
- "There's a version of this scene where the warmth is threatening. What does that
  tell you about the character?"

**Integration:** Seeds are formatted as a `CREATIVE SEEDS (from the muse -- use or
ignore as inspiration):` block and appended to the drafting user prompt, after the
brief and fandom context, before the length instruction.

#### 4.2.2 Mid-revision muse

**Fires:** After the first EVALUATE pass (whether it passes or fails), before the
first revision or before PREPARE. Feeds into the revision brief or into a "deepening"
note for the PREPARE stage.

**Input:**
- The draft text
- SOUL.md
- Evaluation scores (per-dimension)

**Model:** Same as pre-draft muse (configurable)

**Temperature:** `muse_temperature * 0.9` (slightly lower -- grounded in existing text)

**System prompt:**
```
You are the creative subconscious reviewing a draft. You have read the writer's
thematic DNA (SOUL.md) and the evaluation scores. Your job is to identify what is
emotionally missing -- not craft problems (those are handled elsewhere) but soul
problems. Where is the piece skating on the surface of something it should sit
with? Where does the emotional logic break? What thematic thread is present but
not yet pulled taut?

Generate exactly {seed_count} soul notes. Each should be 1-3 sentences. These are
not revision instructions -- they are observations about the emotional and thematic
interior of the piece.
```

**User prompt:**
```
SOUL (the writer's thematic DNA):
{soul_md}

EVALUATION SCORES:
{formatted_scores}

DRAFT:
{draft_text}

What is emotionally missing?
```

**Output:** Examples:
- "The piece knows these characters are hurt but it hasn't decided whether that's a
  tragedy or a beginning. Pick one and lean in."
- "The ending resolves too neatly for what the rest of the piece is doing. The body
  of the text is ambivalent but the last paragraph is reassuring."
- "The freedom theme is stated but not embodied. Show us what freedom feels like in
  the body, not just what the character thinks about it."

**Integration:** Mid-revision muse output is included in the revision brief alongside
mechanical feedback. Formatted as a `SOUL NOTES (what's emotionally missing):` block.
If the draft passed evaluation and proceeds directly to PREPARE, mid-revision muse
output is stored in state for potential use in the learning loop.

#### 4.2.3 Post-feedback muse

**Fires:** During the `/learn` skill, after reader feedback has been collected and
digested.

**Input:**
- SOUL.md (current)
- Feedback digest (what readers said, what they quoted, what they praised)

**Model:** Same as other muse calls (configurable)

**Temperature:** `muse_temperature * 0.8` (most grounded -- working from real data)

**System prompt:**
```
You are the creative subconscious processing reader feedback. You have the writer's
current thematic DNA (SOUL.md) and a digest of reader responses. Your job is to
identify which thematic veins readers responded to most strongly and propose
specific updates to SOUL.md.

Propose updates as concrete edits: "Add to Obsessions: ...", "Strengthen in
Motifs: ...", "New Growth Edge: ...". Be specific. Reference reader quotes where
possible.
```

**User prompt:**
```
CURRENT SOUL.md:
{soul_md}

FEEDBACK DIGEST:
{feedback_digest}

What should evolve in the writer's thematic DNA?
```

**Output:** Proposed SOUL.md updates. These are NOT applied automatically -- they
are stored and presented to the human/orchestrator for approval.

**Integration:** Post-feedback muse output is returned as proposed edits. The
orchestrator reviews and applies changes to `identity/soul.md` as part of the
`/learn` cycle.

### 4.3 Multi-Pass Revision

Replaces the current single-purpose revision in `write/revision.py`. Each pass is a
separate Claude call with a system prompt focused on that pass's intent. The draft
evolves through all passes sequentially.

#### Pass definitions

##### Pass 1: Structure

**Intent:** Does the piece have shape? Is there movement? Does it earn its ending?

**System prompt:**
```
You are a structural editor. Read this piece for shape and movement. Your ONLY
concern is structure:

- Does the piece have forward motion, or does it stall?
- Does each scene/section earn its place?
- Is there a turn -- a moment where something shifts?
- Does the ending feel earned by what came before?
- Are there sections that repeat the same emotional beat without progression?

If the structure works, make minimal changes. If it doesn't, restructure. Preserve
voice and prose quality -- you are NOT line editing. Return the complete revised
text.
```

**Temperature:** `revision_temperature` (default 0.7)

##### Pass 2: Depth

**Intent:** Where could interiority go deeper? Feed mid-revision muse output here.

**System prompt:**
```
You are a depth editor. Read this piece for emotional and thematic depth. Your
ONLY concern is interiority and resonance:

- Where is the piece skating on the surface of something it should sit with?
- Where could a character's internal experience be more specific, more embodied?
- Where does the prose tell us what a character feels instead of showing us what
  they do with that feeling?
- Are the thematic concerns of the piece present in the texture (sensory details,
  physical gestures, rhythms) or only in the dialogue/internal monologue?

SOUL NOTES (what the muse noticed):
{muse_mid_revision_output}

Deepen where needed. Do NOT restructure. Do NOT line edit. Return the complete
revised text.
```

**Temperature:** `revision_temperature` (default 0.7)

##### Pass 3: Voice

**Intent:** Read every sentence for voice consistency.

**System prompt:**
```
You are a voice editor. Read this piece sentence by sentence for voice consistency.
Your ONLY concern is whether every line sounds like the same writer:

VOICE REFERENCE:
{identity_block}

ANTI-SLOP RULES:
{anti_slop_rules}

Check for:
- Sentences that shift register (suddenly more formal, more casual, more purple)
- Repetitive constructions (same sentence opener, same rhythm, same verb)
- Moments where craft overrides character (a beautiful sentence that doesn't sound
  like how this character would think)
- Slop patterns: banned words, AI tells, structural tics
- Em-dash density (max 8 per 1000 words)
- "He/She looked at" frequency (max 3 per chapter)

Fix voice breaks. Do NOT restructure. Do NOT change emotional content. Return the
complete revised text.
```

**Temperature:** `revision_temperature - 0.1` (tighter -- voice consistency
requires more determinism; clamped to 0.5 minimum)

##### Pass 4: Cut

**Intent:** What can be removed without losing anything?

**System prompt:**
```
You are a cutting editor. Your ONLY job is removal. Read the piece and identify
anything that can be cut without losing meaning, emotion, or thematic resonance.

SOUL.md (thematic DNA -- passages serving these themes earn their place):
{soul_md}

Cut rules:
- Remove redundant beats (if a gesture shows the emotion, cut the sentence that
  explains it)
- Remove filler transitions that don't do work
- Remove any sentence where the prose admires itself rather than serving the story
- DO NOT cut passages that serve SOUL.md themes, even if they are "slow" -- these
  are the point
- DO NOT cut for the sake of cutting -- only cut what genuinely adds nothing
- If nothing needs cutting, return the text unchanged

Return the complete text with cuts applied.
```

**Temperature:** `revision_temperature` (default 0.7)

#### Pass orchestration

```python
# sketch
def multi_pass_revision(
    draft_text: str,
    context: dict[str, Any],
    config: WriteConfig,
    muse_notes: list[str] | None = None,
    passes: list[str] | None = None,
) -> tuple[str, list[dict]]:
    """Run multi-pass revision on a draft.

    Args:
        draft_text: The current draft text.
        context: Assembled context (identity, fandom, anti-slop).
        config: Harness configuration.
        muse_notes: Mid-revision muse output (used in depth pass).
        passes: Which passes to run, in order. Default: all four
                ["structure", "depth", "voice", "cut"].

    Returns:
        (revised_text, pass_log) where pass_log is a list of dicts
        recording each pass's input word count, output word count,
        and a diff summary.
    """
```

The number of passes is configurable via `revision_passes` (default 4, range 1-4).
When fewer than 4 passes are configured, they are selected in order: 1 pass = structure,
2 passes = structure + voice, 3 passes = structure + depth + voice, 4 = all.

The `passes` argument can also override the selection explicitly, e.g.,
`passes=["voice", "cut"]` to skip structure and depth for a draft that only failed
voice evaluation.

Each pass receives the output of the previous pass as input. The pass log records
word counts before and after each pass for diagnostics.

#### Integration with the evaluate-revise loop

The existing evaluate -> revise loop is preserved but enhanced:

1. EVALUATE runs as before (slop gate, quality gate, characterization gate).
2. If evaluation fails, mid-revision muse fires (if enabled).
3. Multi-pass revision runs with passes appropriate to the failure:
   - SLOP_FAIL: voice pass only (focused on slop removal).
   - CHARACTERIZATION_FAIL: structure pass + depth pass (with fandom context
     emphasized in the depth pass system prompt).
   - QUALITY_FAIL: all four passes.
   - PASS (but muse notes suggest deepening): depth pass only (optional, if
     `muse_enabled` and first evaluation).
4. Re-evaluate.
5. Repeat up to `max_revision_cycles` times.

### 4.4 Harness Knobs

Configuration lives in `write/config.json` (defaults) with per-brief overrides via
`StoryBrief.config_overrides: dict[str, Any]`.

#### Config schema

```python
# sketch
@dataclass
class WriteConfig:
    # Drafting
    temperature: float = 0.8            # 0.5-1.0 -- drafting creativity
    writer_model: str = "sonnet"        # sonnet/opus -- writer model choice

    # Revision
    revision_temperature: float = 0.7   # 0.5-0.9 -- revision creativity
    revision_passes: int = 4            # 1-4 -- how many revision passes
    max_revision_cycles: int = 3        # 1-5 -- max evaluate-revise loops

    # Muse
    muse_enabled: bool = True           # whether muse fires at all
    muse_temperature: float = 1.0       # 0.7-1.2 -- muse wildness
    muse_model: str = "haiku"           # haiku/sonnet/opus -- muse model
    muse_seed_count: int = 4            # 1-7 -- creative seeds per call

    # Quality gates
    slop_threshold: float = 3.0         # 1.0-5.0 -- slop gate strictness
    quality_threshold: float = 7.0      # 5.0-9.0 -- quality gate strictness

    # Length
    target_length_tolerance: float = 0.15   # 0.05-0.30 -- acceptable deviation
    length_enforcement: str = "prompt"      # prompt/retry/none

def load_config(
    config_path: str = "write/config.json",
    overrides: dict[str, Any] | None = None,
) -> WriteConfig:
    """Load config from JSON, apply per-brief overrides, validate ranges.

    Raises ValueError for out-of-range values.
    """

def validate_config(config: WriteConfig) -> list[str]:
    """Validate all knobs are within their allowed ranges.

    Returns a list of validation error messages (empty if valid).
    """
```

#### Default config file

```json
{
  "temperature": 0.8,
  "writer_model": "sonnet",
  "revision_temperature": 0.7,
  "revision_passes": 4,
  "max_revision_cycles": 3,
  "muse_enabled": true,
  "muse_temperature": 1.0,
  "muse_model": "haiku",
  "muse_seed_count": 4,
  "slop_threshold": 3.0,
  "quality_threshold": 7.0,
  "target_length_tolerance": 0.15,
  "length_enforcement": "prompt"
}
```

#### Knob reference

| Knob | Default | Range | What it controls |
|------|---------|-------|-----------------|
| `temperature` | 0.8 | 0.5-1.0 | Drafting creativity. Lower = more predictable prose. Higher = more surprising but riskier. |
| `revision_temperature` | 0.7 | 0.5-0.9 | Revision creativity. Lower = more conservative edits. Higher = more willing to restructure. |
| `muse_temperature` | 1.0 | 0.7-1.2 | Muse wildness. Higher = more oblique, unexpected seeds. Lower = more grounded in brief. |
| `muse_model` | "haiku" | haiku/sonnet/opus | Muse model choice. Haiku is fast and cheap for experimentation. Opus for deeper creative connections. |
| `writer_model` | "sonnet" | sonnet/opus | Writer model choice. Sonnet for speed. Opus for quality (higher characterization accuracy expected). |
| `revision_passes` | 4 | 1-4 | How many revision passes to run. 1=structure only. 4=full pipeline. |
| `max_revision_cycles` | 3 | 1-5 | Max evaluate-revise loops before proceeding to PREPARE with warning. |
| `slop_threshold` | 3.0 | 1.0-5.0 | Slop gate strictness. Lower = stricter (fewer AI tells tolerated). |
| `quality_threshold` | 7.0 | 5.0-9.0 | Quality gate strictness. Lower = more permissive. Higher = more revision cycles. |
| `muse_enabled` | true | bool | Whether the muse system fires. Set to false for A/B testing muse impact. |
| `muse_seed_count` | 4 | 1-7 | How many creative seeds per muse call. More seeds = more options but more noise. |
| `target_length_tolerance` | 0.15 | 0.05-0.30 | Acceptable length deviation from target. 0.15 = 15% undershoot/overshoot allowed. |
| `length_enforcement` | "prompt" | prompt/retry/none | How to handle length undershoot. See 4.5. |

#### Per-brief overrides

The `StoryBrief` gains an optional `config_overrides` field:

```python
# sketch -- addition to StoryBrief
config_overrides: dict[str, Any] = field(default_factory=dict)
# e.g., {"temperature": 0.9, "muse_model": "opus", "revision_passes": 2}
```

Overrides are applied after loading `write/config.json` defaults. Validation runs
on the merged config. This allows per-experiment configuration: "run this brief at
temperature 0.9 with opus muse to test whether deeper creative seeds improve
characterization."

### 4.5 Length Undershoot Analysis

**Evidence:**
- Calibration 1: target 5000, actual 4094 (82%)
- Calibration 2: target 6500, actual 4639 (71%)

**Hypotheses:**
1. The model treats "TARGET LENGTH" as a ceiling, not a floor. The word "target"
   implies "aim for approximately" which the model interprets conservatively.
2. The anti-pattern rules ("70% in-scene", "vary paragraph length", "no section
   breaks as rhythm crutches") create caution -- the model self-edits during
   generation to comply with constraints, producing shorter output.
3. The model is self-editing for quality during generation. It recognizes that
   shorter, tighter prose is often better prose, and optimizes for quality over
   length.
4. Sonnet at temperature 0.8 may naturally produce shorter output than Opus.

**Proposed fix -- prompt language:**

Replace:
```
TARGET LENGTH: {target_length} words.
```

With:
```
MINIMUM LENGTH: {target_length} words. Write at least {target_length} words.
The piece should feel complete and unhurried at this length, not truncated or
compressed. Allow scenes to breathe. Do not self-edit for brevity during drafting
-- that is what revision is for.
```

**Proposed fix -- retry mode:**

When `length_enforcement` is "retry" and the draft word count is below
`target_length * (1 - target_length_tolerance)`:

1. Log the undershoot.
2. Redraft with a stronger length instruction:
   ```
   CRITICAL: Your previous draft was {actual} words. The MINIMUM is {target} words.
   You MUST write at least {target} words. Expand scenes, add interiority, let
   dialogue breathe. Do not compress.
   ```
3. If the redraft still undershoots, proceed to EVALUATE with a warning flag.
4. Maximum 1 retry (to avoid infinite loops).

**Length enforcement modes:**
- `"prompt"` (default): Include the strengthened minimum-length language in the
  prompt. No retry. Accept whatever length comes out.
- `"retry"`: Prompt language + automatic redraft if below tolerance.
- `"none"`: No length instruction in the prompt. Accept natural length. Useful for
  experimental runs testing what the model naturally produces.

## 5. Test Cases

```
TEST: TC-01 SOUL.md loading
INPUT: load_soul() when identity/soul.md exists with all sections
EXPECTED: Returns a string containing the full SOUL.md text. String is non-empty
  and contains all section headers: "Obsessions", "Questions", "Motifs",
  "Emotional Register", "Lens", "Tensions", "Growth Edge".
RATIONALE: SOUL.md must load correctly for integration into context assembly.

TEST: TC-02 SOUL.md missing graceful degradation
INPUT: load_soul() when identity/soul.md does not exist
EXPECTED: Returns an empty string and logs a warning. Does NOT raise an exception.
  The write loop continues without soul context.
RATIONALE: The system must function without SOUL.md (e.g., before initial population)
  rather than failing hard.

TEST: TC-03 Pre-draft muse generates seeds
INPUT: call_muse_pre_draft(soul_md=SOUL, brief=BRIEF, fandom_context=FANDOM)
  with muse_enabled=True, muse_seed_count=4
EXPECTED: Returns a list of exactly 4 strings. Each string is 1-3 sentences.
  No string contains plot directives ("the character should...", "in scene 2...").
  At least one string references a theme from SOUL.md.
RATIONALE: Muse seeds must be the right count, the right length, and oblique
  rather than directive.

TEST: TC-04 Pre-draft muse with muse disabled
INPUT: call_muse_pre_draft(...) with muse_enabled=False
EXPECTED: Returns an empty list. No API call is made.
RATIONALE: The muse must be fully disableable for A/B testing.

TEST: TC-05 Pre-draft muse seeds integrate into drafting prompt
INPUT: Drafting prompt assembly with muse_seeds=["seed1", "seed2"]
EXPECTED: The user prompt sent to the writer model contains a "CREATIVE SEEDS"
  block with both seeds. The block appears after the fandom context and before
  the length instruction.
RATIONALE: Seeds must be positioned where the writer model sees them as optional
  inspiration, not as primary instructions.

TEST: TC-06 Mid-revision muse generates soul notes
INPUT: call_muse_mid_revision(draft_text=DRAFT, soul_md=SOUL, scores=SCORES)
  with muse_enabled=True
EXPECTED: Returns a list of strings. Each string addresses emotional or thematic
  content, not craft mechanics. No string says "fix the pacing" or "add more
  dialogue" -- those are evaluation concerns.
RATIONALE: Mid-revision muse is specifically for soul-level notes, not craft.

TEST: TC-07 Post-feedback muse proposes SOUL.md updates
INPUT: call_muse_post_feedback(soul_md=SOUL, feedback_digest=DIGEST)
EXPECTED: Returns a list of proposed edits. Each edit references a specific SOUL.md
  section ("Add to Obsessions:", "Strengthen in Motifs:"). At least one edit
  references reader feedback ("readers responded to...").
RATIONALE: Post-feedback muse must produce actionable, specific SOUL.md edits
  grounded in real feedback data.

TEST: TC-08 Multi-pass revision runs all four passes
INPUT: multi_pass_revision(draft, context, config) with revision_passes=4
EXPECTED: Returns (revised_text, pass_log) where pass_log has 4 entries. Each
  entry records pass name, input word count, and output word count. The revised
  text is non-empty. Pass order is: structure, depth, voice, cut.
RATIONALE: Full pipeline must run all passes in the correct order.

TEST: TC-09 Multi-pass revision with reduced passes
INPUT: multi_pass_revision(draft, context, config) with revision_passes=2
EXPECTED: pass_log has 2 entries. Pass order is: structure, voice. Depth and cut
  passes are skipped.
RATIONALE: Reduced pass count must select the correct subset in order.

TEST: TC-10 Multi-pass revision with explicit pass selection
INPUT: multi_pass_revision(draft, context, config, passes=["voice", "cut"])
EXPECTED: pass_log has 2 entries: voice, then cut. Structure and depth passes
  are not run.
RATIONALE: Explicit pass selection must override the default ordering for cases
  where only specific passes are needed (e.g., SLOP_FAIL needing only voice pass).

TEST: TC-11 Harness config loading with defaults
INPUT: load_config("write/config.json") with no overrides
EXPECTED: Returns a WriteConfig with all defaults: temperature=0.8,
  writer_model="sonnet", revision_temperature=0.7, revision_passes=4,
  max_revision_cycles=3, muse_enabled=True, muse_temperature=1.0,
  muse_model="haiku", muse_seed_count=4, slop_threshold=3.0,
  quality_threshold=7.0, target_length_tolerance=0.15,
  length_enforcement="prompt".
RATIONALE: Default config must match documented defaults exactly.

TEST: TC-12 Harness config with per-brief overrides
INPUT: load_config("write/config.json", overrides={"temperature": 0.9,
  "muse_model": "opus"})
EXPECTED: Returns WriteConfig with temperature=0.9 and muse_model="opus".
  All other values remain at defaults.
RATIONALE: Per-brief overrides must merge cleanly with defaults.

TEST: TC-13 Harness config validation rejects out-of-range
INPUT: load_config(overrides={"temperature": 1.5})
EXPECTED: Raises ValueError with message indicating temperature must be 0.5-1.0.
RATIONALE: Out-of-range knobs must fail fast with clear error messages rather
  than producing unpredictable behavior.

TEST: TC-14 Harness config validation rejects invalid enum
INPUT: load_config(overrides={"length_enforcement": "aggressive"})
EXPECTED: Raises ValueError with message indicating valid values are
  prompt/retry/none.
RATIONALE: String enum knobs must validate against allowed values.

TEST: TC-15 Length enforcement "prompt" mode
INPUT: Draft prompt assembly with length_enforcement="prompt" and
  target_length=5000
EXPECTED: The drafting prompt contains "MINIMUM LENGTH: 5000 words. Write at
  least 5000 words." and does NOT contain "TARGET LENGTH".
RATIONALE: The prompt language must change from "target" to "minimum" to address
  the undershoot pattern.

TEST: TC-16 Length enforcement "retry" mode triggers redraft
INPUT: First draft returns 3500 words with target_length=5000 and
  target_length_tolerance=0.15 and length_enforcement="retry".
  Threshold is 5000 * (1 - 0.15) = 4250.
EXPECTED: A second draft call is made with the strengthened length instruction.
  The retry is logged in state. If the second draft also undershoots, it proceeds
  to EVALUATE with a warning flag.
RATIONALE: Retry mode must trigger when undershoot exceeds tolerance and must
  not loop indefinitely.

TEST: TC-17 Length enforcement "none" mode
INPUT: Draft prompt assembly with length_enforcement="none" and
  target_length=5000
EXPECTED: The drafting prompt contains NO length instruction. No retry is
  attempted regardless of output length.
RATIONALE: "None" mode must fully remove length constraints for natural-length
  experiments.

TEST: TC-18 SLOP_FAIL triggers voice pass only
INPUT: Evaluation returns SLOP_FAIL. Multi-pass revision is called.
EXPECTED: Only the voice pass runs (pass_log has 1 entry: "voice"). Structure,
  depth, and cut passes are skipped.
RATIONALE: Slop failures are voice-level issues that don't require structural
  or depth revision.

TEST: TC-19 End-to-end with muse enabled
INPUT: A complete write loop run with muse_enabled=True.
  Brief: one-shot, 5000 words, BG3 fandom, gen, hurt/comfort.
EXPECTED: The run proceeds through:
  1. CONTEXT -- loads SOUL.md
  2. Pre-draft muse fires -- seeds generated
  3. DRAFT -- seeds included in prompt
  4. EVALUATE -- scores generated
  5. Mid-revision muse fires -- soul notes generated
  6. REVISE (if needed) -- soul notes in revision brief
  7. PREPARE -> QUEUE -> DONE
  Muse calls are recorded in state (pre_draft_seeds, mid_revision_notes).
RATIONALE: End-to-end test verifying the full integration of muse with the
  existing write loop.

TEST: TC-20 Config missing file uses all defaults
INPUT: load_config("nonexistent/path.json") with no overrides
EXPECTED: Returns WriteConfig with all default values. Logs a warning about
  missing config file.
RATIONALE: Missing config file should not crash the system -- defaults are
  sufficient for operation.
```

## 6. Implementation Notes

### Module structure

```
identity/
  soul.md           -- SOUL.md document (new)
  self.md           -- existing voice craft
  voice_priors.json -- existing quantitative voice parameters
  inspirations.md   -- existing literary influences

write/
  config.json       -- default harness configuration (new)
  config.py         -- config loading and validation (new)
  muse.py           -- muse system: pre-draft, mid-revision, post-feedback (new)
  revision.py       -- enhanced with multi-pass support (modified)
  loop.py           -- state machine: muse integration points, config loading (modified)
  evaluate_fanfic.py -- thresholds from config instead of constants (modified)
  api.py            -- model resolution from config (modified)
```

### Model resolution

The `muse_model` and `writer_model` knobs use short names ("haiku", "sonnet", "opus")
that must be resolved to full model IDs. Suggested mapping:

```python
# sketch
MODEL_MAP = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}
```

This mapping should live in `write/config.py` and be updated as new model versions
are released. The `write/api.py` `call_claude` function should accept a `model`
parameter to override the default.

### State additions

`WriteLoopState` gains new fields:

```python
# sketch -- additions to WriteLoopState
pre_draft_seeds: list[str] = field(default_factory=list)
mid_revision_notes: list[str] = field(default_factory=list)
revision_pass_log: list[list[dict]] = field(default_factory=list)
config_snapshot: dict[str, Any] = field(default_factory=dict)
length_retry_count: int = 0
```

The `config_snapshot` records the exact configuration used for the run, enabling
retrospective analysis of what parameters produced which outputs.

### API call budget

Worst-case API calls per run with all features enabled:
- Pre-draft muse: 1 call (haiku -- fast and cheap)
- Draft: 1 call (sonnet)
- Evaluate: 1 call (mechanical + stub LLM)
- Mid-revision muse: 1 call (haiku)
- Revision (4 passes): 4 calls (sonnet)
- Re-evaluate: 1 call
- Total per cycle: 9 calls
- Max cycles: 3 (up to 5 with config)
- Worst case: 1 (muse) + 1 (draft) + 3 * (1 eval + 1 muse + 4 rev) = 20 calls

Cost control: the muse defaults to haiku (cheapest model) to keep the per-run cost
low while still providing creative provocation.

## 7. Open Questions

1. **Muse model diversity:** Should the muse use a different model *family* (not just
   a different model size) to maximize creative diversity? The spec assumes Claude
   models throughout, but a future consideration might be using a different provider
   for the muse to avoid same-model blind spots.

2. **SOUL.md versioning:** Should SOUL.md changes be tracked with version numbers and
   timestamps, the way `voice_priors.json` has a version field? This would enable
   correlating SOUL.md evolution with output quality over time.

3. **Pass ordering flexibility:** The current spec fixes pass order (structure, depth,
   voice, cut). Should pass ordering be configurable, or is the fixed order an
   intentional constraint based on editing best practices?

4. **Muse seed quality evaluation:** How do we measure whether muse seeds are actually
   improving output quality? The A/B test (muse_enabled true vs. false) is the primary
   experiment, but we may need a way to evaluate seed quality independently.

5. **Cut pass and length targets:** The cut pass may reduce word count below the
   minimum target. Should the cut pass be aware of the length target, or should it
   cut purely on quality and let the length enforcement system handle any undershoot?

## 8. Future Considerations

1. **SOUL.md as a living document:** After multiple feedback cycles, SOUL.md should
   reflect what readers actually respond to, not just what the initial calibration
   drafts suggested. The post-feedback muse proposes updates, but the rate and criteria
   for accepting updates need to be defined in the `/learn` spec.

2. **Muse conversation history:** Currently each muse call is independent. A future
   enhancement could maintain a muse "memory" across runs -- recurring creative themes,
   seeds that led to strong drafts, thematic veins that readers responded to. This
   would make the muse more like an ongoing creative conversation.

3. **Reader-facing SOUL transparency:** Some of the SOUL.md obsessions and questions
   could inform the author's notes on AO3, giving readers a window into the writer's
   thematic concerns. This builds the persona's authenticity. (This is a `specs/pen-
   name.md` concern, not implemented here.)

4. **Multi-draft muse:** Instead of seeds that modify a single drafting call, the
   muse could generate multiple draft "directions" and the system could draft 2-3
   versions of the same piece with different creative seeds, then evaluate all and
   select the strongest. This is expensive but could significantly improve quality
   for important pieces.

5. **Pass-specific evaluation:** Instead of a single evaluation after all revision
   passes, each pass could have its own lightweight evaluation to determine if it
   improved the text. This would allow early termination (skip remaining passes if
   the piece is already strong) and pass-specific quality tracking.

6. **Adaptive knob tuning:** After enough experiments, the harness could analyze
   which parameter configurations produce the highest-quality output for different
   types of briefs (fandom, length, genre) and suggest optimal configurations for
   new briefs. This is a learning loop concern.
