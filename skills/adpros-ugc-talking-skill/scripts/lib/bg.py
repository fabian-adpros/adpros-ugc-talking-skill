"""Optional background removal. Captions are burned later, on the composite.

The matte comes from `backgroundremover` (MIT) and the U2-Net weights
(Apache-2.0). The default model is `u2net`, the general saliency net.
`u2net_human_seg` is person-only and often erases a product held in the hand.

backgroundremover's own video path resizes the frame to a height of 320 and
then squares it to 320x320. It does not take an inference size. When the
Python package imports, this skill runs the same weights at `bg.infer_size`
(short side, aspect kept). A temporal median, a morphological close, and a
guided feather follow. The edge can still flicker. Grounded-SAM-2 is the
next step when a hand-held product still drops out. Apple Silicon was not
tested (PyTorch MPS is not selected).
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from .engine import (
    ben2_available,
    birefnet_available,
    device_name,
    estimate_bg_seconds,
    bg_cost_should_stop,
    pick_device,
    predict_masks,
    select_engine,
    u2net_python_available,
)
from .matte import smooth_alpha, working_size
from .media import probe, run_cmd
from .render import cut_stamp_path
from .util import UGCError, load_json

MODELS = ("u2net", "u2net_human_seg", "u2netp")
AWAITING_BG = 13
AWAITING_BG_COST = 14
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
    settings = _settings(args, saved, cfg)
    engine, explicit = _pick_engine(args, saved, cfg)
    settings["engine"] = engine
    settings["engine_explicit"] = explicit
    if skip or flag == "keep":
        return _state(False, "keep", None, model, threshold, True, [], settings)

    if flag == "transparent":
        enabled, mode, file = True, "transparent", None
    elif flag:
        enabled, mode, file = True, "replace", str(flag)
    elif "enabled" in saved:
        enabled = bool(saved.get("enabled"))
        mode = saved.get("mode") or "keep"
        file = saved.get("file")
        if not enabled:
            return _state(False, "keep", None, model, threshold, True, [], settings)
    elif cfg.get("enabled"):
        mode = cfg.get("mode") or "keep"
        file = cfg.get("file")
        enabled = mode != "keep"
        if not enabled:
            return _state(False, "keep", None, model, threshold, True, [], settings)
    else:
        return _state(False, "keep", None, model, threshold, True, [], settings)

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
    state = _state(enabled, mode, file, model, threshold, approved, previews, settings)
    if saved.get("timings"):
        state["timings"] = saved["timings"]
    return state


def _pick_engine(args, saved: dict, cfg: dict) -> tuple[str, bool]:
    flag = getattr(args, "bg_engine", None)
    if flag:
        return str(flag), True
    if saved.get("engine"):
        return str(saved["engine"]), bool(saved.get("engine_explicit"))
    return str(cfg.get("engine") or "birefnet"), False


def _settings(args, saved: dict, cfg: dict) -> dict:
    infer_size = _pick_int(args, "bg_infer_size", saved, cfg, "infer_size", 320)
    temporal = _pick_int(args, "bg_smooth", saved, cfg, "temporal_smooth", 3)
    feather = _pick_int(args, "bg_feather", saved, cfg, "feather", 0)
    refine_flag = getattr(args, "bg_refine", None)
    if refine_flag:
        refine = True
    elif "refine" in saved:
        refine = bool(saved.get("refine"))
    else:
        refine = bool(cfg.get("refine", False))
    morph = saved.get("morph_close", cfg.get("morph_close", 1))
    morph = 1 if morph is None else int(morph)
    mode = saved.get("smooth_mode") or cfg.get("smooth_mode") or "median"
    if mode not in ("median", "ema"):
        raise UGCError(
            "bg.smooth_mode must be median or ema.",
            "bg.smooth_mode tiene que ser median o ema.",
        )
    if infer_size < 64 or infer_size > 1024:
        raise UGCError(
            "bg.infer_size must be from 64 to 1024.",
            "bg.infer_size tiene que estar entre 64 y 1024.",
        )
    if temporal < 0 or temporal > 5:
        raise UGCError(
            "bg.temporal_smooth must be from 0 to 5.",
            "bg.temporal_smooth tiene que estar entre 0 y 5.",
        )
    if feather < 0 or feather > 8 or morph < 0 or morph > 3:
        raise UGCError(
            "Background feather must be 0–8 and morph_close 0–3.",
            "El feather del fondo es 0–8 y morph_close 0–3.",
        )
    return {
        "infer_size": int(infer_size),
        "temporal_smooth": int(temporal),
        "smooth_mode": mode,
        "morph_close": int(morph),
        "feather": int(feather),
        "refine": bool(refine),
    }


def _pick_int(args, flag: str, saved: dict, cfg: dict, key: str, default: int) -> int:
    value = getattr(args, flag, None)
    if value is None:
        value = saved.get(key, cfg.get(key, default))
    if value is None:
        value = default
    return int(value)


def _choice_changed(args, saved: dict, flag, file, mode: str) -> bool:
    if not saved:
        return False
    if getattr(args, "bg_model", None) and getattr(args, "bg_model") != saved.get("model"):
        return True
    if getattr(args, "bg_threshold", None) is not None and int(args.bg_threshold) != saved.get("threshold"):
        return True
    if getattr(args, "bg_engine", None) and getattr(args, "bg_engine") != saved.get("engine"):
        return True
    if getattr(args, "bg_infer_size", None) is not None and int(args.bg_infer_size) != saved.get("infer_size"):
        return True
    if getattr(args, "bg_smooth", None) is not None and int(args.bg_smooth) != saved.get("temporal_smooth"):
        return True
    if getattr(args, "bg_feather", None) is not None and int(args.bg_feather) != saved.get("feather"):
        return True
    if flag == "transparent" and saved.get("mode") != "transparent":
        return True
    if flag and flag not in ("transparent", "keep") and str(file) != str(saved.get("file")):
        return True
    if flag and saved.get("mode") != mode:
        return True
    return False


def _state(enabled, mode, file, model, threshold, approved, previews, settings: dict | None = None) -> dict:
    state = {
        "enabled": bool(enabled),
        "mode": mode,
        "file": file,
        "model": model,
        "threshold": threshold,
        "approved": bool(approved),
        "previews": previews,
        "infer_size": 320,
        "temporal_smooth": 3,
        "smooth_mode": "median",
        "morph_close": 1,
        "feather": 0,
        "refine": False,
        "engine": "birefnet",
        "engine_explicit": False,
    }
    if settings:
        state.update(settings)
    return state


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


def render_matte(src: Path, dest: Path, state: dict) -> None:
    """Write a matte at the cut's size. The guided filter is not used."""
    _bind_engine(state)
    engine = state.get("engine_used") or "u2net"
    started = time.perf_counter()
    if engine != "u2net" or u2net_python_available():
        try:
            infer_matte(src, dest, state)
        except UGCError:
            raise
        except Exception as exc:
            raise UGCError(
                f"Background model {engine} failed ({exc}). Try --bg-engine u2net or ./install.sh --with-bg.",
                f"Falló el modelo de fondo {engine} ({exc}). Prueba --bg-engine u2net o ./install.sh --with-bg.",
            ) from exc
        refine_started = time.perf_counter()
        fit_matte(src, dest, {**state, "temporal_smooth": 0})
        state["timings"]["refine_s"] = round(time.perf_counter() - refine_started, 3)
        state["timings"]["total_s"] = round(time.perf_counter() - started, 3)
    else:
        write_matte(src, dest, state.get("model") or "u2net")
        infer_s = round(time.perf_counter() - started, 3)
        refine_started = time.perf_counter()
        fit_matte(src, dest, state)
        state["timings"] = {
            "path": "cli",
            "engine": "u2net",
            "device": "cli",
            "infer_s": infer_s,
            "refine_s": round(time.perf_counter() - refine_started, 3),
            "infer_size": None,
            "frames": None,
            "reused": False,
            "note": "backgroundremover CLI resizes to height 320 and squares to 320. No Python engine was importable.",
        }
    _print_timings(state)


