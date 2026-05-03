---
name: mail
description: React to one or more new non-self AO3 comments. Updates the digest, drafts a reply via in-harness subagent, queues it on disk, files a P1 human bead so Andrew can post it. Invoked from /heartbeat row 2 when fresh mail is detected.
---

## Execution

This is an in-session skill. The orchestrator runs every step directly using Read, Write, Edit, Bash, and the Agent tool (for the reply-drafting subagent dispatch). **Do not add a Python tool that calls the Anthropic API for /mail** — the reply prose is a subagent dispatch wrapped in `wrap_for_subagent_structured`. The orchestrator is the runtime.

If you find yourself wanting to write `mail.py` that imports `anthropic`, stop. The skill is the spec.

# /mail — React to one new comment

Source of truth: spec bead **bd-49j** Section 4.2 + 3.3 (human-bead protocol). Read those before working in this skill.

Inputs (from /heartbeat invocation): `[(work_id, comment), ...]` — list of new non-self comments. Could be one, could be several from a single heartbeat scan across multiple works.

For each `(work_id, comment)` tuple, run the per-comment pipeline below.

## Per-comment pipeline

### Step 1 — Paranoid self-check

```python
from identity.handles import is_self
if is_self(comment.author):
    log(f"skipping self-authored comment from {comment.author}")
    continue
```

`get_comments(filter_self=True)` already drops these inside `api/ao3_client.py`. This is a defense-in-depth check — if a future refactor accidentally flips the default, /mail still won't draft replies to ourselves.

### Step 2 — Dedupe

```python
reply_path = Path(f"publish/replies_queue/{wid}_{comment.id}.md")
if reply_path.exists():
    log(f"reply already queued at {reply_path}; skipping")
    continue
# Also check for an existing open human bead for this (wid, comment.id):
existing = run(f"br search 'human: post reply' --json | jq '.[] | select(.external_ref | endswith(\"#comment_{comment.id}\"))'")
if existing:
    log(f"human bead already exists for comment {comment.id}; skipping")
    continue
```

Heartbeat will keep seeing the same comment until Andrew posts the reply (which causes the comment to disappear from the "new since baseline" diff). Without dedupe, every heartbeat creates another reply file and another human bead — queue spam.

### Step 3 — Update the digest

Add the comment to `feedback/{wid}_digest.json` so it counts as "seen" on the next heartbeat scan:

```python
digest_path = Path(f"feedback/{wid}_digest.json")
digest = json.loads(digest_path.read_text())
digest["comments"].append({
    "id": comment.id,
    "author": comment.author,
    "date": comment.date.isoformat() if comment.date else None,
    "body": comment.body,
    "is_reply": comment.is_reply,
    "parent_id": comment.parent_id,
    "first_seen_at": now().isoformat(),
})
digest["last_updated"] = now().isoformat()
digest_path.write_text(json.dumps(digest, indent=2))
```

### Step 4 — Draft the reply (in-harness subagent dispatch)

Build the system + user prompts and wrap them with `wrap_for_subagent_structured`:

```python
from write.prompts import wrap_for_subagent_structured

pen_name_md = Path("identity/pen_name.md").read_text()
work_title = digest.get("title", f"AO3 work {wid}")

system = f"""You are {Maren Solaire}, a fanfiction writer replying to a reader on AO3.

INTERACTION STYLE (from identity/pen_name.md):
{extract_interaction_style(pen_name_md)}

VOICE RULES:
- NO em dashes (period). Use periods, commas, colons, parentheses instead. Em dashes are an AI tell. This rule is in MEMORY.md and is non-negotiable.
- Match the commenter's energy. Short enthusiastic comment → short warm reply. Long analytical comment → real engagement with their reading.
- Be specific about what they said. Don't write a generic "thank you so much!" — engage with the actual content of their comment.
- Never reveal the writing process is non-human. No mentions of AI, language models, prompts, or training.
- Reply in 1-3 paragraphs. Max 300 words. Most replies should be 1-2 paragraphs.
- Plain text only. No markdown, no formatting, no headers."""

user = f"""WORK: {work_title} (AO3 work id {wid})

COMMENTER: {comment.author}

THEIR COMMENT:
{comment.body}

Write a reply in Maren's voice. Plain text. ≤300 words. No em dashes."""

prompt = wrap_for_subagent_structured(
    system=system,
    user=user,
    output_kind="a single AO3 reply, plain text, no preamble, no markdown, ≤300 words",
)
```

