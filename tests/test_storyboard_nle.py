"""Storyboard and NLE export on a generated clip. No personal media."""

from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "skills" / "adpros-ugc-talking-skill" / "scripts"
sys.path.insert(0, str(ROOT))

from lib.config import DEFAULTS  # noqa: E402
from lib.nle import export_nle  # noqa: E402
from lib.storyboard import align_kept, build_storyboard, cut_out_frames, write_storyboard  # noqa: E402

UGC = Path(__file__).resolve().parents[1] / "skills" / "adpros-ugc-talking-skill" / "scripts" / "ugc_edit.py"


def _clip(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x224466:s=320x180:r=30:d=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=4",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "34",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
    )


def _plan(source: Path) -> dict:
    return {
        "version": 1,
        "language": "es",
        "source": str(source),
        "source_duration": 4.0,
        "output_duration": 2.4,
        "silence": {"cuts": [{"start": 1.0, "end": 1.8}, {"start": 3.2, "end": 4.0}]},
        "fillers": {"items": [{"text": "eh", "start": 2.2, "end": 2.4, "tier": "clear"}]},
        "kept_ranges": [
            {"src_start": 0.0, "src_end": 1.0, "dst_start": 0.0, "dst_end": 1.0},
            {"src_start": 1.8, "src_end": 2.2, "dst_start": 1.0, "dst_end": 1.4},
            {"src_start": 2.4, "src_end": 3.2, "dst_start": 1.4, "dst_end": 2.2},
        ],
        "captions": [
            {
                "start": 0.1,
                "end": 0.9,
                "words": [
                    {"text": "cómo", "start": 0.1, "end": 0.4},
                    {"text": "ahorrar", "start": 0.4, "end": 0.9},
                ],
            }
        ],
        "hook": {"text": "¿Hoy te muestro? It's today's", "start": 0, "end": 3, "reason": "user"},
        "warnings": [],
    }


