"""Rendered captions, hook text, and cut sync. Needs ffmpeg."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "skills" / "adpros-ugc-talking-skill" / "scripts"
sys.path.insert(0, str(ROOT))

from lib.config import DEFAULTS  # noqa: E402
from lib.edit import build_ass, caption_center  # noqa: E402
from lib.render import cut_video, segment_frames, style_ffmpeg  # noqa: E402

SAFE = {"top": 250, "bottom": 420, "left": 80, "right": 140}
pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _streams(path: Path) -> dict[str, float]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,duration,nb_frames,start_time",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    info: dict[str, float] = {}
    for stream in json.loads(completed.stdout)["streams"]:
        info[stream["codec_type"]] = float(stream.get("duration") or 0)
        info[stream["codec_type"] + "_start"] = float(stream.get("start_time") or 0)
        info[stream["codec_type"] + "_frames"] = float(stream.get("nb_frames") or 0)
    return info


def _color_clip(path: Path, seconds: float, size: str, codec: list[str]) -> None:
    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x203040:s={size}:r=30:d={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={seconds}",
            *codec,
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ]
    )


def _assert_locked(path: Path, ranges: list[dict], fps: int = 30) -> None:
    expected = sum(segment_frames(item["src_start"], item["src_end"], fps)[1] for item in ranges)
    info = _streams(path)
    assert abs(info["video"] - info["audio"]) < 1.5 / fps
    assert abs(info["video"] - expected) < 1.5 / fps
    assert abs(info["video_start"]) < 0.02
    assert abs(info["audio_start"]) < 0.02
    assert abs(info["video_frames"] - round(expected * fps)) <= 1


def test_default_caption_center_is_in_the_lower_safe_area():
    _x, y = caption_center(1080, 1920, 0.75, 72, SAFE)
    assert 1300 < y < 1920 - 420


def test_explicit_center_ratio_stays_when_it_is_inside_the_safe_zone():
    _x, y = caption_center(1080, 1920, 0.46, 72, SAFE)
    assert abs(y - round(0.46 * 1920)) <= 1


def test_ass_hook_keeps_spanish_punctuation_and_apostrophes():
    hook = "¿Hoy te muestro? It's today's plan"
    ass = build_ass(
        [
            {
                "start": 0.1,
                "end": 1.2,
                "words": [
                    {"text": "cómo", "start": 0.1, "end": 0.6},
                    {"text": "ahorrar", "start": 0.6, "end": 1.2},
                ],
            }
        ],
        "Inter",
        72,
        "#FFFFFF",
        "#FFE14A",
        True,
        caption_xy=(540, 1440),
        hook_text=hook,
        hook_end=3,
        hook_xy=(540, 307),
        hook_font_size=62,
    )
    assert hook in ass
    assert r"{\an8\pos(540,307)}" in ass
    assert r"{\an5\pos(540,1440)}" in ass
    assert "Dialogue: 1," in ass


def test_short_cuts_keep_audio_and_video_on_one_clock(tmp_path: Path):
    src = tmp_path / "cfr.mp4"
    _color_clip(src, 6, "160x284", ["-c:v", "libx264", "-preset", "veryfast", "-crf", "36"])
    ranges = []
    cursor = 0.0
    for _ in range(80):
        ranges.append({"src_start": cursor, "src_end": cursor + 0.051})
        cursor += 0.051
    dest = tmp_path / "cut.mp4"
    cut_video(src, dest, ranges, 160, 284, 30, 36, "64k")
    _assert_locked(dest, ranges)


def test_hevc_short_cuts_keep_audio_and_video_on_one_clock(tmp_path: Path):
    encoders = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if "libx265" not in encoders:
        pytest.skip("libx265 is not available")
    src = tmp_path / "hevc.mp4"
    _color_clip(
        src,
        6,
        "160x284",
        ["-c:v", "libx265", "-preset", "ultrafast", "-crf", "36", "-tag:v", "hvc1"],
    )
    ranges = []
    cursor = 0.05
    for index in range(40):
        span = 0.07 if index % 2 == 0 else 0.12
        ranges.append({"src_start": cursor, "src_end": cursor + span})
        cursor += span + 0.04
    dest = tmp_path / "cut-hevc.mp4"
    cut_video(src, dest, ranges, 160, 284, 30, 36, "64k")
    _assert_locked(dest, ranges)


def test_ffmpeg_frame_places_hook_above_and_captions_below_center(tmp_path: Path):
    src = tmp_path / "full.mp4"
    _color_clip(src, 2, "1080x1920", ["-c:v", "libx264", "-preset", "veryfast", "-crf", "32"])
    preset = json.loads(json.dumps(DEFAULTS))
    preset["export"]["crf"] = 30
    plan = {
        "captions": [
            {
                "start": 0.1,
                "end": 1.8,
                "words": [
                    {"text": "cómo", "start": 0.1, "end": 0.7},
                    {"text": "ahorrar", "start": 0.7, "end": 1.8},
                ],
            }
        ],
        "hook": {"text": "¿Hoy te muestro? It's today's plan", "start": 0, "end": 3},
    }
    styled = tmp_path / "styled.mp4"
    info = style_ffmpeg(src, styled, plan, preset, None, tmp_path / "work")
    assert info["hook"] == "libass"
    assert info["caption_xy"][1] > 1300
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-ss",
            "0.45",
            "-i",
            str(styled),
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout
    width, height = 1080, 1920
    assert len(raw) == width * height * 3

    def bright(y0: int, y1: int) -> int:
        count = 0
        for y in range(y0, y1):
            row = raw[y * width * 3 : (y + 1) * width * 3]
            for x in range(0, width * 3, 3):
                red, green, blue = row[x], row[x + 1], row[x + 2]
                if red + green + blue > 420 or (red > 190 and green > 160 and blue < 90):
                    count += 1
        return count

    hook_band = bright(280, 520)
    face_band = bright(820, 1100)
    lower_band = bright(1320, 1580)
    assert hook_band > 80, hook_band
    assert lower_band > 80, lower_band
    assert hook_band > face_band * 3
    assert lower_band > face_band * 3
    ass = (tmp_path / "work" / "captions.ass").read_text(encoding="utf-8")
    assert "¿Hoy" in ass
    assert "It's" in ass
    assert "today's" in ass
    assert "Dialogue: 1," in ass
