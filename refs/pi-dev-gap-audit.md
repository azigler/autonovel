# pi.dev Gap Audit vs Heartbeat (Epic D E2)

**Date:** 2026-05-25
**Scrutinize requirement:** "Install pi.dev on pico. Implement *one* tool: `read_state(path)` that returns `feedback/heartbeat-state.json`. Implement the agent loop with: sanity checks, sleep_until, single tool call per tick, structured JSON log line per tick. Run for 24h. Catalog what's missing vs. heartbeat SKILL.md (persona suppression? hooks? bead JSONL fast path? scheduled wakeup vs. internal sleep?). Produce `refs/pi-dev-gap-audit.md` analogous to `refs/api-vs-harness.md`."

**Pass criterion:** gap list has ≤3 items, all with named workarounds. **Fail = revisit P2 (extend heartbeat instead).**

**This audit's scope:** initial install + smoke + tool-call probe. Full 24h run deferred until prose-tier decision lands. The gap list below is from static-analysis + probe, not from 24h operation.

---

## What was installed

```bash
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
```

Version: `0.75.5` (2026-05-25). Installed on **zig** (orchestrator host), not pico (pi.dev is a client; models stay on pico via tailnet).

Config files created:
- `~/.pi/agent/models.json` — defines `pico-ollama` and `pico-mlx` custom providers with all 6 resident models
- `~/.pi/agent/settings.json` — not yet created; pi.dev runs without it

## Smoke tests

| Test | Result | Notes |
|---|---|---|
| `pi --no-tools --no-session -p "Reply PONG"` against Qwen3 Ollama | ✅ returns "PONG" | end-to-end pi.dev → pico tailnet → Ollama → Qwen3 works |
| `pi --tools read,bash -p "What's in /tmp/pi-test.txt?"` | ❌ tool NOT executed | Qwen3 emitted `<function=read><parameter=path>/tmp/pi-test.txt</parameter></function>` as text; pi.dev did NOT intercept; `toolResults: []` |
| `pi --mode json` same probe | ❌ same result; JSON stream confirms zero tool_use events | input_tokens=1023 suggests pi.dev DID inject some tool-context preamble, but not via the OpenAI tools schema parameter |

---

## Gap analysis vs heartbeat (`~/.claude/skills/heartbeat/SKILL.md`)

