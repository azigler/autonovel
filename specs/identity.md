# Spec: Identity System

## 1. Overview

The identity system is the foundation that makes the agentic fanfiction author a
distinctive creative voice rather than a generic text generator. It manages the
agent's evolving sense of self -- voice parameters, aesthetic preferences, growth
history, pen name persona, fandom knowledge, and literary influences.

The identity system serves three roles:

1. **Context assembly** -- loads identity files into the writing pipeline so every
   draft carries the agent's voice.
2. **Evolution** -- updates voice priors and self-reflection after each feedback
   cycle, so the agent learns from real readers.
3. **Consistency** -- enforces drift limits and validation rules so the agent's
   personality evolves gradually rather than lurching between identities.

### Dependencies

- **Learning engine** (`learning/`) -- produces `FeedbackDigest` and
  `SelfReflection` objects that drive identity updates.
- **Writing pipeline** (autonovel core) -- consumes the loaded identity context
  when drafting chapters.
- **Feedback collector** (`feedback/`) -- provides raw metrics and comments that
  the learning engine distills into feedback digests.

### Not Covered

- How feedback is collected from AO3 (see future `specs/feedback.md`).
- How the writing pipeline uses identity context to generate prose (see future
  `specs/pipeline.md`).
- Prompt evolution and few-shot bank curation (`learning/`).

### 1.1 Sources and Provenance

| Source | Insight applied to this spec |
|--------|------------------------------|
| `identity/schema.py` | Data models, persistence functions, type definitions |
| `identity/__init__.py` | Public API surface |
| `identity/voice_priors.json` | Default voice parameter values |
| `identity/self.md` | Self-reflection template structure |
| `identity/pen_name.md` | Persona template and constraints |
| `identity/fandom_context.md` | Fandom knowledge template |
| `identity/inspirations.md` | Literary influence template |
| `.claude/refs/PLAN.md` | Architecture overview, core loop, milestones |
| `CLAUDE.md` | Project constraints (anti-AI detection, human-in-the-loop) |

## 2. Current State / Baseline

### Files

The `identity/` directory contains:

- **`schema.py`** -- Dataclass models (`VoicePriors`, `SelfReflection`,
  `FeedbackDigest`, `ReaderComment`) and three persistence functions
  (`load_identity`, `update_self`, `update_voice_priors`).
- **`__init__.py`** -- Re-exports all public models and functions.
- **`voice_priors.json`** -- JSON file with default voice parameters (version 1,
  `updated_at: null`). All categorical parameters have values; `strengths` and
  `weaknesses` are empty lists.
- **`self.md`** -- Template with six sections (Voice, Strengths, Growth Areas,
  Reader Relationship, Current Focus, History). All sections contain placeholder
  guidance text in square brackets. History section has an HTML comment template.
- **`pen_name.md`** -- Template with four sections (Name, Bio, Author's Note
  Voice, Interaction Style). All placeholder text.
- **`fandom_context.md`** -- Template with six sections (Fandom, Canon Summary,
  Character Voices, Popular Ships & Tropes, Fandom Norms, Our Niche). All
  placeholder text.
- **`inspirations.md`** -- Template with three sections (Core Influences, Fandom
  Influences, Anti-Influences). All placeholder text.

### Existing Behaviors

- `load_identity()` reads all five identity files (four markdown + one JSON) and
  returns a dict. Markdown files are returned as raw strings; voice priors are
  deserialized into a `VoicePriors` dataclass.
- `update_self(reflection)` appends a formatted history entry to `self.md`. It
  does not modify any other section.
- `update_voice_priors(adjustments)` merges a partial dict into the current
  priors, bumps the version, sets `updated_at`, and writes back to JSON.
- There is no drift limiting, validation, or rejection logic. Any value can be
  set to any value in a single update.
- There is no token budget awareness -- `load_identity()` returns all content
  regardless of size.
- `_MAX_VERSION_DRIFT = 5` is defined but never used.

### Key Data Structures (from `schema.py`)