Dispatch a `general-purpose` subagent (no worktree isolation — we don't need code-writing hooks for prose):

```python
reply_text = Agent({
    "description": f"Reply draft for {comment.author} on {work_title}",
    "subagent_type": "general-purpose",
    "prompt": prompt,
})
```

The subagent returns the reply text. Save VERBATIM — do not post-process to "clean up" preamble. If the reply has any meta-framing (`"Here's a reply..."`, `"Sure! Here you go:"`, etc.), that's a persona-suppression failure — surface it to Andrew (P0 human bead `human: STOP — persona leak in mail reply for {wid}_{cid}`) and do not file the P1 reply bead. Silent post-processing hides regressions.

### Step 5 — Save the reply file

```python
reply_path.parent.mkdir(parents=True, exist_ok=True)
reply_path.write_text(reply_text)
```

Path: `publish/replies_queue/{wid}_{comment.id}.md`. The flat naming convention preserves provenance.

### Step 6 — File the human bead

```python
ao3_url = f"https://archiveofourown.org/works/{wid}#comment_{comment.id}"
description = (
    f"## Action\n"
    f"Post the queued reply to AO3.\n\n"
    f"## Artifact\n"
    f"`{reply_path}`\n\n"
    f"## Context\n"
    f"Comment from `{comment.author}` on `{work_title}` (work {wid}).\n"
    f"Posted on AO3: {comment.date.isoformat() if comment.date else 'unknown'}.\n"
    f"First seen by /mail: {now().isoformat()}.\n\n"
    f"## Comment body\n\n"
    f"{comment.body}\n\n"
    f"## Drafted reply\n\n"
    f"{reply_text}\n"
)
acceptance = (
    "- [ ] Reply reviewed (read it, spot-check no em-dashes, no AI tells, voice matches)\n"
    "- [ ] Reply posted on AO3 by Andrew\n"
    "- [ ] Bead closed by Andrew (NEVER by /mail or /heartbeat)"
)

bead_id = run([
    "br", "create",
    "-t", "human",
    "-p", "1",
    f"human: post reply — {comment.author} on {work_title}",
])
run(["br", "update", bead_id, "--description", description])
run(["br", "update", bead_id, "--acceptance-criteria", acceptance])
run(["br", "update", bead_id, "--external-ref", ao3_url])
```

`/mail` then commits the digest update + reply file + bead state in ONE commit:

```bash
br sync --flush-only
git add feedback/{wid}_digest.json publish/replies_queue/{wid}_{cid}.md .beads/issues.jsonl
git commit -m ":envelope: mail: queued reply to {comment.author} on {work_title}

Bead: {bead_id}"
```

## Anti-patterns

- ❌ **Auto-posting to AO3.** /mail NEVER posts. Replies go to `publish/replies_queue/` and the human posts. AO3 TOS forbids automation.
- ❌ **Silently stripping subagent preamble.** If the reply text starts with "Here's a draft..." or any meta-framing, that's a persona-suppression failure. Surface as P0 STOP bead. Silent post-processing hides regressions and lets future leaks through.
- ❌ **Dropping comments to the floor.** Every non-self comment must result in EITHER a reply queued (with human bead) OR an explicit "skipped because X" log line. No silent skips.
- ❌ **Calling `br close` on the human bead.** Only Andrew closes human beads. /mail creates and populates; /mail never updates status.
- ❌ **Missing dedupe on (wid, comment.id).** Heartbeat re-fires until Andrew posts, so /mail can be invoked multiple times for the same comment. Without dedupe → spam queue + duplicate human beads.
- ❌ **Modifying digest fields outside the per-comment update.** Other digest fields (`baseline_at`, `last_fetched_at`, `title`, etc.) are owned by /heartbeat and /feedback. /mail only appends to `comments[]` and updates `last_updated`.
- ❌ **Em dashes in the reply.** This rule is in MEMORY.md (`feedback_no_em_dashes`). Em dashes are AI tells. Use periods, commas, colons. If the subagent returns a reply with em dashes, log a warning, replace them with periods/commas, and proceed (this is rare; the system prompt forbids them).
- ❌ **Replies longer than 300 words.** Match the commenter's scale. A 50-word comment doesn't get a 250-word essay. Truncate or re-dispatch with stronger length guidance.

## Comment-author edge cases

| Case | Handling |
|---|---|
| Self-authored (`is_self(author)` True) | Skipped at Step 1 (defense-in-depth; should already be filtered by `api.ao3_client.get_comments`). |
| Reply to our own reply (a back-and-forth) | Treat as a normal new comment — these are real reader engagement. Filter only on author identity, not on `is_reply`. |
| Anonymous / guest commenter (no author handle) | Reply normally; the human bead title says "human: post reply — Anonymous on {work}". |
| Hostile / abusive comment | DO NOT auto-draft. Pattern-match on slurs / known abuse signals; if matched, file a P0 human bead `human: review hostile comment on {work}` with the comment body and ask Andrew to decide (block, ignore, reply manually). Default rules: this is rare for the pen-name's audience, but the guard should exist. |
| Spam / promotional | Same as hostile — P0 human bead, no auto-reply. |

For the hostile/spam cases, lean conservative: **better a false-positive that escalates to Andrew than a false-negative that auto-replies to abuse**. Andrew can override by closing the bead with `won't reply` notes.

## See also

- Spec: `br show bd-49j` (Section 4.2 pseudocode this skill implements)
- `/heartbeat` — invokes /mail (row 2 of the routing table)
- `/feedback` — separate skill for full digest establish/rebuild; /mail is the per-comment incremental path
- `identity/handles.py` — `is_self` (Step 1 + paranoid double-check)
- `identity/pen_name.md` — Interaction Style (used in Step 4 system prompt)
- `write/prompts.py` — `wrap_for_subagent_structured`
- Memory: `feedback_no_em_dashes` (the em-dash rule), `reference_pen_name_handles` (the maren_eurynome incident that earned the self-recognition discipline)
- AO3 TOS: forbids automated posting — that's why /mail queues for human review, never posts