def _bind_engine(state: dict) -> None:
    if state.get("engine_used"):
        return
    engine, note = select_engine(state.get("engine") or "birefnet", bool(state.get("engine_explicit")))
    state["engine_used"] = engine
    state["engine_note"] = note
    if note:
        print("bg: " + note)


def _print_timings(state: dict) -> None:
    timings = state.get("timings") or {}
    if timings.get("reused"):
        print("bg: reused the existing matte")
        return
    print(
        "bg: "
        f"path={timings.get('path')} device={timings.get('device')} "
        f"infer_size={timings.get('infer_size')} frames={timings.get('frames')} "
        f"engine={timings.get('engine')} "
        f"infer={timings.get('infer_s')}s per_frame={timings.get('per_frame_s')}s "
        f"smooth={timings.get('smooth_s')}s fit={timings.get('refine_s')}s"
    )


def fit_matte(cut: Path, matte: Path, state: dict) -> None:
    """Scale the matte to the cut, then optional close and a small blur. No guided filter."""
    if not matte.exists():
        return
    info = probe(cut)
    width = int(info["width"])
    height = int(info["height"])
    chain = [f"scale={width}:{height}:flags=lanczos", "format=gray"]
    temporal = int(state.get("temporal_smooth") or 0)
    if temporal >= 3:
        chain.append(f"tmix=frames={int(temporal)}")
    for _ in range(max(0, int(state.get("morph_close") or 0))):
        chain.append("dilation")
        chain.append("erosion")
    # Guided refine copied the picture into the mask. It stays off unless bg.refine is set,
    # and then it is only a blur of the alpha.
    if state.get("refine") and int(state.get("feather") or 0) > 0:
        sigma = max(0.4, min(float(state["feather"]), 3.0))
        chain.append(f"gblur=sigma={sigma}")
    fitted = matte.with_name(matte.stem + "-fitted.mp4")
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(matte),
            "-vf",
            ",".join(chain),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            str(fitted),
        ]
    )
    fitted.replace(matte)