```python
# sketch -- simplified from actual dataclasses

@dataclass
class VoicePriors:
    sentence_length: SentenceLength     # {mean, std, min, max}
    paragraph_length: ParagraphLength   # {mean, std}
    dialogue_ratio: float               # 0.0 - 1.0
    interiority_depth: InterirorityDepth  # "shallow" | "medium" | "deep"
    metaphor_density: MetaphorDensity   # "sparse" | "moderate" | "dense"
    pov: POV                            # "first" | "second" | "third_limited" | "third_omniscient"
    tense: Tense                        # "past" | "present"
    vocabulary_register: VocabularyRegister  # "colloquial" | "literary_accessible" | "literary_dense" | "formal"
    humor_frequency: FrequencyLevel     # "rare" | "occasional" | "frequent" | "pervasive"
    sensory_detail_density: SensoryDensity  # "low" | "medium" | "high"
    emotional_directness: EmotionalDirectness  # "direct" | "indirect" | "mixed"
    pacing_preference: PacingPreference  # "fast" | "moderate" | "slow_burn"
    chapter_length_target: ChapterLengthTarget  # {min, max}
    strengths: list[str]
    weaknesses: list[str]
    updated_at: str | None
    version: int

@dataclass
class FeedbackDigest:
    publication_title: str
    fandom: str
    date: str
    hits: int
    kudos: int
    bookmarks: int
    comment_count: int
    subscriber_delta: int
    comments: list[ReaderComment]
    top_praise: list[str]
    top_criticism: list[str]
    recurring_themes: list[str]
    engagement_trend: Literal["rising", "stable", "declining"]

@dataclass
class SelfReflection:
    publication_title: str
    fandom: str
    date: str
    what_happened: str
    what_worked: str
    what_didnt_work: str
    lesson: str
    voice_prior_adjustments: dict
```

## 3. Changes and Decisions

### 3.1 Drift Limiting on Voice Priors

- **Change:** Every call to `update_voice_priors()` must enforce per-parameter
  drift limits. No numeric parameter may change by more than 15% of its current
  value in a single feedback cycle. Categorical parameters may shift at most one
  ordinal position per cycle (e.g., `"sparse"` -> `"moderate"` is allowed;
  `"sparse"` -> `"dense"` is rejected).
- **Decision:** PLAN.md specifies "Voice/style: readers bond with consistency;
  sudden shifts lose trust." This is the mechanism that enforces that constraint.
- **Rationale:** Without drift limits, a single outlier feedback cycle (e.g.,
  one viral comment praising humor) could whipsaw the agent's personality. The
  15% cap and one-step ordinal rule ensure gradual, defensible evolution.

### 3.2 Drift Decay (Recency Weighting)

- **Change:** When the learning engine produces voice prior adjustments from a
  `FeedbackDigest`, the magnitude of the adjustment should be weighted by
  recency. Feedback from the most recent cycle gets weight 1.0; each prior cycle
  decays by a factor of 0.7. Only the last 5 cycles contribute.
- **Decision:** Driven by the core loop design in PLAN.md -- the agent learns
  from real readers, and recent signal is more relevant than historical signal.
- **Rationale:** Prevents stale feedback from anchoring the agent's evolution.
  If the agent's audience shifts (e.g., moves to a new fandom), old feedback
  should fade rather than permanently constrain the voice.

### 3.3 Validation on Identity Updates

- **Change:** Add a `validate_voice_priors(priors: VoicePriors) -> list[str]`
  function that checks all parameter bounds. `update_voice_priors()` must call
  this and raise `ValueError` if validation fails.
- **Decision:** The "one-way doors" principle from PLAN.md -- voice is listed as
  a one-way door, so we must guard against invalid states.
- **Rationale:** Currently any dict can be written to `voice_priors.json` with
  no type or range checking. This could corrupt the identity silently.

### 3.4 Token Budget for Identity Loading

- **Change:** Add a `load_identity(max_tokens: int | None = None)` parameter
  that controls how much identity context is assembled. When a budget is set,
  identity components are loaded in priority order and truncated to fit.
- **Decision:** Writing pipeline has finite context windows. Identity context
  competes with the actual story content, outline, and craft instructions.
- **Rationale:** The current `load_identity()` returns everything. As the agent
  publishes more works and self.md grows, this will exceed useful context size.

### 3.5 Fandom Context Population

- **Change:** Define a `populate_fandom_context(fandom: str)` function that
  fills `fandom_context.md` using structured data from AO3 browsing (via API
  proxy). Character voices are documented from canon analysis. Canon facts are
  verified against source material.
- **Decision:** PLAN.md M1 includes "Choose fandom" and the fandom context
  template exists but is unpopulated.
- **Rationale:** Fandom context is the bridge between the agent's identity and
  the world it writes in. An empty template produces generic fanfic.

### 3.6 Self.md Section-Aware Updates

- **Change:** `update_self()` currently only appends to the History section. It
  should be extended to update any section of self.md (Voice, Strengths, Growth
  Areas, Reader Relationship, Current Focus) based on the learning engine's
  output, while preserving the document's structure.
