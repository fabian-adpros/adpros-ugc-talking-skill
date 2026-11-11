"""Preset defaults and filler lists."""

from __future__ import annotations

from pathlib import Path

from .util import deep_merge, load_json, skill_root

DEFAULTS: dict = {
    "silence": {
        "min_seconds": 0.4,
        "padding_seconds": 0.12,
        "fade_seconds": 0.015,
        "engine": "auto",
        "audio_threshold": 0.04,
        "analysis_fps": 100,
    },
    "fillers": {"mode": "conservative"},
    "captions": {
        "min_words": 2,
        "max_words": 3,
        "highlight_active_word": True,
        "font_size": 72,
        "color": "#FFFFFF",
        "highlight_color": "#FFE14A",
        "stroke_color": "#000000",
        "y_ratio": 0.75,
    },
    "hook": {"duration_seconds": 3.0, "font_size": 62, "y_ratio": 0.16, "max_chars": 42, "max_words": 8},
    "music": {"file": None, "duck_db": -18, "engine": "volume"},
    "export": {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "crf": 18,
        "audio_bitrate": "192k",
        "lufs": -14,
        "true_peak": -1.5,
        "lra": 11,
        "max_duration": 60,
        "trim_if_over": True,
    },
    "safe_zone": {"top": 250, "bottom": 420, "left": 80, "right": 140},
    "storyboard": {"inline": False, "inline_max_bytes": 1_500_000, "thumb_width": 320},
    "delivery": {
        "editor_projects": False,
        "editors": ["premiere", "fcpx", "resolve"],
        "review_storyboard": False,
    },
    "bg": {
        "enabled": False,
        "mode": "keep",
        "file": None,
        "engine": "birefnet",
        "model": "u2net",
        "threshold": None,
        "infer_size": 320,
        "temporal_smooth": 3,
        "smooth_mode": "median",
        "morph_close": 1,
        "feather": 0,
        "refine": False,
    },
    "transcription": {
        "engine": "auto",
        "model": None,
        "device": "auto",
        "vad_filter": False,
        "beam_size": 5,
    },
}

# initial_prompt keeps fillers in the first window. It can also hallucinate
# them, so the phrases stay short. See references/fillers.md.
FILLER_PROMPTS = {
    "en": "Um, uh, erm, hmm, like, you know, I mean.",
    "es": "Eh, este, o sea, pues, bueno, mmm, digamos, tipo, me entiendes.",
    "auto": "Um, uh, eh, este, o sea, mmm.",
}


def assets_dir() -> Path:
    return skill_root() / "assets"


def load_preset(path: Path | None = None) -> dict:
    preset = dict(DEFAULTS)
    default_file = assets_dir() / "preset.json"
    chosen = path or (default_file if default_file.exists() else None)
    if chosen:
        preset = deep_merge(preset, load_json(chosen))
    preset["_preset_path"] = str(chosen) if chosen else None
    return preset


def load_fillers(path: Path | None = None) -> dict:
    chosen = path or (assets_dir() / "fillers.json")
    return load_json(chosen)


def font_path() -> Path:
    return assets_dir() / "fonts" / "Inter-Bold.ttf"


def default_music_path() -> Path | None:
    bed = assets_dir() / "music" / "bed.m4a"
    return bed if bed.exists() else None
