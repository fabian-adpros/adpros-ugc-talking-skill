"""macOS person matte via Vision. People only: a product in the hand can disappear.

Measured on one Mac clip: 30 frames in 7s, about 0.24s each, roughly 5 minutes
for 1,270 frames. Face, hair, and hands held. The shirt edge on the left
shoulder was a little rougher than BiRefNet. This was not run in CI.
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import subprocess
from pathlib import Path

from .util import UGCError, skill_root

QUALITIES = ("fast", "balanced", "accurate")
# One Mac clip, 30 frames, 7 seconds. Not a general benchmark.
MEASURED_SECONDS_PER_FRAME = 0.24


def supported() -> bool:
    return platform.system() == "Darwin"


def matte_contract() -> dict:
    """What the Swift tool must write so the rest of the pipeline can use it."""
    return {
        "container": "mp4",
        "person": "high luma",
        "background": "low luma",
        "size": "same width and height as the input",
        "timing": "same frame count as the input",
    }


def command(binary: Path, src: Path, dest: Path, quality: str = "accurate") -> list[str]:
    if quality not in QUALITIES:
        raise UGCError(
            f"Unknown Vision quality {quality}. Use fast, balanced, or accurate.",
            f"Calidad de Vision desconocida {quality}.",
        )
    return [str(binary), "--input", str(src), "--output", str(dest), "--quality", quality]


def source_path() -> Path:
    return skill_root() / "scripts" / "apple_vision_matte.swift"


def binary_path() -> Path:
    digest = hashlib.sha256(source_path().read_bytes()).hexdigest()[:12]
    return Path.home() / ".cache" / "adpros-ugc-talking-skill" / f"apple-vision-matte-{digest}"


def ensure_binary() -> Path:
    if not supported():
        raise UGCError(
            "apple-vision only runs on macOS. It segments people, and a product in the hand can be erased.",
            "apple-vision solo corre en macOS. Separa personas, y un producto en la mano puede desaparecer.",
        )
    binary = binary_path()
    if binary.exists():
        return binary
    compiler = shutil.which("swiftc") or shutil.which("swift")
    if not compiler:
        raise UGCError(
            "swiftc is not installed, so the Vision matte cannot be built.",
            "No está swiftc, así que no se puede construir el mate de Vision.",
        )
    binary.parent.mkdir(parents=True, exist_ok=True)
    source = source_path()
    if compiler.endswith("swiftc"):
        cmd = [compiler, "-O", "-o", str(binary), str(source)]
    else:
        cmd = [compiler, str(source)]
    completed = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if completed.returncode != 0 or not binary.exists():
        tail = (completed.stderr or completed.stdout or "")[-800:]
        raise UGCError(
            f"Could not compile the Vision matte tool.\n{tail}",
            f"No se pudo compilar la herramienta de Vision.\n{tail}",
        )
    return binary
