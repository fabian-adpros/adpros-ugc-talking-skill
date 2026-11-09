"""Editor timelines. Premiere and Final Cut come from auto-editor 29.

OpenTimelineIO and its extra adapters are optional. The skill still runs
without them.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import default_music_path, load_preset
from .media import auto_editor_available, probe, run_cmd
from .storyboard import cut_out_frames, write_storyboard
from .util import UGCError, dump_json, load_json

NLE_CHOICES = ("all", "premiere", "fcpx", "otio", "edl")


def _auto_editor_version(exe: str) -> tuple[int, int, int]:
    completed = subprocess.run([exe, "--version"], text=True, capture_output=True, check=False)
    text = (completed.stdout or completed.stderr or "").strip().split()[0]
    parts = []
    for piece in text.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def require_auto_editor_29() -> str:
    exe = auto_editor_available()
    if not exe:
        raise UGCError(
            "auto-editor is not installed. Premiere and FCPXML export need auto-editor 29.",
            "auto-editor no está instalado. Premiere y FCPXML necesitan auto-editor 29.",
        )
    major, minor, _patch = _auto_editor_version(exe)
    if major != 29:
        raise UGCError(
            f"auto-editor {major}.{minor} is installed. This export uses the 29.x flags only "
            "(--edit none, --cut-out, --export premiere, --export final-cut-pro). "
            "It does not use edl, resolve-fcp7, premiere-otio, or version=.",
            f"Está auto-editor {major}.{minor}. Esta exportación solo usa flags de la 29.x.",
        )
    return exe


def conform_cfr(src: Path, dest: Path, width: int, height: int, fps: int, crf: int, audio_bitrate: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_cmd(
        [
            "ffmpeg",
            "-y",
            "-fflags",
            "+genpts",
            "-i",
            str(src),
            "-vf",
            (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"fps={fps},format=yuv420p"
            ),
            "-r",
            str(fps),
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
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(dest),
        ]
    )


def _rewrite_media_paths(path: Path, absolute: Path, relative: str) -> None:
    text = path.read_text(encoding="utf-8")
    absolute_text = str(absolute.resolve())
    replacements = [
        absolute_text,
        absolute_text.replace("\\", "/"),
        "file://" + absolute_text,
        "file://" + absolute_text.replace("\\", "/"),
    ]
    for old in replacements:
        text = text.replace(old, relative)
    path.write_text(text, encoding="utf-8")


def _run_auto_editor(exe: str, media: Path, cuts: list[tuple[int, int]], fps: int, mode: str, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe,
        str(media),
        "--edit",
        "none",
        "--margin",
        "0",
        "--frame-rate",
        str(fps),
        "--export",
        mode,
        "--output",
        str(output),
        "--no-open",
        "--quiet",
    ]
    for start, end in cuts:
        cmd.extend(["--cut-out", f"{start},{end}"])
    run_cmd(cmd)
    if not output.exists():
        raise UGCError(
            f"auto-editor did not write {output.name}.",
            f"auto-editor no escribió {output.name}.",
        )


def otio_available() -> bool:
    try:
        import opentimelineio  # noqa: F401
    except ImportError:
        return False
    return True


def otio_adapter(name: str) -> bool:
    if not otio_available():
        return False
    import opentimelineio as otio

    return name in otio.adapters.available_adapter_names()


def build_otio(story: dict):
    import opentimelineio as otio

    fps = int(story["fps"])

    def span(start: int, frames: int):
        return otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(int(start), fps),
            duration=otio.opentime.RationalTime(int(frames), fps),
        )

    video_clips = story["tracks"]["video"]
    total = video_clips[-1]["src_out"] if video_clips else 0
    # available range covers the conformed source, which is at least the last source out
    source_frames = max([total, int(round(float(story["source_duration"]) * fps))], default=0)
    source_ref = otio.schema.ExternalReference(
        target_url="media/source.mp4",
        available_range=span(0, max(1, source_frames)),
    )
    video = otio.schema.Track(name="video", kind=otio.schema.TrackKind.Video)
    voice = otio.schema.Track(name="audio_voice", kind=otio.schema.TrackKind.Audio)
    for clip in video_clips:
        frames = clip["src_out"] - clip["src_in"]
        source_range = span(clip["src_in"], frames)
        video.append(otio.schema.Clip(name=f"keep_{clip['index']:03d}", media_reference=source_ref, source_range=source_range))
        voice.append(otio.schema.Clip(name=f"voice_{clip['index']:03d}", media_reference=source_ref, source_range=source_range))
    music_track = otio.schema.Track(name="music", kind=otio.schema.TrackKind.Audio)
    music = story["tracks"]["music"]
    music_frames = int(music["dst_out"])
    if music_frames > 0 and music.get("file"):
        music_ref = otio.schema.ExternalReference(
            target_url="media/music.m4a",
            available_range=span(0, music_frames),
        )
        music_clip = otio.schema.Clip(
            name="bed",
            media_reference=music_ref,
            source_range=span(0, music_frames),
        )
        music_clip.metadata["ugc"] = {"level_db": music["level_db"]}
        music_track.append(music_clip)
    hook = story["overlays"].get("hook") or {}
    if hook.get("text"):
        hook_frames = max(1, int(round(float(hook.get("end") or 0) * fps)))
        video.markers.append(
            otio.schema.Marker(
                name="hook",
                marked_range=span(0, hook_frames),
                color=otio.schema.MarkerColor.BLUE,
            )
        )
    for cut in story["cuts"]:
        start = int(round(float(cut["start"]) * fps))
        frames = max(1, int(round((float(cut["end"]) - float(cut["start"])) * fps)))
        video.markers.append(
            otio.schema.Marker(
                name=str(cut["reason"]),
                marked_range=span(start, frames),
                color=otio.schema.MarkerColor.ORANGE if cut["reason"] == "filler" else otio.schema.MarkerColor.BLACK,
            )
        )
    for slot in story["broll_slots"]:
        if slot.get("label") == "product_reveal" and slot.get("confidence") == "low":
            continue
        frames = int(slot["dst_out"]) - int(slot["dst_in"])
        video.markers.append(
            otio.schema.Marker(
                name=str(slot["label"]),
                marked_range=span(int(slot["dst_in"]), max(1, frames)),
                color=otio.schema.MarkerColor.GREEN,
            )
        )
    timeline = otio.schema.Timeline(name="adpros-ugc-talking-skill")
    timeline.global_start_time = otio.opentime.RationalTime(0, fps)
    timeline.tracks.extend([video, voice, music_track])
    return timeline


def _write_otio(story: dict, export: Path, targets: set[str], notes: list[str]) -> None:
    if not ({"otio", "edl"} & targets):
        return
    if not otio_available():
        notes.append("OpenTimelineIO is not installed. timeline.otio and the EDL were skipped.")
        if targets <= {"otio", "edl"}:
            raise UGCError(
                "OpenTimelineIO is not installed. Re-run install.sh --with-otio.",
                "OpenTimelineIO no está instalado. Vuelve a correr install.sh --with-otio.",
            )
        return
    import opentimelineio as otio

    timeline = build_otio(story)
    if "otio" in targets or "all" in targets:
        otio.adapters.write_to_file(timeline, str(export / "timeline.otio"))
    if "edl" in targets or "all" in targets:
        if otio_adapter("cmx_3600"):
            otio.adapters.write_to_file(timeline, str(export / "project.edl"), adapter_name="cmx_3600")
        else:
            notes.append("otio-cmx3600-adapter is not installed. project.edl was skipped.")
            if targets == {"edl"}:
                raise UGCError(
                    "otio-cmx3600-adapter is not installed, so the EDL cannot be written.",
                    "No está otio-cmx3600-adapter, así que no se puede escribir el EDL.",
                )


def _fallback_xml(story: dict, export: Path, adapter: str, dest: Path, notes: list[str]) -> bool:
    if not otio_adapter(adapter):
        return False
    import opentimelineio as otio

    timeline = build_otio(story)
    otio.adapters.write_to_file(timeline, str(dest), adapter_name=adapter)
    notes.append(f"Wrote {dest.name} with the OpenTimelineIO {adapter} adapter because auto-editor was not used.")
    return True


def export_nle(workdir: Path, which: str, preset: dict | None = None) -> dict:
    if which not in NLE_CHOICES:
        raise UGCError(f"Unknown --nle {which}.", f"--nle desconocido: {which}.")
    preset = preset or load_preset(None)
    export = workdir / "export"
    story_path = export / "storyboard.json"
    if not story_path.exists():
        write_storyboard(workdir, preset, None)
    story = load_json(story_path)
    source = Path(str(story.get("source") or ""))
    if not source.exists():
        raise UGCError(f"Source video is missing: {source}", f"No está el video de origen: {source}")
    media = export / "media"
    media.mkdir(parents=True, exist_ok=True)
    fps = int(story["fps"])
    conformed = media / "source.mp4"
    conform_cfr(
        source,
        conformed,
        int(story["width"]),
        int(story["height"]),
        fps,
        int(preset["export"]["crf"]),
        str(preset["export"]["audio_bitrate"]),
    )
    bed = default_music_path()
    if bed:
        shutil.copyfile(bed, media / "music.m4a")
    final = workdir / "final.mp4"
    if final.exists():
        shutil.copyfile(final, media / "preview.mp4")
    cuts = cut_out_frames(float(probe(conformed)["duration"]), story["tracks"]["video"], fps)
    targets = set(NLE_CHOICES[1:]) if which == "all" else {which}
    notes: list[str] = []
    written: list[str] = []
    exe = auto_editor_available()
    if exe:
        major = _auto_editor_version(exe)[0]
        if major != 29:
            exe = ""
            notes.append(f"auto-editor {major} is outside the 29.x pin, so Premiere and FCPXML used the OTIO fallback when it was installed.")
    if "premiere" in targets:
        dest = export / "project_premiere.xml"
        if exe:
            _run_auto_editor(exe, conformed, cuts, fps, "premiere", dest)
            _rewrite_media_paths(dest, conformed, "media/source.mp4")
            written.append(dest.name)
        elif not _fallback_xml(story, export, "fcp_xml", dest, notes):
            raise UGCError(
                "Premiere export needs auto-editor 29 or the otio-fcp-adapter fallback.",
                "La exportación de Premiere necesita auto-editor 29 o el fallback otio-fcp-adapter.",
            )
        else:
            written.append(dest.name)
    if "fcpx" in targets:
        dest = export / "project.fcpxml"
        if exe:
            _run_auto_editor(exe, conformed, cuts, fps, "final-cut-pro", dest)
            _rewrite_media_paths(dest, conformed, "media/source.mp4")
            written.append(dest.name)
            text = dest.read_text(encoding="utf-8")
            if "<fcpxml" not in text:
                raise UGCError("final-cut-pro export was not FCPXML.", "La exportación final-cut-pro no es FCPXML.")
        elif not _fallback_xml(story, export, "fcpx_xml", dest, notes):
            raise UGCError(
                "FCPXML export needs auto-editor 29 or the otio-fcpx-xml-adapter fallback.",
                "La exportación FCPXML necesita auto-editor 29 o el fallback otio-fcpx-xml-adapter.",
            )
        else:
            written.append(dest.name)
    if "otio" in targets or "edl" in targets:
        _write_otio(story, export, targets, notes)
        for name in ("timeline.otio", "project.edl"):
            if (export / name).exists() and name not in written:
                written.append(name)
    dump_json(export / "nle.json", {"written": written, "notes": notes, "cut_out_frames": cuts, "fcpxml": "1.11"})
    return {"written": written, "notes": notes, "cut_out": cuts}
