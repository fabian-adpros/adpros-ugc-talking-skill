"""Storyboard files derived from plan.json. No model calls."""

from __future__ import annotations

import base64
import csv
import html
import json
import subprocess
from pathlib import Path

from .config import default_music_path, load_preset
from .edit import cues_to_srt
from .media import run_cmd
from .render import segment_frames
from .util import UGCError, dump_json

VISION_LABELS = {
    "talking_head",
    "product_visible",
    "product_reveal",
    "hands",
    "screen_or_laptop",
    "text_on_screen",
    "environment",
    "unclear",
}
VISION_CONFIDENCE = {"low", "medium", "high"}
BROLL_LABELS = VISION_LABELS - {"talking_head", "unclear"}


def _fps(preset: dict) -> int:
    return int(preset["export"]["fps"])


def align_kept(kept: list[dict], fps: int) -> list[dict]:
    """Frame-align kept ranges. Destination frames are contiguous."""
    dst = 0
    aligned = []
    for index, block in enumerate(kept, start=1):
        frames, _exact = segment_frames(float(block["src_start"]), float(block["src_end"]), fps)
        src_in = int(round(float(block["src_start"]) * fps))
        if src_in < 0:
            src_in = 0
        item = {
            "index": index,
            "src_in": src_in,
            "src_out": src_in + frames,
            "dst_in": dst,
            "dst_out": dst + frames,
        }
        item["src_start"] = item["src_in"] / fps
        item["src_end"] = item["src_out"] / fps
        item["dst_start"] = item["dst_in"] / fps
        item["dst_end"] = item["dst_out"] / fps
        aligned.append(item)
        dst += frames
    return aligned


def cut_out_frames(source_duration: float, aligned: list[dict], fps: int) -> list[tuple[int, int]]:
    """Inverse of the kept ranges, in source frames. Empty slices are dropped."""
    total = max(0, int(round(float(source_duration) * fps)))
    cursor = 0
    cuts: list[tuple[int, int]] = []
    for block in aligned:
        start = max(0, int(block["src_in"]))
        end = max(start, int(block["src_out"]))
        if start > cursor:
            cuts.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < total:
        cuts.append((cursor, total))
    return [(start, end) for start, end in cuts if end > start]


