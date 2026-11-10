"""Optional background removal. Captions are burned later, on the composite.

The matte comes from `backgroundremover` (MIT) and the U2-Net weights
(Apache-2.0). The default model is `u2net`, the general saliency net.
`u2net_human_seg` is person-only and often erases a product held in the hand.

The tool's video path (`-tv`, `-mk`) does not forward `-mt`. A requested
threshold is applied here, on the matte, before the subject is composited.
Removal is frame by frame, so the edge can flicker. Apple Silicon speed was
not tested (PyTorch MPS might work; it was not tried).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .media import probe, run_cmd
from .util import UGCError, load_json

MODELS = ("u2net", "u2net_human_seg", "u2netp")
AWAITING_BG = 13
_PRODUCT_LABELS = ("product_visible", "product_reveal", "hands")


def backgroundremover_available() -> str | None:
    return shutil.which("backgroundremover")


def resolve_bg(args, preset: dict, plan: dict | None) -> dict:
    saved = dict((plan or {}).get("bg") or {})
    cfg = dict(preset.get("bg") or {})
    flag = getattr(args, "bg", None)
    skip = bool(getattr(args, "bg_skip", False))
    yes = bool(getattr(args, "yes", False))
    approve = bool(getattr(args, "bg_yes", False))
    if skip and (flag not in (None, "keep")):
        raise UGCError(
            "Pass either a background or --bg-skip, not both.",
            "Pasa un fondo o --bg-skip, no los dos.",
        )
    model = getattr(args, "bg_model", None) or saved.get("model") or cfg.get("model") or "u2net"
    if model not in MODELS:
        raise UGCError(
            f"Unknown background model {model}. Use u2net, u2net_human_seg, or u2netp.",
            f"Modelo de fondo desconocido {model}.",
        )
    threshold = getattr(args, "bg_threshold", None)
    if threshold is None:
        threshold = saved.get("threshold", cfg.get("threshold"))
    if threshold is not None:
        threshold = int(threshold)
        if threshold < 0 or threshold > 255:
            raise UGCError(
                "Background threshold must be from 0 to 255.",
                "El umbral del fondo tiene que estar entre 0 y 255.",
            )
    if skip or flag == "keep":
        return _state(False, "keep", None, model, threshold, True, [])

    if flag == "transparent":
        enabled, mode, file = True, "transparent", None
    elif flag:
        enabled, mode, file = True, "replace", str(flag)
    elif "enabled" in saved:
        enabled = bool(saved.get("enabled"))
        mode = saved.get("mode") or "keep"
        file = saved.get("file")
        if not enabled:
            return _state(False, "keep", None, model, threshold, True, [])
    elif cfg.get("enabled"):
        mode = cfg.get("mode") or "keep"
        file = cfg.get("file")
        enabled = mode != "keep"
        if not enabled:
            return _state(False, "keep", None, model, threshold, True, [])
    else:
        return _state(False, "keep", None, model, threshold, True, [])

    if enabled and mode == "replace" and not file:
        raise UGCError(
            "A replacement background needs an image or video path.",
            "El fondo de reemplazo necesita la ruta de una imagen o un video.",
        )
    if enabled and mode == "replace" and not Path(str(file)).exists():
        raise UGCError(
            f"Background file not found: {file}",
            f"No está el archivo de fondo: {file}",
        )
    changed = _choice_changed(args, saved, flag, file, mode)
    approved = approve or yes or (bool(saved.get("approved")) and not changed)
    previews = list(saved.get("previews") or [])
    return _state(enabled, mode, file, model, threshold, approved, previews)


def _choice_changed(args, saved: dict, flag, file, mode: str) -> bool:
    if not saved:
        return False
    if getattr(args, "bg_model", None) and getattr(args, "bg_model") != saved.get("model"):
        return True
    if getattr(args, "bg_threshold", None) is not None and int(args.bg_threshold) != saved.get("threshold"):
        return True
    if flag == "transparent" and saved.get("mode") != "transparent":
        return True
    if flag and flag not in ("transparent", "keep") and str(file) != str(saved.get("file")):
        return True
    if flag and saved.get("mode") != mode:
        return True
    return False


def _state(enabled, mode, file, model, threshold, approved, previews) -> dict:
    return {
        "enabled": bool(enabled),
        "mode": mode,
        "file": file,
        "model": model,
        "threshold": threshold,
        "approved": bool(approved),
        "previews": previews,
    }


def write_matte(src: Path, dest: Path, model: str = "u2net") -> None:
    exe = backgroundremover_available()
    if not exe:
        raise UGCError(
            "backgroundremover is not installed. Run ./install.sh --with-bg. "
            "The first run downloads the u2net weights (about 176 MB) into ~/.u2net.",
            "backgroundremover no está instalado. Corre ./install.sh --with-bg. "
            "La primera vez baja los pesos u2net (unos 176 MB) a ~/.u2net.",
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_cmd([exe, "-i", str(src), "-o", str(dest), "-m", model, "-mk"])
    if not dest.exists():
        raise UGCError(
            "backgroundremover did not write the matte.",
            "backgroundremover no escribió el mate.",
        )


def subject_from_matte(cut: Path, matte: Path, dest: Path, threshold: int | None) -> None:
    """ProRes 4444 subject. The matte luma becomes alpha. Captions are not burned here."""
    info = probe(cut)
    width = int(info["width"])
    height = int(info["height"])
    mask = (
        f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},format=gray"
    )
    if threshold is not None:
        mask += f",geq=lum='if(gte(lum(X,Y),{int(threshold)}),255,0)'"
    filt = f"[0:v]format=gbrp[fg];{mask}[m];[fg][m]alphamerge,format=yuva444p10le[v]"
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(cut),
            "-i",
            str(matte),
            "-filter_complex",
            filt,
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "prores_ks",
            "-profile:v",
            "4",
            "-pix_fmt",
            "yuva444p10le",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(dest),
        ]
    )


def composite_subject(
    subject: Path,
    background: Path,
    dest: Path,
    width: int,
    height: int,
    fps: int,
    duration: float,
    crf: int,
    audio_bitrate: str,
) -> None:
    """Scale and crop the plate to the frame, then loop or trim it to `duration`."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    image = background.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    cmd = ["ffmpeg", "-y", "-i", str(subject)]
    if image:
        cmd += ["-loop", "1", "-i", str(background)]
    else:
        cmd += ["-stream_loop", "-1", "-i", str(background)]
    cmd += [
        "-filter_complex",
        (
            f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},fps={fps},trim=duration={duration:.3f},setpts=PTS-STARTPTS[bg];"
            f"[0:v]scale={width}:{height},format=rgba[fg];"
            f"[bg][fg]overlay=0:0:format=auto:shortest=1,format=yuv420p[v]"
        ),
        "-map",
        "[v]",
        "-map",
        "0:a?",
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
        "-t",
        f"{duration:.3f}",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    run_cmd(cmd)


