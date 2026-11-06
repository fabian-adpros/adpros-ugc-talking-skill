# Setup

Run `bash install.sh` from the skill directory, or `./install.sh` from the repo root. It is safe to run twice.

What it installs:

- ffmpeg (Homebrew on macOS, apt on Linux) when it is missing
- a Python venv at `.venv` inside the skill folder
- `faster-whisper` and `auto-editor` from `requirements.txt`
- `npm ci` plus `npx remotion browser ensure` in `template/`

WhisperX is not installed by default. It pulls PyTorch for alignment. Opt in with:

```bash
INSTALL_WHISPERX=1 ./install.sh
```

The pipeline uses WhisperX when the `whisperx` command is on `PATH`, and faster-whisper otherwise.

## First model download

faster-whisper downloads weights on the first transcription, into the Hugging Face cache (`~/.cache/huggingface`). On CPU the default model is `small` (about 500 MB). On CUDA it is `large-v3` (about 3 GB). That first run can sit at "downloading" for several minutes. Later runs reuse the files. Pass `--model base` or `--model tiny` when you want a smaller download.

## doctor

`bash doctor.sh` prints one line per tool. `MISSING` on ffmpeg, ffprobe, libass, drawtext, loudnorm, faster-whisper (when WhisperX is also missing), or the Inter font means the pipeline cannot run. `optional` on WhisperX, auto-editor, or Remotion means a fallback exists.

## Where Claude Code loads the skill

- Personal: `~/.claude/skills/ugc-talking-head/`
- Project: `.claude/skills/ugc-talking-head/`

Copy the `ugc-talking-head` folder, not the zip's parent. From GitHub:

```bash
npx skills add fabian-adpros/adpros-ugc-talking-skill --skill ugc-talking-head -a claude-code
```

The skill lives at `skills/ugc-talking-head/` so `npx skills add` can find it.

## claude.ai

Upload `dist/ugc-talking-head.zip` from Settings → Capabilities → Skills. The archive root is the folder `ugc-talking-head/`, and `SKILL.md` is inside it. A zip whose root is `SKILL.md` itself is ignored. Build it with `scripts/package.sh` from the repo. `dist/ugc-talking-head.skill` is the same zip with the other extension.

claude.ai's code sandbox may not have ffmpeg, Whisper, or Node. This skill is meant for Claude Code on a machine where `install.sh` has run. In chat, say so instead of pretending the render happened.
