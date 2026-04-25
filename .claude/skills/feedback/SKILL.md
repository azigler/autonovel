---
name: feedback
description: Collect and parse reader feedback from AO3 for a published work
argument-hint: "[work-id or url]"
---

## Execution

This is an in-session skill. The orchestrator runs every step directly using Read, Write, Edit, and Bash tools. **Do not add a Python tool or call the Anthropic API for /feedback** — that defeats the harness's whole point. AO3 reads go through `api/ao3_client.py` (httpx, not anthropic) and that's fine; the skill itself — synthesizing the digest, parsing comments into structured feedback — is in-session reasoning over files the orchestrator already has open.

If you find yourself wanting to write `feedback.py` that imports `anthropic`, stop. The skill is the spec; the orchestrator is the runtime.

# /feedback - Collect Reader Feedback

Scrape AO3 metrics and parse comments for a published work. Generate a feedback
digest that feeds into `/learn`.

## Prerequisites
- Work is published on AO3
- AO3 credentials in `.env`
- API proxy running (or use direct ao3-api)

## Process

1. **Fetch metrics:**
   ```
   GET /works/{work_id}/stats
   ```
   Kudos, hits, bookmarks, subscriptions, comment_count.

2. **Fetch comments:**
   ```
   GET /works/{work_id}/comments
   ```

3. **Parse comments:**
   For each comment, extract:
   - Sentiment (positive, constructive, negative)
   - Quoted passages (what lines readers highlighted)
   - Specific feedback (characterization, pacing, voice, plot)
   - Which character they're responding to

4. **Generate feedback digest:**
   ```
   What worked: [passages that got quoted, positive themes]
   What didn't: [constructive criticism, confusion points]
   Characterization: [did readers feel characters were in-character?]
   Voice: [did anyone comment on prose style, good or bad?]
   Engagement: [kudos/hit ratio, bookmark rate, subscription rate]
   ```

5. **Update experiment bead:**
   ```bash
   br update {bead-id} -d "Feedback collected.
   Kudos: X, Hits: Y, Comments: Z
   Key feedback: [summary]"
   ```

## Output
- Feedback digest saved to `feedback/{work_id}_digest.json`
- Experiment bead updated with metrics
- Ready for `/learn`
