"""Partial backgrounds, the Mac person matte contract, and model tips."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "skills" / "adpros-ugc-talking-skill" / "scripts"
sys.path.insert(0, str(ROOT))

from lib.applevision import command, matte_contract, supported  # noqa: E402
from lib.engine import CPU_SECONDS_PER_FRAME, estimate_bg_seconds, mps_crash_action, select_engine  # noqa: E402
from lib.moments import build_moment_extract_command, envelope_expr, moment_seconds, parse_moments, partial_composite_graph  # noqa: E402
from lib.nextsteps import STAGES, build_next_steps, model_tip  # noqa: E402
from lib.util import UGCError  # noqa: E402
import pytest


def test_moments_are_one_decode_and_only_those_seconds():
    segments = parse_moments("0-3, 12.5-15, 20-23")
    assert moment_seconds(segments) == pytest.approx(8.5)
    cmd = build_moment_extract_command(Path("cut.mp4"), Path("moments.mp4"), segments, 30)
    assert cmd.count("-i") == 1
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "concat=n=3" in graph
    assert "trim=start=0.000:end=3.000" in graph
    assert "trim=start=12.500:end=15.000" in graph
    expr = envelope_expr(segments)
    assert "between(T,0.000,3.000)" in expr
    composite = partial_composite_graph(segments, 1080, 1920, 30, 30.0)
    assert composite.count("maskedmerge") == 2
    assert "between(T,20.000,23.000)" in composite


def test_apple_vision_contract_and_linux_refusal():
    argv = command(Path("apple-vision-matte"), Path("in.mp4"), Path("matte.mp4"), "accurate")
    assert argv[-1] == "accurate"
    assert "--input" in argv and "--output" in argv
    contract = matte_contract()
    assert contract["person"] == "high luma"
    assert contract["timing"] == "same frame count as the input"
    assert CPU_SECONDS_PER_FRAME["apple-vision"] == 0.24
    estimate = estimate_bg_seconds("apple-vision", 1270, "cpu", 320)
    assert estimate == pytest.approx(1270 * 0.24)
    if not supported():
        with pytest.raises(UGCError):
            select_engine("apple-vision", explicit=True)


def test_mps_crash_stops_before_a_long_cpu_fallback():
    long_cpu = estimate_bg_seconds("birefnet", 1270, "cpu", 320)
    assert mps_crash_action(long_cpu, approved=False) == "checkpoint"
    assert mps_crash_action(long_cpu, approved=True) == "cpu"
    steps = build_next_steps("bg_cost", {"suggest_apple_vision": True})
    text = " ".join((step["en"] + " " + (step["command"] or "")) for step in steps)
    assert "apple-vision" in text
    assert "0.24" in text
    assert "product" in text.lower() or "hand" in text.lower()


def test_each_stage_has_one_model_tip():
    for stage in STAGES:
        tip = model_tip(stage)
        assert tip is not None
        assert tip["en"] and tip["es"]
        assert "/model" in tip["en"]
    assert model_tip("transcribe")["kind"] == "lighter"
    assert model_tip("hook")["kind"] == "top"
    assert model_tip("storyboard")["kind"] == "top"
    assert model_tip("render")["kind"] == "lighter"
    assert model_tip("final")["kind"] == "top"
