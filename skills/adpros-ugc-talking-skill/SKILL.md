---
name: adpros-ugc-talking-skill
description: "Turn a raw 60-90s vertical 9:16 UGC talking-head phone clip into a launch-ready 1080x1920 MP4 with word-level captions, silence and filler cuts, a 3-second hook, and a ducked music bed. English and Spanish. Use when the user says edit this clip, talking head, UGC, captions, subtitles, remove silences, remove filler words, Reels, TikTok, launch-ready, edita este video, edita este clip, cabeza parlante, subtítulos, quita los silencios, quita las muletillas, gancho, or déjalo listo para publicar."
license: MIT
compatibility: Requires ffmpeg (libass, libx264, aac, loudnorm), Python 3.10+, and faster-whisper or WhisperX. auto-editor is the preferred silence engine. Node.js and Remotion are optional; FFmpeg renders if they are missing. CPU or CUDA. English and Spanish. No hosted API.
metadata:
  author: Fabian
  version: "0.3.0"
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
4. After they confirm, write the storyboard. This does not render the final video.

```bash
"$PY" "$SKILL_DIR/scripts/ugc_edit.py" storyboard --workdir "$WORKDIR" --ui es
```

That fills `$WORKDIR/export/` with `storyboard.json`, `storyboard.html`, `storyboard.md`, `storyboard.csv`, `thumbs/keep_NNN.jpg`, `contact-sheet.jpg`, `captions.srt`, `hook.srt`, and `RELINK.md`. `storyboard.html` points at the thumbnail files. That is the local default. The SRT files are in edited-timeline time.

Add `--inline`, or set `storyboard.inline` in the preset, to also write `storyboard.inline.html`. That file is one HTML document: CSS is in a `<style>` block, thumbnails are JPEG data URIs around 320 px wide, and it does not load a script, a CDN, or a local image file. `storyboard.inline_max_bytes` (default 1500000) is the cap. If the page would be larger, thumbnails are shrunk and then dropped, and the page says so. This cap was not checked against Claude.ai's real artifact limit.

After `storyboard`:

- In Claude.ai, if the chat can show an HTML artifact, pass `--inline` and present the full text of `export/storyboard.inline.html` as that artifact. Also offer the export files for download. This artifact path was not verified inside Claude.ai.
- In Claude Code there is no artifact. Paste `export/storyboard.md` into the chat. Tell the user the path and how to open the local page: `open export/storyboard.html` on macOS, `xdg-open export/storyboard.html` on Linux.

Optional vision labels, only after you have looked at the thumbnails (still frames, not the video). Write `labels.json` with a closed set: `talking_head`, `product_visible`, `product_reveal`, `hands`, `screen_or_laptop`, `text_on_screen`, `environment`, `unclear`. Confidence is `low`, `medium`, or `high`, plus a short `evidence` string that names what you actually see in that JPEG. A `low` confidence `product_reveal` does not become a marker. Then:

```bash
"$PY" "$SKILL_DIR/scripts/ugc_edit.py" storyboard \
  --workdir "$WORKDIR" --vision-labels "$WORKDIR/labels.json"
```

```json
{"labels":[{"index":1,"label":"product_visible","confidence":"high","evidence":"A bottle is visible in keep_001.jpg."}]}
```

5. After the hook is approved, ask three delivery questions before rendering. Do not invent the answers. Exit 11 is that checkpoint, not a failure. `--yes` skips it and uses `delivery` in `preset.json` (editor projects off unless the preset says otherwise).

Ask, in the user's language:

- Do you want editor project files at the end?
- Which editors? Premiere, Final Cut, DaVinci Resolve, CapCut (media and SRT only; no project file), OTIO, EDL. Several are allowed.
- Review the storyboard before exporting?

Then re-run with their choices:

```bash
"$PY" "$SKILL_DIR/scripts/ugc_edit.py" run "$CLIP" \
  --workdir "$WORKDIR" --from render --nle premiere,fcpx,resolve --review-storyboard --ui es
```

`--nle none --no-review-storyboard` means no project files and no storyboard stop. The answers are stored on `plan.json` and copied into `storyboard.json`, so a later run does not ask again.

6. Exit 12 means the storyboard is ready for review. Show `export/storyboard.html` and `export/contact-sheet.jpg`. Wait for approval. Then continue with `--storyboard-yes`. Do not export the NLE files before that.

7. Background removal is off unless the user asks or `bg.enabled` is true in the preset. It runs after the cuts, on the kept picture, and before captions, the hook, and music. Captions are burned onto the composited picture, so the matte cannot erase them.

```bash
"$PY" "$SKILL_DIR/scripts/ugc_edit.py" run "$CLIP" \
  --workdir "$WORKDIR" --from render --bg /path/to/plate.png --ui es
```

`--bg transparent` writes a ProRes 4444 alpha `subject.mov` and styles the MP4 over black. `./install.sh --with-bg` installs CPU torch, BiRefNet's runtime, and `backgroundremover`. If that install fails, the script exits non-zero. `doctor` reports BiRefNet as not installed until the imports work. The first BiRefNet run downloads `ZhengPeng7/BiRefNet_lite` at revision `aa62cd87eafb` (MIT). That repo is trusted. `HF_TOKEN` is optional and only raises the Hub rate limit. U2-Net weights (about 176 MB) download into `~/.u2net` only if that fallback runs. Do not switch a BiRefNet result to `u2net_human_seg`: that model is person-only and often deletes a product in the hand.

