# autonovel -- Agentic Fanfiction Author

An autonomous agent that writes fanfiction under a pen name, publishes on AO3,
collects reader feedback, and learns from it. The agent develops its own voice,
taste, and creative identity through real interaction with real readers.

**The goal is not "write a novel." The goal is "become an author."** An author has
voice, taste, a relationship with readers, and a reputation that evolves over time.
The agent must develop all of these -- and it must never look like AI writing, or
the fanbase will turn on it.

Built on top of [autonovel](https://github.com/erhnysr/autonovel), an autonomous
novel-writing pipeline (27 Python tools for drafting, evaluation, revision,
typesetting, and audiobook generation). The writing engine provides the foundation;
the agentic layer adds identity, publishing, feedback, and learning.

---

## Architecture

The agent runs a continuous loop:

```
identity --> write --> publish --> feedback --> learn
    ^                                           |
    +-------------------------------------------+
```

1. **Identity** (`identity/`) -- The agent's creative self. A `self.md` document
   that evolves after each feedback cycle, quantified voice priors, pen name,
   and literary inspirations.

2. **Write** (`write/`) -- A state machine that takes a story brief from idea to
   publication-ready draft. States: BRIEF, CONTEXT, DRAFT, EVALUATE, REVISE,
   PREPARE, QUEUE, DONE. Uses the autonovel engine for drafting and evaluation,
   with anti-slop and anti-pattern detection to avoid AI tells.

3. **Publish** -- The write loop prepares AO3-formatted output (tags, summary,
   author's notes) and queues it for human review. A human posts manually --
   AO3 TOS prohibits automated posting, and human review is a quality gate.

4. **Feedback** -- Metrics collection from AO3: kudos, bookmarks, hits,
   subscriptions, comments. The API proxy (`api/`) provides a local REST
   interface that decouples agent code from AO3 scraping.

5. **Learn** -- The agent updates its identity based on what readers responded to.
   Prompt evolution, few-shot bank curation, evaluation weight adjustment, and
   self-reflection entries in `self.md`.

---

## File Structure

```
# --- agentic author ---
api/                 -- Local AO3 API proxy (FastAPI, mock mode available)
identity/            -- Creative identity: self.md, voice priors, pen name
write/               -- Write loop state machine, briefs, evaluation, revision
specs/               -- Authoritative technical specifications (see below)
tests/               -- Test suite

# --- autonovel engine (writing foundation) ---
*.py                 -- 27 Python tools (drafting, evaluation, revision, etc.)
CRAFT.md             -- Narrative craft frameworks (plot, character, world, prose)
ANTI-SLOP.md         -- Word-level AI tell detection
ANTI-PATTERNS.md     -- Structural AI pattern detection
voice.md             -- Voice guardrails template
program.md           -- Agent instructions per pipeline phase
PIPELINE.md          -- Full pipeline specification
WORKFLOW.md          -- Step-by-step human guide
typeset/             -- LaTeX typesetting and ePub generation

# --- configuration ---
.env.example         -- API keys
pyproject.toml       -- Python dependencies (managed by uv)
```

---

## Specifications

Three specs serve as the authoritative technical documentation:

| Spec | What it covers |
|------|---------------|
| [specs/identity.md](specs/identity.md) | Identity system: self.md schema, voice priors, drift limiting, feedback digests |
| [specs/write-loop.md](specs/write-loop.md) | Write loop state machine: states, transitions, evaluation gates, revision cycles |
| [specs/api-proxy.md](specs/api-proxy.md) | AO3 API proxy: endpoints, publish queue, mock mode, metrics collection |

For the underlying writing engine, see [PIPELINE.md](PIPELINE.md) and
[WORKFLOW.md](WORKFLOW.md).

---

## Quick Start

```bash
# Clone and install
git clone <repo-url> && cd autonovel
cp .env.example .env    # Add your API keys (see below)
uv sync

# Start the AO3 API proxy (mock mode -- no real AO3 requests)
uv run python -m api.server --mock

# Start in real mode (requires AO3 credentials in .env)
uv run python -m api.server

# Run the write loop (programmatic -- see write/loop.py)
# Create a StoryBrief, then call write.loop.run(brief)
```

The API proxy runs at `http://127.0.0.1:8000` and provides endpoints for
browsing fandoms, reading metrics, fetching comments, and queuing works for
human review. See [specs/api-proxy.md](specs/api-proxy.md) for the full
endpoint reference.

---

## API Keys

| Service | Environment Variable | Used for |
|---------|---------------------|----------|
| Anthropic | `ANTHROPIC_API_KEY` | Writing, evaluation, revision (Sonnet + Opus) |
| AO3 | `AO3_USERNAME`, `AO3_PASSWORD` | Metrics scraping via unofficial API |
| fal.ai | `FAL_KEY` | Cover art generation (optional) |
| ElevenLabs | `ELEVENLABS_API_KEY` | Audiobook generation (optional) |

Only `ANTHROPIC_API_KEY` is required for the core write loop. AO3 credentials
are needed for live metrics collection (the API proxy can run in mock mode
without them). Art and audiobook keys are for the autonovel engine's export
pipeline and are optional.

---

## One-Way Doors

This project has irreversible decisions. Unlike autonovel's keep/discard loop,
published work cannot be unpublished without consequences. Readers remember.
Reputation accumulates.

Decisions that must be gotten right:

- **Pen name** -- permanent identity, chosen once
- **First fandom** -- sets initial audience expectations
- **First published work** -- the first impression
- **Voice and style** -- readers bond with consistency; sudden shifts lose trust
- **Posting frequency** -- sets reader expectations
- **Author's note voice** -- part of the persona

Mitigation: a human reviews every publication before posting. Early works are
lower-stakes one-shots to calibrate before committing to multi-chapter series.

---

## Critical Constraints

1. **Anti-AI detection is the top priority.** If readers suspect AI, the project
   is dead. Every piece of writing passes mechanical slop detection (ANTI-SLOP.md,
   ANTI-PATTERNS.md) and must read as human-written.

2. **Human-in-the-loop for publishing.** The agent prepares, the human posts.
   This respects AO3 TOS and serves as a quality gate.

3. **The agent learns from real readers, not from itself.** Self-evaluation is a
   bootstrap. The real gradient comes from AO3 engagement metrics and comments.

---

## How It Connects to autonovel

The autonovel pipeline (27 Python scripts for novel generation) provides the
writing engine: drafting, evaluation, revision, anti-slop detection, voice
fingerprinting, and craft frameworks. The agentic layer wraps this engine with
identity, publishing, feedback collection, and learning -- turning a one-shot
novel pipeline into a continuously improving author.

For the engine internals, see [PIPELINE.md](PIPELINE.md) and the tool table in
[WORKFLOW.md](WORKFLOW.md).

---

## Production History (autonovel)

The writing engine produced its first novel, *The Second Son of the House of
Bells* (19 chapters, 79,456 words), through 6 automated revision cycles and
6 Opus review rounds. See the `autonovel/bells` branch.

---

## Inspiration

- [karpathy/autoresearch](https://github.com/karpathy/autoresearch) -- the autonomous research loop that inspired autonovel
- Brandon Sanderson's writing lectures (Laws of Magic, character sliders)
- K.M. Weiland's *Creating Character Arcs*
- Blake Snyder's *Save the Cat*
- Ursula K. Le Guin's "From Elfland to Poughkeepsie"
- [slop-forensics](https://github.com/sam-paech/slop-forensics) and [EQ-Bench Slop Score](https://eqbench.com/slop-score.html)