- **Decision:** PLAN.md describes self.md as "updated by the agent itself after
  each feedback cycle" -- not just the history log.
- **Rationale:** The agent's self-knowledge should evolve across all dimensions,
  not just accumulate a changelog.

## 4. Formal Specification

### 4.1 self.md Update Mechanism

#### Input

A `SelfReflection` object produced by the learning engine after processing a
`FeedbackDigest`.

#### Processing Rules

1. **History append** (existing behavior): Format and append a history entry.
2. **Section updates** (new): The learning engine may include section-specific
   updates in a `section_updates: dict[str, str]` field on `SelfReflection`.
   Each key is a section name (`"voice"`, `"strengths"`, `"growth_areas"`,
   `"reader_relationship"`, `"current_focus"`). The value is the new content for
   that section.
3. **Merge strategy**: For list-like sections (Strengths, Growth Areas), new
   items are appended. Existing items are preserved unless explicitly removed.
   For prose sections (Voice, Reader Relationship, Current Focus), the new
   content replaces the old.
4. **Placeholder detection**: If a section still contains text in square
   brackets (the template placeholder pattern), the update replaces the entire
   section content. This handles first-time initialization.

#### Output

The updated `self.md` file, written atomically (write to temp file, then rename).

#### Pseudocode

```python
# sketch
def update_self(reflection: SelfReflection) -> str:
    current = _SELF_PATH.read_text()
    sections = parse_sections(current)  # dict[str, str]

    # Append history entry
    history_entry = format_history_entry(reflection)
    sections["history"] += "\n\n" + history_entry

    # Apply section updates if present
    for section_name, new_content in reflection.section_updates.items():
        if section_name not in sections:
            continue
        old_content = sections[section_name]
        if is_placeholder(old_content):
            sections[section_name] = new_content
        elif section_name in ("strengths", "growth_areas"):
            sections[section_name] = merge_list_section(old_content, new_content)
        else:
            sections[section_name] = new_content

    updated = render_sections(sections)
    atomic_write(_SELF_PATH, updated)
    return history_entry
```

### 4.2 voice_priors.json Evolution

#### Drift Limits

Numeric parameters:

| Parameter | Min | Max | Max drift per cycle |
|-----------|-----|-----|-------------------|
| `sentence_length.mean` | 5 | 35 | 15% of current value |
| `sentence_length.std` | 2 | 15 | 15% of current value |
| `sentence_length.min` | 1 | 10 | 15% of current value |
| `sentence_length.max` | 20 | 80 | 15% of current value |
| `paragraph_length.mean` | 1 | 10 | 15% of current value |
| `paragraph_length.std` | 1 | 5 | 15% of current value |
| `dialogue_ratio` | 0.0 | 0.8 | 0.05 (absolute) |
| `chapter_length_target.min` | 1000 | 10000 | 15% of current value |
| `chapter_length_target.max` | 2000 | 20000 | 15% of current value |

Categorical parameters (ordinal scales):

| Parameter | Scale (ordered) | Max drift per cycle |
|-----------|----------------|-------------------|
| `interiority_depth` | shallow < medium < deep | 1 step |
| `metaphor_density` | sparse < moderate < dense | 1 step |
| `humor_frequency` | rare < occasional < frequent < pervasive | 1 step |
| `sensory_detail_density` | low < medium < high | 1 step |
| `emotional_directness` | direct < mixed < indirect | 1 step |
| `pacing_preference` | fast < moderate < slow_burn | 1 step |

Non-ordinal categorical parameters:

| Parameter | Allowed values | Drift rule |
|-----------|---------------|------------|
| `pov` | first, second, third_limited, third_omniscient | Can change freely (story-level choice) |
| `tense` | past, present | Can change freely (story-level choice) |
| `vocabulary_register` | colloquial, literary_accessible, literary_dense, formal | 1 step on the scale |

List parameters (`strengths`, `weaknesses`):

- At most 2 items added per cycle.
- At most 1 item removed per cycle.
- Maximum 10 items per list.

#### Drift Decay

```python
# sketch
DECAY_FACTOR = 0.7
MAX_HISTORY_CYCLES = 5

def compute_weighted_adjustment(
    current_adjustments: dict,
    history: list[dict],  # most recent first
) -> dict:
    weighted = {}
    for key, value in current_adjustments.items():
        weight = 1.0
        weighted[key] = value * weight

    for i, past in enumerate(history[:MAX_HISTORY_CYCLES - 1]):
        weight = DECAY_FACTOR ** (i + 1)
        for key, value in past.items():
            if key in weighted:
                weighted[key] += value * weight

    # Normalize by total weight
    total_weight = sum(DECAY_FACTOR ** i for i in range(min(len(history) + 1, MAX_HISTORY_CYCLES)))
    return {k: v / total_weight for k, v in weighted.items()}
```

