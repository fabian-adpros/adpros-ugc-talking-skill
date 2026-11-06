"""Timeline, filler, and caption rules. No models and no ffmpeg."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "skills" / "ugc-talking-head" / "scripts"
sys.path.insert(0, str(ROOT))

from lib.config import load_fillers  # noqa: E402
from lib.edit import (  # noqa: E402
    auto_editor_chunks_to_cuts,
    build_ass,
    build_timeline,
    find_filler_spans,
    group_captions,
    silence_cuts_from_words,
    suggest_hooks,
)


def words(*rows):
    return [{"word": row[0], "start": row[1], "end": row[2]} for row in rows]


def test_silence_threshold_and_padding():
    spoken = words(("Hoy", 0.50, 0.80), ("te", 0.80, 1.00), ("luego", 1.30, 1.60))
    # 0.30s gap must stay. Leading 0.50s must go, with 0.05s of pad kept.
    cuts = silence_cuts_from_words(spoken, duration=1.70, min_silence=0.4, padding=0.05)
    assert cuts == [(0.0, 0.45)]

    spoken = words(("Hoy", 0.10, 0.40), ("luego", 1.20, 1.50))
    cuts = silence_cuts_from_words(spoken, duration=1.60, min_silence=0.4, padding=0.05)
    assert cuts == [(0.45, 1.15)]
    assert abs((cuts[0][0] - 0.40) - 0.05) < 1e-9
    assert abs((1.20 - cuts[0][1]) - 0.05) < 1e-9


def test_gap_equal_to_threshold_is_kept():
    spoken = words(("a", 0.0, 0.2), ("b", 0.6, 0.8))
    assert silence_cuts_from_words(spoken, 1.0, 0.4, 0.05) == []


def test_conservative_fillers_keep_real_words():
    table = load_fillers()
    spoken = words(
        ("Um", 0.0, 0.2),
        ("I", 0.3, 0.4),
        ("like", 0.4, 0.55),
        ("this", 0.55, 0.8),
        ("you", 1.2, 1.35),
        ("know", 1.35, 1.55),
        ("today", 1.9, 2.2),
    )
    spans = find_filler_spans(spoken, "en", "conservative", table)
    texts = [span["text"] for span in spans]
    assert "Um" in texts
    assert "you know" in texts
    assert all("like" not in text for text in texts)

    aggressive = find_filler_spans(spoken, "en", "aggressive", table)
    aggressive_text = [span["text"] for span in aggressive]
    assert "you know" in aggressive_text
    # "like" sits inside "I like this" with no pause, so it stays.
    assert all(span["text"] != "like" for span in aggressive)


def test_spanish_este_producto_survives():
    table = load_fillers()
    spoken = words(
        ("Este", 0.0, 0.3),
        ("producto", 0.32, 0.8),
        ("eh", 1.3, 1.5),
        ("sirve", 1.7, 2.1),
    )
    spans = find_filler_spans(spoken, "es", "conservative", table)
    texts = [span["text"] for span in spans]
    assert texts == ["eh"]
    assert "Este" not in texts


def test_spanish_o_sea_needs_a_pause_in_conservative_mode():
    table = load_fillers()
    glued = words(("es", 0.0, 0.2), ("o", 0.22, 0.3), ("sea", 0.3, 0.45), ("cierto", 0.5, 0.8))
    assert find_filler_spans(glued, "es", "conservative", table) == []
    paused = words(("es", 0.0, 0.2), ("o", 0.6, 0.7), ("sea", 0.7, 0.9), ("cierto", 1.4, 1.8))
    texts = [span["text"] for span in find_filler_spans(paused, "es", "conservative", table)]
    assert texts == ["o sea"]
    aggressive = [span["text"] for span in find_filler_spans(glued, "es", "aggressive", table)]
    assert aggressive == ["o sea"]


def test_timeline_removes_silence_and_filler_and_remaps():
    table = load_fillers()
    spoken = words(
        ("Hoy", 0.50, 0.80),
        ("te", 0.80, 1.00),
        ("um", 1.10, 1.30),
        ("muestro", 1.40, 1.90),
        ("el", 3.20, 3.40),
        ("truco", 3.40, 3.80),
    )
    timeline = build_timeline(spoken, 4.50, "en", "conservative", table, 0.4, 0.05, None)
    kept_words = [word["word"] for word in timeline["words"]]
    assert "um" not in [word.lower() for word in kept_words]
    assert kept_words[0] == "Hoy"
    # Leading silence is gone, so the first word starts near 0.05 (0.50 - 0.45).
    assert abs(timeline["words"][0]["start"] - 0.05) < 1e-9
    assert timeline["output_duration"] < 4.5
    assert timeline["silence_removed_seconds"] > 0
    captions = group_captions(timeline["words"], max_words=3)
    assert captions
    assert all(1 <= len(card["words"]) <= 3 for card in captions)


def test_auto_editor_min_silence_gate():
    # 100 fps timeline. A 0.70s cut in the middle was a 0.80s silence after 0.05s margins.
    long = auto_editor_chunks_to_cuts([[0, 105, 1], [105, 175, 99999], [175, 300, 1]], 100, 0.4, 0.05)
    assert long == [(1.05, 1.75)]
    # A 0.10s cut was a 0.20s silence. It must stay.
    short = auto_editor_chunks_to_cuts([[0, 60, 1], [60, 70, 99999], [70, 140, 1]], 100, 0.4, 0.05)
    assert short == []


def test_hook_skips_greeting_and_stays_in_language():
    spoken = words(
        ("Hola.", 0.0, 0.3),
        ("Hoy", 0.5, 0.8),
        ("te", 0.8, 0.9),
        ("muestro", 0.9, 1.3),
        ("cómo", 1.3, 1.6),
        ("ahorrar", 1.6, 2.0),
        ("tiempo.", 2.0, 2.4),
    )
    hook = suggest_hooks(spoken, "es", 42, 8)
    assert "Hola" not in hook["text"]
    assert "ahorrar" in hook["text"].lower()
    assert hook["reason"] == "result_word"


def test_ass_highlight_uses_bgr():
    captions = [
        {
            "start": 0.0,
            "end": 0.8,
            "words": [
                {"text": "Hoy", "start": 0.0, "end": 0.4},
                {"text": "te", "start": 0.4, "end": 0.8},
            ],
        }
    ]
    ass = build_ass(captions, "Inter", 72, "#FFFFFF", "#FFE14A", True)
    assert "Style: Caption,Inter,72" in ass
    assert "&H004AE1FF&" in ass
    assert "Dialogue:" in ass
