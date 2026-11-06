#!/usr/bin/env bash
# Idempotent setup for ugc-talking-head.
# Tested on Ubuntu 24.04. The Homebrew branch is for a clean Mac and was not
# executed on macOS in this repo's own test run.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SKILL_DIR"

log() { printf '\n== %s\n' "$*"; }

have() { command -v "$1" >/dev/null 2>&1; }

install_system() {
  if have ffmpeg && have ffprobe && have python3 && have node && have npm; then
    log "ffmpeg, python3, and node are already installed"
    return
  fi
  case "$(uname -s)" in
    Darwin)
      if ! have brew; then
        echo "Homebrew is required. Install it from https://brew.sh and re-run." >&2
        exit 1
      fi
      brew install ffmpeg python@3.12 node
      ;;
    Linux)
      if ! have sudo; then
        echo "ffmpeg, python3, or node is missing and sudo is not available." >&2
        exit 1
      fi
      sudo apt-get update -qq
      sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg python3 python3-venv python3-pip nodejs npm
      ;;
    *)
      echo "Install ffmpeg, Python 3.10+, and Node.js 18+, then re-run." >&2
      exit 1
      ;;
  esac
}

install_system

PY="python3"
if have python3.12; then
  PY="python3.12"
fi

if [[ ! -x "$SKILL_DIR/.venv/bin/python" ]]; then
  log "Creating $SKILL_DIR/.venv"
  "$PY" -m venv "$SKILL_DIR/.venv"
fi

log "Python packages (faster-whisper, auto-editor)"
"$SKILL_DIR/.venv/bin/pip" install -U pip
"$SKILL_DIR/.venv/bin/pip" install -r "$SKILL_DIR/requirements.txt"

if [[ "${INSTALL_WHISPERX:-0}" == "1" ]]; then
  log "Optional WhisperX (this pulls PyTorch)"
  "$SKILL_DIR/.venv/bin/pip" install whisperx || echo "WhisperX did not install. faster-whisper remains the fallback."
fi

log "Remotion template"
if ! have npm; then
  echo "npm is missing. The FFmpeg renderer still works; Remotion will not." >&2
else
  (cd "$SKILL_DIR/template" && npm ci)
  (cd "$SKILL_DIR/template" && npx remotion browser ensure)
fi

cat <<'NOTE'

Installed.

The first transcription downloads a Whisper model into the Hugging Face cache
(small on CPU is about 500 MB, large-v3 on a GPU is about 3 GB). That first
run can take several minutes before any words appear. Later runs reuse the cache.

Activate the venv when you call the pipeline yourself:

  source .venv/bin/activate
  python scripts/ugc_edit.py doctor

WhisperX is optional. Install it with INSTALL_WHISPERX=1 ./install.sh
ffmpeg is the caption fallback when Node or Remotion is missing.
auto-editor is the silence engine when it is installed; word gaps are the fallback.

NOTE
