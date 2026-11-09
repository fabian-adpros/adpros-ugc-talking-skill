# Commands that were actually verified

Do not add flags that are not listed here unless you have run `--help` or the call on this machine. Versions drift.

## auto-editor 29.3.1

`auto-editor --help` on 29.3.1. `--smooth` returns `Unknown option` and is not used.

```bash
auto-editor INPUT \
  --edit audio:threshold=0.04 \
  --margin 0.05sec \
  --frame-rate 100 \
  --export v1 \
  --output WORKDIR/auto-editor \
  --no-open \
  --quiet
```

Confirmed on a generated clip:

- `--export v1` writes `auto-editor.v1`
- chunks are `[startFrame, endFrame, speed]`
- speed `99999` is a cut, speed `1` is kept
- at `--frame-rate 100`, a 0.80s digital silence with `--margin 0.05sec` becomes a 0.70s cut (0.05s of pad on each side)
- a 0.20s silence becomes a short cut and the Python gate drops it, because 0.20 is not greater than 0.40

Also present in that help: `--preview` / `--stats`, `--audio-normalize` (`ebu` or `peak`), `--when-silent`, `--when-normal`. The pipeline does not need them.

## ffmpeg 6.1.1

Filters confirmed with `ffmpeg -h filter=...` on the Linux ffmpeg used for these fixes: `subtitles` (`filename`, `fontsdir`) burns captions and the hook, `loudnorm` (`I`, `TP`, `LRA`, `measured_I`, `measured_TP`, `measured_LRA`, `measured_thresh`, `offset`, `print_format`), `sidechaincompress` (`threshold`, `ratio`, `attack`, `release`, `makeup`, `level_sc`), `amix` (`duration`, `normalize`, `dropout_transition`), `volume`, `silencedetect` (`noise`, `d`), `aformat` (`channel_layouts` on ffmpeg 6, `channel_layout` when that list is gone), `fps`, `tpad` (`stop_mode=clone`), `apad` (`whole_dur`). Encoders: `libx264`, `aac`. drawtext is not on the hook path.

auto-editor 29.3.1 `--help` (this repo pins `>=29,<30`) accepts `--edit none`, `--margin 0`, `--frame-rate N`, repeated `--cut-out START,END` with integer frames, `--export premiere` (FCP 7 xmeml), and `--export final-cut-pro` (FCPXML 1.11). It does not accept `edl`, `otio`, `resolve-fcp7`, `premiere-otio`, or `version=`. Those are not passed.

## Remotion 4.0.541

`npx remotion render --help` lists `--props`, `--codec`, `--pixel-format`, `--crf`, `--concurrency`, `--disallow-parallel-encoding`, `--log`. Chrome for the render is installed with `npx remotion browser ensure`.

## faster-whisper 1.2.1

Library, not a CLI. See [transcription.md](transcription.md).

## WhisperX

Not installed in the environment that verified the other tools. The script shells out only with flags present in that machine's `whisperx --help` (`--model`, and when listed `--language`, `--device`, `--compute_type`, `--output_format`, `--output_dir`, `--initial_prompt`). Do not hard-code a flag you have not seen in `--help`.
