#!/bin/bash
# PostToolUse (Edit|Write): auto-fix formatting and safe lint issues.
# Silent on success. Exit 2 on unfixable errors (feeds back to agent).

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

[ -z "$FILE_PATH" ] && exit 0
[ ! -f "$FILE_PATH" ] && exit 0

case "$FILE_PATH" in
  *.py)
    command -v ruff &>/dev/null || exit 0
    ruff check --fix "$FILE_PATH" 2>/dev/null
    ruff format "$FILE_PATH" 2>/dev/null
    OUTPUT=$(ruff check "$FILE_PATH" 2>&1) || {
      echo "$OUTPUT" >&2
      exit 2
    }
    ;;
esac

exit 0