#### Version Tracking

- `version` increments by 1 on every successful `update_voice_priors()` call.
- `updated_at` is set to the current UTC date in ISO format (`YYYY-MM-DD`).
- The existing `_MAX_VERSION_DRIFT = 5` constant is used: if `version` would
  exceed the previous version by more than 5 in a single session (indicating
  runaway updates), raise `RuntimeError`.

#### Update Pseudocode

```python
# sketch
def update_voice_priors(
    adjustments: dict,
    *,
    bump_version: bool = True,
) -> VoicePriors:
    priors = _load_voice_priors()
    current = priors.to_dict()

    clamped = clamp_adjustments(current, adjustments)
    for key, value in clamped.items():
        if key not in current:
            continue
        if isinstance(current[key], dict) and isinstance(value, dict):
            current[key].update(value)
        else:
            current[key] = value

    if bump_version:
        new_version = current.get("version", 0) + 1
        if new_version - priors.version > _MAX_VERSION_DRIFT:
            raise RuntimeError("Runaway version bump detected")
        current["version"] = new_version
    current["updated_at"] = _utcnow_iso()

    updated = VoicePriors.from_dict(current)
    errors = validate_voice_priors(updated)
    if errors:
        raise ValueError(f"Invalid voice priors: {errors}")

    _save_voice_priors(updated)
    return updated
```

### 4.3 Validation Rules

#### Valid voice_priors.json

```python
# sketch
def validate_voice_priors(priors: VoicePriors) -> list[str]:
    errors = []

    # Numeric bounds
    if not (5 <= priors.sentence_length.mean <= 35):
        errors.append(f"sentence_length.mean out of bounds: {priors.sentence_length.mean}")
    if not (2 <= priors.sentence_length.std <= 15):
        errors.append(f"sentence_length.std out of bounds: {priors.sentence_length.std}")
    if not (1 <= priors.sentence_length.min <= 10):
        errors.append(f"sentence_length.min out of bounds: {priors.sentence_length.min}")
    if not (20 <= priors.sentence_length.max <= 80):
        errors.append(f"sentence_length.max out of bounds: {priors.sentence_length.max}")
    if priors.sentence_length.min >= priors.sentence_length.max:
        errors.append("sentence_length.min must be less than sentence_length.max")

    if not (1 <= priors.paragraph_length.mean <= 10):
        errors.append(f"paragraph_length.mean out of bounds: {priors.paragraph_length.mean}")
    if not (1 <= priors.paragraph_length.std <= 5):
        errors.append(f"paragraph_length.std out of bounds: {priors.paragraph_length.std}")

    if not (0.0 <= priors.dialogue_ratio <= 0.8):
        errors.append(f"dialogue_ratio out of bounds: {priors.dialogue_ratio}")

    if not (1000 <= priors.chapter_length_target.min <= 10000):
        errors.append(f"chapter_length_target.min out of bounds")
    if not (2000 <= priors.chapter_length_target.max <= 20000):
        errors.append(f"chapter_length_target.max out of bounds")
    if priors.chapter_length_target.min >= priors.chapter_length_target.max:
        errors.append("chapter_length_target.min must be less than max")

    # Categorical membership
    VALID_INTERIORITY = ("shallow", "medium", "deep")
    if priors.interiority_depth not in VALID_INTERIORITY:
        errors.append(f"invalid interiority_depth: {priors.interiority_depth}")

    VALID_METAPHOR = ("sparse", "moderate", "dense")
    if priors.metaphor_density not in VALID_METAPHOR:
        errors.append(f"invalid metaphor_density: {priors.metaphor_density}")

    VALID_POV = ("first", "second", "third_limited", "third_omniscient")
    if priors.pov not in VALID_POV:
        errors.append(f"invalid pov: {priors.pov}")

    VALID_TENSE = ("past", "present")
    if priors.tense not in VALID_TENSE:
        errors.append(f"invalid tense: {priors.tense}")

    VALID_REGISTER = ("colloquial", "literary_accessible", "literary_dense", "formal")
    if priors.vocabulary_register not in VALID_REGISTER:
        errors.append(f"invalid vocabulary_register: {priors.vocabulary_register}")

    VALID_FREQUENCY = ("rare", "occasional", "frequent", "pervasive")
    if priors.humor_frequency not in VALID_FREQUENCY:
        errors.append(f"invalid humor_frequency: {priors.humor_frequency}")

    VALID_SENSORY = ("low", "medium", "high")
    if priors.sensory_detail_density not in VALID_SENSORY:
        errors.append(f"invalid sensory_detail_density: {priors.sensory_detail_density}")

    VALID_EMOTIONAL = ("direct", "indirect", "mixed")
    if priors.emotional_directness not in VALID_EMOTIONAL:
        errors.append(f"invalid emotional_directness: {priors.emotional_directness}")

    VALID_PACING = ("fast", "moderate", "slow_burn")
    if priors.pacing_preference not in VALID_PACING:
        errors.append(f"invalid pacing_preference: {priors.pacing_preference}")

    # List bounds
    if len(priors.strengths) > 10:
        errors.append(f"strengths list too long: {len(priors.strengths)}")
    if len(priors.weaknesses) > 10:
        errors.append(f"weaknesses list too long: {len(priors.weaknesses)}")

    # Version
    if priors.version < 1:
        errors.append(f"version must be >= 1: {priors.version}")

    return errors
```

