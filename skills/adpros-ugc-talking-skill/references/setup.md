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

`./install.sh --with-otio` also installs OpenTimelineIO, `otio-cmx3600-adapter`, `otio-fcp-adapter`, and `otio-fcpx-xml-adapter`. The OpenTimelineIO-Plugins package does not include the FCPXML adapter, so it is named on its own. Storyboard, Premiere XML, and FCPXML from auto-editor do not need it.

## First model download

faster-whisper downloads weights on the first transcription, into the Hugging Face cache (`~/.cache/huggingface`). On CPU the default model is `small` (about 500 MB). On CUDA it is `large-v3` (about 3 GB). That first run can sit at "downloading" for several minutes. Later runs reuse the files. Pass `--model base` or `--model tiny` when you want a smaller download.

## doctor

`bash doctor.sh` prints one line per tool, including the ffmpeg version. `MISSING` on ffmpeg, ffprobe, libass, loudnorm, faster-whisper (when WhisperX is also missing), or the Inter font means the pipeline cannot run. `optional` on drawtext, WhisperX, auto-editor, or Remotion means a fallback exists. The hook is burned with libass, not drawtext.

## Where Claude Code loads the skill

- Personal: `~/.claude/skills/adpros-ugc-talking-skill/`
- Project: `.claude/skills/adpros-ugc-talking-skill/`

Copy the `adpros-ugc-talking-skill` folder, not the zip's parent. From GitHub:

```bash
npx skills add fabian-adpros/adpros-ugc-talking-skill --skill adpros-ugc-talking-skill -a claude-code
```

The skill lives at `skills/adpros-ugc-talking-skill/` so `npx skills add` can find it. Invoke it with `/adpros-ugc-talking-skill`.

## Migrating from ugc-talking-head

Release v0.1.0 stays as the historical download for the previous id. If you never installed `ugc-talking-head`, install only the new id. If that folder is already present, move it aside so Claude does not discover both, and keep any customizations in the moved copy. Move `ugc-talking-head.disabled` back to `ugc-talking-head` to enable the old copy again.

```bash
# Only when a previous install exists. This moves the folder; it does not delete it.
if [ -d "$HOME/.claude/skills/ugc-talking-head" ]; then
  mv "$HOME/.claude/skills/ugc-talking-head" "$HOME/.claude/skills/ugc-talking-head.disabled"
fi
if [ -d .claude/skills/ugc-talking-head ]; then
  mv .claude/skills/ugc-talking-head .claude/skills/ugc-talking-head.disabled
fi
npx skills add fabian-adpros/adpros-ugc-talking-skill --skill adpros-ugc-talking-skill -a claude-code -g -y
```

## claude.ai

Upload `dist/adpros-ugc-talking-skill.zip` from Settings → Capabilities → Skills. The archive root is the folder `adpros-ugc-talking-skill/`, and `SKILL.md` is inside it. A zip whose root is `SKILL.md` itself is ignored. Build it with `scripts/package.sh` from the repo. `dist/adpros-ugc-talking-skill.skill` is the same zip with the other extension.

claude.ai's code sandbox may not have ffmpeg, Whisper, or Node. This skill is meant for Claude Code on a machine where `install.sh` has run. In chat, say so instead of pretending the render happened.
