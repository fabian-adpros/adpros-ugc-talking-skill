# Transcription

Output, always on the source timeline:

- `words.json` — word start/end in seconds, engine, model, device, language
- `raw.srt` — one cue per Whisper segment
- `words.srt` — one cue per word
- `transcript.txt` — the words in order
- `audio.wav` — 16 kHz mono, extracted with ffmpeg before the model runs

## Which engine

`--transcribe-engine auto` (the default) runs `whisperx --help` when the binary exists and builds the command from flags that help text actually lists. If WhisperX is missing or exits non-zero, faster-whisper runs in-process. `--transcribe-engine faster-whisper` skips the attempt. `--transcribe-engine whisperx` fails instead of falling back.

## Device

CTranslate2's `get_cuda_device_count()` picks the device. CUDA uses `float16`. CPU uses `int8`. `--device cpu` or `--device cuda` overrides that. GPU model default is `large-v3`. CPU default is `small`.

## Language

`--lang auto` lets the model detect. `--lang en` or `--lang es` forces it. The detected code is stored on `words.json` and selects the filler list and the hook language. Anything other than `en` or `es` is planned with the English filler list and a warning. This skill does not translate.

## Keeping fillers

Whisper is trained to write clean prose. It often deletes `um`, `uh`, `eh`, `mmm` before any script can cut them. Two settings push back, and neither is reliable:

- `initial_prompt` includes a short filler phrase in the clip's language (`Eh, este, o sea...` or `Um, uh, erm...`). faster-whisper applies that prompt to the first window. It can also hallucinate those words, so the phrase stays short.
- `vad_filter` stays off. A VAD that thinks a short `eh` is non-speech will drop it. Turn it on in `assets/preset.json` under `transcription.vad_filter` only when the clip is noisy and you care more about false words than about fillers.

`hotwords` exists on faster-whisper 1.2.1 and is left unset. It biases the decoder harder than `initial_prompt` and invents fillers that were never spoken.

If the last word lands before 72% of the file, the script transcribes again without `initial_prompt` and keeps the longer result. The filler prompt can make the decoder stop early. The plan warning says when that retry happened.

If `plan.json` warns that no listed filler was in the transcript, believe it. Tell the user. Do not report those words as removed.

## faster-whisper call

Verified against faster-whisper 1.2.1 by reading `WhisperModel.transcribe`. There is no CLI in that package. The audio is passed as a float32 numpy array decoded by ffmpeg. faster-whisper 1.2.1 would otherwise call `av.open(..., metadata_errors="ignore")`, and PyAV 19 removed that keyword.

- `word_timestamps=True`
- `temperature=0.0`
- `condition_on_previous_text=True`
- `vad_filter=False` unless the preset says otherwise
- `beam_size` from the preset (5)
- `language` only when the user set `en` or `es`
- `initial_prompt` as above