def _load_vision(path: Path | None) -> list[dict]:
    if path is None:
        return []
    if not path.exists():
        raise UGCError(
            f"Vision label file not found: {path}",
            f"No está el archivo de etiquetas: {path}",
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("labels") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise UGCError(
            "Vision labels must be a list or an object with a labels list.",
            "Las etiquetas tienen que ser una lista o un objeto con labels.",
        )
    clean = []
    for row in rows:
        label = str(row.get("label") or "")
        confidence = str(row.get("confidence") or "")
        if label not in VISION_LABELS:
            raise UGCError(
                f"Unknown vision label {label!r}. Use one of: {', '.join(sorted(VISION_LABELS))}.",
                f"Etiqueta desconocida {label!r}.",
            )
        if confidence not in VISION_CONFIDENCE:
            raise UGCError(
                f"Unknown confidence {confidence!r}. Use low, medium, or high.",
                f"Confianza desconocida {confidence!r}. Usa low, medium o high.",
            )
        clean.append(
            {
                "index": int(row.get("index") or 0),
                "label": label,
                "confidence": confidence,
                "evidence": str(row.get("evidence") or ""),
            }
        )
    return clean


def _broll_allowed(label: str, confidence: str) -> bool:
    if confidence == "low":
        return False
    if label == "product_reveal" and confidence not in {"medium", "high"}:
        return False
    return label in BROLL_LABELS


def build_storyboard(plan: dict, preset: dict, vision: list[dict] | None = None) -> dict:
    fps = _fps(preset)
    width = int(preset["export"]["width"])
    height = int(preset["export"]["height"])
    aligned = align_kept(plan.get("kept_ranges") or [], fps)
    output_frames = aligned[-1]["dst_out"] if aligned else 0
    output_duration = output_frames / fps if fps else 0.0
    by_index = {row["index"]: row for row in vision or []}
    scenes = []
    broll = []
    for clip in aligned:
        seen = by_index.get(clip["index"])
        scene = {
            "index": clip["index"],
            "thumb": f"thumbs/keep_{clip['index']:03d}.jpg",
            "dst_in": clip["dst_in"],
            "dst_out": clip["dst_out"],
            "label": None,
            "confidence": None,
            "evidence": "",
        }
        if seen:
            scene["label"] = seen["label"]
            scene["confidence"] = seen["confidence"]
            scene["evidence"] = seen["evidence"]
            if _broll_allowed(seen["label"], seen["confidence"]):
                broll.append(
                    {
                        "index": clip["index"],
                        "dst_in": clip["dst_in"],
                        "dst_out": clip["dst_out"],
                        "label": seen["label"],
                        "confidence": seen["confidence"],
                        "evidence": seen["evidence"],
                        "marker": seen["label"],
                    }
                )
        scenes.append(scene)
    cuts = []
    for cut in (plan.get("silence") or {}).get("cuts") or []:
        cuts.append({"start": cut["start"], "end": cut["end"], "reason": "silence"})
    for item in (plan.get("fillers") or {}).get("items") or []:
        cuts.append(
            {
                "start": item["start"],
                "end": item["end"],
                "reason": "filler",
                "text": item.get("text") or "",
            }
        )
    music = default_music_path()
    duck = float(preset["music"]["duck_db"])
    hook = dict(plan.get("hook") or {})
    return {
        "version": 1,
        "source": plan.get("source"),
        "fps": fps,
        "width": width,
        "height": height,
        "source_duration": float(plan.get("source_duration") or 0),
        "output_duration": output_duration,
        "plan_output_duration": float(plan.get("output_duration") or 0),
        "tracks": {
            "video": aligned,
            "audio_voice": aligned,
            "music": {
                "file": str(music) if music else None,
                "dst_in": 0,
                "dst_out": output_frames,
                "dst_start": 0.0,
                "dst_end": output_duration,
                "level_db": duck,
            },
        },
        "overlays": {"hook": hook, "captions": plan.get("captions") or []},
        "cuts": cuts,
        "scenes": scenes,
        "broll_slots": broll,
    }


def _thumbs(source: Path, clips: list[dict], folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for clip in clips:
        mid = (float(clip["src_start"]) + float(clip["src_end"])) / 2.0
        dest = folder / f"keep_{clip['index']:03d}.jpg"
        run_cmd(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{mid:.3f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-q:v",
                "4",
                str(dest),
            ]
        )


def _contact_sheet(thumbs: list[Path], dest: Path) -> None:
    if not thumbs:
        return
    cols = min(4, len(thumbs))
    rows = (len(thumbs) + cols - 1) // cols
    cmd = ["ffmpeg", "-y"]
    for thumb in thumbs:
        cmd += ["-i", str(thumb)]
    filters = []
    for index in range(len(thumbs)):
        filters.append(
            f"[{index}:v]scale=160:284:force_original_aspect_ratio=decrease,"
            f"pad=160:284:(ow-iw)/2:(oh-ih)/2,setsar=1[t{index}]"
        )
    layout = []
    for index in range(len(thumbs)):
        col = index % cols
        row = index // cols
        layout.append(f"{col * 160}_{row * 284}")
    filters.append(
        "".join(f"[t{index}]" for index in range(len(thumbs)))
        + f"xstack=inputs={len(thumbs)}:layout={'|'.join(layout)}[sheet]"
    )
    cmd += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[sheet]",
        "-frames:v",
        "1",
        str(dest),
    ]
    run_cmd(cmd)


def _csv(path: Path, story: dict) -> None:
    scenes = {scene["index"]: scene for scene in story["scenes"]}
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "shot",
                "src_in",
                "src_out",
                "dst_in",
                "dst_out",
                "src_start",
                "src_end",
                "dst_start",
                "dst_end",
                "label",
                "confidence",
                "thumb",
            ]
        )
        for clip in story["tracks"]["video"]:
            scene = scenes.get(clip["index"]) or {}
            writer.writerow(
                [
                    clip["index"],
                    clip["src_in"],
                    clip["src_out"],
                    clip["dst_in"],
                    clip["dst_out"],
                    f"{clip['src_start']:.3f}",
                    f"{clip['src_end']:.3f}",
                    f"{clip['dst_start']:.3f}",
                    f"{clip['dst_end']:.3f}",
                    scene.get("label") or "",
                    scene.get("confidence") or "",
                    scene.get("thumb") or "",
                ]
            )