def preview_times(duration: float, preferred: list[float] | None = None, count: int = 4) -> list[float]:
    count = min(5, max(3, count))
    chosen: list[float] = []
    for moment in preferred or []:
        if 0 <= float(moment) < max(duration, 0.001) and moment not in chosen:
            chosen.append(round(float(moment), 3))
    if len(chosen) >= count:
        return chosen[:5]
    if duration <= 0.2:
        return chosen or [0.0]
    span = max(0.1, duration - 0.08)
    need = count - len(chosen)
    for index in range(need):
        moment = round(0.04 + span * (index / max(1, need - 1)), 3)
        if moment not in chosen:
            chosen.append(moment)
    return chosen[:5]


def product_times(workdir: Path, duration: float) -> list[float]:
    path = workdir / "export" / "storyboard.json"
    if not path.exists():
        return []
    story = load_json(path)
    fps = int(story.get("fps") or 30) or 30
    times = []
    for scene in story.get("scenes") or []:
        if scene.get("label") not in _PRODUCT_LABELS:
            continue
        if scene.get("label") == "product_reveal" and scene.get("confidence") == "low":
            continue
        frame = int(scene.get("dst_in") or 0)
        moment = (frame + 1) / fps
        if 0 <= moment < duration:
            times.append(round(moment, 3))
    return times


def side_by_side_frames(original: Path, composited: Path, times: list[float], folder: Path) -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for index, moment in enumerate(times, start=1):
        dest = folder / f"compare_{index:02d}.jpg"
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{moment:.3f}",
                "-i",
                str(original),
                "-ss",
                f"{moment:.3f}",
                "-i",
                str(composited),
                "-filter_complex",
                "[0:v]scale=540:960:force_original_aspect_ratio=decrease,pad=540:960:(ow-iw)/2:(oh-ih)/2[a];"
                "[1:v]scale=540:960:force_original_aspect_ratio=decrease,pad=540:960:(ow-iw)/2:(oh-ih)/2[b];"
                "[a][b]hstack",
                "-frames:v",
                "1",
                str(dest),
            ]
        )
        written.append(str(dest))
    return written


def _solid(path: Path, color: str, width: int, height: int) -> Path:
    if not path.exists():
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c={color}:s={width}x{height}",
                "-frames:v",
                "1",
                str(path),
            ]
        )
    return path


def _stamp_key(cut: Path, state: dict) -> str:
    return f"{state.get('model')}|{state.get('threshold')}|{cut.stat().st_mtime_ns}"


def ensure_subject(cut: Path, workdir: Path, state: dict) -> Path:
    subject = workdir / "subject.mov"
    matte = workdir / "matte.mp4"
    stamp = workdir / "bg-stamp.txt"
    key = _stamp_key(cut, state)
    if subject.exists() and matte.exists() and stamp.exists() and stamp.read_text(encoding="utf-8") == key:
        return subject
    write_matte(cut, matte, state.get("model") or "u2net")
    subject_from_matte(cut, matte, subject, state.get("threshold"))
    stamp.write_text(key, encoding="utf-8")
    return subject


