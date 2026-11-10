#!/usr/bin/env bash
# Idempotent setup for adpros-ugc-talking-skill.
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

WITH_OTIO=0
WITH_BG=0
for arg in "$@"; do
  if [[ "$arg" == "--with-otio" ]]; then
    WITH_OTIO=1
  fi
  if [[ "$arg" == "--with-bg" ]]; then
    WITH_BG=1
  fi
done
if [[ "${INSTALL_OTIO:-0}" == "1" ]]; then
  WITH_OTIO=1
fi
if [[ "${INSTALL_BG:-0}" == "1" ]]; then
  WITH_BG=1
fi
if [[ "$WITH_OTIO" == "1" ]]; then
  log "Optional OpenTimelineIO adapters"
  "$SKILL_DIR/.venv/bin/pip" install \
    'opentimelineio>=0.17,<0.19' \
    'otio-cmx3600-adapter' \
    'otio-fcp-adapter' \
    'otio-fcpx-xml-adapter' \
    || echo "OpenTimelineIO extras did not fully install. Premiere and FCPXML via auto-editor still work."
fi

if [[ "$WITH_BG" == "1" ]]; then
  log "Optional background removal (CPU PyTorch + backgroundremover)"
  "$SKILL_DIR/.venv/bin/pip" install torch torchvision --index-url https://download.pytorch.org/whl/cpu \
    && "$SKILL_DIR/.venv/bin/pip" install backgroundremover \
    || echo "backgroundremover did not install. The rest of the pipeline still works. Re-run ./install.sh --with-bg."
  echo "The first backgroundremover run downloads the u2net weights (about 176 MB) into ~/.u2net."
  echo "Apple Silicon speed was not tested. PyTorch may use MPS there; this install path is the CPU wheel."
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
OpenTimelineIO is optional. Install it with ./install.sh --with-otio
Background removal is optional. Install it with ./install.sh --with-bg
That pulls CPU torch and backgroundremover. The first run downloads u2net (about 176 MB) into ~/.u2net.
The OpenTimelineIO-Plugins meta-package does not include otio-fcpx-xml-adapter, so --with-otio installs that adapter by name.
ffmpeg is the caption fallback when Node or Remotion is missing.
auto-editor is the silence engine when it is installed; word gaps are the fallback.

NOTE