def _workdir(tmp_path: Path) -> Path:
    source = tmp_path / "clip.mp4"
    _clip(source)
    work = tmp_path / "work"
    work.mkdir()
    plan = _plan(source)
    (work / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    return work


def test_storyboard_matches_kept_ranges_and_one_frame(tmp_path: Path):
    work = _workdir(tmp_path)
    preset = json.loads(json.dumps(DEFAULTS))
    preset["export"]["fps"] = 30
    preset["export"]["width"] = 320
    preset["export"]["height"] = 180
    story = write_storyboard(work, preset, None)
    clips = story["tracks"]["video"]
    plan = json.loads((work / "plan.json").read_text(encoding="utf-8"))
    assert len(clips) == len(plan["kept_ranges"])
    total = sum(clip["dst_end"] - clip["dst_start"] for clip in clips)
    assert abs(total - story["output_duration"]) < 1.0 / 30
    for clip in clips:
        assert clip["src_out"] - clip["src_in"] == clip["dst_out"] - clip["dst_in"]
        assert clip["src_in"] % 1 == 0
    export = work / "export"
    html = (export / "storyboard.html").read_text(encoding="utf-8")
    assert "Keep · Conservado" in html
    assert "thumbs/keep_001.jpg" in html
    assert (export / "thumbs" / "keep_001.jpg").exists()
    assert (export / "contact-sheet.jpg").exists()
    srt = (export / "captions.srt").read_text(encoding="utf-8")
    assert "-->" in srt
    assert "cómo ahorrar" in srt
    hook = (export / "hook.srt").read_text(encoding="utf-8")
    assert "It's today's" in hook
    assert (export / "storyboard.csv").exists()
    assert (export / "RELINK.md").exists()
    assert story["scenes"]
    assert story["broll_slots"] == []
    markdown = (export / "storyboard.md").read_text(encoding="utf-8")
    kept_rows = [line for line in markdown.splitlines() if re.match(r"^\| \d+ \|", line)]
    assert len(kept_rows) == len(plan["kept_ranges"])


def test_inline_html_is_self_contained_and_respects_the_cap(tmp_path: Path):
    work = _workdir(tmp_path)
    preset = json.loads(json.dumps(DEFAULTS))
    preset["export"]["width"] = 320
    preset["export"]["height"] = 180
    preset["storyboard"] = {"inline": True, "inline_max_bytes": 20000, "thumb_width": 320}
    write_storyboard(work, preset, None, inline=True)
    page = (work / "export" / "storyboard.inline.html").read_text(encoding="utf-8")
    assert len(page.encode("utf-8")) <= 20000
    assert "thumbs/" not in page
    assert not re.search(r"""(?:src|href)\s*=\s*['"](?!data:)""", page)
    assert "http://" not in page and "https://" not in page
    blobs = re.findall(r"data:image/jpeg;base64,([A-Za-z0-9+/=]+)", page)
    for blob in blobs:
        raw = base64.b64decode(blob)
        assert raw.startswith(b"\xff\xd8")
    if "omitid" not in page and "omitted" not in page:
        assert blobs
    local = (work / "export" / "storyboard.html").read_text(encoding="utf-8")
    assert "thumbs/keep_001.jpg" in local


def test_low_confidence_product_reveal_is_not_a_marker(tmp_path: Path):
    work = _workdir(tmp_path)
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps(
            {
                "labels": [
                    {
                        "index": 1,
                        "label": "product_reveal",
                        "confidence": "low",
                        "evidence": "Maybe a bottle in keep_001.jpg.",
                    },
                    {
                        "index": 2,
                        "label": "product_reveal",
                        "confidence": "high",
                        "evidence": "The bottle is uncovered in keep_002.jpg.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    preset = json.loads(json.dumps(DEFAULTS))
    preset["export"]["width"] = 320
    preset["export"]["height"] = 180
    story = write_storyboard(work, preset, labels)
    markers = [slot for slot in story["broll_slots"] if slot["label"] == "product_reveal"]
    assert [slot["index"] for slot in markers] == [2]
    assert story["scenes"][0]["confidence"] == "low"
    again = write_storyboard(work, preset, None)
    kept = {scene["index"]: scene["label"] for scene in again["scenes"]}
    assert kept[1] == "product_reveal"
    assert kept[2] == "product_reveal"
    assert again["scenes"][0]["confidence"] == "low"
    assert again["scenes"][1]["evidence"].startswith("The bottle")


def test_cut_out_is_the_inverse_of_kept_ranges():
    kept = align_kept(
        [
            {"src_start": 0.0, "src_end": 1.0},
            {"src_start": 1.8, "src_end": 2.2},
        ],
        30,
    )
    cuts = cut_out_frames(4.0, kept, 30)
    covered = []
    for start, end in cuts:
        covered.extend(range(start, end))
    kept_frames = []
    for clip in kept:
        kept_frames.extend(range(clip["src_in"], clip["src_out"]))
    assert not set(covered) & set(kept_frames)
    assert set(covered) | set(kept_frames) == set(range(0, 120))


@pytest.mark.skipif(shutil.which("auto-editor") is None, reason="auto-editor 29 is not installed")
def test_premiere_xml_is_not_fcpxml_and_files_are_well_formed(tmp_path: Path):
    work = _workdir(tmp_path)
    preset = json.loads(json.dumps(DEFAULTS))
    preset["export"]["width"] = 320
    preset["export"]["height"] = 180
    preset["export"]["crf"] = 34
    result = export_nle(work, "all", preset)
    export = work / "export"
    premiere = (export / "project_premiere.xml").read_text(encoding="utf-8")
    fcpx = (export / "project.fcpxml").read_text(encoding="utf-8")
    assert premiere.startswith("<?xml")
    assert "<xmeml" in premiere
    assert "<fcpxml" not in premiere
    assert "<fcpxml" in fcpx
    assert 'version="1.10"' in fcpx
    assert "media/source.mp4" in premiere
    assert "media/source.mp4" in fcpx
    for name in ("project_premiere.xml", "project.fcpxml"):
        xml = export / name
        ET.parse(xml)
        xmllint = shutil.which("xmllint")
        assert xmllint, "xmllint is required to check the project XML"
        lint = subprocess.run([xmllint, "--noout", str(xml)], capture_output=True, text=True)
        assert lint.returncode == 0, lint.stderr
    assert (export / "media" / "source.mp4").exists()
    assert (export / "media" / "music.m4a").exists()
    assert "project_premiere.xml" in result["written"]
    assert "project.fcpxml" in result["written"]


@pytest.mark.skipif(shutil.which("auto-editor") is None, reason="auto-editor 29 is not installed")
def test_fcpxml_asset_covers_a_clip_near_the_end(tmp_path: Path):
    source = tmp_path / "long.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x224466:s=320x180:r=30:d=6",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=6",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "34",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
    )
    work = tmp_path / "work"
    work.mkdir()
    plan = _plan(source)
    plan["source_duration"] = 6.0
    plan["kept_ranges"] = [
        {"src_start": 0.2, "src_end": 0.8, "dst_start": 0.0, "dst_end": 0.6},
        {"src_start": 5.2, "src_end": 5.9, "dst_start": 0.6, "dst_end": 1.3},
    ]
    (work / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    preset = json.loads(json.dumps(DEFAULTS))
    preset["export"]["width"] = 320
    preset["export"]["height"] = 180
    preset["export"]["crf"] = 34
    export_nle(work, "fcpx", preset)
    root = ET.parse(work / "export" / "project.fcpxml").getroot()
    assert root.get("version") == "1.10"
    asset = root.find(".//asset")
    assert asset is not None
    asset_seconds = _rational(asset.get("duration"))
    probed = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=nb_frames",
                "-of",
                "json",
                str(work / "export" / "media" / "source.mp4"),
            ],
            text=True,
        )
    )
    frames = int(probed["streams"][0]["nb_frames"])
    assert abs(asset_seconds - frames / 30) < 1 / 30
    for clip in root.iter("asset-clip"):
        start = _rational(clip.get("start"))
        duration = _rational(clip.get("duration"))
        assert start + duration <= asset_seconds + 1 / 30


def _rational(value: str) -> float:
    text = value[:-1] if value.endswith("s") else value
    if "/" in text:
        num, den = text.split("/", 1)
        return int(num) / int(den)
    return float(text)


def test_otio_round_trip_when_installed(tmp_path: Path):
    pytest.importorskip("opentimelineio")
    import opentimelineio as otio

    work = _workdir(tmp_path)
    preset = json.loads(json.dumps(DEFAULTS))
    preset["export"]["width"] = 320
    preset["export"]["height"] = 180
    story = build_storyboard(json.loads((work / "plan.json").read_text(encoding="utf-8")), preset, [])
    from lib.nle import build_otio

    timeline = build_otio(story)
    path = tmp_path / "timeline.otio"
    otio.adapters.write_to_file(timeline, str(path))
    again = otio.adapters.read_from_file(str(path))
    video = next(track for track in again.tracks if track.name == "video")
    assert len(list(video)) == len(story["tracks"]["video"])
    assert any(track.name == "music" for track in again.tracks)