def _bar(segments: list[tuple[float, float, str]], duration: float) -> str:
    if duration <= 0:
        return ""
    pieces = []
    for start, end, kind in segments:
        left = max(0.0, start / duration * 100.0)
        width = max(0.3, (end - start) / duration * 100.0)
        pieces.append(
            f'<i class="{html.escape(kind)}" style="left:{left:.3f}%;width:{width:.3f}%"></i>'
        )
    return "".join(pieces)


def _clip_text(story: dict, clip: dict) -> str:
    bits = []
    for card in story["overlays"]["captions"]:
        if float(card["end"]) > float(clip["dst_start"]) and float(card["start"]) < float(clip["dst_end"]):
            bits.append(" ".join((word.get("text") or "") for word in card.get("words") or []).strip())
    return " ".join(bit for bit in bits if bit)


def _markdown(story: dict) -> str:
    hook = story["overlays"]["hook"] or {}
    delivery = story.get("delivery") or {}
    editors = delivery.get("editors") or []
    targets = ", ".join(editors) if editors else "not chosen yet · aún no elegidos"
    rows = []
    for clip in story["tracks"]["video"]:
        rows.append(
            f"| {clip['index']} | {clip['src_start']:.2f}–{clip['src_end']:.2f}s | "
            f"{clip['dst_start']:.2f}–{clip['dst_end']:.2f}s | {_clip_text(story, clip)} |"
        )
    cut_rows = []
    for cut in story["cuts"]:
        duration = float(cut["end"]) - float(cut["start"])
        label = cut["reason"]
        if cut.get("text"):
            label = f"{label}: {cut['text']}"
        cut_rows.append(f"| {label} | {float(cut['start']):.2f} | {float(cut['end']):.2f} | {duration:.2f}s |")
    source = float(story["source_duration"] or 0)
    output = float(story["output_duration"] or 0)
    bar = ["·"] * 48
    if source > 0:
        for clip in story["tracks"]["video"]:
            start = int(float(clip["src_start"]) / source * 48)
            end = max(start + 1, int(float(clip["src_end"]) / source * 48))
            for index in range(start, min(48, end)):
                bar[index] = "█"
        for cut in story["cuts"]:
            glyph = "▒" if cut["reason"] == "filler" else "░"
            start = int(float(cut["start"]) / source * 48)
            end = max(start + 1, int(float(cut["end"]) / source * 48))
            for index in range(start, min(48, end)):
                if bar[index] == "·":
                    bar[index] = glyph
    table = "\n".join(rows) if rows else "| — | — | — | — |"
    cuts = "\n".join(cut_rows) if cut_rows else "| — | — | — | — |"
    return f"""# Storyboard · Guion gráfico

- Source / Fuente: {source:.2f}s
- Output / Salida: {output:.2f}s
- Hook / Gancho: {hook.get("text") or "—"}
- Captions / Subtítulos: {len(story["overlays"]["captions"])}
- Export targets / Destinos: {targets}

## Kept segments · Tomas conservadas

| # | src in–out | dst in–out | text |
| --- | --- | --- | --- |
{table}

## Cuts · Cortes

| reason · motivo | start | end | duration |
| --- | --- | --- | --- |
{cuts}

## Timeline · Línea de tiempo

`{''.join(bar)}`

█ keep/conservado · ░ silence/silencio · ▒ filler/muletilla · · empty/vacío
"""


