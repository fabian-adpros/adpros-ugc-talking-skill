# Silence

Default: remove silences **strictly longer than 0.4s**, and keep **0.05s of padding** on each side of the cut so the edit does not clip the word.

`assets/preset.json` keys: `silence.min_seconds`, `silence.padding_seconds`, `silence.engine` (`auto`, `auto-editor`, or `words`).

## Why auto-editor is first

`auto` uses auto-editor when the binary is on `PATH`. It measures the waveform, so a pause Whisper glued into one segment still gets cut. The words engine only sees gaps between transcribed words.

auto-editor 29.3.1 has no minimum-cut flag. `--smooth` is rejected (`Unknown option`). The script therefore:

1. Runs the verified command in [commands.md](commands.md) with `--margin` set to the padding (0.05s) and `--frame-rate` set to `silence.analysis_fps` (100, so the margin lands on a 10 ms grid).
2. Reads the `.v1` timeline. A chunk whose speed is `99999` is a cut. Speed `1` is kept.
3. Adds the margin back to estimate the original silence (one margin on a leading or trailing cut, two margins in the middle). The cut is kept only when that estimate is **greater than** 0.4s. A 0.2s hole stays.

If auto-editor is missing, the command fails, or the cuts would remove more than 70% of the clip, the script switches to word gaps and writes a warning.

## Word-gap fallback

`--silence-engine words` never calls auto-editor. A gap between two word timestamps, or before the first word, or after the last, is removed only when it is longer than 0.4s. The cut starts `padding` after the previous word and ends `padding` before the next one.

Use this when the room tone is loud enough that auto-editor's threshold (`silence.audio_threshold`, default `0.04`) cannot see the pause, or when you want the edit locked to the transcript.

## What the plan shows

`plan.json` → `silence.cuts` is the list that will actually be removed, in source seconds. `silence_engine` is `auto-editor` or `words`. Show both to the user before rendering.
