#!/bin/bash
# TaskCompleted: verify modified files are lint-clean before allowing task completion.
# Exit 2 to block and feed errors back.

set +e

DIRTY=$(git diff --name-only 2>/dev/null)
STAGED=$(git diff --cached --name-only 2>/dev/null)
MODIFIED=$(printf '%s\n%s' "$DIRTY" "$STAGED" | sort -u | grep -v '^$')

[ -z "$MODIFIED" ] && exit 0

ERRORS=""

PY_FILES=$(echo "$MODIFIED" | grep -E '\.py$' | tr '\n' ' ')

if [ -n "$PY_FILES" ] && command -v ruff &>/dev/null; then
  OUTPUT=$(ruff check $PY_FILES 2>&1) || ERRORS="${ERRORS}ruff:\n${OUTPUT}\n\n"
fi

if [ -n "$ERRORS" ]; then
  echo -e "Task has lint errors. Fix before marking complete:\n\n${ERRORS}" >&2
  exit 2
fi

exit 0
