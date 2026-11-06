---
name: adpros-ugc-talking-skill
description: "Turn a raw 60-90s vertical 9:16 UGC talking-head phone clip into a launch-ready 1080x1920 MP4 with word-level captions, silence and filler cuts, a 3-second hook, and a ducked music bed. English and Spanish. Use when the user says edit this clip, talking head, UGC, captions, subtitles, remove silences, remove filler words, Reels, TikTok, launch-ready, edita este video, edita este clip, cabeza parlante, subtítulos, quita los silencios, quita las muletillas, gancho, or déjalo listo para publicar."
license: MIT
compatibility: Requires ffmpeg (libass, libx264, aac, loudnorm), Python 3.10+, and faster-whisper or WhisperX. auto-editor is the preferred silence engine. Node.js and Remotion are optional; FFmpeg renders if they are missing. CPU or CUDA. English and Spanish. No hosted API.
metadata:
  author: Fabian
  version: "0.1.2"
  languages: "en,es"
---

# UGC talking head

Public skill id: `adpros-ugc-talking-skill`. Invoke it with `/adpros-ugc-talking-skill`.

Reply in the user's language. Spanish in, Spanish out. English in, English out. The clip's language is separate: captions, fillers, and the hook stay in the language spoken on camera.

One raw vertical phone clip becomes a 1080x1920 MP4. You do not invent timestamps. The scripts do.

## Resolve the skill directory

`SKILL_DIR` is the folder that contains this file. In Claude Code the token `${CLAUDE_SKILL_DIR}` is rewritten to that path. If you still see the token literally, use the directory of the `SKILL.md` you just read. In claude.ai the same files are next to this file (`scripts/ugc_edit.py`).

Prefer the venv Python when it exists:

```bash
PY="${SKILL_DIR}/.venv/bin/python"
[ -x "$PY" ] || PY=python3
```

## Steps

1. Run `bash "$SKILL_DIR/doctor.sh"`. If a required line says `MISSING`, run `bash "$SKILL_DIR/install.sh"` and read [references/setup.md](references/setup.md). The first transcription downloads a Whisper model and can take several minutes.
2. Transcribe and plan. Do not render yet.

```bash
"$PY" "$SKILL_DIR/scripts/ugc_edit.py" run "$CLIP" \
  --workdir "$WORKDIR" --lang auto --ui es
```

`--ui` is the user's language (`es` or `en`), not the clip's language. `--lang auto` detects the clip. Pass `--lang es` or `--lang en` when the user already told you. Exit code 10 means the plan is ready and you must stop.

3. Show the user the printed plan: duration before and after, silence cuts, fillers actually removed, the hook, one alternate, and every warning. Ask them to confirm the hook or send a different line. Do not render on exit 10.
4. After they say yes (or they already said "sin preguntar" / "just export it"), render and export:

```bash
"$PY" "$SKILL_DIR/scripts/ugc_edit.py" run "$CLIP" \
  --workdir "$WORKDIR" --from render --yes --hook "EL GANCHO" --ui es
```

Omit `--hook` to keep the suggested line. `--renderer ffmpeg` forces the fallback. The default tries Remotion, then FFmpeg.

5. Report `final.mp4`: resolution, duration, LUFS, and the frame PNG. Repeat every warning from `plan.json`, especially fillers the transcript never contained.

Details live in the reference files. Open only the one you need.

| Topic | File |
| --- | --- |
| Install, doctor, model download | [references/setup.md](references/setup.md) |
| WhisperX and faster-whisper | [references/transcription.md](references/transcription.md) |
| Silence cuts | [references/silence.md](references/silence.md) |
| Filler lists and the two modes | [references/fillers.md](references/fillers.md) |
| Hook criteria | [references/hook.md](references/hook.md) |
| Captions, safe zones, music | [references/style.md](references/style.md) |
| Export, 60s, loudness | [references/export.md](references/export.md) |
| Verified CLI flags | [references/commands.md](references/commands.md) |
| JSON shapes | [references/schemas.md](references/schemas.md) |
| When something fails | [references/troubleshooting.md](references/troubleshooting.md) |

## Pick the hook

Read [references/hook.md](references/hook.md) before you replace the suggestion. Short version:

- Same language as the clip. Do not translate.
- Skip greetings (`hola`, `hey`, `buenas`) and fillers.
- Prefer a concrete claim, a number, or a result in the first sentences of the kept transcript.
- At most 8 words and 42 characters so it fits the 9:16 safe zone.
- Offer the script's line plus one alternate. The user decides.

## Defaults you should not silently change

- Fillers: `conservative`. Use `--mode aggressive` only when the user asks to strip more (`agresivo`, `quita todas las muletillas`, `aggressive`).
- Silence: longer than 0.4s, 0.05s of padding on each side. Engine `auto` uses auto-editor when it is installed, otherwise word gaps.
- Captions: 2–3 words in the lower safe area, horizontally centered, active word in yellow. `captions.y_ratio` moves the line. The default is 0.75. This does not detect a face.
- Hook on screen for the first 3 seconds.
- Music bed at about −18 dB under the voice. The shipped bed is `assets/music/bed.m4a`. Replace it with `--music`.
- Export: 1080x1920, H.264 + AAC, about −14 LUFS. Over 60s is trimmed unless `--no-trim`.

Preset file: `assets/preset.json`. Filler lists: `assets/fillers.json`.

## Errors

- Exit 2: read the message, fix that cause, do not invent a parallel edit. See [references/troubleshooting.md](references/troubleshooting.md).
- Exit 10: waiting for the hook. Not a failure.
- If Remotion fails and the user did not force it, the script falls back to FFmpeg and says so. If they forced `--renderer remotion`, show the error.
- If the transcript has no fillers, say that Whisper dropped them. Do not claim they were removed.

## Workdir

`$WORKDIR` holds `words.json`, `raw.srt`, `plan.json`, `cut.mp4`, `styled.mp4`, `final.mp4`, and `frame.png`. Reuse it when the user changes only the hook, so you do not transcribe again.