def _plate(cut: Path, workdir: Path, state: dict, width: int, height: int, preview: bool) -> Path:
    if state.get("mode") == "transparent":
        # Magenta makes holes obvious in the preview. The styled MP4 uses black.
        color = "magenta" if preview else "black"
        return _solid(workdir / f"bg-{color}.png", color, width, height)
    return Path(str(state["file"]))


def _composite(cut: Path, workdir: Path, state: dict, width: int, height: int, fps: int, crf: int, audio_bitrate: str, preview: bool) -> Path:
    subject = ensure_subject(cut, workdir, state)
    info = probe(cut)
    dest = workdir / ("cut-bg-preview.mp4" if preview else "cut-bg.mp4")
    composite_subject(
        subject,
        _plate(cut, workdir, state, width, height, preview),
        dest,
        width,
        height,
        fps,
        float(info["duration"]),
        crf,
        audio_bitrate,
    )
    return dest


def build_preview(cut, workdir, state, width, height, fps, crf, audio_bitrate) -> list[str]:
    composited = _composite(cut, workdir, state, width, height, fps, crf, audio_bitrate, True)
    duration = float(probe(cut)["duration"])
    times = preview_times(duration, product_times(workdir, duration))
    return side_by_side_frames(cut, composited, times, workdir / "bg-preview")


def prepare_picture(cut, workdir, state, width, height, fps, crf, audio_bitrate) -> Path:
    if not state.get("enabled") or state.get("mode") == "keep":
        return cut
    return _composite(cut, workdir, state, width, height, fps, crf, audio_bitrate, False)


def export_bg_layers(workdir: Path, media: Path, plan: dict) -> list[str]:
    state = plan.get("bg") or {}
    if not state.get("enabled") or state.get("mode") == "keep":
        return []
    written = []
    media.mkdir(parents=True, exist_ok=True)
    subject = workdir / "subject.mov"
    if subject.exists():
        shutil.copyfile(subject, media / "subject.mov")
        written.append("media/subject.mov")
    matte = workdir / "matte.mp4"
    if matte.exists():
        shutil.copyfile(matte, media / "matte.mp4")
        written.append("media/matte.mp4")
    if state.get("mode") == "replace" and state.get("file"):
        source = Path(str(state["file"]))
        if source.exists():
            dest = media / f"background{source.suffix.lower()}"
            shutil.copyfile(source, dest)
            written.append(f"media/{dest.name}")
    note = media.parent / "RELINK.md"
    extra = (
        "\n## Background\n\n"
        "`media/subject.mov` is the ProRes 4444 subject (alpha, no captions). "
        "`media/matte.mp4` is the mask. `media/background.*` is the plate when the mode is replace. "
        "These files sit beside `media/source.mp4`. They are not inside the auto-editor sequence.\n\n"
        "`media/subject.mov` es el sujeto en ProRes 4444 (alfa, sin subtítulos). "
        "`media/matte.mp4` es la máscara. `media/background.*` es el fondo cuando el modo es reemplazo. "
        "Están junto a `media/source.mp4`. No van dentro de la secuencia de auto-editor.\n"
    )
    if note.exists() and "## Background" not in note.read_text(encoding="utf-8"):
        note.write_text(note.read_text(encoding="utf-8") + extra, encoding="utf-8")
    return written


def bg_checkpoint_message(ui: str, frames: list[str], state: dict) -> str:
    files = "\n".join(frames)
    plate = "magenta" if state.get("mode") == "transparent" else str(state.get("file"))
    if ui == "es":
        return (
            "exit: 13\n"
            "question: background\n"
            f"model: {state.get('model')}\n"
            f"mode: {state.get('mode')}\n"
            f"plate: {plate}\n"
            "Compara el original (izquierda) con el fondo nuevo (derecha). "
            "En modo transparente la derecha es el sujeto sobre magenta para ver los huecos.\n"
            "Si el producto en la mano o las manos desaparecen o parpadean, no lo des por bueno.\n"
            f"{files}\n"
            "Opciones: --bg-yes | --bg-model u2net_human_seg --bg-yes | --bg-threshold 40 --bg-yes | --bg-skip"
        )
    return (
        "exit: 13\n"
        "question: background\n"
        f"model: {state.get('model')}\n"
        f"mode: {state.get('mode')}\n"
        f"plate: {plate}\n"
        "Compare the original (left) with the new background (right). "
        "In transparent mode the right side is the subject over magenta so holes show.\n"
        "Do not approve it if a hand-held product or the hands are cut out or flicker.\n"
        f"{files}\n"
        "Options: --bg-yes | --bg-model u2net_human_seg --bg-yes | --bg-threshold 40 --bg-yes | --bg-skip"
    )
