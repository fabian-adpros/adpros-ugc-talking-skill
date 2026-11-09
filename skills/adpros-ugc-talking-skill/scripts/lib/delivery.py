"""Editor-delivery choices. Never blocks on input().

Claude Code has no TTY. The CLI prints a question block and exits.
"""

from __future__ import annotations

from .nle import parse_editors
from .util import UGCError

AWAITING_DELIVERY = 11
AWAITING_STORYBOARD = 12


def _preset_delivery(preset: dict) -> dict:
    raw = preset.get("delivery") or {}
    editors = raw.get("editors") or ["premiere", "fcpx", "resolve"]
    return {
        "editor_projects": bool(raw.get("editor_projects", False)),
        "editors": list(editors),
        "review_storyboard": bool(raw.get("review_storyboard", False)),
    }


def resolve_delivery(args, plan: dict | None, preset: dict) -> tuple[str, dict | None]:
    """Return ask, review, or go.

    ask: print the questionnaire and exit 11.
    review: storyboard is written by the caller, then exit 12.
    go: continue. The payload is what to store on the plan.
    """
    saved = dict((plan or {}).get("delivery") or {})
    defaults = _preset_delivery(preset)
    yes = bool(getattr(args, "yes", False))
    nle = getattr(args, "nle", None)
    review_on = bool(getattr(args, "review_storyboard", False))
    review_off = bool(getattr(args, "no_review_storyboard", False))
    approved_flag = bool(getattr(args, "storyboard_yes", False))
    if review_on and review_off:
        raise UGCError(
            "Pass only one of --review-storyboard and --no-review-storyboard.",
            "Pasa solo uno de --review-storyboard y --no-review-storyboard.",
        )

    if yes and nle is None and not review_on and not review_off:
        editors = list(defaults["editors"])
        if not defaults["editor_projects"]:
            editors = []
        return "go", {
            "answered": True,
            "editor_projects": defaults["editor_projects"],
            "editors": editors,
            "review_storyboard": False,
            "storyboard_approved": True,
        }

    explicit = nle is not None or review_on or review_off or approved_flag
    if not explicit and not saved.get("answered") and not yes:
        return "ask", None

    if nle is not None:
        editors = sorted(parse_editors(nle))
        editor_projects = bool(editors)
    elif saved.get("answered"):
        editors = list(saved.get("editors") or [])
        editor_projects = bool(saved.get("editor_projects"))
    else:
        editors = list(defaults["editors"])
        editor_projects = defaults["editor_projects"]
        if not editor_projects:
            editors = []

    if review_on:
        review = True
    elif review_off:
        review = False
    elif saved.get("answered"):
        review = bool(saved.get("review_storyboard"))
    else:
        review = defaults["review_storyboard"]

    approved = (not review) or approved_flag or yes or bool(saved.get("storyboard_approved"))
    payload = {
        "answered": True,
        "editor_projects": editor_projects,
        "editors": editors,
        "review_storyboard": review,
        "storyboard_approved": approved,
    }
    if review and not approved:
        return "review", payload
    return "go", payload


def delivery_questions(ui: str) -> str:
    if ui == "es":
        return """
exit: 11
question: delivery

¿Quieres archivos de proyecto para un editor al final? (sí/no)
¿Qué editores? Puedes elegir varios: premiere, fcpx, resolve, capcut, otio, edl
CapCut no tiene proyecto: solo media conformado y SRT.
¿Revisas el guion gráfico antes de exportar? (sí/no)

Cuando respondas, vuelve a correr con los flags. Ejemplos:
  --nle premiere,fcpx,resolve --review-storyboard
  --nle none --no-review-storyboard
""".strip()
    return """
exit: 11
question: delivery

Do you want editor project files at the end? (yes/no)
Which editors? Multi-select: premiere, fcpx, resolve, capcut, otio, edl
CapCut has no project file: conformed media and SRT only.
Review the storyboard before exporting? (yes/no)

After you answer, re-run with the flags. Examples:
  --nle premiere,fcpx,resolve --review-storyboard
  --nle none --no-review-storyboard
""".strip()


def storyboard_checkpoint(ui: str, html_path: str, contact_path: str) -> str:
    if ui == "es":
        return f"""
exit: 12
question: storyboard
html: {html_path}
contact_sheet: {contact_path}

Mira el guion gráfico y la hoja de contacto. Cuando lo apruebes, sigue con --storyboard-yes.
""".strip()
    return f"""
exit: 12
question: storyboard
html: {html_path}
contact_sheet: {contact_path}

Look at the storyboard and the contact sheet. When you approve them, continue with --storyboard-yes.
""".strip()
