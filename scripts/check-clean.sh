#!/usr/bin/env bash
# Fail if staged files include secrets or runtime logs.
set -euo pipefail

staged="$(git diff --cached --name-only 2>/dev/null || true)"

if echo "$staged" | grep -qE '^\.env$|^logs/|^\.venv/'; then
  echo "ERROR: staged files include .env, logs/, or .venv/ — unstage before pushing." >&2
  exit 1
fi

if echo "$staged" | grep -qE 'IBM_QUANTUM_API_KEY=.{10,}'; then
  echo "ERROR: staged file may contain a real API key." >&2
  exit 1
fi

echo "OK: no sensitive paths in staged files."
exit 0
