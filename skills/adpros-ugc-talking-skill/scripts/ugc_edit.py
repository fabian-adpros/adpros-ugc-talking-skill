#!/usr/bin/env python3
"""UGC talking-head pipeline.

  ugc_edit.py run CLIP --workdir DIR          # stops for approval after the plan
  ugc_edit.py run CLIP --workdir DIR --yes    # transcribe, plan, render, export
  ugc_edit.py run CLIP --workdir DIR --from render --yes
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.config import FILLER_PROMPTS, default_music_path, load_fillers, load_preset  # noqa: E402
from lib.edit import (  # noqa: E402
    auto_editor_chunks_to_cuts,
    build_timeline,
    cues_to_srt,
    group_captions,
    suggest_hooks,
    words_to_sentence_cues,
)
from lib.media import (  # noqa: E402
    apply_loudnorm,
    auto_editor_available,
    auto_editor_v1,
    extract_frame,
    ffmpeg_has_filter,
    ffmpeg_version,
    loudnorm_stats,
    probe,
    trim_media,
)
from lib.bg import (  # noqa: E402
    AWAITING_BG,
    backgroundremover_available,
    bg_checkpoint_message,
    build_preview,
    prepare_picture,
    resolve_bg,
)
from lib.delivery import (  # noqa: E402
    AWAITING_DELIVERY,
    AWAITING_STORYBOARD,
    delivery_questions,
    resolve_delivery,
    storyboard_checkpoint,
)
from lib.nextsteps import print_next_steps  # noqa: E402
from lib.nle import NLE_CHOICES, export_nle, otio_adapter, otio_available, otio_version  # noqa: E402
from lib.render import cut_video, remotion_ready, render_styled  # noqa: E402
from lib.storyboard import write_storyboard  # noqa: E402
from lib.transcribe import detect_device, transcribe, whisperx_bin  # noqa: E402
from lib.util import UGCError, dump_json, load_json, prepend_tool_paths, round_time, skill_root  # noqa: E402

prepend_tool_paths()

AWAITING = 10

REASONS = {
    "en": {
        "result_word": "It is the first clear claim, and it contains a result word.",
        "number": "It leads with a number.",
        "early_claim": "It is the earliest sentence that is not just a greeting.",
        "fallback_opening": "No full sentence scored, so this is the opening line.",
        "user": "You set this hook.",
    },
    "es": {
        "result_word": "Es la primera frase concreta y contiene una palabra de resultado.",
        "number": "Abre con un número.",
        "early_claim": "Es la primera frase que no es solo un saludo.",
        "fallback_opening": "Ninguna frase puntuó, así que este es el arranque.",
        "user": "Este gancho lo definiste tú.",
    },
}


def _ui(value: str, language: str | None) -> str:
    if value in ("en", "es"):
        return value
    if language in ("en", "es"):
        return language
    return "en"


def _say(ui: str, en: str, es: str) -> None:
    print(es if ui == "es" else en)


def _round_plan(plan: dict) -> dict:
    def walk(value):
        if isinstance(value, float):
            return round_time(value)
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    return walk(plan)


def _silence_from_auto_editor(src: Path, workdir: Path, words: list[dict], duration: float, preset: dict) -> tuple[list[tuple[float, float]] | None, list[str]]:
    warnings: list[str] = []
    silence = preset["silence"]
    if not auto_editor_available():
        warnings.append("auto-editor is not installed; silence cuts come from word gaps.")
        return None, warnings
    try:
        payload = auto_editor_v1(
            src,
            workdir / "auto-editor",
            threshold=float(silence["audio_threshold"]),
            margin=float(silence["padding_seconds"]),
            fps=int(silence["analysis_fps"]),
        )
    except UGCError as exc:
        detail = exc.en.lower()
        if "decoder" in detail or "hevc" in detail or "h265" in detail or "h.265" in detail:
            warnings.append(
                "auto-editor could not decode this video (common with iPhone HEVC). "
                "Silence cuts come from word gaps."
            )
        else:
            warnings.append(f"auto-editor failed ({exc.en}); silence cuts come from word gaps.")
        return None, warnings
    cuts = auto_editor_chunks_to_cuts(
        payload.get("chunks") or [],
        fps=float(silence["analysis_fps"]),
        min_silence=float(silence["min_seconds"]),
        margin=float(silence["padding_seconds"]),
    )
    removed = sum(end - start for start, end in cuts)
    if duration > 0 and removed / duration > 0.7:
        warnings.append(
            "auto-editor would remove more than 70% of the clip. Falling back to word-gap cuts."
        )
        return None, warnings
    # Cross-check: if the waveform found nothing but the transcript has a long gap, say so.
    long_gap = False
    if words:
        if words[0]["start"] > float(silence["min_seconds"]):
            long_gap = True
        for left, right in zip(words, words[1:]):
            if right["start"] - left["end"] > float(silence["min_seconds"]):
                long_gap = True
        if duration - words[-1]["end"] > float(silence["min_seconds"]):
            long_gap = True
    if long_gap and not cuts:
        warnings.append(
            "The transcript has a pause over the silence threshold, but auto-editor kept it. Word-gap cuts are available with --silence-engine words."
        )
    return cuts, warnings


def _build_plan(workdir: Path, preset: dict, hook_override: str | None, filler_mode: str, silence_engine: str) -> dict:
    words_doc = load_json(workdir / "words.json")
    source = Path(words_doc["source"])
    info = probe(source)
    duration = float(info["duration"])
    language = words_doc.get("language") or "en"
    if language not in ("en", "es"):
        language = "en"
    words = words_doc["words"]
    warnings = list(words_doc.get("warnings") or [])
    external = None
    engine = silence_engine or preset["silence"]["engine"]
    if engine == "auto":
        external, extra = _silence_from_auto_editor(source, workdir, words, duration, preset)
        warnings.extend(extra)
    elif engine == "auto-editor":
        external, extra = _silence_from_auto_editor(source, workdir, words, duration, preset)
        warnings.extend(extra)
        if external is None:
            raise UGCError(
                "Silence engine auto-editor was requested but it could not produce a timeline.",
                "Pediste auto-editor y no pudo generar el timeline.",
            )
    elif engine != "words":
        raise UGCError(
            f"Unknown silence engine: {engine}",
            f"Motor de silencio desconocido: {engine}",
        )
    timeline = build_timeline(
        words,
        duration,
        language,
        filler_mode,
        load_fillers(),
        min_silence=float(preset["silence"]["min_seconds"]),
        padding=float(preset["silence"]["padding_seconds"]),
        external_silence=external,
    )
    captions = group_captions(timeline["words"], max_words=int(preset["captions"]["max_words"]))
    hook = suggest_hooks(
        timeline["words"],
        language,
        max_chars=int(preset["hook"]["max_chars"]),
        max_words=int(preset["hook"]["max_words"]),
    )
    hook["end"] = float(preset["hook"]["duration_seconds"])
    if hook_override:
        hook["text"] = hook_override.strip()
        hook["reason"] = "user"
    if not timeline["filler_items"]:
        warnings.append(
            "No filler from the list was in the transcript. Whisper often drops um/eh/mmm even with an initial prompt."
        )
    output_duration = float(timeline["output_duration"])
    max_duration = float(preset["export"]["max_duration"])
    will_trim = bool(preset["export"]["trim_if_over"]) and output_duration > max_duration + 0.05
    if will_trim:
        warnings.append(
            f"Edited duration is {output_duration:.1f}s. Export will trim to {max_duration:.0f}s."
        )
    elif output_duration > max_duration + 0.05:
        warnings.append(
            f"Edited duration is {output_duration:.1f}s, over the {max_duration:.0f}s target. Trim is off."
        )
    plan = {
        "version": 1,
        "language": language,
        "source": str(source),
        "source_duration": duration,
        "output_duration": output_duration,
        "silence_engine": timeline["silence_engine"] if engine != "words" else "words",
        "filler_mode": filler_mode,
        "silence": {
            "min_seconds": preset["silence"]["min_seconds"],
            "padding_seconds": preset["silence"]["padding_seconds"],
            "removed_seconds": timeline["silence_removed_seconds"],
            "cuts": timeline["silence_cuts"],
        },
        "fillers": {
            "removed_seconds": timeline["filler_removed_seconds"],
            "items": timeline["filler_items"],
        },
        "removed_seconds": timeline["removed_seconds"],
        "kept_ranges": timeline["kept_ranges"],
        "words": timeline["words"],
        "captions": captions,
        "hook": hook,
        "warnings": warnings,
        "trim": {"max_duration": max_duration, "will_trim": will_trim},
        "initial_prompt": words_doc.get("prompt") or FILLER_PROMPTS.get(language),
        "transcription_engine": words_doc.get("engine"),
        "model": words_doc.get("model"),
    }
    # If the user forced the words engine, the timeline note already says words.
    if engine == "words":
        plan["silence_engine"] = "words"
    plan = _round_plan(plan)
    dump_json(workdir / "plan.json", plan)
    (workdir / "edited.srt").write_text(cues_to_srt(words_to_sentence_cues(plan["words"])), encoding="utf-8")
    return plan


def _fmt_cuts(cuts: list[dict], limit: int = 6) -> str:
    if not cuts:
        return "—"
    shown = cuts[:limit]
    text = ", ".join(f"{cut['start']:.2f}–{cut['end']:.2f}s" for cut in shown)
    extra = len(cuts) - len(shown)
    if extra > 0:
        text += f" (+{extra})"
    return text


def format_summary(plan: dict, ui: str, awaiting: bool = True) -> str:
    hook = plan["hook"]
    reason = REASONS.get(ui, REASONS["en"]).get(hook.get("reason"), hook.get("reason", ""))
    fillers = " · ".join(item["text"].strip(" ,.") for item in plan["fillers"]["items"]) or "—"
    warnings = plan["warnings"] or []
    if ui == "es":
        lines = [
            "Plan listo. Falta tu ok antes de renderizar.",
            f"Idioma del clip: {plan['language']}",
            f"Duración: {plan['source_duration']:.1f}s → {plan['output_duration']:.1f}s",
            f"Silencio ({plan['silence_engine']}): {plan['silence']['removed_seconds']:.1f}s en {len(plan['silence']['cuts'])} cortes [{_fmt_cuts(plan['silence']['cuts'])}]",
            f"Muletillas ({plan['filler_mode']}): {fillers}",
            f"Gancho ({plan['hook']['end']:.0f}s): {hook['text']}",
            f"Por qué: {reason}",
        ]
        if hook.get("alternates"):
            lines.append("Alternativas: " + " | ".join(hook["alternates"]))
        if plan["trim"]["will_trim"]:
            lines.append(f"Aviso: se recortará a {plan['trim']['max_duration']:.0f}s en la exportación.")
        for warning in warnings:
            lines.append(f"Aviso: {warning}")
        lines.append(
            "Responde que sí para renderizar, o pásame otro gancho."
            if awaiting
            else "Sigo con el render."
        )
    else:
        lines = [
            "Plan is ready. Confirm before the render.",
            f"Clip language: {plan['language']}",
            f"Duration: {plan['source_duration']:.1f}s → {plan['output_duration']:.1f}s",
            f"Silence ({plan['silence_engine']}): {plan['silence']['removed_seconds']:.1f}s across {len(plan['silence']['cuts'])} cuts [{_fmt_cuts(plan['silence']['cuts'])}]",
            f"Fillers ({plan['filler_mode']}): {fillers}",
            f"Hook ({plan['hook']['end']:.0f}s): {hook['text']}",
            f"Why: {reason}",
        ]
        if hook.get("alternates"):
            lines.append("Alternates: " + " | ".join(hook["alternates"]))
        if plan["trim"]["will_trim"]:
            lines.append(f"Note: export will trim to {plan['trim']['max_duration']:.0f}s.")
        for warning in warnings:
            lines.append(f"Note: {warning}")
        lines.append(
            "Say yes to render, or send a different hook."
            if awaiting
            else "Rendering next."
        )
    return "\n".join(lines)


def _resolve_music(preset: dict, override: str | None) -> Path | None:
    if override:
        path = Path(override)
        if not path.exists():
            raise UGCError(f"Music file not found: {path}", f"No está el archivo de música: {path}")
        return path
    configured = preset["music"].get("file")
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise UGCError(f"Music file not found: {path}", f"No está el archivo de música: {path}")
        return path
    return default_music_path()


def _do_transcribe(args: argparse.Namespace, preset: dict, workdir: Path) -> dict:
    if not args.input:
        raise UGCError("Pass the clip path.", "Pasa la ruta del clip.")
    video = Path(args.input).resolve()
    if not video.exists():
        raise UGCError(f"Input not found: {video}", f"No está el archivo: {video}")
    probe(video)
    model = args.model or preset["transcription"].get("model")
    return transcribe(
        video,
        workdir,
        engine=args.transcribe_engine or preset["transcription"]["engine"],
        model=model,
        language=args.lang,
        device_pref=args.device or preset["transcription"]["device"],
        vad_filter=bool(preset["transcription"]["vad_filter"]),
        beam_size=int(preset["transcription"]["beam_size"]),
    )


def _follow(stage: str, ui: str, plan: dict | None, workdir: Path | None, error: str | None = None) -> None:
    print_next_steps(stage, ui, plan, error=error)
    if plan is not None and workdir is not None:
        dump_json(workdir / "plan.json", plan)


def _do_render(args: argparse.Namespace, preset: dict, workdir: Path, plan: dict, ui: str) -> dict:
    if args.hook:
        plan["hook"]["text"] = args.hook.strip()
        plan["hook"]["reason"] = "user"
        dump_json(workdir / "plan.json", plan)
    source = Path(plan["source"])
    export = preset["export"]
    cut = workdir / "cut.mp4"
    cut_video(
        source,
        cut,
        plan["kept_ranges"],
        width=int(export["width"]),
        height=int(export["height"]),
        fps=int(export["fps"]),
        crf=int(export["crf"]),
        audio_bitrate=export["audio_bitrate"],
    )
    state = resolve_bg(args, preset, plan)
    picture = cut
    if state["enabled"]:
        width = int(export["width"])
        height = int(export["height"])
        fps = int(export["fps"])
        if not state["approved"]:
            frames = build_preview(
                cut,
                workdir,
                state,
                width,
                height,
                fps,
                int(export["crf"]),
                export["audio_bitrate"],
            )
            state["previews"] = frames
            state["approved"] = False
            plan["bg"] = state
            print(bg_checkpoint_message(ui, frames, state))
            _follow("bg", ui, plan, workdir)
            return {"awaiting": AWAITING_BG, "renderer": None}
        picture = prepare_picture(
            cut,
            workdir,
            state,
            width,
            height,
            fps,
            int(export["crf"]),
            export["audio_bitrate"],
        )
        state["approved"] = True
    plan["bg"] = state
    dump_json(workdir / "plan.json", plan)
    music = _resolve_music(preset, args.music)
    styled = workdir / "styled.mp4"
    if args.renderer and args.renderer != "auto":
        preset["_renderer_explicit"] = True
    info = render_styled(
        picture,
        styled,
        plan,
        preset,
        music,
        workdir,
        renderer=args.renderer or "auto",
    )
    dump_json(workdir / "render.json", info)
    return info


def _do_export(preset: dict, workdir: Path, plan: dict) -> dict:
    export = preset["export"]
    styled = workdir / "styled.mp4"
    if not styled.exists():
        raise UGCError("styled.mp4 is missing. Render first.", "Falta styled.mp4. Primero renderiza.")
    current = styled
    trimmed = False
    info = probe(styled)
    if plan["trim"]["will_trim"] or (
        export["trim_if_over"] and info["duration"] > float(export["max_duration"]) + 0.05
    ):
        trimmed_path = workdir / "trimmed.mp4"
        trim_media(
            styled,
            trimmed_path,
            float(export["max_duration"]),
            export["audio_bitrate"],
            int(export["crf"]),
        )
        current = trimmed_path
        trimmed = True
    stats = loudnorm_stats(
        current,
        float(export["lufs"]),
        float(export["true_peak"]),
        float(export["lra"]),
    )
    final = workdir / "final.mp4"
    apply_loudnorm(
        current,
        final,
        stats,
        float(export["lufs"]),
        float(export["true_peak"]),
        float(export["lra"]),
        export["audio_bitrate"],
    )
    measured = loudnorm_stats(
        final,
        float(export["lufs"]),
        float(export["true_peak"]),
        float(export["lra"]),
    )
    final_info = probe(final)
    hook_end = float(plan["hook"]["end"])
    frame_at = min(1.2, max(0.4, hook_end * 0.4))
    if plan["captions"]:
        first = plan["captions"][0]
        mid = (first["start"] + first["end"]) / 2
        if mid < hook_end:
            frame_at = mid
    frame = workdir / "frame.png"
    extract_frame(final, frame, frame_at)
    summary = {
        "final": str(final.resolve()),
        "frame": str(frame.resolve()),
        "duration": final_info["duration"],
        "width": final_info["width"],
        "height": final_info["height"],
        "lufs": float(measured.get("input_i")),
        "true_peak": float(measured.get("input_tp")),
        "trimmed": trimmed,
        "renderer": load_json(workdir / "render.json").get("renderer") if (workdir / "render.json").exists() else None,
    }
    dump_json(workdir / "export.json", summary)
    return summary


def _print_export(summary: dict, ui: str) -> None:
    if ui == "es":
        print(
            f"Listo: {summary['final']}\n"
            f"{summary['width']}x{summary['height']}, {summary['duration']:.1f}s, "
            f"{summary['lufs']:.1f} LUFS (pico {summary['true_peak']:.1f} dBTP).\n"
            f"Frame: {summary['frame']}"
        )
    else:
        print(
            f"Ready: {summary['final']}\n"
            f"{summary['width']}x{summary['height']}, {summary['duration']:.1f}s, "
            f"{summary['lufs']:.1f} LUFS (peak {summary['true_peak']:.1f} dBTP).\n"
            f"Frame: {summary['frame']}"
        )


def cmd_doctor(args: argparse.Namespace) -> int:
    ui = _ui(args.ui, None)
    rows = []

    def add(name: str, ok: bool, detail: str, required: bool) -> None:
        rows.append((name, ok, detail, required))

    from shutil import which

    add("ffmpeg", bool(which("ffmpeg")), which("ffmpeg") or "missing", True)
    add("ffprobe", bool(which("ffprobe")), which("ffprobe") or "missing", True)
    add("libass", ffmpeg_has_filter("ass"), "subtitles/ass filter", True)
    add("drawtext", ffmpeg_has_filter("drawtext"), "not used for the hook; libass burns it", False)
    add("ffmpeg version", True, ffmpeg_version(), False)
    add("loudnorm", ffmpeg_has_filter("loudnorm"), "EBU R128", True)
    add("sidechaincompress", ffmpeg_has_filter("sidechaincompress"), "optional duck", False)
    device, compute = detect_device()
    add("device", True, f"{device} / {compute}", False)
    try:
        import faster_whisper  # noqa: F401

        add("faster-whisper", True, "import ok", True)
    except Exception as exc:
        add("faster-whisper", False, str(exc), True)
    add("whisperx", bool(whisperx_bin()), whisperx_bin() or "not installed (fallback will be used)", False)
    add("auto-editor", bool(auto_editor_available()), auto_editor_available() or "not installed (word gaps will be used)", False)
    root = skill_root()
    add("font", (root / "assets" / "fonts" / "Inter-Bold.ttf").exists(), "Inter Bold", True)
    add("music bed", (root / "assets" / "music" / "bed.m4a").exists(), "generated bed", False)
    add("node", bool(which("node")), which("node") or "missing", False)
    add("remotion", remotion_ready(root / "template"), "template/node_modules/remotion", False)
    add("opentimelineio", otio_available(), otio_version() or "not installed", False)
    add("otio cmx_3600", otio_adapter("cmx_3600"), "optional CMX EDL", False)
    add("otio fcp_xml", otio_adapter("fcp_xml"), "optional FCP7 fallback", False)
    add("otio fcpx_xml", otio_adapter("fcpx_xml"), "optional FCPXML fallback", False)
    bg_bin = backgroundremover_available()
    add(
        "backgroundremover",
        bool(bg_bin),
        bg_bin or "not installed; ./install.sh --with-bg (u2net weights, about 176 MB, into ~/.u2net)",
        False,
    )
    failed = False
    for name, ok, detail, required in rows:
        mark = "ok" if ok else ("MISSING" if required else "optional")
        if required and not ok:
            failed = True
        print(f"{mark:8} {name:20} {detail}")
    if ui == "es":
        print("La primera transcripción descarga el modelo (small en CPU, unos minutos).")
    else:
        print("The first transcription downloads the model (small on CPU, a few minutes).")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ugc_edit")
    sub = parser.add_subparsers(dest="cmd", required=True)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--ui", default="auto", choices=["auto", "en", "es"])
    doctor.set_defaults(func=lambda args: cmd_doctor(args))

    def add_common(target: argparse.ArgumentParser, needs_input: bool) -> None:
        target.add_argument("--ui", default="auto", choices=["auto", "en", "es"])
        if needs_input:
            target.add_argument("input", nargs="?" if target.prog.endswith("run") else None)
        target.add_argument("--workdir", required=True)
        target.add_argument("--preset")
        target.add_argument("--lang", default="auto", choices=["auto", "en", "es"])
        target.add_argument("--model")
        target.add_argument("--device", choices=["auto", "cpu", "cuda"])
        target.add_argument("--transcribe-engine", choices=["auto", "whisperx", "faster-whisper"])
        target.add_argument("--silence-engine", choices=["auto", "auto-editor", "words"])
        target.add_argument("--mode", choices=["conservative", "aggressive"])
        target.add_argument("--hook")
        target.add_argument("--music")
        target.add_argument("--renderer", choices=["auto", "remotion", "ffmpeg"])
        target.add_argument("--max-duration", type=float)
        target.add_argument("--no-trim", action="store_true")

    run = sub.add_parser("run")
    add_common(run, True)
    run.add_argument("--yes", action="store_true")
    run.add_argument("--from", dest="from_step", choices=["transcribe", "plan", "render", "export"])
    run.add_argument("--until", choices=["plan", "render", "export"])
    run.add_argument("--nle", default=None, help="Comma-separated editors, all, or none.")
    run.add_argument("--review-storyboard", action="store_true")
    run.add_argument("--no-review-storyboard", action="store_true")
    run.add_argument("--storyboard-yes", action="store_true")
    run.add_argument("--inline", action="store_true")
    run.add_argument("--no-inline", action="store_true")
    _add_bg_flags(run)

    for name, needs_input in (
        ("transcribe", True),
        ("plan", False),
        ("render", False),
        ("export", False),
    ):
        command = sub.add_parser(name)
        add_common(command, needs_input)
        if name == "export":
            command.add_argument("--nle", default=None, help="Comma-separated editors, all, or none.")
        if name == "render":
            _add_bg_flags(command)
        command.set_defaults(
            func=None,
            yes=False,
            from_step=None,
            until=None,
            nle=None,
            review_storyboard=False,
            no_review_storyboard=False,
            storyboard_yes=False,
            inline=False,
            no_inline=False,
            bg=None,
            bg_model=None,
            bg_threshold=None,
            bg_yes=False,
            bg_skip=False,
        )
    storyboard = sub.add_parser("storyboard")
    storyboard.add_argument("--workdir", required=True)
    storyboard.add_argument("--preset")
    storyboard.add_argument("--ui", default="auto", choices=["auto", "en", "es"])
    storyboard.add_argument("--vision-labels")
    storyboard.add_argument("--inline", action="store_true")
    storyboard.add_argument("--no-inline", action="store_true")
    storyboard.set_defaults(func=None, nle=None, inline=False, no_inline=False)
    run.set_defaults(func=None)
    return parser


def _add_bg_flags(target: argparse.ArgumentParser) -> None:
    target.add_argument("--bg", default=None, help="Image or video path, transparent, or keep.")
    target.add_argument("--bg-model", default=None, choices=["u2net", "u2net_human_seg", "u2netp"])
    target.add_argument("--bg-threshold", type=int, default=None, help="Matte luma cutoff, 0-255.")
    target.add_argument("--bg-yes", action="store_true", help="Approve the background preview.")
    target.add_argument("--bg-skip", action="store_true", help="Keep the original background.")


def _inline_flag(args: argparse.Namespace) -> bool | None:
    inline = bool(getattr(args, "inline", False))
    no_inline = bool(getattr(args, "no_inline", False))
    if inline and no_inline:
        raise UGCError(
            "Pass only one of --inline and --no-inline.",
            "Pasa solo uno de --inline y --no-inline.",
        )
    if inline:
        return True
    if no_inline:
        return False
    return None


def _preset_from_args(args: argparse.Namespace) -> dict:
    preset = load_preset(Path(args.preset) if getattr(args, "preset", None) else None)
    if getattr(args, "max_duration", None):
        preset["export"]["max_duration"] = args.max_duration
    if getattr(args, "no_trim", False):
        preset["export"]["trim_if_over"] = False
    return preset


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "doctor":
        return cmd_doctor(args)
    if args.cmd == "storyboard":
        try:
            story = write_storyboard(
                Path(args.workdir),
                _preset_from_args(args),
                Path(args.vision_labels) if args.vision_labels else None,
                inline=_inline_flag(args),
            )
        except UGCError as exc:
            _fail(args, exc)
            return 2
        ui = _ui(args.ui, None)
        _say(
            ui,
            f"Storyboard: {len(story['tracks']['video'])} shots in {args.workdir}/export/",
            f"Guion gráfico: {len(story['tracks']['video'])} tomas en {args.workdir}/export/",
        )
        _follow("storyboard", ui, _load_plan(Path(args.workdir)), Path(args.workdir))
        return 0
    if args.cmd == "export" and getattr(args, "nle", None):
        try:
            result = export_nle(Path(args.workdir), args.nle, _preset_from_args(args))
        except UGCError as exc:
            _fail(args, exc)
            return 2
        ui = _ui(args.ui, None)
        names = ", ".join(result["written"]) or "—"
        _say(ui, f"NLE export: {names}", f"Exportación NLE: {names}")
        for note in result["notes"]:
            print(note)
        _follow("final", ui, _load_plan(Path(args.workdir)), Path(args.workdir))
        return 0
    try:
        workdir = Path(args.workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        preset = _preset_from_args(args)
        mode = args.mode or preset["fillers"]["mode"]
        silence_engine = args.silence_engine or preset["silence"]["engine"]
        start = getattr(args, "from_step", None) or "transcribe"
        until = getattr(args, "until", None) or ("export" if args.cmd == "run" else args.cmd)
        if args.cmd != "run":
            start = args.cmd
            until = args.cmd
        order = ["transcribe", "plan", "render", "export"]
        if start not in order or until not in order or order.index(start) > order.index(until):
            raise UGCError("--from is after --until.", "--from está después de --until.")

        words_doc = None
        if order.index(start) <= order.index("transcribe") <= order.index(until):
            words_doc = _do_transcribe(args, preset, workdir)
        elif (workdir / "words.json").exists():
            words_doc = load_json(workdir / "words.json")

        language = (words_doc or {}).get("language")
        ui = _ui(args.ui, language)

        plan = None
        if order.index(start) <= order.index("plan") <= order.index(until):
            plan = _build_plan(workdir, preset, args.hook, mode, silence_engine)
            awaiting = args.cmd == "run" and not args.yes
            print(format_summary(plan, ui, awaiting=awaiting))
            needs_approval = args.cmd == "run" and not args.yes and until != "plan"
            # Stop when the user has not approved, even if --until is later.
            if args.cmd == "run" and not args.yes and start == "transcribe":
                _say(
                    ui,
                    "Stopped for approval (exit 10). Re-run with --from render --yes after confirming the hook.",
                    "Paré para tu aprobación (salida 10). Cuando confirmes el gancho, corre de nuevo con --from render --yes.",
                )
                _follow("hook", ui, plan, workdir)
                return AWAITING
            if needs_approval:
                _follow("hook", ui, plan, workdir)
                return AWAITING
        elif (workdir / "plan.json").exists():
            plan = load_json(workdir / "plan.json")

        if order.index("render") <= order.index(until) and order.index(start) <= order.index("render"):
            if plan is None:
                raise UGCError("plan.json is missing.", "Falta plan.json.")
            if args.cmd == "run":
                status, payload = resolve_delivery(args, plan, preset)
                if status == "ask":
                    print(delivery_questions(ui))
                    _follow("delivery", ui, plan, workdir)
                    return AWAITING_DELIVERY
                if status == "review":
                    plan["delivery"] = payload
                    write_storyboard(workdir, preset, None, inline=_inline_flag(args))
                    print(
                        storyboard_checkpoint(
                            ui,
                            str(workdir / "export" / "storyboard.html"),
                            str(workdir / "export" / "contact-sheet.jpg"),
                        )
                    )
                    _follow("storyboard", ui, plan, workdir)
                    return AWAITING_STORYBOARD
                plan["delivery"] = payload
                dump_json(workdir / "plan.json", plan)
            info = _do_render(args, preset, workdir, plan, ui)
            if info.get("awaiting") == AWAITING_BG:
                return AWAITING_BG
            _say(
                ui,
                f"Styled with {info['renderer']}.",
                f"Estilizado con {info['renderer']}.",
            )
        if order.index("export") <= order.index(until) and order.index(start) <= order.index("export"):
            if plan is None:
                plan = load_json(workdir / "plan.json")
            summary = _do_export(preset, workdir, plan)
            _print_export(summary, ui)
            delivery = (plan or {}).get("delivery") or {}
            if delivery.get("editor_projects") and delivery.get("editors"):
                result = export_nle(workdir, ",".join(delivery["editors"]), preset)
                names = ", ".join(result["written"]) or "—"
                _say(ui, f"NLE export: {names}", f"Exportación NLE: {names}")
                for note in result["notes"]:
                    print(note)
        if until == "transcribe":
            stage = "transcribe"
        elif until == "plan":
            stage = "hook"
        elif until == "render":
            stage = "render"
        else:
            stage = "final"
        _follow(stage, ui, plan, workdir)
        return 0
    except UGCError as exc:
        _fail(args, exc)
        return 2


def _load_plan(workdir: Path) -> dict | None:
    path = workdir / "plan.json"
    if not path.exists():
        return None
    return load_json(path)


def _fail(args: argparse.Namespace, exc: UGCError) -> None:
    ui = _ui(getattr(args, "ui", "auto"), None)
    print(exc.text(ui), file=sys.stderr)
    workdir = Path(args.workdir) if getattr(args, "workdir", None) else None
    plan = _load_plan(workdir) if workdir else None
    _follow("error", ui, plan, workdir, error=exc.text(ui))


if __name__ == "__main__":
    raise SystemExit(main())