| Heartbeat capability | pi.dev equivalent | Gap severity | Workaround |
|---|---|---|---|
| **Session JSONL persistence** | ✅ Native — `~/.pi/agent/sessions/<cwd>/<id>.jsonl` with parent/child branching | none | n/a |
| **Halt gates (stop file, P0 bead, error budget, identity drift, git drift)** | ⚠️ Partial — extensions can implement via hooks; nothing built-in | **MEDIUM** | Write a pi.dev extension that runs the 5 gates pre-turn; abort if any trips |
| **Tool-use against local Ollama models** | ❌ **BROKEN for openai-completions API path** | **HIGH** | (a) Switch to `anthropic-messages` API and route via CCR which knows how to inject OpenAI tools schema, OR (b) write a pi.dev extension that registers tools via prompt-based protocol (XML `<function=...>`) and parses model output to execute, OR (c) fix upstream pi.dev to inject `tools: [...]` parameter on openai-completions calls |
| **Tools: read/write/edit/bash/grep/find/ls** | ✅ Native (if tool-use works at all — see above) | none if HIGH gap is fixed | n/a |
| **Persona suppression (`wrap_for_subagent`)** | ✅ Native via `--system-prompt` / `--append-system-prompt` flags | none | n/a |
| **MCP servers** | ⚠️ Not mentioned in docs | **LOW** | Extensions can wrap MCP if needed |
| **Hooks (PostToolUse, PreToolUse, SessionStart)** | ✅ Native via extension API: `pi.on("tool_call", ...)` | none | n/a |
| **Skills (Agent Skills standard)** | ✅ Native — `~/.pi/agent/skills/` | none | n/a |
| **Bead JSONL fast path (`br create/update/close` integration)** | ⚠️ Nothing built-in | **LOW** | Trivial extension or just shell out from a tool |
| **ScheduleWakeup (heartbeat's launchd-driven re-entry)** | ⚠️ **No built-in scheduler** — pi.dev runs only when invoked | **MEDIUM** | Use systemd timer or launchd plist to invoke `pi -c` (continue session) on a cadence. Mirrors how autonovel's heartbeat is actually triggered (cron-spawned) |
| **`Skill` invocation from skill body** | ⚠️ Skills can use `/skill:name` syntax; nesting depth unclear | **LOW** | Probe further; likely fine |
| **`Agent` tool (subagent dispatch)** | ❌ **No analog** — pi.dev's agent model is single-agent with extensions, not orchestrator+subagent | **HIGH** | (a) Spawn a child `pi` process per subagent dispatch via Bash tool, (b) write a "subagent" extension that wraps `pi --no-session -p "..."` and returns the result, (c) re-architect autonovel to not need subagents (the orchestrator IS the agent) |
| **Cost-tracking JSON usage emission** | ✅ Native — `usage: {input, output, cacheRead, cacheWrite, totalTokens, cost: {...}}` in every message | none | n/a — pi.dev's cost tracking is BETTER than Claude Code's manual ledger |
| **Settings.json `env` block (env var injection)** | ⚠️ Not mentioned | **LOW** | Pi inherits orchestrator shell env directly |
| **Token caching / KV-cache reuse across turns** | ✅ `cacheRead, cacheWrite` fields are reported in usage; suggests built-in or planned support | none | n/a |

### Gap count
- **HIGH:** 2 (tool-use broken for Ollama-served models; no subagent dispatch analog)
- **MEDIUM:** 2 (no built-in halt gates; no built-in scheduler)
- **LOW:** 4 (MCP / bead integration / skill nesting / env injection — all easy)

**Pass criterion was ≤3 gaps with workarounds. Result: 2 HIGH gaps. The HIGH gaps have workarounds but both require non-trivial engineering.**

---

## Implications for Epic D

### The good
- pi.dev's session model, hook system, skill system, and cost-tracking are GOOD — better than autonovel's current "Skill invocation from /write" pattern in some dimensions (e.g., native usage emission).
- The pi.dev concept (long-running daemon with built-in tool-calling and state) is sound.
- Persona suppression via `--system-prompt` covers `wrap_for_subagent` cleanly.

### The bad
- **Tool-use against local Ollama via the openai-completions path is broken.** This is the load-bearing capability for D's `write_run` (which makes tool calls for evaluate_slop, prepare_ao3_package, etc.). If we can't get structured tool calls from local Qwen3 *through pi.dev's tool layer*, the entire E2 thesis is shaky.
- **No subagent dispatch analog.** Autonovel currently uses Claude Code's `Agent` tool for sub-task spinoffs (per `~/explore/autonovel/CLAUDE.md`). pi.dev's "extensions can shell out" workaround is real but adds complexity.

### Recommended next steps (per scrutinize threshold)
- **Gap count > 3** → **fail criterion triggered** → P2 pivot becomes the lower-risk path:
  - **P2 alternative:** create `write/local_api.py` that calls Qwen3 Ollama directly via HTTP (we have empirical evidence Qwen3 Ollama produces structured tool_calls when called via the standard OpenAI API — see GUARDRAILS G9 in `~/dotfiles/local-models/`). Wire from `write/loop.py` (or wherever the orchestrator's `/write` Skill currently calls subagent). Keep Claude Code as orchestrator; only the prose-generation step routes local.
  - **Revised P2 estimate:** 1-2 weeks (updated from scrutinize's "1 week" — write/api.py was removed during bd-75p migration, so this is a re-creation, not extension)
- **P1 alternative (continue with pi.dev):** invest 2-4 weeks fixing pi.dev tool-use for Ollama + building subagent extension. This is the explore-7hh "productize pi.dev concept" work.

**My (orchestrator) recommendation pending user blind-rate:** if Pane D from `/tmp/d-e1-blind-rate-v3.md` (Qwen3 Ollama prose) lands well, go P2. The prose tier is the load-bearing question, not the harness. Pi.dev productization (explore-7hh) is a separate, longer-horizon arc.

---

## CCR-path confirmation probe (2026-05-25 follow-up)

Same probe routed through CCR's anthropic-messages endpoint instead of direct Ollama. Added `via-ccr-anthropic` provider to pi.dev's `models.json` pointing at `http://127.0.0.1:3456`, model `pico-ollama,qwen3-coder:30b`. Result: **same failure mode** — Qwen3 emitted `<function=read>` text, pi.dev did NOT intercept, no tool execution.

**However, this gap is more nuanced than first reported (research-agent + reproduction 2026-05-25 evening):**

A research agent intercepted pi.dev's actual wire payload via a logging HTTP proxy and confirmed:
- pi.dev's openai-completions adapter DOES inject a well-formed `tools: [{type:"function", function:{name:"read", parameters:{...}}}]` array
- Source verified: `~/.../node_modules/@earendil-works/pi-ai/dist/providers/openai-completions.js:421-435`
- Pi.dev has a harmony-text recovery path that CAN parse `<function=...>` XML and execute (per agent's packet capture in some scenarios)

Empirical reproduction (2026-05-25 evening): direct curl to BOTH `/v1/chat/completions` AND `/api/chat` with same tools schema → Qwen3 Ollama returns 2 structured `tool_calls[]` ✅. But pi.dev's request to the same Qwen3 → XML text, no execution.

**Working hypothesis on the gap:** pi.dev's request differs from direct curl in some way (probably system prompt context, message wrapping, or tool-name shape — pi.dev uses bare `read` while direct curl uses `read_file`). Qwen3 Ollama's structured-tool-call path may be context-sensitive — it falls back to harmony XML for ambiguous prompts. Pi.dev's harmony-recovery path is present but unreliable.

**Severity remains HIGH for D's purposes**: even if all the components are theoretically present, the integration is empirically flaky for custom-provider tool-use. Building an agent on top of "sometimes works" isn't viable. Workarounds:

1. **Build a 30-line pi.dev extension** that wraps the openai-completions adapter and forces structured tool-call parsing (uses ExtensionAPI hook `before_provider_request`)
2. **Use MLX backend instead of Ollama for tool-use** (research agent's recommendation; MLX server's Qwen-shaped parser path may be more reliable)
3. **Don't use pi.dev for tool-heavy work**; reserve for prose-only workloads (the working part)
4. **Wait for pi.dev refactor freeze to end** (2026-05-17+); upstream issues #4439, #3976, #4625 all relate to this; PRs were closed unmerged but may be revisited post-refactor

## Probes deferred to follow-up

- **Inspect pi.dev source** to confirm whether tools schema is intentionally omitted for custom providers or whether the integration is buggy. If buggy, file an issue / PR upstream.
- **Extension that wraps the HTTP layer** and injects `tools: [...]` parameter manually.
- **24h run** as scrutinize originally specified: deferred until tool-use gap is resolved.
- **Stdio RPC mode:** `pi --mode rpc` exposes a JSON-RPC interface for programmatic use. Worth a probe for the autonovel orchestrator integration pattern.

---

## Cross-references

- `~/dotfiles/local-models/GUARDRAILS.md` — tool-use rules (G9, G13, G1)
- `~/explore/refs/cross-epic-overlap-2026-05-25.md` — D depends on this audit; explore-7hh productization arc captures pi.dev plugin needs
- `~/.claude/skills/heartbeat/SKILL.md` — canonical pattern being compared against
- `~/explore/autonovel/CLAUDE.md` — current autonovel architecture
- Bead: `bd-b5p.1` — D's spec (this audit appended to --notes)
