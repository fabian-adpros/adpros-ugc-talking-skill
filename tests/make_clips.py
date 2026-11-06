#!/usr/bin/env python3
"""Synthetic 9:16 talking-head clips with pauses and fillers.

Prefers gTTS (clearer for Whisper). Falls back to espeak-ng.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ES = [
    ("Hola.", 0.75),
    ("Hoy te muestro cómo ahorrar tiempo editando.", 0.22),
    ("Este, o sea, el truco es una sola toma.", 0.85),
    ("Eh, pues funciona en el celular.", 0.2),
    ("Publica hoy mismo.", 0.8),
]

EN = [
    ("Hey.", 0.75),
    ("Today I'll show you the fastest way to edit.", 0.22),
    ("Um, you know, it takes a single take.", 0.85),
    ("Uh, I mean, it works on your phone.", 0.2),
    ("Post it today.", 0.8),
]


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def silence(path: Path, seconds: float) -> None:
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=mono",
            "-t",
            f"{seconds:.3f}",
            "-c:a",
            "pcm_s16le",
            str(path),
        ]
    )


def tts_gtts(text: str, lang: str, dest_wav: Path) -> None:
    from gtts import gTTS

    mp3 = dest_wav.with_suffix(".mp3")
    gTTS(text=text, lang=lang).save(str(mp3))
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(mp3),
            "-ar",
            "48000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(dest_wav),
        ]
    )


def tts_espeak(text: str, lang: str, dest_wav: Path) -> None:
    voice = "es-419" if lang == "es" else "en-us"
    run(["espeak-ng", "-v", voice, "-s", "145", "-w", str(dest_wav), text])
    # espeak's sample rate varies. Normalize.
    normalized = dest_wav.with_suffix(".norm.wav")
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(dest_wav),
            "-ar",
            "48000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(normalized),
        ]
    )
    normalized.replace(dest_wav)


def build(name: str, lang: str, lines: list[tuple[str, float]], dest: Path, engine: str) -> None:
    work = dest.parent / f".{name}-parts"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    pieces: list[Path] = []
    lead = work / "lead.wav"
    silence(lead, 0.65)
    pieces.append(lead)
    for index, (text, pause) in enumerate(lines):
        wav = work / f"line{index}.wav"
        if engine == "gtts":
            tts_gtts(text, lang, wav)
        else:
            tts_espeak(text, lang, wav)
        pieces.append(wav)
        if pause > 0:
            gap = work / f"gap{index}.wav"
            silence(gap, pause)
            pieces.append(gap)
    listing = work / "list.txt"
    listing.write_text("".join(f"file '{piece}'\n" for piece in pieces), encoding="utf-8")
    audio = work / "voice.wav"
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-c",
            "copy",
            str(audio),
        ]
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(audio),
            "-f",
            "lavfi",
            "-i",
            "color=c=0x141820:s=1080x1920:r=30",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(dest),
        ]
    )
    print(dest)


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "examples/raw")
    engine = "gtts"
    try:
        import gtts  # noqa: F401
    except ImportError:
        engine = "espeak"
    if engine == "gtts":
        try:
            # Probe once so a network failure falls back before a half-built clip.
            from gtts import gTTS

            gTTS("hola", lang="es")
        except Exception as exc:
            print(f"gTTS unavailable ({exc}); using espeak-ng", file=sys.stderr)
            engine = "espeak"
    build("es", "es", ES, out / "es.mp4", engine)
    build("en", "en", EN, out / "en.mp4", engine)


if __name__ == "__main__":
    main()
