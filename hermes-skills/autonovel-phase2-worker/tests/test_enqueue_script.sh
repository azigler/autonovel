#!/usr/bin/env bash
# Tests for the cron-fired enqueue wrapper at
# `~/.hermes/scripts/enqueue-autonovel-phase2.sh` (spec §4.2).
#
# Covers spec test cases T-K-1, T-K-2 (operational sanity), T-K-9,
# T-K-16 (smoke), T-K-17 (idempotency).
#
# Discipline: NO Hermes-side state mutation — uses a stub `hermes`
# binary that records its argv to a tempfile rather than enqueuing a
# real kanban card. The stub validates the wrapper's contract without
# polluting the host's kanban board.
#
# Bead: bd-b5p.7.2 · Parent spec: bd-b5p.7 · OQ walk: bd-b5p.7.1
#
# Run: bash test_enqueue_script.sh
# Exit 0 = all tests pass; non-zero = failure (the first failing line).

set -uo pipefail

# ---------------------------------------------------------------------------
# Constants pulled from spec
# ---------------------------------------------------------------------------

ENQUEUE_SCRIPT="/home/ubuntu/.hermes/scripts/enqueue-autonovel-phase2.sh"
EXPECTED_WORKSPACE="dir:/home/ubuntu/explore/autonovel"
EXPECTED_SKILL="autonovel-phase2-worker"
EXPECTED_ASSIGNEE="autonovel-writer"
EXPECTED_MAX_RUNTIME="30m"
TODAY_UTC=$(date -u +%F)
EXPECTED_IDEMPOTENCY_KEY="autonovel-phase2-${TODAY_UTC}"

# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------

FAILED=0
PASSED=0
TOTAL=0

pass() {
  PASSED=$((PASSED + 1))
  TOTAL=$((TOTAL + 1))
  echo "PASS: $1"
}

fail() {
  FAILED=$((FAILED + 1))
  TOTAL=$((TOTAL + 1))
  echo "FAIL: $1"
}

skip() {
  TOTAL=$((TOTAL + 1))
  echo "SKIP: $1"
}

# Set up a tempdir with a stub `hermes` binary on PATH that records args
setup_stub_hermes() {
  STUB_DIR=$(mktemp -d)
  STUB_LOG="$STUB_DIR/hermes-invocation.log"
  cat > "$STUB_DIR/hermes" <<'STUB_EOF'
#!/usr/bin/env bash
# Stub that records its argv (one arg per line) to $STUB_LOG and
# returns a fake `hermes kanban create` JSON line so the wrapper's
# stdout-piping path also exercises the JSON-line return contract.
printf '%s\n' "$@" >> "$STUB_LOG"
# Emit a fake `kanban create` JSON line — the wrapper's stdout
# should pass this through verbatim (cron --deliver local picks it
# up). Use a fixed task id so idempotency tests can compare.
echo '{"task_id": "t_deadbeefcafef00d", "status": "ready", "idempotent_hit": false}'
STUB_EOF
  chmod +x "$STUB_DIR/hermes"
  export PATH="$STUB_DIR:$PATH"
  export STUB_LOG
}

teardown_stub_hermes() {
  rm -rf "$STUB_DIR"
}

# ---------------------------------------------------------------------------
# T-1: script file exists (correct TDD: will fail until /impl wave)
# ---------------------------------------------------------------------------

if [[ -f "$ENQUEUE_SCRIPT" ]]; then
  pass "T-1: enqueue script exists at $ENQUEUE_SCRIPT"
else
  fail "T-1: enqueue script missing at $ENQUEUE_SCRIPT (correct TDD failure until /impl wave creates it)"
fi

# ---------------------------------------------------------------------------
# T-2: script is executable
# ---------------------------------------------------------------------------

if [[ -x "$ENQUEUE_SCRIPT" ]]; then
  pass "T-2: enqueue script is executable"
else
  fail "T-2: enqueue script is NOT executable (must be chmod +x per spec §4.2)"
fi

