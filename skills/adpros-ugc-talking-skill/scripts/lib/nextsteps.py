"""Short numbered follow-ups printed after every stage.

Each item has English and Spanish text. The command prints the language that
matches the clip, and stores the full list on plan.json.
"""

from __future__ import annotations

import json

STAGES = ("hook", "delivery", "storyboard", "bg", "render", "final", "error", "transcribe")


def _short(text: str, limit: int = 160) -> str:
    flat = " ".join((text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"


def _error_advice(error: str | None) -> tuple[str, str, str | None]:
    text = error or ""
    low = text.lower()
    brief = _short(text)
    if "non full-range yuv" in low or "strict_std_compliance" in low or "yuvj420p" in low:
        return (
            "The preview JPEG was rejected as TV-range YUV. Re-run the same command; JPEGs are written full-range now.",
            "El JPEG de la vista previa fue rechazado por el rango YUV. Vuelve a correr el mismo comando.",
            "run --from render",
        )
    if "no preview frame" in low or "nothing was written" in low:
        return (
            "A preview time was past the last frame. Re-run; times now stop two frames before the end.",
            "Un tiempo de la vista previa quedó después del último cuadro. Vuelve a correr.",
            "run --from render",
        )
    if "backgroundremover" in low or "--with-bg" in low:
        return (
            "Install the optional background tool, then re-run the same command: ./install.sh --with-bg",
            "Instala la herramienta opcional de fondo y vuelve a correr el mismo comando: ./install.sh --with-bg",
            "./install.sh --with-bg",
        )
    if "plan.json" in low:
        return (
            "The plan is missing. Transcribe and plan first: run CLIP --workdir DIR",
            "Falta el plan. Primero transcribe y planifica: run CLIP --workdir DIR",
            "run CLIP --workdir DIR",
        )
    if "styled.mp4" in low:
        return (
            "Render before export: run CLIP --workdir DIR --from render --renderer ffmpeg",
            "Renderiza antes de exportar: run CLIP --workdir DIR --from render --renderer ffmpeg",
            "run CLIP --workdir DIR --from render --renderer ffmpeg",
        )
    if "decoder" in low or "hevc" in low or "h265" in low:
        return (
            "This ffmpeg could not decode the clip. Make an H.264 copy and run that file.",
            "Este ffmpeg no decodificó el clip. Haz una copia H.264 y corre ese archivo.",
            "ffmpeg -i CLIP -c:v libx264 -c:a aac copy.mp4",
        )
    if "ugc-ffmpeg.log" in low or "bg-infer.log" in low:
        return (
            f"Open the log named above, fix that line, and re-run the same command. {brief}",
            f"Abre el log de arriba, corrige esa línea y vuelve a correr el mismo comando. {brief}",
            None,
        )
    if "not found" in low or "no está" in low:
        return (
            f"Check the path, then run the same command again. {brief}",
            f"Revisa la ruta y vuelve a correr el mismo comando. {brief}",
            None,
        )
    return (
        f"Read the short message above, fix that cause, and run the same command again. {brief}",
        f"Lee el mensaje corto de arriba, corrige esa causa y vuelve a correr el mismo comando. {brief}",
        None,
    )


def build_next_steps(stage: str, plan: dict | None = None, error: str | None = None) -> list[dict]:
    plan = plan or {}
    if stage == "hook":
        items = [
            ("approve_hook", "Approve this hook and continue", "Aprueba este gancho y sigue", "--from render --yes"),
            ("change_hook", "Send a different hook", "Pásame otro gancho", "--hook \"...\""),
            ("editor_files", "Also make Premiere, Final Cut, and Resolve files", "También archivos de Premiere, Final Cut y Resolve", "--nle all"),
            ("caption_place", "Move the captions if they cover the product", "Mueve los subtítulos si tapan el producto", "captions.y_ratio"),
        ]
    elif stage == "delivery":
        items = [
            ("editors_review", "Premiere, Final Cut, and Resolve, and review the storyboard first", "Premiere, Final Cut y Resolve, y revisa el storyboard antes", "--nle premiere,fcpx,resolve --review-storyboard"),
            ("no_editors", "No editor files, just the MP4", "Sin archivos de editor, solo el MP4", "--nle none"),
            ("capcut", "CapCut media and subtitles only", "Solo medios y subtítulos para CapCut", "--nle capcut"),
            ("storyboard_only", "Review the storyboard before rendering", "Revisa el storyboard antes de renderizar", "--review-storyboard"),
        ]
    elif stage == "storyboard":
        items = [
            ("approve_board", "Approve the storyboard and render", "Aprueba el storyboard y renderiza", "--storyboard-yes"),
            ("change_hook", "Change the hook first", "Cambia el gancho primero", "--hook \"...\""),
            ("skip_review", "Skip the storyboard review", "Salta la revisión del storyboard", "--no-review-storyboard"),
            ("caption_place", "Move the captions if they cover the product", "Mueve los subtítulos si tapan el producto", "captions.y_ratio"),
        ]
    elif stage == "bg":
        items = [
            ("keep_bg", "Keep this background", "Quédate con este fondo", "--bg-yes"),
            ("person_model", "Try the person-only model (it can erase a product)", "Prueba el modelo solo de persona (puede borrar el producto)", "--bg-model u2net_human_seg --bg-yes"),
            ("threshold", "Adjust the mask threshold", "Ajusta el umbral de la máscara", "--bg-threshold 40 --bg-yes"),
            ("skip_bg", "Skip and keep the original background", "Salta y deja el fondo original", "--bg-skip"),
        ]
    elif stage == "render":
        items = [
            ("export", "Export the MP4", "Exporta el MP4", "export"),
            ("change_hook", "Change the hook and render again", "Cambia el gancho y vuelve a renderizar", "--hook \"...\""),
            ("another_bg", "Try another background", "Prueba otro fondo", "--bg <image-or-video>"),
            ("caption_place", "Move the captions if they cover the product", "Mueve los subtítulos si tapan el producto", "captions.y_ratio"),
        ]
    elif stage == "final":
        items = [
            ("change_hook", "Change the hook", "Cambia el gancho", "--hook \"...\""),
            ("another_bg", "Try another background", "Prueba otro fondo", "--bg <image-or-video>"),
            ("export_nle", "Export for Premiere, Final Cut, and Resolve", "Exporta para Premiere, Final Cut y Resolve", "--nle all"),
            ("other_ratio", "Make another video with this preset, a 1:1 or 4:5 version, or move captions if they cover the product", "Haz otro video con este preset, una versión 1:1 o 4:5, o mueve los subtítulos si tapan el producto", "export.width / captions.y_ratio"),
        ]
    elif stage == "transcribe":
        items = [
            ("plan", "Build the plan and the hook", "Arma el plan y el gancho", "plan"),
            ("doctor", "Run doctor if a tool was missing", "Corre doctor si faltó una herramienta", "doctor"),
        ]
    elif stage == "error":
        en, es, command = _error_advice(error)
        low = (error or "").lower()
        if "ugc-ffmpeg.log" in low or "non full-range" in low or "no preview frame" in low:
            second = (
                "open_log",
                "Open ugc-ffmpeg.log next to the output and read the last lines",
                "Abre ugc-ffmpeg.log junto a la salida y lee las últimas líneas",
                None,
            )
        else:
            second = (
                "doctor",
                "Run doctor and fix the first missing tool",
                "Corre doctor y arregla la primera herramienta que falte",
                "doctor",
            )
        items = [
            ("fix", en, es, command),
            second,
            ("retry", "Run the same command again after the fix", "Vuelve a correr el mismo comando después del arreglo", "run"),
        ]
    else:
        items = [
            ("status", "Check the project status", "Revisa el estado del proyecto", "status"),
            ("doctor", "Run doctor", "Corre doctor", "doctor"),
        ]
    steps = []
    for number, (step_id, en, es, command) in enumerate(items, start=1):
        steps.append({"n": number, "id": step_id, "en": en, "es": es, "command": command})
    return steps


def print_next_steps(stage: str, ui: str, plan: dict | None = None, error: str | None = None) -> list[dict]:
    steps = build_next_steps(stage, plan, error)
    if plan is not None:
        plan["next_steps"] = steps
    title = "Qué sigue" if ui == "es" else "What's next"
    print(title)
    for step in steps:
        text = step["es"] if ui == "es" else step["en"]
        hint = f"  ({step['command']})" if step.get("command") else ""
        print(f"{step['n']}. {text}{hint}")
    print(json.dumps({"next_steps": steps}, ensure_ascii=False))
    return steps
