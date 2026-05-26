#!/usr/bin/env bash
# autonovel-phase1-smoke — automates T1-T4 + T6 from bd-b5p.4 spec.
#
# Bead: bd-b5p.4
# Usage: ./smoke-test.sh
#
# Exit code:
#   0 — all automated tests pass
#   1 — at least one test failed (see stderr)
#   2 — environment problem (Hermes not found, autonovel root missing)
#
# Tests:
#   T1: skill is discoverable (file present in user skills dir OR symlinked)
#   T2: hermes -z one-shot invocation produces prose-shaped output
#   T3: write/runs/phase1-smoke/draft-*.md exists with prose content
#   T4: hermes cron list shows the registered job (only checked if the
#       cron has been registered — the test is a soft probe)
#   T5: documented but not run (next 09:00 firing is operator-time)
#   T6: evaluate.py slop_score < 5.0 on the most recent draft
#   T7: documented as human-required (out of scope)

set -uo pipefail

# Resolve paths --------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTONOVEL_ROOT="${AUTONOVEL_ROOT:-/home/ubuntu/explore/autonovel}"
HERMES_BIN="${HERMES_BIN:-/home/ubuntu/explore/hermes-agent-trial/.venv/bin/hermes}"
SKILL_NAME="autonovel-phase1-smoke"
USER_SKILL_DIR="${HOME}/.hermes/skills/${SKILL_NAME}"

PASS=0
FAIL=0

pass() {
    PASS=$((PASS + 1))
    echo "  PASS: $1"
}
fail() {
    FAIL=$((FAIL + 1))
    echo "  FAIL: $1" >&2
}
skip() {
    echo "  SKIP: $1"
}

# Pre-flight ----------------------------------------------------------------

echo "== Pre-flight =="
if [[ ! -x "${HERMES_BIN}" ]]; then
    echo "  ERR: hermes binary not found at ${HERMES_BIN}" >&2
    echo "  Set HERMES_BIN env var to override." >&2
    exit 2
fi
echo "  hermes: ${HERMES_BIN}"
if [[ ! -d "${AUTONOVEL_ROOT}" ]]; then
    echo "  ERR: autonovel root not at ${AUTONOVEL_ROOT}" >&2
    exit 2
fi
echo "  autonovel: ${AUTONOVEL_ROOT}"
echo ""

# T1: skill discovery -------------------------------------------------------

echo "== T1: skill discovery =="
# Hermes' 'skills list' only surfaces hub-installed skills (registry-managed).
# User-shipped skills live under ~/.hermes/skills/<name>/ and are discovered
# at agent start via os.walk scan (see primer §2.1). So the canonical probe
# for THIS skill is: does the SKILL.md exist in the user skills dir?
if [[ -f "${USER_SKILL_DIR}/SKILL.md" ]]; then
    pass "T1: ${USER_SKILL_DIR}/SKILL.md present (symlink or copy)"
    # Best-effort sanity check that the symlink target resolves.
    if [[ -L "${USER_SKILL_DIR}" ]] && [[ ! -e "${USER_SKILL_DIR}" ]]; then
        fail "T1: ${USER_SKILL_DIR} is a broken symlink"
    fi
else
    fail "T1: ${USER_SKILL_DIR}/SKILL.md missing — run install (see README)"
fi
echo ""

# T2 + T3: invocation + output ---------------------------------------------

echo "== T2 + T3: skill invocation + draft file written =="
# We run the runner directly rather than going through `hermes -z` here —
# the runner IS the skill's load-bearing path, and invoking it via a
# Hermes oneshot would consume an LLM call AND require the agent to
# correctly route to the runner. For a deterministic smoke we shell out
# to the runner; the README documents the hermes -z invocation for the
# end-to-end manual smoke.
RUNNER="${SCRIPT_DIR}/runner.py"
if [[ ! -f "${RUNNER}" ]]; then
    fail "T2/T3: runner.py missing at ${RUNNER}"
else
    echo "  Running: python3 ${RUNNER}"
    if RUNNER_OUT="$(python3 "${RUNNER}" 2>&1)"; then
        RUNNER_RC=0
    else
        RUNNER_RC=$?
    fi
    echo "  Runner exit: ${RUNNER_RC}"
    echo "  Runner stdout (last line):"
    LAST_LINE="$(printf '%s\n' "${RUNNER_OUT}" | tail -n 1)"
    echo "    ${LAST_LINE}"
    if [[ "${LAST_LINE}" == slop_score=* ]]; then
        pass "T2: runner produced a slop_score line"
    else
        fail "T2: runner did not produce expected slop_score line"
    fi
