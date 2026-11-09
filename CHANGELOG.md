# Changelog

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
