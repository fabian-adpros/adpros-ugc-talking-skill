# Style, safe zones, music

Canvas is 1080×1920. Captions are bold, two or three words at a time, horizontally centered. The default `captions.y_ratio` is 0.75, so the line sits in the lower safe area rather than across the face. There is no face detection. The active word is `#FFE14A` when `captions.highlight_active_word` is true. The hook sits higher, on a dark plate, for the first 3 seconds.

## Safe zone

Phone UI covers the edges. The preset `safe_zone` is the union of Reels and TikTok, in pixels of a 1080×1920 frame:

| Edge | Pixels | What sits there |
| --- | --- | --- |
| Top | 250 | Reels profile and audio sticker; TikTok following/live is closer to 150. The hook starts at `max(250, 0.16×1920)` ≈ 307. |
| Bottom | 420 | Username, caption, music ticker, home indicator. Default captions sit just above this band (`y_ratio` 0.75 → center near 1440). |
| Left | 80 | Small margin. |
| Right | 140 | Like, comment, and share. Captions are centered inside the inset, not under the buttons. |

Do not move the hook into the top 250px or the captions into the bottom 420px.

## Remotion (primary)

`template/` is a Remotion 4 composition, id `TalkingHead`. The pipeline copies the cut video, the looped bed, and Inter Bold into `template/public/`, writes `props.json`, and runs:

```bash
npx remotion render src/index.ts TalkingHead OUT.mp4 --props=props.json \
  --codec=h264 --pixel-format=yuv420p --crf=18 --concurrency=1 \
  --disallow-parallel-encoding
```

Those flags were read from `npx remotion render --help` on Remotion 4.0.541. Props carry the captions, the hook, `musicVolume` (`10^(duck_db/20)`, so −18 dB is about 0.126), and the safe-zone insets. The font is loaded with `FontFace` from `public/fonts/Inter-Bold.ttf` (Latin-1, enough for English and Spanish accents).

If `template/node_modules/remotion` is missing, or the render exits non-zero, and the user did not pass `--renderer remotion`, the pipeline renders with FFmpeg instead and records the fallback.

Remotion is free for an individual or a for-profit team of up to 3 people, including commercial use. Larger companies need a Remotion company license. See the credits in the README.

## FFmpeg (fallback)

`--renderer ffmpeg` burns:

- `captions.ass` through the `subtitles` filter (`fontsdir` points at Inter Bold). Each caption dialogue uses `\an5\pos` at the safe-zone center from `captions.y_ratio`. Active-word events swap the ASS primary colour to `&H004AE1FF` (BGR for `#FFE14A`).
- The hook is another dialogue in that same file (`\an8\pos`, opaque box). Apostrophes and `¿` `¡` stay in the text. drawtext is not used for the hook, because its `text_align` and `enable` syntax is not the same on every ffmpeg build and can omit the plate while libass captions still appear.
- The bed with `volume=-18dB` and `amix=normalize=0`, so the voice is not scaled down and the bed sits 18 dB under it.

`music.engine=sidechain` uses `sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300:makeup=1` on a bed that is already at −18 dB, so speech pushes the bed a bit lower and pauses let it back up. The default is the static −18 dB cut, which is the one that matches the number.

## Music file

`music.file` null means `assets/music/bed.m4a`, an original 8-second chord loop generated for this repo (no third-party track). `--music path` replaces it. The file is looped to the cut duration. If you pass a track you do not have rights to, that is on you; the skill does not ship commercial music.
