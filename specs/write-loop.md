# Spec: Write Loop

## 1. Overview

The write loop is the core orchestrator that transforms a story idea into a
publication-ready fanfic package. It is the "lever" of the system -- the component
that actually produces writing. Everything else (identity, feedback, learning,
strategy) either feeds into or reads from the write loop's output.

**What it does:**
- Accepts a story brief (fandom, characters, premise, constraints)
- Assembles context from the identity system, fandom knowledge, and few-shot bank
- Drafts one or more chapters using the adapted autonovel drafting pipeline
- Evaluates the draft through mechanical slop detection and LLM-based judgment
- Revises until quality thresholds are met (or max cycles exhausted)
- Prepares the final work for AO3 posting (formatting, tags, summary, author's notes)
- Queues the package for human review via the API proxy
- Tracks the experiment (hypothesis, results, scores)

**What it does NOT do:**
- Decide what to write next (that is `strategy/`)
- Collect reader feedback after publication (that is `feedback/`)
- Update identity or voice priors (that is `learning/`)
- Post to AO3 (that is the human)

**Dependencies:**
- `identity/schema.py` -- loads identity context (`load_identity()`)
- `evaluate.py` -- mechanical slop scoring (`slop_score()`) and LLM evaluation
- `draft_chapter.py` -- chapter drafting (adapted for fanfic)
- `gen_brief.py` / `gen_revision.py` -- revision pipeline (adapted)
- `api/server.py` -- publish queue (`POST /works`)
- `api/models.py` -- `PublishRequest`, `QueueItem`, `Rating`
- `ANTI-SLOP.md`, `ANTI-PATTERNS.md` -- slop/pattern databases (loaded at context assembly)

### 1.1 Sources and Provenance

| Source | Insight applied to this spec |
|---|---|
| `.claude/refs/PLAN.md` | Core loop design, architecture, milestone structure, anti-AI-detection priority |
| `CLAUDE.md` | Anti-AI detection as #1 constraint, human-in-the-loop publishing, one-way door caution |
| `identity/schema.py` | `VoicePriors`, `load_identity()`, identity context structure |
| `api/models.py` | `PublishRequest`, `QueueItem`, `Rating` schemas for the publish queue |
| `api/server.py` | `POST /works` endpoint (queues for human review), queue management endpoints |
| `evaluate.py` | `slop_score()` interface, `call_judge()` interface, chapter evaluation prompt structure |
| `draft_chapter.py` | Drafting interface, context assembly pattern, writer model configuration |
| `gen_brief.py` | Revision brief generation from evaluation feedback |
| `gen_revision.py` | Revision chapter generation from brief + existing draft |
| `ANTI-SLOP.md` | Banned word tiers, structural slop patterns, AI detection signals |
| `ANTI-PATTERNS.md` | Structural anti-patterns: over-explain, triadic listing, negative assertion, etc. |

## 2. Current State / Baseline

The autonovel pipeline was built for a single long-form fantasy novel. Its tools
operate on a fixed directory structure (`chapters/`, `voice.md`, `world.md`, etc.)
and assume a specific novel context.

**Existing tools we reuse:**

- **`evaluate.py`**: Two evaluation modes relevant to the write loop:
  - `slop_score(text)` -- mechanical, no LLM, returns a dict with `slop_penalty` (0-10),
    tier1/tier2/tier3 hits, fiction AI tells, structural tics, telling violations.
  - `evaluate_chapter(chapter_num)` -- LLM-based evaluation that scores voice adherence,
    beat coverage, character voice, prose quality, engagement, etc. Returns a dict with
    `overall_score` (0-10, already adjusted by slop penalty).
  - The judge model is intentionally different from the writer model (Opus vs Sonnet)
    to avoid self-congratulation.

- **`draft_chapter.py`**: Calls the writer model with a structured prompt containing
  voice definition, chapter outline, previous chapter tail, world bible, character
  registry, and anti-pattern rules. Currently hardcoded to a specific novel. Temperature
  0.8, max_tokens 16000.

- **`gen_brief.py`**: Generates revision briefs from panel feedback, eval callouts, or
  adversarial cuts. Outputs structured briefs with PROBLEM / WHAT TO KEEP / WHAT TO
  CHANGE / VOICE RULES / TARGET sections. Currently reads from `eval_logs/` and
  `edit_logs/` directories specific to the novel pipeline.

- **`gen_revision.py`**: Takes a chapter number and brief file, calls the writer model
  with the existing draft + brief + context to produce a revised chapter. Anti-pattern
  rules are hardcoded in the prompt.

**What needs adaptation:**
- All tools are hardcoded to a specific novel's directory layout and context files
- `draft_chapter.py` assumes `voice.md`, `world.md`, `characters.md`, `outline.md` exist
  at the project root
- `evaluate.py` chapter evaluation uses a prompt tuned for fantasy novels with specific
  scoring dimensions (lore_integration, canon_compliance, etc.)
- None of the tools know about the identity system, fandom context, or AO3 formatting
- No state machine or resumability -- each tool is a standalone CLI script

## 3. Changes and Decisions

### 3.1 State machine architecture

**Change:** The write loop is a state machine with explicit states, transitions, and
persisted state, rather than a linear script.

**Decision:** Resumability and human checkpoints require explicit state management.

**Rationale:** The write loop may be interrupted at any point -- API failures, human
review pauses, rate limits. It may also need human approval before proceeding (the QUEUE
state). A state machine makes each transition explicit, each state inspectable, and
resumption trivial: load `state.json`, check current state, re-enter at the correct
transition. This also enables future features like parallel drafting of chapters and
mid-loop human intervention.

### 3.2 Anti-slop as a hard gate

**Change:** Mechanical slop detection (via `slop_score()`) is a hard gate. If
`slop_penalty >= 3.0`, the draft MUST be revised regardless of LLM evaluation score.
This is separate from and in addition to the LLM evaluation soft gate.

**Decision:** Anti-AI detection is the project's #1 priority (per CLAUDE.md).

**Rationale:** LLM judges are unreliable at detecting their own patterns. The mechanical
slop detector catches lexical and structural tells that an LLM evaluator might overlook
or actively generate. A human reader noticing AI patterns is a project-ending event.
The mechanical check is deterministic, fast, and catches the highest-signal tells. Making
it a hard gate means no amount of "but the prose is beautiful" from the LLM judge can
override a concrete slop detection. The threshold of 3.0 (out of 10) is deliberately
strict -- it allows minor hits (a single tier-2 word, moderate em dash usage) but blocks
anything that clusters.

### 3.3 Automatic experiment bead creation

**Change:** The write loop automatically creates an experiment bead at the BRIEF state
and updates it with results at DONE.

**Decision:** Every writing run is an experiment that should be tracked.

**Rationale:** The learning engine needs structured data about what was tried, what was
hypothesized, and what actually happened. Manual experiment tracking is forgotten or
inconsistent. By making it automatic, every run generates a data point. The hypothesis
field in the story brief (optional but encouraged) makes it explicit what the agent is
testing: "Does second-person POV increase engagement in this fandom?" / "Does a slower
opening retain readers?" The DONE state records scores, revision count, and a summary
of what was learned.

### 3.4 Fanfic-adapted evaluation

**Change:** The LLM evaluation prompt is adapted from `evaluate.py`'s chapter evaluation
to fanfic-specific dimensions, replacing novel-specific dimensions (lore_integration,
canon_compliance with the novel's world bible) with fanfic-relevant ones
(characterization_accuracy, fandom_voice_fit).

**Decision:** Fanfic readers have different quality signals than novel readers.

**Rationale:** A fanfic reader cares deeply about whether characters sound and behave
like their canon selves. "Lore integration" in the autonovel sense (does the world do
work in this chapter?) matters less than "does this feel like it belongs in this fandom?"
The evaluation must also check for fandom-specific conventions (tag accuracy, rating
appropriateness, content warning completeness).

### 3.5 Context window budget

**Change:** The write loop explicitly manages a token budget for context assembly,
allocating fixed percentages to identity, fandom, few-shot examples, and draft space.

**Decision:** Context window is finite and must be managed deliberately.

**Rationale:** The writer model has a large context window (up to 1M tokens with the
beta header), but cramming everything in produces worse output than curated context.
The budget forces selection: which few-shot examples are most relevant? Which parts of
the fandom context matter for this specific story? This also prevents the "context
pollution" problem where irrelevant context degrades generation quality.

## 4. Formal Specification

### 4.1 State Machine

```
BRIEF --> CONTEXT --> DRAFT --> EVALUATE --> PREPARE --> QUEUE --> DONE
                                   |   ^
                                   v   |
                                 REVISE
```

#### States and Transitions

##### BRIEF

**Entry conditions:** A story brief is provided (either programmatically from the
strategy planner or manually).

**Actions:**
1. Validate the story brief against the required schema (see 4.2).
2. Assign a unique `run_id` (UUID4).
3. Create an experiment bead via `br create -p 3 "experiment: {brief.title}"`.
4. Record the experiment hypothesis (from `brief.experiment_hypothesis` or
   auto-generated: "Standard {genre} {fandom} one-shot").
5. Initialize `state.json` with `state: "BRIEF"`, the brief, and the run_id.
6. Persist state.

**Exit conditions:** Brief passes validation. State file written.

**Failure transitions:**
- Invalid brief (missing required fields) -> ERROR state with validation details.

**Next state:** CONTEXT

##### CONTEXT

**Entry conditions:** Valid brief exists in state. Identity files are loadable.

**Actions:**
1. Load identity context via `load_identity()` from `identity/schema.py`.
   Returns: `self` (markdown), `pen_name` (markdown), `inspirations` (markdown),
   `fandom_context` (markdown), `voice_priors` (VoicePriors dataclass).
2. Load fandom-specific context: character sheets, canon references, fandom conventions.
   Source: `identity/fandom_context.md` and any fandom-specific files referenced therein.
3. Load few-shot bank: select examples relevant to this brief's fandom, genre, and tone.
   Selection criteria: fandom match > genre match > tone match > recency.
   Maximum examples: 3 (to preserve draft space).
4. Assemble the context package with token budget allocation (see 4.3).
5. Load anti-slop and anti-pattern databases from `ANTI-SLOP.md` and `ANTI-PATTERNS.md`.
   Extract the banned word lists, structural patterns, and fiction AI tells into a
   compact rules block for the writer prompt.
6. Persist assembled context to state.

**Exit conditions:** Context package assembled within token budget.

**Failure transitions:**
- Identity files missing or corrupted -> ERROR with details of what is missing.
- Fandom context not found for the specified fandom -> WARNING (proceed with generic
  context, but flag for human review at QUEUE).

**Next state:** DRAFT

##### DRAFT

**Entry conditions:** Context package assembled in state.

**Actions:**
1. Determine draft strategy:
   - One-shot (brief.target_length <= 15000 words): single draft call.
   - Multi-chapter (brief.target_length > 15000 words): sequential chapter drafting
     with continuity (see 4.4).
2. For each chapter/segment:
   a. Build the writer prompt from context package + chapter-specific instructions.
   b. Call the writer model (adapted `draft_chapter.py` interface).
   c. Record the raw draft text and word count.
3. Persist draft(s) to state.

**Exit conditions:** All chapters/segments drafted. Total word count within 20% of
target_length.

**Failure transitions:**
- API error (rate limit, timeout) -> Persist partial state, transition to ERROR with
  retry metadata (which chapter failed, attempt count).
- Draft wildly off target length (>50% deviation) -> Persist draft, proceed to EVALUATE
  (let evaluation catch the issue).

**Next state:** EVALUATE

##### EVALUATE

**Entry conditions:** Draft text exists in state.

**Actions:**
1. Run mechanical slop detection: `slop_score(draft_text)` for each chapter/segment.
2. Check hard gate: if any chapter has `slop_penalty >= 3.0`, flag as SLOP_FAIL.
3. Run LLM evaluation (adapted from `evaluate.py` chapter evaluation, see 4.5):
   - Fanfic-specific dimensions: voice_adherence, characterization_accuracy,
     fandom_voice_fit, prose_quality, engagement, pacing, emotional_arc.
   - Returns per-dimension scores and an overall_score (0-10).
4. Check soft gate: overall_score >= 7.0 is the target threshold.
5. Check characterization accuracy specifically: characterization_accuracy >= 6.0
   is required (characters must be recognizably in-character).
6. Record all scores and gate results in state.

**Exit conditions:**
- All gates pass -> transition to PREPARE.
- Any gate fails AND revision_count < max_revisions (3) -> transition to REVISE.
- Any gate fails AND revision_count >= max_revisions -> transition to PREPARE with
  a `max_revisions_reached: true` warning flag. The work still proceeds to human
  review but is flagged.

**Failure transitions:**
- API error during LLM evaluation -> Persist partial results, transition to ERROR
  with retry metadata.

**Next state:** PREPARE (if pass or max revisions) or REVISE (if fail and retries remain)

##### REVISE

**Entry conditions:** Evaluation failed at least one gate. revision_count < 3.

**Actions:**
1. Increment `revision_count` in state.
2. Generate a revision brief from evaluation results:
   - If SLOP_FAIL: brief focuses on specific slop hits (tier1 words to replace,
     fiction AI tells to rewrite, structural tics to restructure).
   - If LLM score too low: brief focuses on weakest dimensions from evaluation
     (adapted from `gen_brief.py` eval-brief generation).
   - If characterization_accuracy too low: brief includes specific character notes
     from fandom context, with quotes of canonical behavior.
3. Call the revision model (adapted `gen_revision.py` interface) with:
   - The existing draft
   - The revision brief
   - The full context package (identity, fandom, voice rules)
   - Anti-pattern rules
4. Record the revised draft.

**Exit conditions:** Revised draft produced.

**Failure transitions:**
- API error -> ERROR with retry metadata.

**Next state:** EVALUATE (re-evaluate the revised draft)

##### PREPARE

**Entry conditions:** Draft exists in state that either passed evaluation or exhausted
max revisions.

**Actions:**
1. Format the work for AO3:
   - Convert markdown to AO3-compatible HTML (AO3 uses a subset of HTML).
   - Handle chapter breaks for multi-chapter works.
   - Ensure proper paragraph spacing and dialogue formatting.
2. Generate tags:
   - Required tags: fandom, rating, archive warnings, relationship tags, character tags.
   - Additional tags: genre, tropes, content descriptors.
   - Source: `brief.tags_hint` + fandom conventions from `fandom_context.md`.
   - Tags must follow AO3 conventions (canonical tag names, wrangled format).
3. Generate summary:
   - 1-3 sentences that hook without spoiling.
   - Written in the pen name's voice (from `identity/pen_name.md`).
   - Must not sound AI-generated (run slop_score on the summary itself).
4. Generate author's notes:
   - Use the pen name's author-notes voice from `identity/pen_name.md`.
   - Content: brief context for the fic, any relevant content notes, optional
     personal touches (consistent with persona).
   - Must not sound AI-generated (run slop_score on the notes).
5. Assemble the `PublishRequest` object (from `api/models.py`):
   ```python
   # sketch
   PublishRequest(
       title=brief.title or generated_title,
       fandom=brief.fandom,
       rating=brief.rating,
       tags=generated_tags,
       summary=generated_summary,
       body=formatted_body,
       author_notes=generated_notes,
   )
   ```
6. If `max_revisions_reached` flag is set, add a warning to the package metadata
   (not to the AO3 content) for human review.
7. Persist the prepared package to state.

**Exit conditions:** `PublishRequest` fully populated. Summary and author's notes
pass slop check (slop_penalty < 2.0).

**Failure transitions:**
- Summary or author's notes fail slop check -> regenerate (up to 3 attempts),
  then proceed with WARNING flag.

**Next state:** QUEUE

##### QUEUE

**Entry conditions:** Prepared `PublishRequest` exists in state.

**Actions:**
1. POST the `PublishRequest` to the API proxy: `POST /works`.
2. Receive a `QueueItem` with `queue_id` and `status: "pending"`.
3. Record `queue_id` in state.
4. Log the complete package to `write/logs/{run_id}.json` for audit trail.

**Exit conditions:** `queue_id` received from API. State persisted.

**Pause behavior:** The loop pauses here. The human reviews the queued work via
`GET /queue/{queue_id}`, optionally edits it, and either:
- Posts it to AO3, then calls `PATCH /queue/{queue_id}` with the `ao3_work_id`.
- Rejects it via `DELETE /queue/{queue_id}`.

The write loop polls or is notified when the queue item status changes.

**Failure transitions:**
- API proxy unavailable -> ERROR with retry metadata.
- Human rejects the work -> transition to DONE with `outcome: "rejected"`.

**Next state:** DONE (after human action)

##### DONE

**Entry conditions:** Queue item resolved (published or rejected).

**Actions:**
1. Record final outcome in state: published (with ao3_work_id) or rejected.
2. Update the experiment bead with results:
   - Final evaluation scores (slop_penalty, overall_score per dimension).
   - Number of revision cycles used.
   - Outcome (published / rejected).
   - What was learned (auto-generated summary from scores + hypothesis).
3. Close the experiment bead.
4. Persist final state.

**Exit conditions:** Experiment bead updated. State file marked as complete.

**No further transitions.**

##### ERROR

**Entry conditions:** An unrecoverable error occurred in any state.

**Actions:**
1. Record the error details, stack trace, and the state at time of failure.
2. Persist state with `state: "ERROR"` and the previous state as `error_from`.

**Resume behavior:** The loop can be restarted. It reads state.json, sees ERROR,
and retries the `error_from` state. API errors have an `attempt_count` that
increments; after 3 failed attempts at the same state, the loop halts and requires
human intervention.

### 4.2 Story Brief Schema

The story brief is the input to the write loop. All fields are validated at the
BRIEF state before proceeding.

```python
# sketch
@dataclass
class StoryBrief:
    # Required
    fandom: str                    # e.g., "Harry Potter - J. K. Rowling"
    characters: list[str]          # e.g., ["Draco Malfoy", "Harry Potter"]
    premise: str                   # 1-5 sentences describing the story idea
    target_length: int             # target word count (3000-80000)
    rating: Rating                 # from api.models: General, Teen, Mature, Explicit

    # Required with defaults
    format: Literal["one_shot", "multi_chapter"] = "one_shot"
    genre: str = "general"         # e.g., "angst", "fluff", "hurt/comfort"
    tone: str = "neutral"          # e.g., "dark", "humorous", "bittersweet"

    # Optional
    title: str | None = None       # if None, generated during PREPARE
    ship: str | None = None        # e.g., "Draco Malfoy/Harry Potter"
    tags_hint: list[str] = field(default_factory=list)  # suggested tags
    experiment_hypothesis: str | None = None  # what we're testing
    chapter_count: int | None = None  # for multi_chapter; if None, derived from target_length
    additional_context: str = ""   # freeform notes for the writer
```

**Validation rules:**
- `fandom` must be non-empty.
- `characters` must contain at least one character.
- `premise` must be non-empty and between 10 and 2000 characters.
- `target_length` must be between 1000 and 80000.
- `rating` must be a valid `Rating` enum value.
- If `format == "multi_chapter"` and `chapter_count` is None, derive as
  `target_length // 4000` (aiming for ~4000 words per chapter), clamped to [2, 20].

### 4.3 Context Assembly and Token Budget

Context assembly happens at the CONTEXT state. The assembled context is used by both
DRAFT and REVISE states.

**Token budget allocation** (for a 200K effective context window; the writer model
supports up to 1M with beta header, but quality degrades beyond ~200K):

| Slot | Budget | Contents |
|---|---|---|
| Identity | 15% (30K tokens) | `self.md`, `pen_name.md`, `inspirations.md`, `voice_priors` (serialized) |
| Fandom context | 20% (40K tokens) | `fandom_context.md`, character sheets for relevant characters, canon references |
| Anti-slop rules | 5% (10K tokens) | Compact extraction from `ANTI-SLOP.md` and `ANTI-PATTERNS.md`: banned words, pattern rules, fiction AI tells |
| Few-shot examples | 15% (30K tokens) | Up to 3 curated passages from the few-shot bank, tagged with what makes them good |
| Brief + outline | 5% (10K tokens) | The story brief, chapter outline (if multi-chapter), and any additional context |
| Draft space | 40% (80K tokens) | Reserved for the model's output. For one-shots up to ~15K words; for multi-chapter, per-chapter budget |

**Assembly procedure:**
1. Load all identity files. If total exceeds 30K tokens, truncate `inspirations.md`
   first (least critical), then `self.md` history section.
2. Load fandom context. Prioritize: character sheets for `brief.characters` >
   general fandom conventions > world details. Truncate from the bottom.
3. Extract anti-slop rules into a compact format:
   - Tier 1 banned words as a comma-separated list.
   - Top 10 fiction AI tell patterns as a numbered list.
   - Top 5 anti-patterns as brief rules.
4. Select few-shot examples from the bank:
   - Filter by fandom match, then genre, then tone.
   - Rank by quality score (from the learning engine).
   - Take top 3 that fit within budget.
5. Remaining budget is draft space.

**Token counting:** Use a conservative estimate of 4 characters per token for English
prose. Exact tokenization is not required at assembly time; the budget is a guideline
to prevent context overflow.

### 4.4 Drafting

Drafting adapts `draft_chapter.py` for fanfic. The key changes are:
- System prompt references fanfic conventions instead of "literary fiction fantasy novel"
- Context includes identity and fandom material instead of a fixed novel's world bible
- Anti-pattern rules are loaded from the databases rather than hardcoded

**One-shot drafting:**

A single call to the writer model with the full context package. The prompt structure:

```
System: You are writing fanfiction under a specific pen name and voice.
        You write in {voice_priors.pov} {voice_priors.tense}.
        You follow the voice definition exactly. You hit every story beat.
        You never use words from the banned list. You show, never tell emotions.
        Your prose is specific, sensory, grounded. You write the FULL work.

User:   VOICE DEFINITION: {identity.self + identity.voice_priors}
        PEN NAME VOICE: {identity.pen_name}
        FANDOM CONTEXT: {fandom_context}
        CHARACTER NOTES: {character_sheets}
        FEW-SHOT EXAMPLES: {selected_examples}
        STORY BRIEF: {brief}
        ANTI-SLOP RULES: {compact_rules}
        ANTI-PATTERN RULES: {compact_patterns}

        Write the complete story now. Target ~{target_length} words.
```

Writer model configuration: temperature 0.8, max_tokens 16000 (for one-shots up to
~12K words). For longer one-shots, use max_tokens 32000.

**Multi-chapter drafting:**

Sequential chapter-by-chapter drafting with continuity threading:

1. Generate a chapter outline from the brief (if not provided):
   - Break the premise into chapter-level beats.
   - Assign POV, emotional arc, and key events per chapter.
2. For each chapter `i` in `[1..chapter_count]`:
   a. Build the chapter-specific prompt:
      - Include the chapter outline entry.
      - Include the previous chapter's last 2000 characters (for continuity).
      - Include the next chapter's outline entry (for flow).
   b. Call the writer model.
   c. Persist the chapter draft to state.
   d. If the chapter's word count deviates >30% from the per-chapter target,
      log a warning but continue.

### 4.5 Evaluation Gate

Evaluation has three checks, applied in order:

#### Check 1: Mechanical Slop Score (HARD GATE)

Call `slop_score(text)` from `evaluate.py` on each chapter/segment.

**Pass condition:** `slop_penalty < 3.0` for every chapter.

This is a hard gate. No exceptions. If any chapter fails, the draft transitions
to REVISE with a slop-focused revision brief.

The slop score components (from `evaluate.py`):
- Tier 1 banned words: up to 4 points
- Tier 2 word clusters: up to 2 points
- Tier 3 filler phrases: up to 2 points
- Excessive em dashes: up to 1 point
- Uniform sentence length: 1 point
- Transition word abuse: up to 1 point
- Fiction AI tells: up to 2 points
- Show-don't-tell violations: up to 1.5 points
- Structural AI tics: up to 2 points

Total possible: ~16.5 points, capped at 10.0. Threshold of 3.0 means the draft
can have minor issues but no significant patterns.

#### Check 2: LLM Evaluation Score (SOFT GATE)

Call an adapted version of `evaluate.py`'s chapter evaluation, with fanfic-specific
dimensions:

| Dimension | Description | Weight |
|---|---|---|
| voice_adherence | Does prose match the identity's voice definition? | 20% |
| characterization_accuracy | Are characters recognizably in-character for this fandom? | 25% |
| fandom_voice_fit | Does the work feel like it belongs in this fandom's tradition? | 15% |
| prose_quality | Sentence variety, specificity, metaphor quality, show-don't-tell | 15% |
| engagement | Would a reader keep reading? Is there something surprising? | 15% |
| pacing | Does tension build and release appropriately for the work's length? | 5% |
| emotional_arc | Is the emotional journey earned, not just asserted? | 5% |

**Pass condition:** Weighted overall_score >= 7.0.

This is a soft gate. If the score is below 7.0 but above 5.0, revision is attempted.
If below 5.0, the work is flagged for potential full rewrite but still goes through
the revision loop.

#### Check 3: Characterization Accuracy (ADDITIONAL GATE)

Extracted from the LLM evaluation's `characterization_accuracy` dimension.

**Pass condition:** `characterization_accuracy.score >= 6.0`.

This is an additional gate because getting characters wrong is the fastest way to
lose fanfic readers. Even if the overall score passes, bad characterization sends
the draft to REVISE with character-focused notes.

#### Combined Gate Logic

```python
# sketch
def evaluate_gate(scores: dict) -> tuple[bool, str]:
    slop = scores["slop_penalty"]
    overall = scores["overall_score"]
    char_acc = scores["characterization_accuracy"]["score"]

    if slop >= 3.0:
        return False, "SLOP_FAIL"
    if char_acc < 6.0:
        return False, "CHARACTERIZATION_FAIL"
    if overall < 7.0:
        return False, "QUALITY_FAIL"
    return True, "PASS"
```

### 4.6 Revision Loop

Maximum 3 revision cycles (configurable via `max_revisions` in state).

**Revision brief generation** (adapted from `gen_brief.py`):

Depending on the failure reason:

- **SLOP_FAIL:** Brief lists every slop hit with location and suggested replacement.
  Focus is entirely on mechanical cleanup -- replace banned words, rewrite fiction AI
  tell patterns, restructure tic-heavy passages. The brief does NOT ask for creative
  changes; it is a mechanical cleanup pass.

- **CHARACTERIZATION_FAIL:** Brief includes:
  - The specific characterization_accuracy feedback from the LLM evaluation.
  - Relevant character notes from fandom context (canonical speech patterns, behavioral
    tendencies, key character traits).
  - Specific passages where characters are out-of-character, quoted with suggested
    rewrites.

- **QUALITY_FAIL:** Brief includes:
  - Scores for all dimensions, highlighting the weakest.
  - The LLM evaluation's `top_3_revisions` list.
  - The `weakest_moment` from each low-scoring dimension.
  - Anti-pattern check results.

**Revision call** (adapted from `gen_revision.py`):

The revision model receives:
- The existing draft (full text)
- The revision brief
- The full context package (same as original draft)
- Anti-pattern rules

The system prompt instructs the model to preserve what works and fix what the brief
identifies, writing the FULL revised text (no truncation).

**Exit conditions for the revision loop:**

| Condition | Action |
|---|---|
| All gates pass | Exit to PREPARE |
| Any gate fails, revision_count < 3 | Loop back to REVISE |
| Any gate fails, revision_count >= 3 | Exit to PREPARE with `max_revisions_reached` warning |

When `max_revisions_reached` is true, the PREPARE state adds a warning to the
package metadata (visible to the human reviewer, not in the AO3 content):
"This work reached the maximum revision count (3) without fully passing evaluation.
Scores: [final scores]. Human review is especially important."

### 4.7 Post Preparation

PREPARE formats the work for AO3 and generates metadata.

#### AO3 Formatting

AO3 accepts a subset of HTML. The formatter:
1. Converts markdown paragraphs to `<p>` tags.
2. Converts markdown italics (`*text*`) to `<em>text</em>`.
3. Converts markdown bold (`**text**`) to `<strong>text</strong>`.
4. Converts section breaks (`---`) to `<hr />`.
5. Preserves dialogue formatting (no smart quotes conversion -- AO3 handles this).
6. For multi-chapter works, splits into chapter bodies.

#### Tag Generation

Tags are generated from the brief's `tags_hint` combined with fandom conventions
from `fandom_context.md`.

Tag categories (AO3 taxonomy):
- **Fandom:** from `brief.fandom` (must use canonical AO3 fandom tag)
- **Rating:** from `brief.rating`
- **Archive Warning:** derived from content analysis (e.g., "No Archive Warnings Apply",
  "Creator Chose Not To Use Archive Warnings")
- **Relationship:** from `brief.ship` (must use canonical AO3 relationship format:
  "Character A/Character B" for romantic, "Character A & Character B" for platonic)
- **Character:** from `brief.characters` (canonical AO3 character tags)
- **Additional Tags:** genre, tropes, content descriptors from `brief.tags_hint` and
  fandom conventions. Follow fandom tagging norms (e.g., "Slow Burn", "Angst with a
  Happy Ending", "Post-Canon").

The tag generator consults `fandom_context.md` for fandom-specific conventions:
which tags are commonly used, which are considered good form, which to avoid.

#### Summary Generation

The summary is 1-3 sentences that hook without spoiling. Requirements:
- Written in the pen name's voice.
- Passes `slop_score()` with `slop_penalty < 2.0` (stricter than body text because
  summaries are short and every word is scrutinized).
- Does not reveal the ending.
- Matches fandom conventions (some fandoms prefer in-universe excerpts as summaries,
  others prefer plot descriptions).

#### Author's Notes Generation

Author's notes use the pen name's voice from `identity/pen_name.md`. The notes:
- Provide brief context for the fic (what inspired it, any relevant content notes).
- May include personal touches consistent with the persona (thanking readers, mentioning
  what was fun to write, noting influences).
- Must pass `slop_score()` with `slop_penalty < 2.0`.
- Must NOT mention AI, automation, or anything that hints at non-human authorship.

### 4.8 Queue

The QUEUE state posts the prepared work to the API proxy.

```python
# sketch
import httpx

def queue_work(publish_request: PublishRequest, api_base: str = "http://127.0.0.1:8000") -> str:
    resp = httpx.post(
        f"{api_base}/works",
        json=publish_request.model_dump(),
    )
    resp.raise_for_status()
    queue_item = QueueItem(**resp.json())
    return queue_item.queue_id
```

The human then:
1. Reviews the work at `GET /queue/{queue_id}`.
2. Optionally edits it (outside the system).
3. Posts to AO3 manually.
4. Marks as published: `PATCH /queue/{queue_id}` with `{"ao3_work_id": 12345}`.
   OR rejects: `DELETE /queue/{queue_id}`.

The write loop can poll `GET /queue/{queue_id}` to detect status changes, or the
next run can check outstanding queue items before starting a new write.

### 4.9 Experiment Tracking

Every write loop run is an experiment. Tracking is automatic.

**At BRIEF state:**
```bash
# sketch -- executed by the write loop
br create -p 3 "experiment: {brief.fandom} - {brief.title or brief.premise[:50]}"
br update {bead_id} --description "Hypothesis: {brief.experiment_hypothesis or 'Standard run'}"
```

**At DONE state:**
```python
# sketch -- data recorded to experiment bead description
experiment_results = {
    "run_id": state.run_id,
    "fandom": brief.fandom,
    "title": brief.title,
    "hypothesis": brief.experiment_hypothesis,
    "revision_count": state.revision_count,
    "final_scores": {
        "slop_penalty": state.final_slop_penalty,
        "overall_score": state.final_overall_score,
        "characterization_accuracy": state.final_char_accuracy,
    },
    "outcome": "published" | "rejected",
    "ao3_work_id": state.ao3_work_id,  # if published
    "learned": auto_generated_summary,
}
```

The `learned` field is auto-generated from the delta between initial and final scores:
"Revision cycle 1 fixed slop (penalty 4.2 -> 1.8). Revision cycle 2 improved
characterization (5.4 -> 7.1). Final overall score: 7.3. Hypothesis outcome: TBD
(awaiting reader feedback)."

### 4.10 State Persistence

State is persisted to `write/runs/{run_id}/state.json`. This is separate from
autonovel's `state.json` (which tracks the novel pipeline).

```python
# sketch
@dataclass
class WriteLoopState:
    run_id: str                      # UUID4
    state: str                       # current state name
    brief: StoryBrief                # the input brief
    created_at: str                  # ISO datetime
    updated_at: str                  # ISO datetime

    # Context (populated at CONTEXT)
    context_assembled: bool = False
    context_token_counts: dict = field(default_factory=dict)  # slot -> token count

    # Draft (populated at DRAFT)
    draft_chapters: list[str] = field(default_factory=list)   # chapter texts
    draft_word_count: int = 0

    # Evaluation (populated at EVALUATE, updated on re-evaluation)
    evaluation_history: list[dict] = field(default_factory=list)  # list of eval results
    current_slop_penalty: float = 0.0
    current_overall_score: float = 0.0
    current_char_accuracy: float = 0.0
    gate_result: str = ""            # "PASS", "SLOP_FAIL", "CHARACTERIZATION_FAIL", "QUALITY_FAIL"

    # Revision (populated at REVISE)
    revision_count: int = 0
    revision_briefs: list[str] = field(default_factory=list)  # brief texts
    max_revisions_reached: bool = False

    # Prepare (populated at PREPARE)
    publish_request: dict | None = None  # serialized PublishRequest
    warnings: list[str] = field(default_factory=list)

    # Queue (populated at QUEUE)
    queue_id: str | None = None

    # Done (populated at DONE)
    outcome: str | None = None       # "published", "rejected"
    ao3_work_id: int | None = None
    experiment_bead_id: str | None = None
    final_scores: dict = field(default_factory=dict)

    # Error (populated on error)
    error_from: str | None = None    # state where error occurred
    error_detail: str | None = None
    error_attempt_count: int = 0
```

**Resumability:** On startup, the write loop:
1. Checks for `write/runs/*/state.json` files with `state != "DONE"` and `state != "ERROR"`.
2. For each incomplete run, reads the state and re-enters at the current state.
3. The state machine re-executes the current state's actions from the beginning
   (actions are idempotent or check for existing output before re-executing).

**Idempotency rules:**
- BRIEF: Skip if brief already validated and run_id assigned.
- CONTEXT: Reassemble (context may have changed if identity was updated).
- DRAFT: Skip if draft already exists; only re-draft missing chapters.
- EVALUATE: Always re-evaluate (scores should reflect current draft).
- REVISE: Skip if revision for this cycle already produced a new draft.
- PREPARE: Regenerate (formatting is cheap and deterministic).
- QUEUE: Skip if queue_id already assigned (check queue status instead).
- DONE: Skip if already recorded.

## 5. Test Cases

    TEST: TC-01 Happy path one-shot
    INPUT: StoryBrief(fandom="Harry Potter", characters=["Luna Lovegood"],
           premise="Luna finds a creature nobody else can see",
           target_length=5000, rating=Rating.GENERAL, format="one_shot",
           genre="whimsy", tone="bittersweet")
    EXPECTED: State machine progresses BRIEF -> CONTEXT -> DRAFT -> EVALUATE (pass)
              -> PREPARE -> QUEUE -> DONE. QueueItem with status "pending" returned.
              state.json shows state="DONE", outcome depends on human action.
    RATIONALE: Verifies the complete happy path with no revision cycles needed.

    TEST: TC-02 Evaluate fails, revise, re-evaluate, pass
    INPUT: Same brief as TC-01, but draft_chapter produces text with
           overall_score=5.8 on first evaluation.
    EXPECTED: EVALUATE -> REVISE (revision_count=1) -> EVALUATE (score >= 7.0)
              -> PREPARE. evaluation_history has 2 entries.
    RATIONALE: Verifies the revision loop fires on soft gate failure and can recover.

    TEST: TC-03 Max revisions exhausted
    INPUT: Brief that consistently produces low-scoring output (contrived by
           using a very challenging premise with minimal fandom context).
    EXPECTED: EVALUATE -> REVISE -> EVALUATE -> REVISE -> EVALUATE -> REVISE
              -> EVALUATE (still failing) -> PREPARE with max_revisions_reached=true
              and a warning in publish_request metadata. revision_count=3.
    RATIONALE: Verifies the loop terminates after max revisions and still produces
               output for human review rather than silently failing.

    TEST: TC-04 Anti-slop hard gate forces revision
    INPUT: Draft text artificially seeded with tier-1 banned words ("delve",
           "tapestry", "myriad") producing slop_penalty=4.5.
    EXPECTED: EVALUATE returns gate_result="SLOP_FAIL". Transitions to REVISE.
              Revision brief focuses on specific banned word replacements.
              After revision, slop_penalty < 3.0.
    RATIONALE: Verifies the hard gate behavior -- slop must be fixed regardless
               of LLM score. Also verifies the revision brief correctly targets slop.

    TEST: TC-05 Anti-slop hard gate with passing LLM score
    INPUT: Draft with overall_score=8.2 but slop_penalty=3.5 (fiction AI tells
           like "a wave of sadness washed over" and "eyes widened").
    EXPECTED: EVALUATE returns gate_result="SLOP_FAIL" despite high LLM score.
              Transitions to REVISE. The high LLM score does not override the
              hard gate.
    RATIONALE: Confirms that slop is a hard gate, not a soft score that can be
               outweighed by other dimensions. This is the core anti-AI-detection
               guarantee.

    TEST: TC-06 Resume from saved state at DRAFT
    INPUT: state.json with state="DRAFT", context assembled, no draft yet.
           Simulate process restart.
    EXPECTED: Write loop loads state.json, detects state="DRAFT", re-enters
              DRAFT state, produces draft, continues through remaining states.
    RATIONALE: Verifies resumability after interruption during drafting.

    TEST: TC-07 Resume from saved state at EVALUATE
    INPUT: state.json with state="EVALUATE", draft exists, no evaluation yet.
    EXPECTED: Write loop resumes at EVALUATE, runs evaluation, proceeds.
    RATIONALE: Verifies resumability at a different state boundary.

    TEST: TC-08 Resume from ERROR state
    INPUT: state.json with state="ERROR", error_from="DRAFT",
           error_attempt_count=1, error_detail="API timeout".
    EXPECTED: Write loop detects ERROR state, retries DRAFT state,
              error_attempt_count increments to 2. If successful, proceeds normally.
    RATIONALE: Verifies error recovery and retry logic.

    TEST: TC-09 Resume from ERROR with max retries exceeded
    INPUT: state.json with state="ERROR", error_from="DRAFT",
           error_attempt_count=3.
    EXPECTED: Write loop refuses to retry, logs "Max retries exceeded for DRAFT.
              Human intervention required." State remains ERROR.
    RATIONALE: Verifies the loop does not retry indefinitely.

    TEST: TC-10 One-shot vs multi-chapter branching
    INPUT: Two briefs -- one with target_length=5000 (one-shot) and one with
           target_length=40000, format="multi_chapter".
    EXPECTED: One-shot produces a single draft call. Multi-chapter produces
              chapter_count calls (derived as 40000//4000 = 10 chapters),
              each with continuity from the previous chapter.
    RATIONALE: Verifies the branching logic in DRAFT state and chapter count derivation.

    TEST: TC-11 Context assembly respects token budget
    INPUT: Identity files totaling 50K tokens (exceeding the 30K identity budget).
           Fandom context of 60K tokens (exceeding the 40K fandom budget).
    EXPECTED: Context assembly truncates inspirations.md first, then self.md
              history section. Fandom context truncated from the bottom.
              Total assembled context within 200K token budget.
    RATIONALE: Verifies the token budget enforcement and truncation priority.

    TEST: TC-12 Post preparation generates valid AO3 format
    INPUT: Draft with markdown formatting: paragraphs, *italics*, **bold**,
           --- section breaks, dialogue with quotation marks.
    EXPECTED: Output body uses <p> tags, <em>, <strong>, <hr />. No raw markdown.
              Dialogue quotation marks preserved. Paragraph spacing correct.
    RATIONALE: Verifies AO3-compatible HTML generation.

    TEST: TC-13 Experiment bead created with hypothesis
    INPUT: StoryBrief with experiment_hypothesis="Second-person POV increases
           engagement in Naruto fandom".
    EXPECTED: At BRIEF, a bead is created with title "experiment: Naruto - ..."
              and description containing the hypothesis. experiment_bead_id is
              stored in state.
    RATIONALE: Verifies automatic experiment tracking at the start of a run.

    TEST: TC-14 Experiment bead updated with results at DONE
    INPUT: Completed run with final_scores, revision_count=2, outcome="published",
           ao3_work_id=98765.
    EXPECTED: At DONE, the experiment bead is updated with a results summary
              including all scores, revision count, outcome, and a "learned"
              summary. Bead is closed.
    RATIONALE: Verifies experiment tracking completion and data recording.

    TEST: TC-15 Invalid brief missing required fields
    INPUT: StoryBrief with fandom="" (empty string) and characters=[] (empty list).
    EXPECTED: BRIEF state returns validation error: "fandom is required",
              "characters must contain at least one character". State transitions
              to ERROR with validation details. No context assembly or drafting
              occurs.
    RATIONALE: Verifies input validation catches bad briefs early.

    TEST: TC-16 Queue item human review flow
    INPUT: Completed work queued via POST /works. Human reviews and publishes.
    EXPECTED: QueueItem status changes from "pending" to "published" after
              PATCH with ao3_work_id. Write loop detects the change and
              transitions QUEUE -> DONE with outcome="published".
    RATIONALE: Verifies the human-in-the-loop flow works end-to-end.

    TEST: TC-17 Characterization accuracy gate
    INPUT: Draft where characters behave wildly out of character (e.g., a
           canonically stoic character is bubbly and effusive).
           characterization_accuracy score = 4.0, overall_score = 7.5.
    EXPECTED: EVALUATE returns gate_result="CHARACTERIZATION_FAIL" despite
              passing overall score. Revision brief includes character-specific
              notes and canonical behavior references.
    RATIONALE: Verifies that characterization is gated independently of overall
               score, because out-of-character writing is the top complaint from
               fanfic readers.

    TEST: TC-18 Summary and author's notes slop check
    INPUT: PREPARE state generates a summary containing "delve into the
           tapestry of their relationship" (slop_penalty > 2.0).
    EXPECTED: Summary is regenerated (up to 3 attempts). If all attempts fail,
              a WARNING is added to the package but preparation continues.
    RATIONALE: Verifies that even metadata text (summary, notes) passes anti-slop
               checks, since these are the first text a reader sees.

## 6. Implementation Notes

### Module Structure

```
write/
    __init__.py
    loop.py              # State machine: run(), resume(), state transitions
    brief.py             # StoryBrief dataclass, validation, brief parsing
    context.py           # Context assembly, token budget, few-shot selection
    evaluate_fanfic.py   # Fanfic-adapted evaluation (wraps evaluate.py)
    prepare.py           # AO3 formatting, tag generation, summary, author's notes
    revision.py          # Revision brief generation, revision call
    experiment.py        # Experiment bead creation and update
    state.py             # WriteLoopState dataclass, load/save, resume logic
```

### Key Implementation Considerations

**`write/loop.py`** is the orchestrator. It should be a single `run(brief: StoryBrief)`
function that drives the state machine, plus a `resume(run_id: str)` function for
interrupted runs. Each state transition is a method call that reads and writes state.

**`write/evaluate_fanfic.py`** wraps `evaluate.py` but replaces the prompt. It:
- Imports `slop_score` directly from `evaluate.py` (no changes needed).
- Imports `call_judge` and `parse_json_response` from `evaluate.py`.
- Provides its own evaluation prompt with fanfic-specific dimensions.
- Returns a unified result dict compatible with the gate logic.

**`write/context.py`** uses `identity.schema.load_identity()` directly. It adds:
- Few-shot bank loading (new; bank format TBD by the learning engine).
- Token budget enforcement.
- Anti-slop rule extraction (parsing the markdown databases into compact rule blocks).

**`write/prepare.py`** is entirely new. It needs:
- A markdown-to-AO3-HTML converter (simple; AO3's HTML subset is small).
- A tag generator that consults fandom conventions.
- Summary and author's note generators that use the pen name voice and pass slop checks.

**`write/brief.py`** is a straightforward dataclass with validation. Consider using
Pydantic (consistent with `api/models.py`) rather than plain dataclasses for built-in
validation.

### Performance Considerations

- Draft calls are the bottleneck (60-180 seconds per chapter at temperature 0.8).
- Slop scoring is fast (regex, no LLM) -- always run before LLM evaluation to
  short-circuit if possible.
- Context assembly should be cached per-run (identity and fandom context rarely change
  mid-run).
- State persistence should be after every state transition, not batched.

### Security Considerations

- API keys are loaded from environment variables, never persisted to state.json.
- Draft text may contain sensitive content (depending on rating). State files should
  not be committed to version control. Add `write/runs/` to `.gitignore`.
- The API proxy runs locally; no authentication is needed for local-only access.

## 7. Open Questions

1. **Few-shot bank format:** The learning engine has not yet defined how the few-shot
   bank is stored or indexed. Context assembly assumes a queryable bank with fandom/genre
   tags and quality scores. The learning engine spec must align with this interface.

2. **Multi-chapter outline generation:** For multi-chapter works, who generates the
   chapter outline -- the write loop or the strategy planner? This spec assumes the
   write loop generates it at DRAFT time from the brief, but the strategy planner
   might be a better fit for longer works.

3. **Fandom context sourcing:** Where does `fandom_context.md` come from initially?
   Is it hand-written, scraped from wikis, or generated? The write loop consumes it
   but does not create it.

4. **Queue polling vs notification:** Should the write loop poll the queue API to
   detect human action, or should there be a callback/notification mechanism? Polling
   is simpler but less responsive.

5. **Token counting precision:** The spec uses a rough 4-chars-per-token estimate.
   Should the implementation use a proper tokenizer (e.g., `tiktoken` or the Anthropic
   tokenizer) for exact counts?

6. **Revision model vs writer model:** Should revisions use the same model as initial
   drafts, or a different model? `gen_revision.py` currently uses the same writer model.
   A case could be made for using a stronger model for revision (since the context
   includes the existing draft, the revision task is more editorial than generative).

## 8. Future Considerations

### Multi-chapter series support

The current spec handles multi-chapter works within a single write loop run. Series
(multiple related works published over time) would require:
- A series-level state that tracks continuity across runs.
- Character and plot state that persists between works.
- The ability to reference previous works in the series during context assembly.
- Series-level AO3 metadata (series name, order, summary).

The current design is forward-compatible: `WriteLoopState` could gain a `series_id`
field, and context assembly could load previous works' state files.

### Collaborative writing

If the agent ever co-writes with other agents or humans:
- The state machine would need a REVIEW state between DRAFT and EVALUATE where
  a collaborator provides input.
- The context package would need to include the collaborator's style/voice to
  maintain consistency.

### Parallel chapter drafting

For multi-chapter works, chapters could be drafted in parallel (with outline-only
continuity rather than full-text continuity from previous chapters). This would
require:
- A fork in the DRAFT state that dispatches multiple draft calls.
- A join that collects all chapters before proceeding to EVALUATE.
- A continuity-check pass after joining to ensure chapters connect.

### Adaptive evaluation thresholds

As the agent improves through the learning loop, evaluation thresholds could be
raised. A work that scored 7.0 in month 1 might only need 7.5 in month 3. This
would be driven by the learning engine updating a threshold config.

### Real-time slop database updates

The ANTI-SLOP.md and ANTI-PATTERNS.md databases are currently static. As new AI
tells are discovered (by readers, by research, or by the agent's own analysis of
what gets flagged), these databases should be updateable. The write loop would pick
up changes on the next run since it loads the databases at CONTEXT time.
