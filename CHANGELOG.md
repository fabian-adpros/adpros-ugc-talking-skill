# Changelog

## 0.3.1

- The cut decodes the source once and encodes every kept range in that same ffmpeg process, at CRF 18 / `veryfast` (or VideoToolbox H.264 on a Mac when that encoder exists). Do not hand-roll one ffmpeg per segment.
- Default silence padding is 0.12s, each join fades for 15ms, and a cut that still lands on speech is widened before the encode.
- Before background removal the script prints the device, frame count, and a CPU time estimate. A CPU estimate longer than about 3 minutes stops (exit 14) so you can continue, switch to U2-Net, lower the inference size, or skip. MPS is selected on Apple Silicon when PyTorch reports it; that speed was not measured.
- `./install.sh --with-bg` runs only when a background was requested, and it starts in the background while transcription and the cut continue.
- If BiRefNet crashes on Apple's GPU, the error is written to `bg-infer.log` and the run stops for a decision instead of silently spending half an hour on the CPU. The model is loaded in fp32, with `PYTORCH_ENABLE_MPS_FALLBACK=1`. That crash path was not re-run on a Mac here.
- `apple-vision` is a macOS-only person matte (Vision, quality `.accurate`). On one Mac clip it took 30 frames in 7 s, about 0.24 s/frame, about 5 minutes for 1,270 frames. Face, hair, and hands held; the shirt edge was a little rougher. It segments people only, so a product in the hand can disappear. It was not run in CI.
- `--bg-moments 0-3,12-15,20-23` segments only those stretches. The original picture stays everywhere else, with a short ramp at each edge.
- Each stage prints one short model tip: a lighter model for mechanical steps, a top model for hook, storyboard, background review, and the final look. In Claude Code, `/model` applies on the next message and the chat stays.

## 0.3.0

- Optional background replacement with `backgroundremover` and U2-Net. The default model is `u2net`, not the person-only net, so a product in the hand is less likely to disappear. `--bg`, `--bg transparent`, and `--bg-threshold` run after the cuts and before captions. Exit 13 shows side-by-side preview frames. `./install.sh --with-bg` installs it. `export --nle` also copies the alpha, the matte, and the plate.
- Every stage prints a `next_steps` list in the clip's language and stores it on `plan.json`.
- Frame-by-frame removal can flicker. Apple Silicon speed was not tested. Grounded-SAM-2 is the next step if a hand-held product still drops out.
- Preview times stop two frames before the end, JPEG previews are full-range, and one missed frame does not abort the preview. ffmpeg failures stay short and point at `ugc-ffmpeg.log`.
- A storyboard rewrite keeps existing vision labels. An unchanged cut is not encoded again, so approving the background does not rerun U2-Net.
- When the Python package imports, U2-Net runs at `bg.infer_size` (default 320, aspect kept) instead of backgroundremover's 320-square path, then a temporal median and a close. The guided filter is off. Timings are printed, including when a matte is reused.
- `bg.engine` selects `birefnet` (default, MIT `ZhengPeng7/BiRefNet_lite` revision `aa62cd87eafb`), `ben2` (optional MIT base), or `u2net`. Device order is MPS, then CUDA, then CPU. On a real 11 s clip (331 frames, CPU, short side 320) BiRefNet_lite took about 1.05 s/frame, about 6 minutes. The U2-Net CLI took about 72 s. Apple Silicon MPS was not timed. A black shirt, a black product box, and a waving hand stayed solid; a brief leak around 5.0 s during a lift remained.
- `./install.sh --with-bg` no longer pins `numpy<2`. If those packages fail, the script exits non-zero. Exit 13 names the engine that ran, and its follow-ups are `--bg-engine u2net`, `--bg-engine ben2`, `--bg-infer-size`, and `--bg-smooth`.

## 0.2.2

- `storyboard --inline` writes `storyboard.inline.html`: one file, inline CSS, JPEG thumbnails as data URIs, no network. The local `storyboard.html` plus `thumbs/` stays the default. `storyboard.md` is a chat summary.
- The inline page stays under `storyboard.inline_max_bytes` by shrinking or dropping thumbnails. Showing it as a Claude.ai artifact was not verified.

## 0.2.1

- FCPXML asset duration is the full conformed source, and the file is marked 1.10 so a clip near the end of an iPhone file stays inside the asset.
- `install.sh --with-otio` allows OpenTimelineIO 0.18.x. `doctor.sh` prints that version.
- After the hook is approved, exit 11 asks whether to write editor files, which editors, and whether to review the storyboard. Exit 12 waits on that storyboard. `--yes` uses the preset and does not ask. Answers are stored on the plan.

## 0.2.0

- `ugc_edit.py storyboard` writes `export/storyboard.json`, an HTML timeline, a CSV shot list, thumbnails, a contact sheet, edited-timeline SRT files, and `RELINK.md`.
- `ugc_edit.py export --nle` writes a constant-frame-rate media copy plus Premiere FCP 7 XML and FCPXML 1.11 from auto-editor 29. OpenTimelineIO, CMX EDL, and the XML adapter fallbacks are optional via `install.sh --with-otio`.
- Optional `--vision-labels` merges a closed set of still-frame labels. Low-confidence `product_reveal` does not become a marker.

## 0.1.2

- Captions default to the lower safe area. The hook is burned with libass. Each silence cut shares one frame duration for audio and video.

## 0.1.1

- Public skill id is `adpros-ugc-talking-skill`.

## 0.1.0

- First downloadable archive of the talking-head pipeline.
