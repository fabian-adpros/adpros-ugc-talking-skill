# Export

`final.mp4` is the file you hand back.

- 1080×1920, H.264 (`libx264`, CRF 18, `yuv420p`) and AAC (192 kbps, 48 kHz, stereo)
- `+faststart` so it plays before the download finishes
- Loudness about **−14 LUFS** integrated, true peak **−1.5 dBTP**, LRA 11, via two-pass `loudnorm`. The measured LUFS is printed and stored in `export.json`. A value a few tenths off −14 is normal.
- Duration target **60 seconds**. When the edited cut is longer and `export.trim_if_over` is true (the default), export trims to `export.max_duration` with a 0.3s audio fade and the plan warns before the render. `--no-trim` keeps the full cut and only warns. `--max-duration 45` changes the cap for one run.

Order of work: cut to the kept ranges → style (captions, hook, bed) → trim if needed → loudnorm. Loudness is measured on the file the viewer will hear, bed included.

`frame.png` is one frame inside the hook window, chosen at the first caption when that caption starts before the hook ends. Use it to check that the hook and the captions are both readable.