def infer_matte(src: Path, dest: Path, state: dict) -> None:
    """Run the selected engine at `infer_size` (short side, aspect kept)."""
    import numpy as np

    _bind_engine(state)
    info = probe(src)
    width, height = working_size(int(info["width"]), int(info["height"]), int(state.get("infer_size") or 320))
    fps = float(info.get("fps") or 30)
    frame_bytes = width * height * 3
    log_path = dest.with_name("bg-infer.log")
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(src),
                "-vf",
                f"scale={width}:{height}:flags=lanczos,setsar=1",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            stdout=subprocess.PIPE,
            stderr=log,
        )
        frames = []
        assert proc.stdout is not None
        while True:
            blob = proc.stdout.read(frame_bytes)
            if len(blob) < frame_bytes:
                break
            frames.append(np.frombuffer(blob, dtype=np.uint8).reshape(height, width, 3).copy())
        proc.wait()
    if proc.returncode not in (0, None) or not frames:
        raise UGCError(
            f"Could not read frames for the matte. See {log_path}.",
            f"No se pudieron leer los cuadros del mate. Mira {log_path}.",
        )
    device = pick_device()
    try:
        masks = predict_masks(frames, state.get("engine_used") or "u2net", state.get("model") or "u2net", device)
    except UGCError:
        raise
    except Exception as exc:
        raise UGCError(
            f"Background model {state.get('engine_used')} failed ({exc}). Try --bg-engine u2net.",
            f"Falló el modelo {state.get('engine_used')} ({exc}). Prueba --bg-engine u2net.",
        ) from exc
    infer_s = round(time.perf_counter() - started, 3)
    smooth_started = time.perf_counter()
    volume = np.stack(masks, axis=0)
    smoothed = smooth_alpha(volume, int(state.get("temporal_smooth") or 0), state.get("smooth_mode") or "median")
    smooth_s = round(time.perf_counter() - smooth_started, 3)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        encoder = subprocess.Popen(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "gray",
                "-s",
                f"{width}x{height}",
                "-r",
                f"{fps:.6f}",
                "-i",
                "pipe:0",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "16",
                "-pix_fmt",
                "yuv420p",
                str(dest),
            ],
            stdin=subprocess.PIPE,
            stderr=log,
        )
        assert encoder.stdin is not None
        for mask in smoothed:
            encoder.stdin.write(np.ascontiguousarray(mask, dtype=np.uint8).tobytes())
        encoder.stdin.close()
        encoder.wait()
    if encoder.returncode != 0 or not dest.exists():
        raise UGCError(
            f"Could not write the matte. See {log_path}.",
            f"No se pudo escribir el mate. Mira {log_path}.",
        )
    per_frame = round(infer_s / max(1, len(masks)), 4)
    state["timings"] = {
        "path": "python",
        "engine": state.get("engine_used"),
        "device": str(device),
        "infer_s": infer_s,
        "per_frame_s": per_frame,
        "smooth_s": smooth_s,
        "frames": len(masks),
        "infer_size": [width, height],
        "reused": False,
    }


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


def preview_times(
    duration: float,
    preferred: list[float] | None = None,
    count: int = 4,
    fps: int = 30,
) -> list[float]:
    """Times that still have a frame. The last seek stops two frames before the end."""
    count = min(5, max(3, count))
    margin = 2.0 / max(1, int(fps))
    last = max(0.0, float(duration) - margin)

    def clamp(moment: float) -> float:
        return round(min(max(0.0, float(moment)), last), 3)

    chosen: list[float] = []
    for moment in preferred or []:
        item = clamp(moment)
        if item not in chosen:
            chosen.append(item)
    if len(chosen) < count and duration > 0.2:
        span = max(0.0, last - 0.04)
        need = count - len(chosen)
        for index in range(max(1, need)):
            item = clamp(0.04 + span * (index / max(1, need - 1)))
            if item not in chosen:
                chosen.append(item)
    if not chosen:
        chosen = [0.0]
    return sorted(set(chosen))[:5]


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
    skipped = []
    for index, moment in enumerate(times, start=1):
        dest = folder / f"compare_{index:02d}.jpg"
        try:
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
                    "[a][b]hstack,format=yuvj420p",
                    "-strict",
                    "unofficial",
                    "-frames:v",
                    "1",
                    str(dest),
                ]
            )
        except UGCError:
            skipped.append(moment)
            if dest.exists():
                dest.unlink()
            continue
        if dest.exists() and dest.stat().st_size > 0:
            written.append(str(dest))
        else:
            skipped.append(moment)
    if not written:
        raise UGCError(
            f"No preview frame could be written (tried {times}). See ugc-ffmpeg.log.",
            f"No se pudo escribir ningún cuadro de vista previa (intenté {times}). Mira ugc-ffmpeg.log.",
        )
    if skipped:
        print(f"Skipped preview times with no frame: {skipped}")
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


