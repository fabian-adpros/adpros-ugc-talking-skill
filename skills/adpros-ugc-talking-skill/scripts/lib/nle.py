"""Editor timelines. Premiere and Final Cut come from auto-editor 29.

OpenTimelineIO and its extra adapters are optional. The skill still runs
without them.
"""

from __future__ import annotations

import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from .bg import export_bg_layers
from .config import default_music_path, load_preset
from .media import auto_editor_available, probe, run_cmd
from .storyboard import cut_out_frames, write_storyboard
from .util import UGCError, dump_json, load_json

NLE_CHOICES = ("all", "none", "premiere", "fcpx", "resolve", "capcut", "otio", "edl")
EDITORS = ("premiere", "fcpx", "resolve", "capcut", "otio", "edl")


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


def parse_editors(value: str) -> set[str]:
    text = (value or "").strip().lower()
    if text in {"", "none", "no", "off"}:
        return set()
    if text in {"all", "*"}:
        return set(EDITORS)
    aliases = {
        "finalcut": "fcpx",
        "final-cut": "fcpx",
        "final_cut": "fcpx",
        "davinci": "resolve",
        "davinci-resolve": "resolve",
        "fcpxml": "fcpx",
    }
    chosen: set[str] = set()
    for part in text.split(","):
        name = aliases.get(part.strip(), part.strip())
        if not name:
            continue
        if name not in EDITORS:
            raise UGCError(
                f"Unknown editor {part!r}. Use {', '.join(NLE_CHOICES)}.",
                f"Editor desconocido {part!r}. Usa {', '.join(NLE_CHOICES)}.",
            )
        chosen.add(name)
    return chosen


def _time_seconds(value: str) -> float:
    text = (value or "0s").strip()
    if text.endswith("s"):
        text = text[:-1]
    if "/" in text:
        num, den = text.split("/", 1)
        return int(num) / int(den)
    return float(text)


def conformed_frames(path: Path, fps: int) -> int:
    completed = run_cmd(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_frames,duration",
            "-of",
            "json",
            str(path),
        ]
    )
    import json

    data = json.loads(completed.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    frames = stream.get("nb_frames")
    if frames not in (None, "", "N/A"):
        return int(frames)
    return max(1, int(round(float(stream.get("duration") or 0) * fps)))


def repair_fcpxml(path: Path, source_frames: int, fps: int) -> str:
    """Point the asset at the full conformed file and prefer FCPXML 1.10.

    auto-editor 29 writes version 1.11 and sets the asset duration to the
    edited timeline, so a later source clip can start past that duration.
    It has no version= flag. The elements it emits validate as 1.10 once the
    version attribute is 1.10, which Resolve 18/19 import.
    """
    tree = ET.parse(path)
    root = tree.getroot()
    if root.tag != "fcpxml":
        raise UGCError("final-cut-pro export was not FCPXML.", "La exportación final-cut-pro no es FCPXML.")
    duration = f"{source_frames}/{fps}s"
    limit = source_frames / float(fps)
    for asset in root.iter("asset"):
        asset.set("duration", duration)
    for element in root.iter():
        if element.tag == "asset":
            continue
        if "duration" in element.attrib and element.tag == "format":
            element.set("duration", duration)
    for clip in list(root.iter("asset-clip")) + list(root.iter("audio")) + list(root.iter("video")):
        if "start" not in clip.attrib and "duration" not in clip.attrib:
            continue
        if clip.tag not in {"asset-clip", "clip", "audio", "video", "title"}:
            continue
        start = _time_seconds(clip.get("start") or "0s")
        span = _time_seconds(clip.get("duration") or "0s")
        if start + span > limit + (0.5 / fps):
            raise UGCError(
                f"{clip.tag} starts at {start:.3f}s and lasts {span:.3f}s, past the {limit:.3f}s source.",
                f"{clip.tag} empieza en {start:.3f}s y dura {span:.3f}s, fuera de los {limit:.3f}s del origen.",
            )
    # Apple's 1.10 DTD accepts this document when version is 1.10.
    # The DTD is copyright Apple, so it is not vendored. The check was run
    # locally against that DTD; CI checks well-formedness and the duration math.
    root.set("version", "1.10")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return "1.10"


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
    return otio_version() is not None


def otio_version() -> str | None:
    try:
        import opentimelineio as otio
    except ImportError:
        return None
    version = getattr(otio, "__version__", None)
    if version:
        return str(version)
    nested = getattr(otio, "version", None)
    return str(getattr(nested, "__version__", "installed"))


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
    chosen = parse_editors(which)
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
    targets = chosen
    if not targets:
        return {"written": [], "notes": ["No editor project requested."], "cut_out": cuts, "fcpxml": None}
    notes: list[str] = []
    written: list[str] = []
    fcpxml_version = None
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
    if "fcpx" in targets or "resolve" in targets:
        dest = export / "project.fcpxml"
        if exe:
            _run_auto_editor(exe, conformed, cuts, fps, "final-cut-pro", dest)
            _rewrite_media_paths(dest, conformed, "media/source.mp4")
            fcpxml_version = repair_fcpxml(dest, conformed_frames(conformed, fps), fps)
            written.append(dest.name)
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
    if (export / "project.fcpxml").exists() and not fcpxml_version:
        fcpxml_version = repair_fcpxml(export / "project.fcpxml", conformed_frames(conformed, fps), fps)
    if "capcut" in targets:
        notes.append("CapCut has no project file. Use media/source.mp4, media/music.m4a, captions.srt, and hook.srt.")
        for name in ("media/source.mp4", "captions.srt", "hook.srt"):
            if name not in written:
                written.append(name)
    plan_path = workdir / "plan.json"
    if plan_path.exists():
        for name in export_bg_layers(workdir, media, load_json(plan_path)):
            if name not in written:
                written.append(name)
        if any(name.startswith("media/subject") or name.startswith("media/matte") or name.startswith("media/background") for name in written):
            notes.append(
                "Background layers are separate files: media/subject.mov (ProRes 4444 alpha, no captions), "
                "media/matte.mp4, and media/background.* when the mode is replace. They are not inside the auto-editor sequence."
            )
    dump_json(export / "nle.json", {"written": written, "notes": notes, "cut_out_frames": cuts, "fcpxml": fcpxml_version})
    return {"written": written, "notes": notes, "cut_out": cuts}