def _jpeg_bytes(path: Path, width: int, quality: int) -> bytes:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vf",
            f"scale={int(width)}:-2",
            "-q:v",
            str(int(quality)),
            "-f",
            "image2",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _fit_inline_images(story: dict, thumb_dir: Path, max_bytes: int, thumb_width: int) -> tuple[dict[int, str], str]:
    clips = list(story["tracks"]["video"])
    widths = []
    for width in (thumb_width, 240, 160, 96):
        if width <= thumb_width and width not in widths:
            widths.append(width)
    note = (
        "Some thumbnails were omitted to stay under the size cap. "
        "/ Algunas miniaturas se omitieron para no pasar el tope de tamaño."
    )

    def encode(width: int, quality: int, chosen: list[dict]) -> dict[int, str]:
        images = {}
        for clip in chosen:
            jpg = thumb_dir / f"keep_{clip['index']:03d}.jpg"
            if not jpg.exists():
                continue
            raw = _jpeg_bytes(jpg, width, quality)
            images[clip["index"]] = "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
        return images

    for width in widths:
        for quality in (6, 10, 14):
            images = encode(width, quality, clips)
            if len(_html(story, images, "").encode("utf-8")) <= max_bytes:
                return images, ""
    images: dict[int, str] = {}
    omitted = False
    for clip in clips:
        trial = encode(widths[-1], 14, [clip])
        merged = {**images, **trial}
        if len(_html(story, merged, note).encode("utf-8")) <= max_bytes:
            images = merged
        else:
            omitted = True
    if not images and len(_html(story, {}, note).encode("utf-8")) > max_bytes:
        return {}, note
    return images, note if omitted or len(images) < len(clips) else ""


def _html(story: dict, images: dict[int, str] | None = None, note: str = "") -> str:
    source_duration = float(story["source_duration"] or 0)
    output_duration = float(story["output_duration"] or 0)
    keep = [(clip["src_start"], clip["src_end"], "keep") for clip in story["tracks"]["video"]]
    silence = [
        (cut["start"], cut["end"], "silence")
        for cut in story["cuts"]
        if cut["reason"] == "silence"
    ]
    filler = [
        (cut["start"], cut["end"], "filler")
        for cut in story["cuts"]
        if cut["reason"] == "filler"
    ]
    hook = story["overlays"]["hook"] or {}
    hook_end = float(hook.get("end") or 0)
    hook_row = [(0.0, hook_end, "hook")] if hook.get("text") and hook_end > 0 else []
    captions = [
        (float(card["start"]), float(card["end"]), "captions")
        for card in story["overlays"]["captions"]
    ]
    music = story["tracks"]["music"]
    music_row = [(0.0, output_duration, "music")] if output_duration > 0 else []
    broll = [
        (slot["dst_in"] / story["fps"], slot["dst_out"] / story["fps"], "broll")
        for slot in story["broll_slots"]
    ]
    rows = [
        ("Keep · Conservado", keep, source_duration),
        ("Silence · Silencio", silence, source_duration),
        ("Filler · Muletilla", filler, source_duration),
        ("Hook · Gancho", hook_row, output_duration),
        ("Captions · Subtítulos", captions, output_duration),
        ("Music · Música", music_row, output_duration),
        ("B-roll", broll, output_duration),
    ]
    timeline = []
    for label, segments, duration in rows:
        timeline.append(
            f'<div class="row"><span>{html.escape(label)}</span><div class="track">{_bar(segments, duration)}</div></div>'
        )
    cards = []
    scenes = {scene["index"]: scene for scene in story["scenes"]}
    for clip in story["tracks"]["video"]:
        scene = scenes.get(clip["index"]) or {}
        label = scene.get("label") or "—"
        if images is None:
            picture = f'<img src="{html.escape(scene.get("thumb") or "")}" alt="keep {clip["index"]:03d}">'
        elif images.get(clip["index"]):
            picture = f'<img alt="keep {clip["index"]:03d}" src="{images[clip["index"]]}">'
        else:
            picture = '<div class="missing">omitted · omitida</div>'
        cards.append(
            "<figure>"
            f"{picture}"
            f"<figcaption>#{clip['index']:03d} {clip['src_start']:.2f}–{clip['src_end']:.2f}s"
            f"<br>{html.escape(str(label))}</figcaption></figure>"
        )
    table_rows = []
    for clip in story["tracks"]["video"]:
        scene = scenes.get(clip["index"]) or {}
        table_rows.append(
            "<tr>"
            f"<td>{clip['index']}</td>"
            f"<td>{clip['src_in']}–{clip['src_out']}</td>"
            f"<td>{clip['dst_in']}–{clip['dst_out']}</td>"
            f"<td>{html.escape(str(scene.get('label') or ''))}</td>"
            f"<td>{html.escape(str(scene.get('confidence') or ''))}</td>"
            f"<td>{html.escape(str(scene.get('evidence') or ''))}</td>"
            "</tr>"
        )
    hook_text = html.escape(str(hook.get("text") or ""))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Storyboard · Guion gráfico</title>
