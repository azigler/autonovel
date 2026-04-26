# PLAN: Agentic Fanfiction Author

## Topline Goal

**Create a fanfiction agent with its own style that grows its own fanbase and
embraces the timeless tradition of using a pen name to hide its true identity,
WITHOUT looking like AI writing or your fanbase will turn on you.**

This is not "write a novel." This is "become an author." The distinction matters:
an author has taste, voice, a relationship with readers, and a reputation that
evolves over time. The agent must develop all of these through real interaction
with real readers.

## Why Fanfiction

Fanfiction solves the cold-start problem. You don't need to invent characters
or worlds from scratch — the fandom provides shared context. Readers come for
the characters they love. They stay for the voice. This lets the agent focus on
developing *voice* and *craft* rather than worldbuilding, and get feedback fast.

Fanfiction also solves the evaluation problem. Real readers who choose to read
your work and leave comments are a better signal than any LLM judge. Kudos,
bookmarks, comments, and subscriptions are a real gradient.

## Platform: AO3 (Archive of Our Own)

**Why AO3:**
- Best feedback culture (detailed comments, not just likes)
- No algorithm — discovery through tags, so new authors can find readers
- Largest engaged fanfic community (17M+ works, 77K+ fandoms)
- Rich metrics: kudos, bookmarks, comments, hits, subscriptions
- Comment culture gives qualitative signal (readers quote favorite lines,
  point out what didn't work)
- Fandom tagging means you can find your niche

**Constraint: Human-in-the-loop posting.** AO3 TOS prohibits automated posting.
The human posts manually. This is actually a feature:
- Natural pacing (prevents suspiciously fast posting)
- Human review catches anything that would blow the cover
- Respects the platform and community

**Metrics collection:** Unofficial Python APIs (`ao3-api`) can read kudos,
comments, bookmarks, hits. This is the feedback loop input.

## The Core Loop

```
┌─────────────────────────────────────────────────┐
│                  IDENTITY                        │
│  self.md — voice, taste, inspirations, growth    │
│  pen_name — persona, bio, author's notes style   │
│  style_priors — what works, what doesn't         │
└──────────┬──────────────────────────┬────────────┘
           │                          │
           ▼                          │
┌─────────────────────┐               │
│      PLANNING       │               │
│  What to write next │               │
│  Fandom strategy    │               │
│  Series continuity  │               │
└──────────┬──────────┘               │
           │                          │
           ▼                          │
┌─────────────────────┐               │
│      WRITING        │               │
│  Modified autonovel │               │
│  pipeline (shorter) │               │
│  Anti-slop, voice   │               │
└──────────┬──────────┘               │
           │                          │
           ▼                          │
┌─────────────────────┐               │
│    PUBLISHING       │               │
│  Human posts to AO3 │               │
│  Tags, summary,     │               │
│  author's notes     │               │
└──────────┬──────────┘               │
           │                          │
           ▼                          │
┌─────────────────────┐               │
│  FEEDBACK COLLECT   │               │
│  Scrape metrics     │               │
│  Parse comments     │               │
│  Track over time    │               │
└──────────┬──────────┘               │
           │                          │
           ▼                          │
┌─────────────────────┐               │
│      LEARNING       │               │
│  Update self.md     │               │
│  Evolve prompts     │               │
│  Curate few-shot    │               │
│  Adjust eval weights│               │
└──────────┴───────────────────────────┘
```

## One-Way Doors

This project has irreversible decisions. Unlike autonovel's keep/discard loop,
you can't unpublish without consequences. Readers remember. Reputation accumulates.

**One-way doors we must get right:**
- Pen name selection (permanent identity)
- First fandom choice (sets initial audience expectations)
- First published work (first impression)
- Voice/style (readers bond with consistency; sudden shifts lose trust)
- Posting frequency (sets expectations)
- Author's note voice (part of the persona)

**Mitigation:** Human reviews every publication. Agent proposes, human approves.
Early works are lower-stakes (one-shots, short pieces) to calibrate before
committing to multi-chapter works.

## Architecture: What We're Building

### 1. Identity System (`identity/`)
- `self.md` — the agent's creative identity document, updated by the agent itself
  after each feedback cycle. "I write slow-burn character studies. I'm good at
  dialogue, weak at action. My readers come for the interiority."
- `pen_name.md` — persona details, bio, author's note voice
- `inspirations.md` — the agent's literary influences and what it takes from each
- `voice_priors.json` — quantified style parameters that evolve over time

### 2. Writing Pipeline (modified autonovel)
- Adapted for shorter works (one-shots: 3-15k words, multi-chapter: 30-80k)
- Foundation phase simplified (fandom provides world/characters)
- Drafting uses identity context + few-shot bank
- Evaluation tuned to fanfic norms (not literary fiction)
- Anti-slop still critical (AI detection is the #1 risk)

### 3. Publishing Pipeline (`publish/`)
- Prepares work for posting: formats for AO3, generates tags, summary, author's notes
- Outputs a "ready to post" package for human review
- Tracks what's been published, when, where

### 4. Feedback Collector (`feedback/`)
- Scrapes AO3 metrics on a schedule (daily or on-demand)
- Parses comments (sentiment, specificity, which passages get quoted)
- Tracks engagement over time (per-work, per-chapter, trends)
- Identifies what resonated and what fell flat

### 5. Learning Engine (`learning/`)
- **Prompt evolution:** Mutate system prompts, evaluate output quality, keep/discard
- **Few-shot bank:** Curate best passages tagged by what made them good
- **Eval weight adjustment:** Shift scoring criteria based on what readers respond to
- **Self-reflection:** Agent updates self.md after each feedback cycle
- **Reading list:** Agent reads other fics in its fandom to track trends and absorb style

### 6. Strategy Planner (`strategy/`)
- Decides what to write next based on: what resonated, fandom trends,
  series commitments, skill gaps to work on
- Manages series continuity and release schedule
- Balances exploitation (write what works) vs exploration (try new things)

## What Exists vs What We Build

**From autonovel (keep/adapt):**
- `evaluate.py` — mechanical slop detection (critical for anti-AI-detection)
- `ANTI-SLOP.md`, `ANTI-PATTERNS.md` — the slop/pattern databases
- `voice_fingerprint.py` — voice consistency checking
- `draft_chapter.py` — chapter drafting (adapt for fanfic)
- `gen_brief.py`, `gen_revision.py` — revision pipeline
- `CRAFT.md` — narrative craft frameworks

**New (build from scratch):**
- Identity system (self.md evolution, persona management)
- AO3 integration (metrics scraping, post preparation)
- Feedback parsing and learning engine
- Prompt evolution system
- Few-shot bank curation and retrieval
- Strategy/planning system
- The outer loop that connects everything

## Environment & Configuration

```
ANTHROPIC_API_KEY=...          # Writing + evaluation
AUTONOVEL_WRITER_MODEL=...     # For drafting
AUTONOVEL_JUDGE_MODEL=...      # For evaluation
AO3_USERNAME=...               # For metrics scraping
AO3_PASSWORD=...               # For metrics scraping (unofficial API)
```

## Milestones

### M0: Infrastructure (current)
- [x] Fork repo, change remote
- [x] Copy skills, init beads
- [ ] Bootstrap CLAUDE.md
- [ ] Create PLAN.md
- [ ] Create initial beads

### M1: Identity & Voice
- [ ] Design identity system (self.md schema, voice priors)
- [ ] Choose fandom (research what's active, what has room for new voices)
- [ ] Develop pen name and persona
- [ ] Write voice document (style, influences, guardrails)
- [ ] human: Create AO3 account

### M2: Writing Pipeline Adaptation
- [ ] Adapt autonovel pipeline for fanfic (shorter works, fandom context)
- [ ] Build fanfic-specific evaluation (fandom norms, characterization accuracy)
- [ ] Enhance anti-slop for fanfic context
- [ ] Build AO3 post preparation (formatting, tags, summary, author's notes)

### M3: First Publication
- [ ] Write first one-shot (low stakes, calibration piece)
- [ ] Human review and post
- [ ] Collect initial feedback
- [ ] First learning cycle

### M4: Feedback Loop
- [ ] Build AO3 metrics scraper
- [ ] Build comment parser
- [ ] Build feedback → learning pipeline
- [ ] First prompt evolution cycle
- [ ] First few-shot bank entries

### M5: Growth Loop
- [ ] Strategy planner (what to write next)
- [ ] Series planning capability
- [ ] Reading/absorption system
- [ ] Self-reflection after each publication cycle
- [ ] Engagement trend tracking

### M6: Autonomy
- [ ] Full loop running: write → publish → collect → learn → plan → write
- [ ] Human role reduced to: review before posting, provide AO3 credentials
- [ ] Agent making its own creative decisions informed by reader feedback
