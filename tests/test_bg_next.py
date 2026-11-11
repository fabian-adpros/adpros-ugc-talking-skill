"""Background composite and next_steps. Synthetic media only. No U2-Net weights."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ["UGC_SKIP_BG_INSTALL"] = "1"

import pytest

ROOT = Path(__file__).resolve().parents[1] / "skills" / "adpros-ugc-talking-skill" / "scripts"
sys.path.insert(0, str(ROOT))

from lib.bg import (  # noqa: E402
    bg_checkpoint_message,
    composite_subject,
    ensure_subject,
    export_bg_layers,
    fit_matte,
    preview_times,
    product_times,
    resolve_bg,
    side_by_side_frames,
    subject_from_matte,
    write_matte,
    _matte_key,
    _subject_key,
)
from lib.engine import BIREFNET_REVISION  # noqa: E402
from lib.engine import predict_masks, select_engine  # noqa: E402
from lib.config import DEFAULTS  # noqa: E402
from lib.matte import morph_close, smooth_alpha, working_size  # noqa: E402
from lib.media import run_cmd  # noqa: E402
from lib.render import cut_video  # noqa: E402
from lib.nextsteps import STAGES, build_next_steps, print_next_steps  # noqa: E402
from lib.util import UGCError  # noqa: E402

UGC = Path(__file__).resolve().parents[1] / "skills" / "adpros-ugc-talking-skill" / "scripts" / "ugc_edit.py"
pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")


def _load_cli():
    spec = importlib.util.spec_from_file_location("ugc_edit_bg", UGC)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def _clip(path: Path, color: str, seconds: float = 1.0, size: str = "320x180") -> None:
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
            f"color=c={color}:s={size}:r=30:d={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={seconds}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "30",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ]
    )


def _matte(path: Path) -> None:
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
            "color=c=black:s=320x180:r=30:d=1",
            "-vf",
            "geq=lum='if(lt(hypot(X-160,Y-90),36),255,0)':cb=128:cr=128",
            "-frames:v",
            "30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    )


def _png(path: Path, color: str, size: str = "80x60") -> None:
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
            f"color=c={color}:s={size}",
            "-frames:v",
            "1",
            str(path),
        ]
    )


def _pixel(path: Path, x: int, y: int) -> tuple[int, int, int]:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"format=rgb24,crop=1:1:{x}:{y}",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    data = completed.stdout
    assert len(data) >= 3
    return data[0], data[1], data[2]


def _args(**kwargs):
    base = dict(yes=False, bg=None, bg_model=None, bg_threshold=None, bg_yes=False, bg_skip=False)
    base.update(kwargs)
    return argparse.Namespace(**base)


def _preset(path: Path) -> None:
    preset = json.loads(json.dumps(DEFAULTS))
    preset["export"]["width"] = 320
    preset["export"]["height"] = 180
    preset["export"]["crf"] = 30
    preset["captions"]["font_size"] = 28
    preset["hook"]["font_size"] = 24
    preset["safe_zone"] = {"top": 8, "bottom": 8, "left": 8, "right": 8}
    preset["music"]["file"] = None
    path.write_text(json.dumps(preset), encoding="utf-8")


def _plan(source: Path) -> dict:
    return {
        "language": "es",
        "source": str(source),
        "source_duration": 1.0,
        "output_duration": 1.0,
        "kept_ranges": [{"src_start": 0.0, "src_end": 1.0, "dst_start": 0.0, "dst_end": 1.0}],
        "captions": [
            {
                "start": 0.1,
                "end": 0.8,
                "words": [
                    {"text": "producto", "start": 0.1, "end": 0.4},
                    {"text": "visible", "start": 0.4, "end": 0.8},
                ],
            }
        ],
        "hook": {"text": "Mira esto", "start": 0, "end": 1, "reason": "user", "alternates": []},
        "trim": {"will_trim": False, "max_duration": 60},
        "warnings": [],
    }


def test_resolve_bg_defaults_to_general_model_and_keeps_the_plate():
    state = resolve_bg(_args(), DEFAULTS, {})
    assert state["enabled"] is False
    assert state["mode"] == "keep"
    assert state["model"] == "u2net"
    assert state["approved"] is True


def test_replace_waits_until_bg_yes_and_skip_wins(tmp_path: Path):
    plate = tmp_path / "plate.png"
    plate.write_bytes(b"not-read")
    waiting = resolve_bg(_args(bg=str(plate)), DEFAULTS, {})
    assert waiting["enabled"] is True
    assert waiting["mode"] == "replace"
    assert waiting["model"] == "u2net"
    assert waiting["approved"] is False
    approved = resolve_bg(_args(bg=str(plate), bg_yes=True), DEFAULTS, {"bg": waiting})
    assert approved["approved"] is True
    preset = json.loads(json.dumps(DEFAULTS))
    preset["bg"]["enabled"] = True
    preset["bg"]["mode"] = "replace"
    preset["bg"]["file"] = str(plate)
    skipped = resolve_bg(_args(bg_skip=True), preset, {})
    assert skipped["enabled"] is False
    assert skipped["mode"] == "keep"


def test_yes_applies_an_enabled_preset_without_a_checkpoint(tmp_path: Path):
    plate = tmp_path / "plate.png"
    plate.write_bytes(b"x")
    preset = json.loads(json.dumps(DEFAULTS))
    preset["bg"]["enabled"] = True
    preset["bg"]["mode"] = "transparent"
    state = resolve_bg(_args(yes=True), preset, {})
    assert state["mode"] == "transparent"
    assert state["approved"] is True
    with pytest.raises(UGCError):
        resolve_bg(_args(bg_threshold=300), DEFAULTS, {})


def test_missing_backgroundremover_names_the_install(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("lib.bg.backgroundremover_available", lambda: None)
    with pytest.raises(UGCError) as caught:
        write_matte(tmp_path / "in.mp4", tmp_path / "matte.mp4")
    assert "./install.sh --with-bg" in caught.value.en
    assert "176" in caught.value.en


def test_composite_puts_the_plate_behind_the_subject(tmp_path: Path):
    cut = tmp_path / "cut.mp4"
    matte = tmp_path / "matte.mp4"
    plate = tmp_path / "plate.png"
    subject = tmp_path / "subject.mov"
    out = tmp_path / "out.mp4"
    _clip(cut, "0x224466")
    _matte(matte)
    _png(plate, "red")
    subject_from_matte(cut, matte, subject, threshold=128)
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name,pix_fmt", "-of", "json", str(subject)],
        check=True,
        capture_output=True,
        text=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    assert stream["codec_name"] == "prores"
    assert "yuva" in stream["pix_fmt"]
    composite_subject(subject, plate, out, 320, 180, 30, 1.0, 30, "128k")
    center = _pixel(out, 160, 90)
    corner = _pixel(out, 4, 4)
    assert center[2] > center[0]
    assert corner[0] > 180 and corner[1] < 80 and corner[2] < 80

    short = tmp_path / "short.mp4"
    _clip(short, "red", seconds=0.2, size="160x90")
    looped = tmp_path / "looped.mp4"
    composite_subject(subject, short, looped, 320, 180, 30, 1.0, 30, "128k")
    duration = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(looped)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert float(json.loads(duration.stdout)["format"]["duration"]) >= 0.9


def test_preview_times_include_a_product_frame(tmp_path: Path):
    work = tmp_path / "work"
    (work / "export").mkdir(parents=True)
    (work / "export" / "storyboard.json").write_text(
        json.dumps(
            {
                "fps": 30,
                "scenes": [{"label": "product_visible", "confidence": "high", "dst_in": 15, "dst_out": 20}],
            }
        ),
        encoding="utf-8",
    )
    preferred = product_times(work, 1.0)
    times = preview_times(1.0, preferred)
    assert 3 <= len(times) <= 5
    assert any(abs(moment - (16 / 30)) < 0.02 for moment in times)


def test_export_copies_matte_subject_and_plate(tmp_path: Path):
    work = tmp_path / "work"
    media = work / "export" / "media"
    work.mkdir()
    (work / "subject.mov").write_bytes(b"alpha")
    (work / "matte.mp4").write_bytes(b"matte")
    plate = tmp_path / "room.png"
    plate.write_bytes(b"plate")
    (work / "export").mkdir()
    (work / "export" / "RELINK.md").write_text("# Relink\n", encoding="utf-8")
    written = export_bg_layers(
        work,
        media,
        {"bg": {"enabled": True, "mode": "replace", "file": str(plate)}},
    )
    assert "media/subject.mov" in written
    assert "media/matte.mp4" in written
    assert (media / "background.png").read_bytes() == b"plate"
    assert "## Background" in (work / "export" / "RELINK.md").read_text(encoding="utf-8")


def test_next_steps_exist_for_every_stage(capsys):
    plan = {}
    for stage in STAGES:
        error = "styled.mp4 is missing" if stage == "error" else None
        steps = build_next_steps(stage, plan, error=error)
        assert 2 <= len(steps) <= 4
        assert [step["n"] for step in steps] == list(range(1, len(steps) + 1))
        for step in steps:
            assert step["en"] and step["es"]
            assert step["id"]
        printed = print_next_steps(stage, "es", plan, error=error)
        assert plan["next_steps"] == printed
    output = capsys.readouterr().out
    assert "Qué sigue" in output
    assert '"next_steps"' in output
    fix = build_next_steps("error", {}, error="backgroundremover is not installed")[0]
    assert fix["command"] == "./install.sh --with-bg"
    assert "render" in build_next_steps("error", {}, error="styled.mp4 is missing")[0]["command"]


def test_render_stops_at_exit_13_and_styles_the_composite(tmp_path: Path, monkeypatch):
    source = tmp_path / "clip.mp4"
    _clip(source, "0x224466")
    matte = tmp_path / "disk.mp4"
    _matte(matte)
    plate = tmp_path / "plate.png"
    _png(plate, "red")
    work = tmp_path / "work"
    work.mkdir()
    (work / "plan.json").write_text(json.dumps(_plan(source)), encoding="utf-8")
    (work / "export").mkdir()
    (work / "export" / "storyboard.json").write_text(
        json.dumps({"fps": 30, "scenes": [{"label": "product_visible", "confidence": "high", "dst_in": 10}]}),
        encoding="utf-8",
    )
    preset = tmp_path / "preset.json"
    _preset(preset)
    monkeypatch.setattr("lib.bg.write_matte", lambda src, dest, model="u2net": shutil.copyfile(matte, dest))
    cli = _load_cli()
    monkeypatch.setattr(cli, "default_music_path", lambda: None)
    code = cli.main(
        ["render", "--workdir", str(work), "--preset", str(preset), "--bg", str(plate), "--ui", "es", "--renderer", "ffmpeg"]
    )
    assert code == 13
    saved = json.loads((work / "plan.json").read_text(encoding="utf-8"))
    assert saved["bg"]["model"] == "u2net"
    assert saved["bg"]["mode"] == "replace"
    assert saved["bg"]["approved"] is False
    assert saved["bg"]["file"] == str(plate)
    assert 3 <= len(saved["bg"]["previews"]) <= 5
    assert saved["next_steps"][0]["id"] == "keep_bg"
    assert (work / "subject.mov").exists()
    assert any(step["es"] for step in saved["next_steps"])
    again = cli.main(
        [
            "render",
            "--workdir",
            str(work),
            "--preset",
            str(preset),
            "--bg",
            str(plate),
            "--bg-yes",
            "--ui",
            "en",
            "--renderer",
            "ffmpeg",
        ]
    )
    assert again == 0
    composite = work / "cut-bg.mp4"
    styled = work / "styled.mp4"
    assert composite.exists() and styled.stat().st_size > 1000
    assert styled.stat().st_mtime >= composite.stat().st_mtime
    corner = _pixel(styled, 4, 4)
    assert corner[0] > 180 and corner[2] < 80
    assert "Dialogue:" in (work / "captions.ass").read_text(encoding="utf-8")
    approved = json.loads((work / "plan.json").read_text(encoding="utf-8"))
    assert approved["bg"]["approved"] is True
    assert approved["next_steps"][0]["id"] == "export"
    assert approved["bg"].get("timings", {}).get("reused") is True


def test_preview_times_stop_before_the_last_frame():
    times = preview_times(11.033, [5.133, 10.567], fps=30)
    limit = 11.033 - 2 / 30
    assert times == sorted(set(times))
    assert 3 <= len(times) <= 5
    assert max(times) <= limit + 1e-9
    assert 10.993 not in times
    assert 5.133 in times


def test_a_missed_preview_frame_does_not_abort(tmp_path: Path):
    clip = tmp_path / "clip.mp4"
    _clip(clip, "0x224466", seconds=0.4)
    written = side_by_side_frames(clip, clip, [0.05, 9.0], tmp_path / "preview")
    assert len(written) == 1
    assert Path(written[0]).stat().st_size > 100


def test_ffmpeg_errors_stay_short_and_name_the_log(tmp_path: Path):
    with pytest.raises(UGCError) as caught:
        run_cmd(["ffmpeg", "-y", "-i", str(tmp_path / "missing.mp4"), str(tmp_path / "out.mp4")])
    assert len(caught.value.en) < 500
    assert "ugc-ffmpeg.log" in caught.value.en
    assert (tmp_path / "ugc-ffmpeg.log").exists()
    assert len((tmp_path / "ugc-ffmpeg.log").read_text(encoding="utf-8")) > len(caught.value.en)
    huge = "ffmpeg failed\n" + ("frame 0\n" * 400)
    advice = build_next_steps("error", {}, error=huge)[0]
    assert len(advice["en"]) < 400
    assert "doctor" not in (advice["command"] or "")
    yuv = build_next_steps("error", {}, error="Non full-range YUV is non-standard, set strict_std_compliance")[0]
    assert "full-range" in yuv["en"]
    logged = build_next_steps("error", {}, error=caught.value.en)
    assert logged[1]["id"] == "open_log"
    assert "doctor" not in (logged[0]["en"] + (logged[0]["command"] or ""))


def test_cut_video_reuses_an_unchanged_encode(tmp_path: Path):
    source = tmp_path / "clip.mp4"
    _clip(source, "0x224466")
    dest = tmp_path / "cut.mp4"
    ranges = [{"src_start": 0.0, "src_end": 1.0}]
    cut_video(source, dest, ranges, 160, 90, 30, 30, "64k")
    first = dest.stat().st_mtime_ns
    cut_video(source, dest, ranges, 160, 90, 30, 30, "64k")
    assert dest.stat().st_mtime_ns == first
    cut_video(source, dest, ranges, 160, 90, 30, 28, "64k")
    assert dest.stat().st_mtime_ns != first


def test_smooth_alpha_fills_a_one_frame_hole():
    flicker = [[[255]], [[0]], [[255]]]
    started = time.perf_counter()
    filled = smooth_alpha(flicker, window=3, mode="median")
    elapsed = time.perf_counter() - started
    assert [frame[0][0] for frame in filled] == [255, 255, 255]
    assert elapsed < 0.5
    hole = [
        [255, 255, 255],
        [255, 0, 255],
        [255, 255, 255],
    ]
    closed = morph_close(hole, radius=1)
    assert closed[1][1] == 255
    width, height = working_size(1080, 1920, 512)
    assert width == 512
    assert height % 32 == 0 and width % 32 == 0
    assert height > width
    assert abs((height / width) - (1920 / 1080)) < 0.05
    assert working_size(1080, 1920, 320)[0] == 320


def test_ndarray_smooth_matches_the_list_path_on_an_even_edge():
    numpy = pytest.importorskip("numpy")
    frames = [[[255]], [[0]], [[255]]]
    volume = numpy.array(frames, dtype=numpy.uint8)
    array_out = smooth_alpha(volume, window=3, mode="median")
    list_out = smooth_alpha(frames, window=3, mode="median")
    assert int(array_out[0, 0, 0]) == list_out[0][0][0] == 255
    assert int(array_out[1, 0, 0]) == 255
    empty = numpy.zeros((0, 1, 1), dtype=numpy.uint8)
    assert smooth_alpha(empty, 3).shape[0] == 0


def test_size_mismatch_is_not_called_a_preview_miss():
    message = (
        "[Parsed_guided_4] Width and height of input videos must be same. "
        "Nothing was written into output file, because at least one of its streams received no packets."
    )
    advice = build_next_steps("error", {}, error=message)[0]
    assert "preview time" not in advice["en"].lower()
    assert "scaled" in advice["en"].lower() or "matte" in advice["en"].lower()
    plain = build_next_steps("error", {}, error="Nothing was written into output file.")[0]
    assert "preview time" not in plain["en"].lower()


def test_fit_matte_scales_to_the_cut(tmp_path: Path):
    cut = tmp_path / "cut.mp4"
    matte = tmp_path / "matte.mp4"
    _clip(cut, "0x224466", seconds=0.3, size="80x48")
    _clip(matte, "white", seconds=0.3, size="32x32")
    fit_matte(cut, matte, {"temporal_smooth": 0, "morph_close": 0, "feather": 0, "refine": False})
    probed = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(matte)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert probed.stdout.strip() == "80,48"


def test_reused_matte_is_printed(tmp_path: Path, capsys):
    cut = tmp_path / "cut.mp4"
    _clip(cut, "0x224466", seconds=0.2, size="64x64")
    work = tmp_path / "work"
    work.mkdir()
    shutil.copyfile(cut, work / "matte.mp4")
    shutil.copyfile(cut, work / "subject.mov")
    state = {
        "model": "u2net",
        "engine": "birefnet",
        "engine_explicit": False,
        "engine_used": "u2net",
        "threshold": None,
        "infer_size": 320,
        "temporal_smooth": 3,
        "smooth_mode": "median",
        "morph_close": 1,
        "feather": 0,
        "refine": False,
    }
    (work / "bg-matte-stamp.txt").write_text(_matte_key(cut, state) + "\n", encoding="utf-8")
    (work / "bg-stamp.txt").write_text(_subject_key(cut, state) + "\n", encoding="utf-8")
    ensure_subject(cut, work, state)
    assert "bg: reused the existing matte" in capsys.readouterr().out
    assert state["timings"]["reused"] is True


def test_engine_selection_falls_back_and_mock_model_is_called(monkeypatch):
    monkeypatch.setattr("lib.engine.birefnet_available", lambda: False)
    monkeypatch.setattr("lib.engine.ben2_available", lambda: False)
    used, note = select_engine("birefnet", explicit=False)
    assert used == "u2net"
    assert "u2net" in note
    with pytest.raises(UGCError):
        select_engine("birefnet", explicit=True)
    monkeypatch.setattr("lib.engine.birefnet_available", lambda: True)
    assert select_engine("birefnet", explicit=True) == ("birefnet", "")
    seen = {}

    def fake(frames, device):
        seen["frames"] = len(frames)
        return ["mask"]

    monkeypatch.setattr("lib.engine._birefnet_masks", fake)
    assert predict_masks(["frame"], "birefnet", "u2net", "cpu") == ["mask"]
    assert seen["frames"] == 1


def test_with_bg_install_does_not_pin_numpy_1_and_fails_closed():
    script = (
        Path(__file__).resolve().parents[1] / "skills" / "adpros-ugc-talking-skill" / "install.sh"
    ).read_text(encoding="utf-8")
    assert "numpy<2" not in script
    bg = script.split('if [[ "$WITH_BG" == "1" ]]; then', 1)[1].split("\nfi", 1)[0]
    assert "exit 1" in bg
    assert "|| echo" not in bg


def test_exit_13_names_birefnet_and_followups_are_engine_aware():
    message = bg_checkpoint_message(
        "en",
        ["frame.jpg"],
        {"engine": "birefnet", "engine_used": "birefnet", "model": "u2net", "mode": "replace", "file": "plate.png"},
    )
    assert "engine: birefnet" in message
    assert "BiRefNet_lite" in message
    assert "model: u2net" not in message
    assert "u2net_human_seg" not in message
    steps = build_next_steps("bg", {"bg": {"engine_used": "birefnet"}})
    commands = " ".join(step["command"] or "" for step in steps)
    assert "--bg-engine u2net" in commands
    assert "--bg-engine ben2" in commands
    assert "u2net_human_seg" not in commands
    assert all(step["es"] for step in steps)
    spanish = bg_checkpoint_message("es", ["frame.jpg"], {"engine_used": "u2net", "model": "u2net", "mode": "replace", "file": "plate.png"})
    assert "engine: u2net" in spanish
    assert "model: u2net" in spanish
    assert len(BIREFNET_REVISION) == 40
