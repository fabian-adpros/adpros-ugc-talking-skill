"""ffprobe / ffmpeg helpers and the verified auto-editor 29.3.1 wrapper."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .util import UGCError, prepend_tool_paths


def _failure_log(cmd: list[str], completed: subprocess.CompletedProcess[str]) -> Path:
    last = Path(cmd[-1]) if cmd else Path("ugc-cmd.log")
    folder = last.parent if last.suffix and last.parent.exists() else Path.cwd()
    path = folder / "ugc-ffmpeg.log"
    body = (completed.stderr or "") + ("\n" + completed.stdout if completed.stdout else "")
    path.write_text(body[-200_000:], encoding="utf-8", errors="replace")
    return path


def _tail_lines(text: str, count: int = 6) -> str:
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return "\n".join(lines[-count:])


def run_cmd(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise UGCError(
            f"Command not found: {cmd[0]}",
            f"No está el comando: {cmd[0]}",
        ) from exc
    if completed.returncode != 0:
        log_path = _failure_log(cmd, completed)
        tail = _tail_lines(completed.stderr or completed.stdout or "")
        message = f"{cmd[0]} failed ({completed.returncode}). Log: {log_path}."
        if tail:
            message = f"{message}\n{tail}"
        if len(message) > 500:
            message = message[:500] + "…"
        raise UGCError(message, message)
    return completed


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise UGCError(
            f"{name} is not on PATH.",
            f"{name} no está en PATH.",
        )
    return path


def probe(path: Path) -> dict:
    require_tool("ffprobe")
    completed = run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    data = json.loads(completed.stdout or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    if video is None:
        raise UGCError(
            "The file has no video stream.",
            "El archivo no tiene pista de video.",
        )
    if audio is None:
        raise UGCError(
            "The file has no audio stream. A talking-head clip needs a voice track.",
            "El archivo no tiene audio. Un talking-head necesita la voz.",
        )
    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    rate = video.get("avg_frame_rate") or "30/1"
    num, _, den = rate.partition("/")
    try:
        fps = float(num) / float(den) if den else float(num)
    except ValueError:
        fps = 30.0
    return {
        "duration": duration,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": fps,
        "has_audio": True,
    }


def extract_wav(src: Path, dest: Path) -> None:
    require_tool("ffmpeg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(dest),
        ]
    )


def loudnorm_stats(path: Path, lufs: float, true_peak: float, lra: float) -> dict:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            f"loudnorm=I={lufs}:TP={true_peak}:LRA={lra}:print_format=json",
            "-f",
            "null",
            "-",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    stderr = completed.stderr or ""
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if completed.returncode != 0 or start < 0 or end < start:
        raise UGCError(
            f"loudnorm measurement failed.\n{stderr[-1500:]}",
            f"Falló la medición loudnorm.\n{stderr[-1500:]}",
        )
    return json.loads(stderr[start : end + 1])


def apply_loudnorm(
    src: Path,
    dest: Path,
    stats: dict,
    lufs: float,
    true_peak: float,
    lra: float,
    audio_bitrate: str,
) -> None:
    measured = (
        f"loudnorm=I={lufs}:TP={true_peak}:LRA={lra}:"
        f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
        f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
        f"offset={stats['target_offset']}:linear=true"
    )
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-c:v",
            "copy",
            "-af",
            measured,
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(dest),
        ]
    )


def trim_media(src: Path, dest: Path, seconds: float, audio_bitrate: str, crf: int) -> None:
    fade_at = max(0.0, seconds - 0.3)
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-t",
            f"{seconds:.3f}",
            "-af",
            f"afade=t=out:st={fade_at:.3f}:d=0.30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-movflags",
            "+faststart",
            str(dest),
        ]
    )


def extract_frame(src: Path, dest: Path, at: float) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(0.0, at):.3f}",
            "-i",
            str(src),
            "-frames:v",
            "1",
            str(dest),
        ]
    )


def loop_music(src: Path, dest: Path, duration: float) -> None:
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(src),
            "-t",
            f"{max(0.1, duration):.3f}",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(dest),
        ]
    )


def auto_editor_available() -> str | None:
    prepend_tool_paths()
    return shutil.which("auto-editor")


def auto_editor_v1(
    src: Path,
    output_stem: Path,
    threshold: float,
    margin: float,
    fps: int,
) -> dict:
    """Run the flags verified against auto-editor 29.3.1.

    `--smooth` does not exist in that version. `--export v1` writes
    `{stem}.v1` with chunks [startFrame, endFrame, speed]. Speed 99999 is a cut.
    """
    exe = auto_editor_available()
    if not exe:
        raise UGCError(
            "auto-editor is not installed.",
            "auto-editor no está instalado.",
        )
    output_stem.parent.mkdir(parents=True, exist_ok=True)
    # Verified: --edit audio:threshold=0.04 --margin 0.05sec --frame-rate N --export v1
    run_cmd(
        [
            exe,
            str(src),
            "--edit",
            f"audio:threshold={threshold}",
            "--margin",
            f"{margin}sec",
            "--frame-rate",
            str(int(fps)),
            "--export",
            "v1",
            "--output",
            str(output_stem),
            "--no-open",
            "--quiet",
        ]
    )
    v1 = output_stem.with_suffix(".v1")
    if not v1.exists():
        # auto-editor appends .v1 even when the stem already has a suffix.
        candidates = list(output_stem.parent.glob(output_stem.name + "*.v1"))
        if not candidates:
            raise UGCError(
                f"auto-editor did not write a v1 timeline next to {output_stem}.",
                f"auto-editor no escribió el timeline v1 junto a {output_stem}.",
            )
        v1 = candidates[0]
    return json.loads(v1.read_text(encoding="utf-8"))


def ffmpeg_has_filter(name: str) -> bool:
    if not shutil.which("ffmpeg"):
        return False
    completed = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"],
        text=True,
        capture_output=True,
        check=False,
    )
    return f" {name} " in (completed.stdout or "")


def ffmpeg_version() -> str:
    if not shutil.which("ffmpeg"):
        return "missing"
    completed = subprocess.run(
        ["ffmpeg", "-version"],
        text=True,
        capture_output=True,
        check=False,
    )
    line = (completed.stdout or completed.stderr or "").splitlines()
    return line[0] if line else "unknown"


def ffmpeg_filter_help(name: str) -> str:
    if not shutil.which("ffmpeg"):
        return ""
    completed = subprocess.run(
        ["ffmpeg", "-hide_banner", "-h", f"filter={name}"],
        text=True,
        capture_output=True,
        check=False,
    )
    return (completed.stdout or "") + (completed.stderr or "")


def audio_format_clause() -> str:
    """Stereo packed float. ffmpeg 7 renamed channel_layouts to channel_layout."""
    help_text = ffmpeg_filter_help("aformat")
    if "channel_layouts" in help_text:
        layout = "channel_layouts=stereo"
    else:
        layout = "channel_layout=stereo"
    return f"aformat=sample_fmts=fltp:{layout}"
