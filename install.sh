#!/usr/bin/env bash
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/skills/adpros-ugc-talking-skill/install.sh" "$@"