# ---------------------------------------------------------------------------
# T-3: script syntax is valid bash
# ---------------------------------------------------------------------------

if [[ -f "$ENQUEUE_SCRIPT" ]]; then
  if bash -n "$ENQUEUE_SCRIPT" 2>/dev/null; then
    pass "T-3: enqueue script bash syntax is valid"
  else
    fail "T-3: enqueue script has bash syntax errors"
  fi
else
  skip "T-3: script missing (covered by T-1 failure)"
fi

# ---------------------------------------------------------------------------
# T-4: script uses `set -euo pipefail` (or similar safety preamble)
# ---------------------------------------------------------------------------

if [[ -f "$ENQUEUE_SCRIPT" ]]; then
  if grep -qE '^\s*set\s+-[eu]+o?\s*' "$ENQUEUE_SCRIPT" 2>/dev/null || \
     grep -q 'set -euo pipefail' "$ENQUEUE_SCRIPT" 2>/dev/null; then
    pass "T-4: enqueue script uses set -e (safety preamble)"
  else
    fail "T-4: enqueue script must use `set -e` (or set -euo pipefail) — silent error swallowing breaks cron observability"
  fi
else
  skip "T-4: script missing (covered by T-1 failure)"
fi

# ---------------------------------------------------------------------------
# T-K-1 (a-e): wrapper invokes `kanban create` with the right flags
# Exercise via stub hermes to capture argv.
# ---------------------------------------------------------------------------

if [[ -f "$ENQUEUE_SCRIPT" ]]; then
  setup_stub_hermes
  # Run the script — stub records args to $STUB_LOG
  # We tolerate non-zero exit (stub may exit 0; script may set -e).
  bash "$ENQUEUE_SCRIPT" > /dev/null 2>&1 || true

  if [[ -f "$STUB_LOG" ]]; then
    SCRIPT_ARGS=$(cat "$STUB_LOG")

    # T-K-1a: `kanban create` subcommand
    if echo "$SCRIPT_ARGS" | grep -qE '^kanban$'; then
      if echo "$SCRIPT_ARGS" | grep -qE '^create$'; then
        pass "T-K-1a: hermes kanban create invoked"
      else
        fail "T-K-1a: 'create' subcommand not found in args"
      fi
    else
      fail "T-K-1a: 'kanban' subcommand not found in args"
    fi

    # T-K-1b: --skill autonovel-phase2-worker
    if grep -qE "^--skill$" "$STUB_LOG"; then
      # Check the line AFTER --skill matches expected
      NEXT_SKILL=$(awk '/^--skill$/{getline; print; exit}' "$STUB_LOG")
      if [[ "$NEXT_SKILL" == "$EXPECTED_SKILL" ]]; then
        pass "T-K-1b: --skill $EXPECTED_SKILL"
      else
        fail "T-K-1b: --skill value mismatch (got '$NEXT_SKILL', want '$EXPECTED_SKILL')"
      fi
    else
      fail "T-K-1b: --skill flag missing"
    fi

    # T-K-1c: --workspace dir:/home/ubuntu/explore/autonovel
    if grep -qE "^--workspace$" "$STUB_LOG"; then
      NEXT_WS=$(awk '/^--workspace$/{getline; print; exit}' "$STUB_LOG")
      if [[ "$NEXT_WS" == "$EXPECTED_WORKSPACE" ]]; then
        pass "T-K-1c: --workspace $EXPECTED_WORKSPACE"
      else
        fail "T-K-1c: --workspace value mismatch (got '$NEXT_WS', want '$EXPECTED_WORKSPACE')"
      fi
    else
      fail "T-K-1c: --workspace flag missing"
    fi

    # T-K-1d: --max-runtime 30m
    if grep -qE "^--max-runtime$" "$STUB_LOG"; then
      NEXT_RT=$(awk '/^--max-runtime$/{getline; print; exit}' "$STUB_LOG")
      if [[ "$NEXT_RT" == "$EXPECTED_MAX_RUNTIME" ]]; then
        pass "T-K-1d: --max-runtime $EXPECTED_MAX_RUNTIME"
      else
        fail "T-K-1d: --max-runtime value mismatch (got '$NEXT_RT', want '$EXPECTED_MAX_RUNTIME')"
      fi
    else
      fail "T-K-1d: --max-runtime flag missing"
    fi

    # T-K-1e: --idempotency-key autonovel-phase2-<today UTC>
    if grep -qE "^--idempotency-key$" "$STUB_LOG"; then
      NEXT_IDEM=$(awk '/^--idempotency-key$/{getline; print; exit}' "$STUB_LOG")
      if [[ "$NEXT_IDEM" == "$EXPECTED_IDEMPOTENCY_KEY" ]]; then
        pass "T-K-1e: --idempotency-key $EXPECTED_IDEMPOTENCY_KEY"
      else
        fail "T-K-1e: --idempotency-key value mismatch (got '$NEXT_IDEM', want '$EXPECTED_IDEMPOTENCY_KEY')"
      fi
    else
      fail "T-K-1e: --idempotency-key flag missing"
    fi

    # T-K-1f: --assignee autonovel-writer (board label per OQ-K-5)
    if grep -qE "^--assignee$" "$STUB_LOG"; then
      NEXT_ASSIGN=$(awk '/^--assignee$/{getline; print; exit}' "$STUB_LOG")
      if [[ "$NEXT_ASSIGN" == "$EXPECTED_ASSIGNEE" ]]; then
        pass "T-K-1f: --assignee $EXPECTED_ASSIGNEE"
      else
        fail "T-K-1f: --assignee value mismatch (got '$NEXT_ASSIGN', want '$EXPECTED_ASSIGNEE')"
      fi
    else
      fail "T-K-1f: --assignee flag missing"
    fi

  else
    fail "T-K-1: stub hermes never invoked (script ran without calling hermes)"
  fi

  teardown_stub_hermes