Exit 13 is the background checkpoint, not a failure. The command writes 3–5 side-by-side frames (`bg-preview/compare_NN.jpg`): original on the left, matted result on the right, including frames where a product is visible when the storyboard already labeled one. The header names the engine that actually ran (`birefnet`, `ben2`, or `u2net`), not a leftover U2-Net model name. Open those JPEGs and compare them. Say explicitly if a hand-held product or the hands were cut out or flicker. Then offer the printed `next_steps` as a numbered list: keep this background (`--bg-yes`), the faster U2-Net fallback (`--bg-engine u2net`), BEN2 (`--bg-engine ben2`), a larger short side or a longer smooth window (`--bg-infer-size`, `--bg-smooth`), or `--bg-skip` to keep the original. `--yes` skips the checkpoint and uses the preset, which keeps the original background unless `bg.enabled` is true.

`bg.engine` is `birefnet`, `ben2`, or `u2net`. The default is `birefnet` (Hugging Face `ZhengPeng7/BiRefNet_lite`, MIT code and MIT weights) when `./install.sh --with-bg` has installed torch, transformers, timm, and kornia. If that import fails and the user did not pass `--bg-engine`, the run falls back to `u2net` and says so. `--bg-engine ben2` uses the MIT base `PramaLLC/BEN2` only when that package is installed. It is not part of `--with-bg`. U2-Net often drops a black shirt or a black product box. BiRefNet is the general-subject net meant to keep those. The device order is MPS, then CUDA, then CPU. Apple Silicon speed was not measured.

`bg.infer_size` is the short side, aspect kept, default 320. On CPU, BiRefNet_lite at that size took about 1.05 s/frame on an 11 s clip (331 frames, about 6 minutes). The U2-Net CLI on the same clip took about 72 s. Apple Silicon MPS is selected when it exists and was not timed. The command prints `bg: ... per_frame=...s`. A reused matte prints `bg: reused the existing matte`.

The matte is scaled to the cut before it is composited. A temporal median (`bg.temporal_smooth`, default 3) and a small close run on the alpha. The guided filter is not used: it copied the picture into the mask. `--bg-refine` only blurs the alpha, and it is off unless you pass it. A cut that is unchanged is not encoded again, so approving the preview does not run the model a second time.

On a real 11 s clip, BiRefNet_lite kept a black shirt, a black product box, and a waving hand. A brief leak around 5.0 s during a lift can still happen. If the product still flickers, Grounded-SAM-2 is the next step and is not in this version. The alpha master does not have captions burned in. Captions are on the MP4 and in the SRT files.

When `export --nle` runs and a background was approved, `export/media/` also gets `subject.mov`, `matte.mp4`, and the background file. They sit beside `media/source.mp4`. They are not inside the auto-editor sequence. `RELINK.md` says so.

8. After they say yes (or they already said "sin preguntar" / "just export it"), render and export. If exit 13 is still open, answer the background preview first.

```bash
"$PY" "$SKILL_DIR/scripts/ugc_edit.py" run "$CLIP" \
  --workdir "$WORKDIR" --from render --yes --hook "EL GANCHO" --ui es
```

Omit `--hook` to keep the suggested line. `--renderer ffmpeg` forces the fallback. The default tries Remotion, then FFmpeg.

9. Report `final.mp4`: resolution, duration, LUFS, and the frame PNG. Repeat every warning from `plan.json`, especially fillers the transcript never contained.
10. If they asked for editor files, `export/` is part of the delivery, next to `final.mp4`. `run` writes only the chosen targets after the loudness export. You can also call export directly:

```bash
"$PY" "$SKILL_DIR/scripts/ugc_edit.py" export --workdir "$WORKDIR" --nle all
```

`--nle` is a comma-separated list, `all`, or `none`. `premiere` is `project_premiere.xml` (FCP 7 xmeml, not FCPXML). `fcpx` and `resolve` share `project.fcpxml` (FCPXML 1.10; the asset duration is the full conformed source). `capcut` copies media and SRT only. `otio` and `edl` need `./install.sh --with-otio` (`opentimelineio>=0.17,<0.19`, so Python 3.13 can use the 0.18 wheel). Read `export/RELINK.md` before telling the user which file to open.

Exit 10 is the hook. Exit 11 is the delivery questionnaire. Exit 12 is the storyboard review. Exit 13 is the background preview. None of them is a crash.

## What's next

Close every stage and every checkpoint with a short "What's next" / "Qué sigue" block. Use the `next_steps` list the command just printed. The same list is stored on `plan.json`. Show 2–4 of those options as a numbered list the user can answer with a number. Do this in Claude.ai and in Claude Code. Match the user's language.

The checkpoints are the hook (exit 10), the delivery questionnaire (exit 11), the storyboard review (exit 12), the background preview (exit 13), the styled render, the final export, and any exit 2 error. After a final render the list can include changing the hook, trying another background, exporting for Premiere, Final Cut, and Resolve, making a 1:1 or 4:5 version, moving captions when they cover the product, and making another video with the same preset. After an error, the first item is the likely fix and the exact next command. Do not invent a different command when `next_steps` already names one.

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

- Exit 2: read the message, then the printed `next_steps`. The first item is the likely fix and the command to run. See [references/troubleshooting.md](references/troubleshooting.md).
- Exit 10: waiting for the hook. Not a failure.
- Exit 11: waiting for the delivery answers. Not a failure.
- Exit 12: waiting for the storyboard review. Not a failure.
- Exit 13: waiting for the background preview. Compare the frames before you approve. Not a failure.
- If Remotion fails and the user did not force it, the script falls back to FFmpeg and says so. If they forced `--renderer remotion`, show the error.
- If the transcript has no fillers, say that Whisper dropped them. Do not claim they were removed.

## Workdir

`$WORKDIR` holds `words.json`, `raw.srt`, `plan.json`, `cut.mp4`, `styled.mp4`, `final.mp4`, and `frame.png`. Reuse it when the user changes only the hook, so you do not transcribe again.
