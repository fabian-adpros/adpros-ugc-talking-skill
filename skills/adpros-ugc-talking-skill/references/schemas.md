# JSON files

UTF-8, times in seconds.

## words.json

```json
{
  "language": "es",
  "language_probability": 0.97,
  "engine": "faster-whisper",
  "model": "small",
  "device": "cpu",
  "compute_type": "int8",
  "duration": 16.1,
  "prompt": "Eh, este, o sea, pues, bueno, mmm, digamos, tipo, me entiendes.",
  "source": "/abs/clip.mp4",
  "segments": [{"start": 0.1, "end": 2.0, "text": "Hoy te muestro"}],
  "words": [{"word": "Hoy", "start": 0.1, "end": 0.4, "probability": 0.91}],
  "warnings": []
}
```

## plan.json

Produced before the render. This is the approval payload.

- `source_duration`, `output_duration`
- `silence_engine`: `auto-editor` or `words`
- `filler_mode`: `conservative` or `aggressive`
- `silence.cuts[]`: `{start, end}` on the source timeline
- `fillers.items[]`: `{text, start, end, tier}`
- `kept_ranges[]`: `{src_start, src_end, dst_start, dst_end}`
- `words[]`: remapped onto the output timeline, fillers already gone
- `captions[]`: `{start, end, words: [{text, start, end}]}` with 2–3 words
- `hook`: `{text, start, end, alternates, reason}`
- `trim`: `{max_duration, will_trim}`
- `warnings[]`

## props.json

What Remotion receives. `videoSrc` and `musicSrc` are filenames inside `template/public/`, not absolute paths. `musicVolume` is a linear gain.

## export.json

`final`, `frame`, `duration`, `width`, `height`, `lufs`, `true_peak`, `trimmed`, `renderer`.