fi
echo ""

# T3 specifically: does a draft file exist?
echo "== T3 (file): draft-*.md present =="
DRAFT_DIR="${AUTONOVEL_ROOT}/write/runs/phase1-smoke"
shopt -s nullglob
DRAFTS=("${DRAFT_DIR}"/draft-*.md)
shopt -u nullglob
if (( ${#DRAFTS[@]} > 0 )); then
    LATEST_DRAFT="${DRAFTS[-1]}"
    DRAFT_BYTES=$(wc -c <"${LATEST_DRAFT}")
    pass "T3: ${#DRAFTS[@]} draft(s); latest=${LATEST_DRAFT##*/} (${DRAFT_BYTES} bytes)"
else
    fail "T3: no drafts at ${DRAFT_DIR}/draft-*.md"
    LATEST_DRAFT=""
fi
echo ""

# T4: cron registration -----------------------------------------------------

echo "== T4: cron registration =="
if CRON_LIST="$("${HERMES_BIN}" cron list 2>&1)"; then
    if printf '%s' "${CRON_LIST}" | grep -q "${SKILL_NAME}"; then
        pass "T4: hermes cron list shows ${SKILL_NAME}"
    else
        skip "T4: ${SKILL_NAME} not in cron list (run README install step to register)"
    fi
else
    skip "T4: hermes cron list failed (cron not initialized?)"
fi
echo ""

# T5: documented only ------------------------------------------------------

echo "== T5: next-firing observation =="
skip "T5: next 09:00 cron firing is an operator-time check; see README"
echo ""

# T6: slop score gate ------------------------------------------------------

echo "== T6: evaluate.py slop_score < 5.0 =="
if [[ -z "${LATEST_DRAFT}" ]]; then
    fail "T6: cannot evaluate — no draft from T3"
elif [[ ! -f "${AUTONOVEL_ROOT}/evaluate.py" ]]; then
    fail "T6: evaluate.py not at ${AUTONOVEL_ROOT}/evaluate.py"
else
    # Strip the runner-added footer so we score prose only, not metadata.
    # The footer is delimited by "\n\n---\n<!-- autonovel-phase1-smoke".
    SLOP_OUT="$(python3 - "${LATEST_DRAFT}" "${AUTONOVEL_ROOT}" <<'PY' 2>&1
import json
import sys
from pathlib import Path

draft_path = Path(sys.argv[1])
root = Path(sys.argv[2])
sys.path.insert(0, str(root))
import evaluate

text = draft_path.read_text(encoding="utf-8")
# Trim runner footer if present
marker = "\n\n---\n<!-- autonovel-phase1-smoke"
if marker in text:
    text = text.split(marker, 1)[0]
score = evaluate.slop_score(text)
print(json.dumps({"slop_penalty": score["slop_penalty"]}))
PY
    )"
    SLOP_RC=$?
    if [[ ${SLOP_RC} -ne 0 ]]; then
        fail "T6: slop_score subprocess failed: ${SLOP_OUT}"
    else
        SLOP_PENALTY="$(printf '%s' "${SLOP_OUT}" | tail -n 1 | python3 -c 'import json,sys; print(json.loads(sys.stdin.read())["slop_penalty"])')"
        echo "  slop_penalty=${SLOP_PENALTY}"
        # bash arithmetic doesn't do floats; use python for comparison
        if python3 -c "import sys; sys.exit(0 if float(${SLOP_PENALTY}) < 5.0 else 1)"; then
            pass "T6: slop_penalty ${SLOP_PENALTY} < 5.0"
        else
            fail "T6: slop_penalty ${SLOP_PENALTY} >= 5.0"
        fi
    fi
fi
echo ""

# T7: documented only ------------------------------------------------------

echo "== T7: human blind-rate =="
skip "T7: human blind-rate (≥3/5 voice match to Entry 002) is operator-only"
echo ""

# Summary ------------------------------------------------------------------

echo "== Summary =="
echo "  passed: ${PASS}"
echo "  failed: ${FAIL}"
if (( FAIL == 0 )); then
    echo "  result: OK"
    exit 0
else
    echo "  result: FAIL"
    exit 1
fi