<style>
body {{ font: 15px/1.4 system-ui, sans-serif; margin: 24px; color: #1c1c1c; background: #f7f5f2; }}
h1 {{ font-size: 22px; margin: 0 0 8px; }}
.meta {{ color: #555; margin-bottom: 18px; }}
.row {{ display: grid; grid-template-columns: 180px 1fr; gap: 8px; align-items: center; margin: 4px 0; }}
.track {{ position: relative; height: 18px; background: #e6e2dc; border-radius: 4px; overflow: hidden; }}
.track i {{ position: absolute; top: 0; bottom: 0; }}
.keep {{ background: #2f9e44; }}
.silence {{ background: #868e96; }}
.filler {{ background: #e67700; }}
.hook {{ background: #1971c2; }}
.captions {{ background: #f59f00; }}
.music {{ background: #9c36b5; }}
.broll {{ background: #0ca678; }}
.shots {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 18px 0; }}
figure {{ margin: 0; width: 120px; }}
img {{ width: 120px; height: 180px; object-fit: cover; background: #ddd; border-radius: 6px; }}
figcaption {{ font-size: 12px; }}
.missing {{ width: 120px; height: 180px; background: #ddd; border-radius: 6px; }}
.note {{ background: #fff4d6; padding: 8px 12px; border-radius: 6px; }}
table {{ border-collapse: collapse; width: 100%; background: #fff; }}
th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; vertical-align: top; }}
th {{ background: #eee; }}
</style>
</head>
<body>
<h1>Storyboard · Guion gráfico</h1>
<p class="meta">{story['width']}×{story['height']} · {story['fps']} fps · source/fuente {source_duration:.2f}s · output/salida {output_duration:.2f}s · music/música {music['level_db']} dB<br>Hook · Gancho: {hook_text}</p>
{f'<p class="note">{html.escape(note)}</p>' if note else ''}
{''.join(timeline)}
<div class="shots">{''.join(cards)}</div>
<table>
<thead><tr><th>#</th><th>src in–out</th><th>dst in–out</th><th>Label · Etiqueta</th><th>Confidence · Confianza</th><th>Evidence · Evidencia</th></tr></thead>
<tbody>{''.join(table_rows)}</tbody>
</table>
</body>
</html>
"""


RELINK = """# Relink · Reconectar medios

The project files next to this note point at `media/` when the editor accepts a relative path. If a clip is offline, relink it to `export/media/`. `captions.srt` and `hook.srt` use the edited timeline, not the raw camera clock. CapCut mobile cannot import SRT. CapCut has no official project format, so this folder ships the conformed media and the SRT files instead of a CapCut project.

Los proyectos junto a esta nota apuntan a `media/` cuando el editor acepta una ruta relativa. Si un clip queda offline, reconéctalo a `export/media/`. `captions.srt` y `hook.srt` van en el tiempo del corte, no en el reloj de la cámara. CapCut móvil no importa SRT. CapCut no tiene un formato de proyecto oficial, así que esta carpeta entrega el media conformado y los SRT, no un proyecto de CapCut.

## Premiere Pro

File → Import `project_premiere.xml` (FCP 7 XML / xmeml, written by auto-editor 29). Relink to `media/source.mp4` and drop `media/music.m4a` on an audio track at the level in `storyboard.json` (`tracks.music.level_db`, default −18 dB). Import the SRT files with File → Import. They are already in edit time.

Archivo → Importar `project_premiere.xml` (XML de FCP 7 / xmeml, escrito por auto-editor 29). Reconecta `media/source.mp4` y pon `media/music.m4a` en una pista de audio al nivel de `storyboard.json` (`tracks.music.level_db`, por defecto −18 dB). Importa los SRT con Archivo → Importar. Ya están en el tiempo del corte.

## DaVinci Resolve

File → Import → Timeline, or File → Import AAF/XML, and choose `project.fcpxml` (FCPXML 1.10). The asset duration is the full conformed source, not the edited length. Relink to `media/source.mp4`. Add `media/music.m4a` on its own track. Subtitle → Import Subtitle for the SRT files.

Archivo → Importar → Timeline, o Archivo → Importar AAF/XML, y elige `project.fcpxml` (FCPXML 1.10). La duración del asset es el origen conformado completo, no el corte. Reconecta `media/source.mp4`. Añade `media/music.m4a` en su pista. Subtítulos → Importar subtítulo para los SRT.

## Final Cut Pro

File → Import → XML and choose `project.fcpxml` (FCPXML 1.10). Relink to `media/source.mp4`. The music bed is `media/music.m4a`. Import the SRT files if your Final Cut version accepts them, or use them as a reference while you type titles.

Archivo → Importar → XML y elige `project.fcpxml` (FCPXML 1.10). Reconecta `media/source.mp4`. La cama es `media/music.m4a`. Importa los SRT si tu versión de Final Cut los acepta, o úsalos de referencia.

## CapCut Desktop

CapCut has no project file we can write. Start a project, import `media/source.mp4` (already constant frame rate) and `media/music.m4a`, then import `captions.srt` and `hook.srt` if the desktop build offers SRT import. Do not expect the mobile app to read those SRT files.

CapCut no tiene un archivo de proyecto que podamos escribir. Crea un proyecto, importa `media/source.mp4` (ya a fps constantes) y `media/music.m4a`, y luego `captions.srt` y `hook.srt` si la versión de escritorio importa SRT. La app móvil no lee esos SRT.
"""


def write_storyboard(
    workdir: Path,
    preset: dict | None = None,
    vision_path: Path | None = None,
    inline: bool | None = None,
) -> dict:
    plan_path = workdir / "plan.json"
    if not plan_path.exists():
        raise UGCError("plan.json is missing. Run the plan step first.", "Falta plan.json. Corre primero el plan.")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    preset = preset or load_preset(None)
    vision = _load_vision(vision_path)
    story = build_storyboard(plan, preset, vision)
    if plan.get("delivery"):
        story["delivery"] = plan["delivery"]
    source = Path(str(plan.get("source") or ""))
    if not source.exists():
        raise UGCError(f"Source video is missing: {source}", f"No está el video de origen: {source}")
    export = workdir / "export"
    thumbs = export / "thumbs"
    export.mkdir(parents=True, exist_ok=True)
    _thumbs(source, story["tracks"]["video"], thumbs)
    _contact_sheet(sorted(thumbs.glob("keep_*.jpg")), export / "contact-sheet.jpg")
    dump_json(export / "storyboard.json", story)
    (export / "storyboard.html").write_text(_html(story), encoding="utf-8")
    (export / "storyboard.md").write_text(_markdown(story), encoding="utf-8")
    board = preset.get("storyboard") or {}
    want_inline = bool(board.get("inline", False)) if inline is None else bool(inline)
    if want_inline:
        max_bytes = int(board.get("inline_max_bytes", 1_500_000))
        thumb_width = int(board.get("thumb_width", 320))
        images, note = _fit_inline_images(story, thumbs, max_bytes, thumb_width)
        page = _html(story, images, note)
        encoded = page.encode("utf-8")
        if len(encoded) > max_bytes:
            page = _html(story, {}, note or "Thumbnails omitted. / Miniaturas omitidas.")
            encoded = page.encode("utf-8")
        (export / "storyboard.inline.html").write_bytes(encoded)
        story["inline"] = {
            "file": "storyboard.inline.html",
            "bytes": len(encoded),
            "max_bytes": max_bytes,
            "embedded": len(images),
            "note": note,
        }
        dump_json(export / "storyboard.json", story)
    _csv(export / "storyboard.csv", story)
    caption_cues = []
    for card in story["overlays"]["captions"]:
        text = " ".join(word.get("text") or "" for word in card.get("words") or []).strip()
        caption_cues.append({"start": card["start"], "end": card["end"], "text": text})
    (export / "captions.srt").write_text(cues_to_srt(caption_cues), encoding="utf-8")
    hook = story["overlays"]["hook"] or {}
    hook_cues = []
    if hook.get("text"):
        hook_cues.append({"start": float(hook.get("start") or 0), "end": float(hook.get("end") or 0), "text": hook["text"]})
    (export / "hook.srt").write_text(cues_to_srt(hook_cues), encoding="utf-8")
    (export / "RELINK.md").write_text(RELINK, encoding="utf-8")
    return story