else
  skip "T-K-1: script missing (covered by T-1 failure)"
fi

# ---------------------------------------------------------------------------
# T-K-9 / T-K-17: idempotency — re-running same script same day uses same key
# ---------------------------------------------------------------------------

if [[ -f "$ENQUEUE_SCRIPT" ]]; then
  setup_stub_hermes
  bash "$ENQUEUE_SCRIPT" > /dev/null 2>&1 || true
  bash "$ENQUEUE_SCRIPT" > /dev/null 2>&1 || true

  # Both invocations should have used the SAME idempotency key
  IDEM_KEYS=$(awk '/^--idempotency-key$/{getline; print}' "$STUB_LOG" | sort -u)
  KEY_COUNT=$(echo "$IDEM_KEYS" | grep -c .)
  if [[ "$KEY_COUNT" == "1" ]] && [[ "$IDEM_KEYS" == "$EXPECTED_IDEMPOTENCY_KEY" ]]; then
    pass "T-K-9/17: idempotency — both runs used same key ($EXPECTED_IDEMPOTENCY_KEY)"
  else
    fail "T-K-9/17: idempotency key drift (got $KEY_COUNT distinct keys: $IDEM_KEYS)"
  fi

  teardown_stub_hermes
else
  skip "T-K-9/17: script missing (covered by T-1 failure)"
fi

# ---------------------------------------------------------------------------
# T-5: script exit code 0 on success (with stub hermes returning 0)
# ---------------------------------------------------------------------------

if [[ -f "$ENQUEUE_SCRIPT" ]]; then
  setup_stub_hermes
  if bash "$ENQUEUE_SCRIPT" > /dev/null 2>&1; then
    pass "T-5: enqueue script exits 0 on success"
  else
    fail "T-5: enqueue script exited non-zero with successful stub"
  fi
  teardown_stub_hermes
else
  skip "T-5: script missing (covered by T-1 failure)"
fi

# ---------------------------------------------------------------------------
# T-6: script propagates non-zero on stub failure
# (delegation-assertion: wrapper should NOT swallow upstream errors)
# ---------------------------------------------------------------------------

