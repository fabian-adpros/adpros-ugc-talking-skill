# Export

`final.mp4` is the file you hand back.

- 1080×1920, H.264 (`libx264`, CRF 18, `yuv420p`) and AAC (192 kbps, 48 kHz, stereo)
- `+faststart` so it plays before the download finishes
- Loudness about **−14 LUFS** integrated, true peak **−1.5 dBTP**, LRA 11, via two-pass `loudnorm`. The measured LUFS is printed and stored in `export.json`. A value a few tenths off −14 is normal.
- Duration target **60 seconds**. When the edited cut is longer and `export.trim_if_over` is true (the default), export trims to `export.max_duration` with a 0.3s audio fade and the plan warns before the render. `--no-trim` keeps the full cut and only warns. `--max-duration 45` changes the cap for one run.

Order of work: cut to the kept ranges → optional background matte and composite → style (captions, hook, bed) → trim if needed → loudnorm. Loudness is measured on the file the viewer will hear, bed included. Captions are burned after the matte, so the key does not erase them.

`--bg PATH` replaces the background. The plate is scaled and cropped to 1080×1920, and a video plate is looped or trimmed to the cut. `--bg transparent` writes `subject.mov` as ProRes 4444 with alpha (`prores_ks`, `yuva444p10le`, profile 4). The styled MP4 for that mode is the subject over black, with captions. The alpha file itself has no burned captions; use the SRT. `--bg-model` defaults to `u2net`. `u2net_human_seg` is person-only and can erase a product in the hand. `--bg-threshold N` (0–255) binarizes the matte in ffmpeg. The upstream video flags `-tv` and `-mk` do not forward the image-only `-mt` flag, so the threshold is applied here.

`bg.engine` defaults to `birefnet` (`ZhengPeng7/BiRefNet_lite`, MIT). `ben2` is the MIT base `PramaLLC/BEN2` when that package is installed. `u2net` is the fallback. `bg.infer_size` (default 320, `--bg-infer-size`) is the short side, aspect preserved. backgroundremover's own path still squares to 320 and is only the fallback when no Python engine imports. `bg.temporal_smooth` (default 3) is a median. The matte is scaled to the cut before compositing. `bg.refine` is false. `--bg-refine` blurs the alpha only. The guided filter is not used. The command prints `bg: ... per_frame=...s`, or `bg: reused the existing matte` when the matte stamp matches.

Removal can still flicker on a waving hand or a product. Grounded-SAM-2 is the next step for a prompted person-plus-product track. Apple Silicon was not tested.

Exit 13 shows 3–5 side-by-side preview frames and waits. `--yes` skips that and keeps the original background unless the preset enables one. `--bg-yes` approves the preview. `--bg-skip` keeps the original.

`frame.png` is one frame inside the hook window, chosen at the first caption when that caption starts before the hook ends. Use it to check that the hook and the captions are both readable.

## Storyboard and editor files

`ugc_edit.py storyboard --workdir DIR` reads `plan.json` and writes `DIR/export/`, including `storyboard.md` for the chat. `--inline` also writes `storyboard.inline.html` (self-contained, no local image links). The multi-file `storyboard.html` remains the local page. `ugc_edit.py export --workdir DIR --nle all` conforms the source to the preset frame rate first (constant frame rate, so an iPhone variable-frame-rate HEVC file does not drift inside the NLE) and then writes:

- `project_premiere.xml` — FCP 7 xmeml from auto-editor 29. This is not FCPXML.
- `project.fcpxml` — auto-editor 29 emits FCPXML 1.11 and sets the asset duration to the edited timeline. This skill rewrites the asset duration to the full conformed source, then sets `version="1.10"` because that document validates against Apple's FCPXML 1.10 DTD (checked locally; the DTD is Apple copyright and is not vendored). Resolve 18/19 and Final Cut import 1.10. The same file is what DaVinci Resolve opens.
- `timeline.otio` and `project.edl` only when OpenTimelineIO and `otio-cmx3600-adapter` import. `./install.sh --with-otio` installs `opentimelineio>=0.17,<0.19` (0.18.1 has a Python 3.13 wheel), `otio-cmx3600-adapter`, `otio-fcp-adapter`, and `otio-fcpx-xml-adapter`. The OpenTimelineIO-Plugins bundle does not include `otio-fcpx-xml-adapter`. `doctor.sh` prints the installed OpenTimelineIO version.
- `media/source.mp4`, `media/music.m4a`, and `media/preview.mp4` when `final.mp4` already exists.

`captions.srt` and `hook.srt` are in edited-timeline time. CapCut has no project format here, and CapCut mobile does not import SRT. See the generated `RELINK.md`.

When `plan.json` has `bg.enabled` and the mode is not `keep`, the same export also copies `media/subject.mov` (ProRes 4444 alpha, no captions), `media/matte.mp4`, and `media/background.*` for a replacement plate. Those files are not inside the auto-editor sequence. Relink them beside `media/source.mp4`.
