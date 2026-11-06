# Troubleshooting

| What you see | What to do |
| --- | --- |
| Exit 10 | Not an error. Read the plan to the user and wait. |
| `faster-whisper is not installed` | `bash install.sh`, then call `.venv/bin/python`, not system `python3`. |
| Transcription sits with no output | The model is downloading. See [setup.md](setup.md). Do not kill it on the first run. |
| `No transcription engine succeeded` | doctor.sh. On CPU, retry with `--model tiny` if the download of `small` failed. |
| Empty transcript | The clip has no usable voice, or `--lang` is wrong. Try `--lang es` or `--lang en`. |
| `auto-editor` unknown option `--smooth` | Expected on 29.3.1. The script does not pass `--smooth`. Update the script if you are on a different version whose `--help` shows it. |
| auto-editor removed almost everything | The threshold is too high for a quiet mic, or too low for a noisy room. The 70% guard falls back to word gaps. Or set `--silence-engine words`, or change `silence.audio_threshold`. |
| Pauses remain | Whisper timestamps covered the pause, and you used `--silence-engine words`. Use the default `auto` engine. |
| Fillers still in the cut | They were not in `words.json`. See [fillers.md](fillers.md). A larger model (`small` or `large-v3`) keeps them more often than `tiny`. |
| A real word was cut (`este producto`, `I like this`) | That is a bug if it happens in conservative mode. Check `fillers.json`. Standalone phrases need air around them. |
| Remotion fails, FFmpeg succeeds | Tell the user which renderer ran. `npx remotion browser ensure` inside `template/` fixes a missing Chrome. Render with `--concurrency=1` is already the default here because 1080×1920 is heavy. |
| `subtitles` missing | The ffmpeg build has no libass. Captions and the hook both need it. Reinstall ffmpeg from Homebrew or a full apt build. doctor.sh checks it. drawtext is optional. |
| Captions cover the face | `captions.y_ratio` 0.46 was the old vertical center. The shipped default is 0.75, just above the bottom safe margin. Set the key in a preset to move the line. The script does not find a face. |
| Hook missing, captions present | The hook is a libass line in `captions.ass`, including apostrophes and `¿` `¡`. If that file has no `Dialogue: 1`, the plan had no hook text. |
| Voice slips later than the picture | Each kept slice is quantized to whole output frames and the audio is padded or trimmed to that same duration before concat. A variable-frame-rate HEVC phone clip used to let those slices diverge. auto-editor saying `Decoder not found` means the cut used word gaps; it does not by itself resync the streams. |
| macOS not rechecked here | Caption placement, the libass hook, and the sync lock were rendered with ffmpeg on Linux. They were not run on a Mac. |
| Loudness far from −14 LUFS | Open `export.json`. Speech plus a quiet bed should land near −14. A clip that is mostly silence before the cut can miss. Re-run export; do not manually add gain on top of loudnorm. |
| Output longer than 60s | The plan's `trim.will_trim` should be true. Pass `--max-duration 60` or leave the default. `--no-trim` keeps it long on purpose. |
| Vertical video looks sideways | ffmpeg autorotates on decode. If a file stays sideways, the phone tagged rotation in a way this ffmpeg ignored. Re-export from the camera roll without the rotation tag, then rerun. |
| claude.ai cannot render | The sandbox usually has no ffmpeg or Whisper. Use Claude Code on the installed machine. |

Do not paper over a failed command by reimplementing the cut with guessed ffmpeg. Fix the flag or the input and run the script again.
