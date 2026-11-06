"""Shipped runtime files. No network and no ffmpeg."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "ugc-talking-head"

TTF_MAGIC = b"\x00\x01\x00\x00"


def _ftyp(path: Path) -> None:
    blob = path.read_bytes()
    assert len(blob) > 1000, path
    assert blob[4:8] == b"ftyp", path


def test_inter_font_and_license_are_real_files():
    font = SKILL / "assets" / "fonts" / "Inter-Bold.ttf"
    public = SKILL / "template" / "public" / "fonts" / "Inter-Bold.ttf"
    license_text = (SKILL / "assets" / "fonts" / "OFL.txt").read_text(encoding="utf-8")
    assert font.read_bytes()[:4] == TTF_MAGIC
    assert font.read_bytes() == public.read_bytes()
    assert "SIL OPEN FONT LICENSE" in license_text


def test_music_bed_and_placeholder_are_media_files():
    _ftyp(SKILL / "assets" / "music" / "bed.m4a")
    _ftyp(SKILL / "template" / "public" / "placeholder.mp4")


def test_package_lock_pins_remotion():
    lock_path = SKILL / "template" / "package-lock.json"
    package = json.loads((SKILL / "template" / "package.json").read_text(encoding="utf-8"))
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    root = lock["packages"][""]
    assert lock["lockfileVersion"] == 3
    assert lock["name"] == package["name"] == "ugc-talking-head-template"
    assert root["dependencies"]["remotion"] == package["dependencies"]["remotion"] == "4.0.541"
    assert root["dependencies"]["@remotion/cli"] == "4.0.541"
    assert len(lock["packages"]) > 10


def test_technical_demos_are_present():
    for name in ("es.mp4", "en.mp4"):
        _ftyp(ROOT / "examples" / "demo" / name)
