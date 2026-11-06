"""Cut the timeline, then style it with Remotion or FFmpeg."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .config import font_path
from .util import skill_root
from .edit import build_ass
from .media import loop_music, probe, run_cmd
from .util import UGCError, dump_json


def _scale_clause(width: int, height: int, fps: int) -> str:
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={fps},format=yuv420p"
    )


def cut_video(
    src: Path,
    dest: Path,
    ranges: list[dict],
    width: int,
    height: int,
    fps: int,
    crf: int,
    audio_bitrate: str,
) -> None:
    if not ranges:
        raise UGCError(
            "The edit removed the whole clip. Loosen the filler mode or the silence threshold.",
            "El corte se quedó sin video. Afloja las muletillas o el umbral de silencio.",
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    scale = _scale_clause(width, height, fps)
    parts: list[str] = []
    labels: list[str] = []
    for index, block in enumerate(ranges):
        start = f"{block['src_start']:.3f}"
        end = f"{block['src_end']:.3f}"
        parts.append(
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,{scale}[v{index}]"
        )
        parts.append(
            f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,"
            f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a{index}]"
        )
        labels.append(f"[v{index}][a{index}]")
    parts.append(f"{''.join(labels)}concat=n={len(ranges)}:v=1:a=1[v][a]")
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-filter_complex",
            ";".join(parts),
            "-map",
            "[v]",
            "-map",
            "[a]",
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


def _wrap_hook(text: str, width_chars: int) -> str:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        trial = " ".join([*current, word])
        if current and len(trial) > width_chars:
            lines.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines[:3])


def _ff_filter_path(path: Path) -> str:
    """Escape a path for an ffmpeg filtergraph value."""
    text = str(path)
    return (
        text.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", "\\'")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
    )


def style_ffmpeg(
    cut: Path,
    dest: Path,
    plan: dict,
    preset: dict,
    music: Path | None,
    workdir: Path,
) -> dict:
    """Burn ASS captions and a drawtext hook, then duck the bed with volume=-18dB.

    `music.engine=sidechain` uses sidechaincompress (verified on ffmpeg 6.1:
    threshold, ratio, attack, release, makeup). The default is a static -18 dB
    cut, which is the gain that actually lands 18 dB under the voice.
    """
    captions_cfg = preset["captions"]
    hook_cfg = preset["hook"]
    export = preset["export"]
    safe = preset["safe_zone"]
    family = _font_family(font_path())
    ass = build_ass(
        plan["captions"],
        font_name=family,
        font_size=int(captions_cfg["font_size"]),
        color=captions_cfg["color"],
        highlight=captions_cfg["highlight_color"],
        highlight_enabled=bool(captions_cfg["highlight_active_word"]),
        play_res_x=int(export["width"]),
        play_res_y=int(export["height"]),
    )
    ass_path = workdir / "captions.ass"
    ass_path.write_text(ass, encoding="utf-8")
    fonts_dir = workdir / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    dest_font = fonts_dir / font_path().name
    if not dest_font.exists():
        shutil.copyfile(font_path(), dest_font)
    hook_file = workdir / "hook.txt"
    hook_text = (plan.get("hook") or {}).get("text") or ""
    hook_size = int(hook_cfg["font_size"])
    usable = int(export["width"]) - int(safe["left"]) - int(safe["right"])
    # Inter Bold is roughly 0.62em wide. Wrap so the plate stays inside the safe zone.
    chars_per_line = max(12, int(usable / (hook_size * 0.62)))
    hook_wrapped = _wrap_hook(hook_text, chars_per_line)
    hook_file.write_text(hook_wrapped, encoding="utf-8")

    video_filters = [
        f"subtitles={_ff_filter_path(ass_path)}:fontsdir={_ff_filter_path(fonts_dir)}"
    ]
    if hook_text:
        hook_end = float(hook_cfg["duration_seconds"])
        y_ratio = float(hook_cfg["y_ratio"])
        # y sits just under the top safe margin (safe_zone.top).
        y_expr = f"max({int(safe['top'])}\\,h*{y_ratio})"
        video_filters.append(
            "drawtext="
            f"fontfile={_ff_filter_path(dest_font)}:"
            f"textfile={_ff_filter_path(hook_file)}:"
            f"fontsize={hook_size}:"
            "fontcolor=white:borderw=6:bordercolor=black:"
            "box=1:boxcolor=black@0.55:boxborderw=16:"
            "line_spacing=6:text_align=center:"
            "x=(w-text_w)/2:"
            f"y={y_expr}:"
            f"enable='between(t,0,{hook_end:.3f})'"
        )
    video = ",".join(video_filters)
    duck = float(preset["music"]["duck_db"])
    engine = preset["music"].get("engine", "volume")
    cmd = ["ffmpeg", "-y", "-i", str(cut)]
    if music:
        cmd += ["-stream_loop", "-1", "-i", str(music)]
        if engine == "sidechain":
            # Bed starts at the requested duck, then sidechaincompress pulls it
            # down further while the voice is loud and lets it back up in gaps.
            audio = (
                f"[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                f"volume={duck}dB[bed];"
                f"[0:a]asplit=2[voice][sc];"
                f"[bed][sc]sidechaincompress=threshold=0.05:ratio=8:attack=20:release=300:makeup=1[ducked];"
                f"[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
            )
        else:
            audio = (
                f"[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
                f"volume={duck}dB[bed];"
                f"[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[voice];"
                f"[voice][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
            )
        filter_complex = f"[0:v]{video}[v];{audio}"
        cmd += [
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            "[a]",
        ]
    else:
        cmd += ["-vf", video, "-map", "0:v", "-map", "0:a"]
    cmd += [
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(export["crf"]),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        export["audio_bitrate"],
        "-movflags",
        "+faststart",
        str(dest),
    ]
    run_cmd(cmd)
    return {"renderer": "ffmpeg", "music": str(music) if music else None, "duck_db": duck, "music_engine": engine if music else None}


def _font_family(path: Path) -> str:
    if not shutil.which("fc-scan"):
        return "Inter"
    completed = subprocess.run(
        ["fc-scan", str(path)],
        text=True,
        capture_output=True,
        check=False,
    )
    for line in (completed.stdout or "").splitlines():
        if "family:" in line and "(s)" in line:
            # family: "Inter"(s)
            quoted = line.split('"', 2)
            if len(quoted) >= 2:
                return quoted[1]
    return "Inter"


def remotion_ready(template: Path) -> bool:
    return (template / "node_modules" / "remotion").exists() and shutil.which("npx") is not None


def style_remotion(cut: Path, dest: Path, plan: dict, preset: dict, music: Path | None, workdir: Path) -> dict:
    template = skill_root() / "template"
    if not remotion_ready(template):
        raise UGCError(
            "Remotion dependencies are missing. Run install.sh or render with --renderer ffmpeg.",
            "Faltan las dependencias de Remotion. Corre install.sh o usa --renderer ffmpeg.",
        )
    public = template / "public"
    public.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cut, public / "input.mp4")
    fonts = public / "fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(font_path(), fonts / font_path().name)
    music_name = None
    if music:
        looped = workdir / "music-loop.m4a"
        loop_music(music, looped, float(plan["output_duration"]) + 0.25)
        shutil.copyfile(looped, public / "music.m4a")
        music_name = "music.m4a"
    duck_db = float(preset["music"]["duck_db"])
    # 10^(-18/20) ≈ 0.1259. The composition multiplies the bed by this.
    volume = 10 ** (duck_db / 20.0)
    duration = float(probe(cut)["duration"])
    captions = preset["captions"]
    hook_cfg = preset["hook"]
    hook = dict(plan.get("hook") or {})
    if hook.get("text"):
        usable = int(preset["export"]["width"]) - int(preset["safe_zone"]["left"]) - int(preset["safe_zone"]["right"])
        chars = max(12, int(usable / (int(hook_cfg["font_size"]) * 0.62)))
        hook["text"] = _wrap_hook(hook["text"], chars)
    props = {
        "videoSrc": "input.mp4",
        "musicSrc": music_name,
        "musicVolume": volume,
        "durationInSeconds": duration,
        "highlight": bool(captions["highlight_active_word"]),
        "hook": hook or None,
        "captions": plan["captions"],
        "style": {
            "fontFamily": "Inter",
            "captionSize": int(captions["font_size"]),
            "hookSize": int(hook_cfg["font_size"]),
            "color": captions["color"],
            "highlightColor": captions["highlight_color"],
            "captionY": float(captions["y_ratio"]),
            "hookY": float(hook_cfg["y_ratio"]),
            "safe": preset["safe_zone"],
        },
    }
    props_path = workdir / "props.json"
    dump_json(props_path, props)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "npx",
        "remotion",
        "render",
        "src/index.ts",
        "TalkingHead",
        str(dest),
        f"--props={props_path}",
        "--codec=h264",
        "--pixel-format=yuv420p",
        "--crf=18",
        "--concurrency=1",
        "--disallow-parallel-encoding",
        "--log=info",
    ]
    completed = subprocess.run(
        cmd,
        cwd=str(template),
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "CI": "1"},
    )
    log = workdir / "remotion.log"
    log.write_text((completed.stdout or "") + "\n" + (completed.stderr or ""), encoding="utf-8")
    if completed.returncode != 0 or not dest.exists():
        tail = (completed.stderr or completed.stdout or "")[-2500:]
        raise UGCError(
            f"Remotion render failed.\n{tail}",
            f"Falló el render de Remotion.\n{tail}",
        )
    return {"renderer": "remotion", "music": str(music) if music else None, "duck_db": duck_db, "music_engine": "volume"}


def render_styled(
    cut: Path,
    dest: Path,
    plan: dict,
    preset: dict,
    music: Path | None,
    workdir: Path,
    renderer: str,
) -> dict:
    if renderer == "auto":
        renderer = "remotion" if remotion_ready(skill_root() / "template") else "ffmpeg"
    if renderer == "remotion":
        try:
            return style_remotion(cut, dest, plan, preset, music, workdir)
        except UGCError:
            if preset.get("_renderer_explicit"):
                raise
            ffmpeg_dest = dest
            info = style_ffmpeg(cut, ffmpeg_dest, plan, preset, music, workdir)
            info["remotion_fallback"] = True
            return info
    if renderer == "ffmpeg":
        return style_ffmpeg(cut, dest, plan, preset, music, workdir)
    raise UGCError(
        f"Unknown renderer: {renderer}",
        f"Renderer desconocido: {renderer}",
    )
