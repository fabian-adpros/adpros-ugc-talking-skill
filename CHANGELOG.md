# Changelog

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
