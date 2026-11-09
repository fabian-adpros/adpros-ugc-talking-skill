# Export

`final.mp4` is the file you hand back.

- 1080×1920, H.264 (`libx264`, CRF 18, `yuv420p`) and AAC (192 kbps, 48 kHz, stereo)
- `+faststart` so it plays before the download finishes
- Loudness about **−14 LUFS** integrated, true peak **−1.5 dBTP**, LRA 11, via two-pass `loudnorm`. The measured LUFS is printed and stored in `export.json`. A value a few tenths off −14 is normal.
- Duration target **60 seconds**. When the edited cut is longer and `export.trim_if_over` is true (the default), export trims to `export.max_duration` with a 0.3s audio fade and the plan warns before the render. `--no-trim` keeps the full cut and only warns. `--max-duration 45` changes the cap for one run.

Order of work: cut to the kept ranges → style (captions, hook, bed) → trim if needed → loudnorm. Loudness is measured on the file the viewer will hear, bed included.

`frame.png` is one frame inside the hook window, chosen at the first caption when that caption starts before the hook ends. Use it to check that the hook and the captions are both readable.

## Storyboard and editor files

`ugc_edit.py storyboard --workdir DIR` reads `plan.json` and writes `DIR/export/`, including `storyboard.md` for the chat. `--inline` also writes `storyboard.inline.html` (self-contained, no local image links). The multi-file `storyboard.html` remains the local page. `ugc_edit.py export --workdir DIR --nle all` conforms the source to the preset frame rate first (constant frame rate, so an iPhone variable-frame-rate HEVC file does not drift inside the NLE) and then writes:

- `project_premiere.xml` — FCP 7 xmeml from auto-editor 29. This is not FCPXML.
- `project.fcpxml` — auto-editor 29 emits FCPXML 1.11 and sets the asset duration to the edited timeline. This skill rewrites the asset duration to the full conformed source, then sets `version="1.10"` because that document validates against Apple's FCPXML 1.10 DTD (checked locally; the DTD is Apple copyright and is not vendored). Resolve 18/19 and Final Cut import 1.10. The same file is what DaVinci Resolve opens.
- `timeline.otio` and `project.edl` only when OpenTimelineIO and `otio-cmx3600-adapter` import. `./install.sh --with-otio` installs `opentimelineio>=0.17,<0.19` (0.18.1 has a Python 3.13 wheel), `otio-cmx3600-adapter`, `otio-fcp-adapter`, and `otio-fcpx-xml-adapter`. The OpenTimelineIO-Plugins bundle does not include `otio-fcpx-xml-adapter`. `doctor.sh` prints the installed OpenTimelineIO version.
- `media/source.mp4`, `media/music.m4a`, and `media/preview.mp4` when `final.mp4` already exists.

`captions.srt` and `hook.srt` are in edited-timeline time. CapCut has no project format here, and CapCut mobile does not import SRT. See the generated `RELINK.md`.