def _cut_identity(cut: Path) -> str:
    stamp = cut_stamp_path(cut)
    if stamp.exists():
        return stamp.read_text(encoding="utf-8").strip()
    return f"mtime:{cut.stat().st_mtime_ns}:{cut.stat().st_size}"


def _matte_key(cut: Path, state: dict) -> str:
    fields = {
        "cut": _cut_identity(cut),
        "model": state.get("model"),
        "engine": state.get("engine_used") or state.get("engine"),
        "infer_size": state.get("infer_size"),
        "temporal_smooth": state.get("temporal_smooth"),
        "smooth_mode": state.get("smooth_mode"),
        "morph_close": state.get("morph_close"),
        "feather": state.get("feather"),
        "refine": bool(state.get("refine")),
    }
    return "|".join(f"{key}={fields[key]}" for key in sorted(fields))


def _subject_key(cut: Path, state: dict) -> str:
    return _matte_key(cut, state) + f"|threshold={state.get('threshold')}"


def ensure_subject(cut: Path, workdir: Path, state: dict) -> Path:
    subject = workdir / "subject.mov"
    matte = workdir / "matte.mp4"
    matte_stamp = workdir / "bg-matte-stamp.txt"
    subject_stamp = workdir / "bg-stamp.txt"
    _bind_engine(state)
    matte_key = _matte_key(cut, state)
    subject_key = _subject_key(cut, state)
    matte_ready = matte.exists() and matte_stamp.exists() and matte_stamp.read_text(encoding="utf-8").strip() == matte_key
    if (
        subject.exists()
        and matte_ready
        and subject_stamp.exists()
        and subject_stamp.read_text(encoding="utf-8").strip() == subject_key
    ):
        state["timings"] = dict(state.get("timings") or {})
        state["timings"]["reused"] = True
        _print_timings(state)
        return subject
    if not matte_ready:
        render_matte(cut, matte, state)
        matte_stamp.write_text(matte_key + "\n", encoding="utf-8")
    subject_from_matte(cut, matte, subject, state.get("threshold"))
    subject_stamp.write_text(subject_key + "\n", encoding="utf-8")
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
    info = probe(cut)
    duration = float(info["duration"])
    fps = int(round(float(info.get("fps") or 30))) or 30
    times = preview_times(duration, product_times(workdir, duration), fps=fps)
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


def _engine_label(state: dict) -> str:
    engine = state.get("engine_used") or state.get("engine") or "birefnet"
    if engine == "u2net":
        return f"engine: u2net\nmodel: {state.get('model') or 'u2net'}"
    if engine == "ben2":
        return "engine: ben2\nweights: PramaLLC/BEN2"
    return "engine: birefnet\nweights: ZhengPeng7/BiRefNet_lite"


def bg_checkpoint_message(ui: str, frames: list[str], state: dict) -> str:
    files = "\n".join(frames)
    plate = "magenta" if state.get("mode") == "transparent" else str(state.get("file"))
    label = _engine_label(state)
    if ui == "es":
        return (
            "exit: 13\n"
            "question: background\n"
            f"{label}\n"
            f"mode: {state.get('mode')}\n"
            f"plate: {plate}\n"
            "Compara el original (izquierda) con el fondo nuevo (derecha). "
            "En modo transparente la derecha es el sujeto sobre magenta para ver los huecos.\n"
            "Si el producto en la mano o las manos desaparecen o parpadean, no lo des por bueno.\n"
            f"{files}\n"
            "Opciones: --bg-yes | --bg-engine u2net --bg-yes | --bg-engine ben2 --bg-yes | "
            "--bg-infer-size 512 --bg-smooth 5 --bg-yes | --bg-skip"
        )
    return (
        "exit: 13\n"
        "question: background\n"
        f"{label}\n"
        f"mode: {state.get('mode')}\n"
        f"plate: {plate}\n"
        "Compare the original (left) with the new background (right). "
        "In transparent mode the right side is the subject over magenta so holes show.\n"
        "Do not approve it if a hand-held product or the hands are cut out or flicker.\n"
        f"{files}\n"
        "Options: --bg-yes | --bg-engine u2net --bg-yes | --bg-engine ben2 --bg-yes | "
        "--bg-infer-size 512 --bg-smooth 5 --bg-yes | --bg-skip"
    )