if [[ -f "$ENQUEUE_SCRIPT" ]]; then
  FAIL_STUB_DIR=$(mktemp -d)
  cat > "$FAIL_STUB_DIR/hermes" <<'FAIL_EOF'
#!/usr/bin/env bash
echo "stub failure" >&2
exit 1
FAIL_EOF
  chmod +x "$FAIL_STUB_DIR/hermes"
  OLD_PATH="$PATH"
  export PATH="$FAIL_STUB_DIR:$PATH"

  if bash "$ENQUEUE_SCRIPT" > /dev/null 2>&1; then
    fail "T-6: enqueue script silently swallowed hermes failure (exit 0 when stub exited 1)"
  else
    pass "T-6: enqueue script propagates hermes non-zero exit"
  fi

  export PATH="$OLD_PATH"
  rm -rf "$FAIL_STUB_DIR"
else
  skip "T-6: script missing (covered by T-1 failure)"
fi

# ---------------------------------------------------------------------------
# T-7: script outputs the kanban create JSON line on stdout (for --deliver local)
# ---------------------------------------------------------------------------

if [[ -f "$ENQUEUE_SCRIPT" ]]; then
  setup_stub_hermes
  OUTPUT=$(bash "$ENQUEUE_SCRIPT" 2>/dev/null || true)
  if echo "$OUTPUT" | grep -qE '"task_id"\s*:\s*"t_'; then
    pass "T-7: script stdout contains kanban create JSON line"
  else
    fail "T-7: script stdout missing kanban create JSON line (got: $OUTPUT)"
  fi
  teardown_stub_hermes
else
  skip "T-7: script missing (covered by T-1 failure)"
fi

# ---------------------------------------------------------------------------
# T-8 (delegation-assertion): script calls `hermes kanban create` ONCE per
# invocation — not multiple times (defensive against accidental loops).
# ---------------------------------------------------------------------------

if [[ -f "$ENQUEUE_SCRIPT" ]]; then
  setup_stub_hermes
  bash "$ENQUEUE_SCRIPT" > /dev/null 2>&1 || true
  CREATE_COUNT=$(grep -c '^create$' "$STUB_LOG" || echo 0)
  if [[ "$CREATE_COUNT" == "1" ]]; then
    pass "T-8: hermes kanban create called exactly once per invocation"
  else
    fail "T-8: hermes kanban create called $CREATE_COUNT times (expected exactly 1)"
  fi
  teardown_stub_hermes
else
  skip "T-8: script missing (covered by T-1 failure)"
fi

# ---------------------------------------------------------------------------
# T-9 (edge case): script uses UTC date, not local, for idempotency key.
# Sanity: the key must end with YYYY-MM-DD format derived from UTC.
# ---------------------------------------------------------------------------

if [[ -f "$ENQUEUE_SCRIPT" ]]; then
  if grep -qE 'date.*-u' "$ENQUEUE_SCRIPT" 2>/dev/null; then
    pass "T-9: script derives date from UTC (date -u) — idempotency-key won't drift on TZ changes"
  else
    fail "T-9: script does not use 'date -u' for the idempotency key — TZ drift will create duplicate keys"
  fi
else
  skip "T-9: script missing (covered by T-1 failure)"
fi

# ---------------------------------------------------------------------------
# T-K-16: operational smoke — `hermes kanban list` reachable
# (we just sanity-check the hermes binary path; full smoke is operator-side)
# ---------------------------------------------------------------------------

REAL_HERMES="/home/ubuntu/explore/hermes-agent-trial/.venv/bin/hermes"
if [[ -x "$REAL_HERMES" ]]; then
  pass "T-K-16: real hermes binary present at $REAL_HERMES (operator smoke is bash-runnable)"
else
  fail "T-K-16: real hermes binary missing at $REAL_HERMES (operational smoke prereq)"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "----------------------------------------"
echo "Total: $TOTAL  Pass: $PASSED  Fail: $FAILED"
echo "----------------------------------------"

if [[ "$FAILED" -gt 0 ]]; then
  exit 1
fi
exit 0
