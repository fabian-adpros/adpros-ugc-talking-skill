#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$SKILL_DIR/.venv/bin/python"
if [[ ! -x "$PY" && -x "$SKILL_DIR/../../.venv/bin/python" ]]; then
  PY="$SKILL_DIR/../../.venv/bin/python"
fi
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi
exec "$PY" "$SKILL_DIR/scripts/ugc_edit.py" doctor "$@"