#### Valid self.md

A valid self.md must:

1. Contain all six section headers: `## Voice`, `## Strengths`, `## Growth Areas`,
   `## Reader Relationship`, `## Current Focus`, `## History`.
2. Each section must have content (at minimum, the placeholder template text).
3. The History section, if it has entries beyond the template, must have entries
   in chronological order (newest last).

#### Update Rejection Criteria

An update to voice priors is rejected if:

1. Any parameter would be set outside its valid bounds (Section 4.3 above).
2. Any numeric parameter drifts more than 15% from its current value in one
   cycle (or 0.05 absolute for `dialogue_ratio`).
3. Any ordinal categorical parameter jumps more than one step.
4. More than 2 items are added to `strengths` or `weaknesses`.
5. More than 1 item is removed from `strengths` or `weaknesses`.
6. The `version` field would jump by more than `_MAX_VERSION_DRIFT`.

When an update is rejected, the function raises `ValueError` with a list of
all violations. The voice priors file is not modified.

### 4.4 Identity Loading

#### Load Order and Priority

Identity components are loaded in this priority order for token budget allocation:

| Priority | Component | Typical size | Min allocation |
|----------|-----------|-------------|----------------|
| 1 | `voice_priors.json` | ~500 tokens | Always loaded in full |
| 2 | `self.md` (Voice + Current Focus) | ~200-500 tokens | Always loaded |
| 3 | `fandom_context.md` (Canon Summary + Character Voices) | ~500-1000 tokens | Always loaded |
| 4 | `pen_name.md` (Author's Note Voice) | ~200 tokens | Loaded for publishing pipeline |
| 5 | `self.md` (full) | ~500-2000 tokens | Loaded if budget allows |
| 6 | `fandom_context.md` (full) | ~500-2000 tokens | Loaded if budget allows |
| 7 | `inspirations.md` | ~500-1000 tokens | Loaded if budget allows |
| 8 | `pen_name.md` (full) | ~300-500 tokens | Loaded if budget allows |
| 9 | `self.md` History | unbounded | Truncated to last N entries |

#### Token Budget Pseudocode

```python
# sketch
DEFAULT_IDENTITY_BUDGET = 4000  # tokens

def load_identity(max_tokens: int | None = None) -> dict:
    budget = max_tokens or DEFAULT_IDENTITY_BUDGET
    result = {}
    remaining = budget

    # Priority 1: voice priors (always loaded, ~500 tokens)
    result["voice_priors"] = _load_voice_priors()
    remaining -= estimate_tokens(result["voice_priors"].to_dict())

    # Priority 2: self.md key sections
    self_md = _SELF_PATH.read_text()
    sections = parse_sections(self_md)
    result["self_voice"] = sections.get("voice", "")
    result["self_focus"] = sections.get("current_focus", "")
    remaining -= estimate_tokens(result["self_voice"] + result["self_focus"])

    # Priority 3: fandom context key sections
    fandom_md = (IDENTITY_DIR / "fandom_context.md").read_text()
    fandom_sections = parse_sections(fandom_md)
    result["canon_summary"] = fandom_sections.get("canon_summary", "")
    result["character_voices"] = fandom_sections.get("character_voices", "")
    remaining -= estimate_tokens(result["canon_summary"] + result["character_voices"])

    # Continue loading lower-priority components if budget allows
    # ...

    return result
```

#### Token Estimation

Use the approximation of 1 token per 4 characters for English text. This is
conservative (actual tokenization is model-specific) but sufficient for budget
allocation.

### 4.5 Fandom Context

#### Population

`populate_fandom_context(fandom: str)` fills `fandom_context.md` by:

1. **Fandom identification**: Resolve the fandom name to an AO3 tag (via API
   proxy). Determine source material and whether canon is complete or ongoing.
2. **Canon summary**: Compile key facts from the source material relevant to
   fanfic writing -- character dynamics, unresolved tensions, emotional landscape.
   Keep under 1000 words.
3. **Character voices**: For each major character (top 5-8 by fic frequency),
   document speech patterns, vocabulary, verbal tics, comfortable topics, and
   deflection patterns. Use the template from `fandom_context.md`.
4. **Popular ships and tropes**: Query AO3 for top ships by fic count in the
   fandom. Identify oversaturated tropes and underserved niches.
5. **Fandom norms**: Document rating distribution, tagging culture, content
   warning expectations, posting rhythm, and comment culture.
6. **Our niche**: Left empty initially -- populated after the agent's first
   publication cycle when reader response data exists.

#### Canon Verification

Character voice documentation must be grounded in specific canon examples.
Each character voice entry should include at least one direct canon quote or
scene reference. When the API proxy returns fandom data, cross-reference
character descriptions against known canon sources.

#### Update Cadence

Fandom context is refreshed:
- When the agent switches to a new fandom.
- When canon updates (new season, book, etc.) are released.
- After every 3 publication cycles, to update the Popular Ships & Tropes and
  Fandom Norms sections with current data.

### 4.6 Pen Name Persona

#### Consistency Constraints

The pen name persona, once established, has strict consistency rules:

1. **Name**: Never changes after first publication.
2. **Bio**: May be updated, but core personality markers must persist. The bio
   should always contain the same "specific detail that feels lived-in" (per
   the template guidance). Updates add new details; they do not contradict
   established ones.
3. **Author's note voice**: Must remain recognizable across works. The tone
   (casual, excited, reflective) can vary by context, but verbal mannerisms
   and humor style stay consistent.
4. **Interaction style**: Comment response patterns are fixed after the first
   10 interactions. Changes to interaction style are treated as one-way doors
   requiring human approval.

#### Author's Notes Generation

When the publishing pipeline generates author's notes, it loads `pen_name.md`
and uses the Author's Note Voice section as a style guide. The notes must:

- Match the pre-chapter/post-chapter tone described in the template.
- Use the persona's established verbal mannerisms.
- Never include language that sounds generated (no "I hope you enjoy this
  journey" or similar AI tells).
- Reference specific details about the writing process that feel authentic
  (e.g., "this chapter was supposed to be half this length but [character]
  wouldn't stop talking").

## 5. Test Cases

    TEST: load_identity returns all components
    INPUT: load_identity() with all template files present
    EXPECTED: Dict with keys "self", "pen_name", "inspirations",
              "fandom_context" (all non-empty strings) and "voice_priors"
              (a VoicePriors instance with version=1)
    RATIONALE: Verifies the basic loading contract -- all identity
               components are read and returned in the expected format.

    TEST: load_identity handles missing files gracefully
    INPUT: load_identity() with fandom_context.md deleted
    EXPECTED: Dict with "fandom_context" key set to empty string;
              all other keys populated normally
    RATIONALE: The agent may not have populated all identity files yet,
               especially early in its lifecycle. Loading must not crash.

    TEST: update_self appends history entry
    INPUT: update_self(SelfReflection(
               publication_title="First Light",
               fandom="Our Flag Means Death",
               what_worked="Dialogue subtext",
               what_didnt_work="Pacing in act 2",
               lesson="Slow the middle; readers want to sit with the tension"))
    EXPECTED: self.md contains a new "### [date] - First Light (Our Flag Means
              Death)" entry with the three bullet points. All prior content
              is preserved.
    RATIONALE: Verifies the core self-reflection append mechanism and that
               existing content is not clobbered.

    TEST: update_voice_priors applies adjustments correctly
    INPUT: update_voice_priors({"dialogue_ratio": 0.40})
           starting from default priors (dialogue_ratio=0.35)
    EXPECTED: Returns VoicePriors with dialogue_ratio=0.40, version=2,
              updated_at set to today's date. All other fields unchanged.
    RATIONALE: Verifies partial updates work -- only the specified key
               changes, version bumps, timestamp updates.

    TEST: update_voice_priors respects numeric drift limit
    INPUT: update_voice_priors({"dialogue_ratio": 0.60})
           starting from default priors (dialogue_ratio=0.35)
    EXPECTED: ValueError raised. The requested change of 0.25 exceeds the
              0.05 absolute drift limit for dialogue_ratio. voice_priors.json
              is not modified.
    RATIONALE: Drift limiting is the core protection against personality
               whiplash. This tests the absolute-value drift limit on
               dialogue_ratio.

    TEST: update_voice_priors respects ordinal categorical drift limit
    INPUT: update_voice_priors({"interiority_depth": "deep"})
           starting from default priors (interiority_depth="medium")
    EXPECTED: Returns VoicePriors with interiority_depth="deep", version=2.
              This is valid because medium->deep is exactly 1 ordinal step.
    RATIONALE: Verifies that single-step ordinal changes are accepted.

    TEST: update_voice_priors rejects multi-step ordinal change
    INPUT: update_voice_priors({"metaphor_density": "dense"})
           starting from priors with metaphor_density="sparse"
    EXPECTED: ValueError raised. "sparse" to "dense" skips "moderate" --
              a 2-step change on a 3-point ordinal scale.
    RATIONALE: Ordinal drift limits prevent sudden personality shifts in
               categorical parameters.

    TEST: validate_voice_priors catches out-of-bounds numeric
    INPUT: validate_voice_priors(VoicePriors(dialogue_ratio=0.95))
    EXPECTED: Returns list containing error string about dialogue_ratio
              being out of bounds (max 0.8).
    RATIONALE: Validation must catch values that exceed the defined ranges,
               even if they were not set through update_voice_priors.

    TEST: load_identity respects token budget
    INPUT: load_identity(max_tokens=1000) with a self.md containing a
           long History section (50 entries, ~5000 tokens)
    EXPECTED: Returned dict contains voice_priors and key self.md sections
              (Voice, Current Focus) but History is truncated or omitted.
              Total estimated tokens of returned content <= 1000.
    RATIONALE: The writing pipeline has a finite context window. Identity
               loading must fit within the allocated budget.

    TEST: round-trip serialization
    INPUT: priors = VoicePriors(); d = priors.to_dict();
           restored = VoicePriors.from_dict(d)
    EXPECTED: priors == restored (all fields identical after round-trip
              through dict serialization and deserialization)
    RATIONALE: Identity state must survive persistence cycles without
               corruption. This is the foundation of all persistence logic.

    TEST: drift limit enforcement with 50% shift attempt
    INPUT: Starting from sentence_length.mean=14,
           update_voice_priors({"sentence_length": {"mean": 21}})
    EXPECTED: ValueError raised. The change from 14 to 21 is a 50% increase,
              far exceeding the 15% drift limit (max allowed: ~16.1).
              voice_priors.json is not modified.
    RATIONALE: Exercises the percentage-based drift limit with a deliberately
               large change to verify clamping/rejection behavior.

    TEST: empty feedback produces no changes
    INPUT: update_voice_priors({}) with bump_version=False
    EXPECTED: Returns current VoicePriors unchanged. version stays the same.
              updated_at is set to current date (timestamp always updates).
    RATIONALE: The learning engine may produce no adjustments after a cycle
               where feedback is ambiguous. The system must handle this
               gracefully without spurious version bumps.

    TEST: first-time initialization from blank templates
    INPUT: Delete voice_priors.json, then call _load_voice_priors()
    EXPECTED: Returns a VoicePriors with all default values (version=1,
              updated_at=None, dialogue_ratio=0.35, etc.)
    RATIONALE: On first run, before any identity has been established, the
               system must bootstrap from hardcoded defaults rather than
               crashing on a missing file.

    TEST: version increment on update
    INPUT: Call update_voice_priors({"tense": "present"}) three times
           sequentially, starting from version=1.
    EXPECTED: After the three calls, version=4. Each call incremented by 1.
    RATIONALE: Version tracking ensures we can detect how many update cycles
               the identity has been through, which is useful for debugging
               and for the drift decay weighting.

    TEST: validate_voice_priors accepts valid default priors
    INPUT: validate_voice_priors(VoicePriors())
    EXPECTED: Returns empty list (no errors).
    RATIONALE: The hardcoded defaults must themselves be valid. This is a
               sanity check that the default values in the dataclass are
               within all defined bounds.

## 6. Implementation Notes

### Suggested Module Structure

The current `identity/schema.py` should be split as the system grows:

- `identity/schema.py` -- Dataclass definitions only (models).
- `identity/persistence.py` -- `load_identity`, `update_self`,
  `update_voice_priors`, and internal I/O helpers.
- `identity/validation.py` -- `validate_voice_priors`,
  `validate_self_md`, drift checking functions.
- `identity/loading.py` -- Token-budget-aware identity assembly for the
  writing pipeline.
- `identity/fandom.py` -- `populate_fandom_context` and fandom data fetching.

### Type Annotations

All existing types use `typing.Literal` for categorical parameters. The ordinal
scales defined in Section 4.2 should be implemented as tuples so that the drift
checker can compute ordinal distance:

```python
# sketch
ORDINAL_SCALES: dict[str, tuple[str, ...]] = {
    "interiority_depth": ("shallow", "medium", "deep"),
    "metaphor_density": ("sparse", "moderate", "dense"),
    "humor_frequency": ("rare", "occasional", "frequent", "pervasive"),
    "sensory_detail_density": ("low", "medium", "high"),
    "emotional_directness": ("direct", "mixed", "indirect"),
    "pacing_preference": ("fast", "moderate", "slow_burn"),
    "vocabulary_register": ("colloquial", "literary_accessible", "literary_dense", "formal"),
}

def ordinal_distance(scale: tuple[str, ...], a: str, b: str) -> int:
    return abs(scale.index(a) - scale.index(b))
```

### Atomic File Writes

All file writes (`_save_voice_priors`, `update_self`) should use atomic writes
(write to a temp file in the same directory, then `os.rename`) to prevent
corruption if the process is interrupted mid-write.

### Performance Considerations

- `load_identity()` reads 5 files from disk. This is fast enough for the
  current use case (called once per pipeline run). If identity files grow large,
  consider caching with mtime-based invalidation.
- Token estimation (4 chars per token) is an approximation. For production
  accuracy, use `tiktoken` or the model's actual tokenizer. The approximation
  is acceptable for budget allocation where +/- 20% is tolerable.

### Typo in Existing Code

`InterirorityDepth` in `schema.py` (line 22) is misspelled -- should be
`InteriorityDepth`. Fix when modifying the module to avoid breaking existing
serialized data that uses the corrected spelling.

## 7. Open Questions

1. **Should drift limits be configurable per parameter?** The current spec uses
   a flat 15% for all numeric parameters. Some parameters (e.g.,
   `dialogue_ratio`) might warrant tighter or looser limits based on how much
   they affect perceived voice.

2. **How should `section_updates` be added to `SelfReflection`?** The current
   dataclass does not have this field. Adding it is a breaking change to the
   schema. Options: add with `field(default_factory=dict)` for backward
   compatibility, or introduce a new `SelfUpdate` model.

3. **What token budget should be the default?** The spec proposes 4000 tokens.
   This needs calibration against actual pipeline context windows and the
   relative importance of identity vs. story content vs. craft instructions.

4. **How does the fandom context population interact with the API proxy?** The
   spec assumes an AO3 API proxy exists but does not specify its interface.
   This depends on the feedback system spec.

5. **Should rejected updates be logged?** When an update is rejected for
   exceeding drift limits, should the system log what was attempted? This would
   be valuable for debugging the learning engine but adds complexity.

6. **Interaction between `pov`/`tense` freedom and consistency.** The spec
   allows `pov` and `tense` to change freely (they are story-level choices,
   not personality parameters). But should there be a "preferred" pov/tense
   that the strategy planner defaults to?

## 8. Future Considerations

### Multi-Fandom Identity

The current design assumes one fandom at a time. If the agent writes across
multiple fandoms, `fandom_context.md` becomes a directory of per-fandom files,
and `load_identity()` needs a `fandom` parameter to select the right context.
The core identity (voice priors, self.md, pen name) remains shared.

### Identity Versioning and Rollback

Currently, `version` is an incrementing integer with no rollback capability. A
future version could store identity snapshots (voice priors + self.md at each
version) to allow rolling back if a feedback cycle produces a degradation in
writing quality.

### Reader Persona Modeling

The `Reader Relationship` section of self.md is currently prose. A future
version could model the reader base as structured data (demographics, reading
preferences, engagement patterns) to inform strategy decisions.

### Identity Transfer

If the agent needs to start fresh in a new fandom under the same pen name,
which parts of identity carry over? Voice priors and pen name should transfer;
fandom context should reset; self.md History should be preserved but Growth
Areas and Current Focus should be re-evaluated.

### Collaborative Identity

If multiple agent instances write under the same pen name (e.g., one drafts,
another edits), they need a shared identity state with conflict resolution.
The current file-based persistence is not designed for concurrent access.
