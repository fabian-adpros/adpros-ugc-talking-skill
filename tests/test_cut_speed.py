"""Single-pass cuts, speech padding, and the long-CPU background checkpoint."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "skills" / "adpros-ugc-talking-skill" / "scripts"
sys.path.insert(0, str(ROOT))

from lib.config import DEFAULTS  # noqa: E402
from lib.engine import bg_cost_should_stop, estimate_bg_seconds  # noqa: E402
from lib.nextsteps import build_next_steps  # noqa: E402
from lib.render import build_cut_command, intermediate_crf  # noqa: E402
from lib.speechpad import widen_ranges, window_db  # noqa: E402
from ugc_edit import needs_bg_install  # noqa: E402


def test_cut_command_decodes_the_source_once_and_stays_fast():
    command = build_cut_command(
        Path("clip.mp4"),
        Path("cut.mp4"),
        [
            {"src_start": 0.0, "src_end": 1.2},
            {"src_start": 2.0, "src_end": 3.4},
        ],
        1080,
        1920,
        30,
        14,
        "192k",
    )
    assert command.count("-i") == 1
    graph = command[command.index("-filter_complex") + 1]
    assert graph.count("[0:v]") == 2
    assert graph.count("[0:a]") == 2
    assert "concat=n=2" in graph
    assert "afade=t=in" in graph
    assert "afade=t=out" in graph
    assert "preset" not in command or command[command.index("-preset") + 1] == "veryfast"
    assert "medium" not in command
    assert intermediate_crf(14) == 18
    assert "-crf" in command
    assert command[command.index("-crf") + 1] == "18"


def test_padding_default_is_wider_and_hot_edges_move():
    assert DEFAULTS["silence"]["padding_seconds"] == 0.12
    ranges = [
        {"src_start": 0.0, "src_end": 1.0, "dst_start": 0.0, "dst_end": 1.0},
        {"src_start": 1.5, "src_end": 2.5, "dst_start": 1.0, "dst_end": 2.0},
    ]
    words = [{"start": 0.9, "end": 1.2, "word": "end"}]

    def energy(_moment: float) -> float:
        return -20.0

    updated, notes = widen_ranges(ranges, energy, words, duration=3.0)
    assert notes
    assert updated[0]["src_end"] > 1.0
    assert updated[0]["src_end"] < updated[1]["src_start"]
    assert updated[1]["dst_start"] > 1.0
    assert window_db([0.0] * 1600, 16000, 0.0) < -36


def test_cpu_background_estimate_stops_and_offers_a_faster_engine():
    frames = 331
    slow = estimate_bg_seconds("birefnet", frames, "cpu", 320)
    assert slow is not None and slow > 180
    assert bg_cost_should_stop("cpu", slow, approved=False) is True
    assert bg_cost_should_stop("cpu", slow, approved=True) is False
    assert estimate_bg_seconds("birefnet", frames, "mps", 320) is None
    assert bg_cost_should_stop("mps", None, approved=False) is False
    fast = estimate_bg_seconds("u2net", frames, "cpu", 320)
    assert fast is not None and fast < slow
    steps = build_next_steps("bg_cost", {})
    commands = " ".join(step["command"] or "" for step in steps)
    assert "--bg-go" in commands
    assert "--bg-engine u2net" in commands
    assert "--bg-infer-size" in commands
    assert "--bg-skip" in commands
    assert all(step["es"] for step in steps)


def test_background_install_does_not_start_unless_a_background_was_asked_for():
    assert needs_bg_install(False, "birefnet", False, False, False) is False
    assert needs_bg_install(True, "birefnet", False, False, True) is True
    assert needs_bg_install(True, "birefnet", True, False, False) is False
    assert needs_bg_install(True, "u2net", False, False, True) is False
    assert needs_bg_install(True, "u2net", False, False, False) is True
    assert needs_bg_install(True, "apple-vision", False, False, False) is False
