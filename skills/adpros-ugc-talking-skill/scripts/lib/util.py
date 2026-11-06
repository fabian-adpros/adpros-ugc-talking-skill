"""Shared errors and small helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class UGCError(Exception):
    """User-facing pipeline error with both languages."""

    def __init__(self, en: str, es: str | None = None):
        super().__init__(en)
        self.en = en
        self.es = es or en

    def text(self, ui: str) -> str:
        return self.es if ui == "es" else self.en


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def round_time(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


_PATHS_READY = False


def prepend_tool_paths() -> None:
    """See binaries installed into the skill venv or the repo venv."""
    global _PATHS_READY
    if _PATHS_READY:
        return
    _PATHS_READY = True
    roots = [skill_root(), skill_root().parents[1]]
    entries = []
    for root in roots:
        bindir = root / ".venv" / "bin"
        if bindir.is_dir():
            entries.append(str(bindir))
    if not entries:
        return
    current = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join(entries + [current])
