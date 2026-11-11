"""Apply a new background only on chosen stretches of the cut.

The model runs on those stretches alone. Everywhere else the original picture
stays. A short ramp at each edge keeps the join from popping.
"""

from __future__ import annotations

from pathlib import Path

from .util import UGCError

TRANSITION_SECONDS = 0.25


def parse_moments(text: str) -> list[dict]:
    """`0-3,12.5-15,20-23` becomes start/end pairs on the cut timeline."""
    pieces = [part.strip() for part in (text or "").split(",") if part.strip()]
    if not pieces:
        raise UGCError(
            "Pass background moments as start-end pairs, for example 0-3,18-21.",
            "Pasa los momentos como pares inicio-fin, por ejemplo 0-3,18-21.",
        )
    segments = []
    for piece in pieces:
        if "-" not in piece:
            raise UGCError(
                f"Cannot read background moment {piece!r}. Use start-end.",
                f"No entiendo el momento {piece!r}. Usa inicio-fin.",
            )
        left, right = piece.split("-", 1)
        start, end = float(left), float(right)
        if end <= start:
            raise UGCError(
                f"Background moment {piece} ends before it starts.",
                f"El momento {piece} termina antes de empezar.",
            )
        segments.append({"start": round(start, 3), "end": round(end, 3)})
    return segments


def moment_seconds(segments: list[dict], duration: float | None = None) -> float:
    total = 0.0
    for segment in segments:
        start = max(0.0, float(segment["start"]))
        end = float(segment["end"])
        if duration is not None:
            end = min(end, float(duration))
        total += max(0.0, end - start)
    return total


def envelope_expr(segments: list[dict], fade: float = TRANSITION_SECONDS) -> str:
    """ffmpeg geq expression, 0 outside the moments and 1 inside, with ramps."""
    terms = []
    for segment in segments:
        start = float(segment["start"])
        end = float(segment["end"])
        span = max(0.02, end - start)
        ramp = min(float(fade), span / 2.0)
        terms.append(
            "if(between(T,{s:.3f},{e:.3f}),"
            "min(1\\,min((T-{s:.3f})/{r:.3f}\\,({e:.3f}-T)/{r:.3f}))"
            ",0)".format(s=start, e=end, r=ramp)
        )
    expr = terms[0]
    for term in terms[1:]:
        expr = f"max({expr},{term})"
    return expr


def build_moment_extract_command(src: Path, dest: Path, segments: list[dict], fps: int) -> list[str]:
    """One decode. Only the chosen stretches are written, in order."""
    parts = []
    labels = []
    for index, segment in enumerate(segments):
        start = float(segment["start"])
        end = float(segment["end"])
        parts.append(
            f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,fps={int(fps)}[v{index}]"
        )
        labels.append(f"[v{index}]")
    parts.append(f"{''.join(labels)}concat=n={len(segments)}:v=1:a=0[v]")
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-filter_complex",
        ";".join(parts),
        "-map",
        "[v]",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        str(dest),
    ]


def partial_composite_graph(segments: list[dict], width: int, height: int, fps: int, duration: float) -> str:
    """Original picture outside the moments, new plate behind the person inside them.

    Input 0 is the cut, input 1 is the plate, input 2 is the person matte
    (white person, black elsewhere, already timed to the full cut).
    """
    expr = envelope_expr(segments)
    return (
        f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps={fps},trim=duration={duration:.3f},setpts=PTS-STARTPTS,format=yuv420p[bg];"
        f"[0:v]format=yuv420p[orig];"
        f"[2:v]scale={width}:{height},format=gray[person];"
        f"color=c=black:s={width}x{height}:r={fps}:d={duration:.3f},format=yuv420p,"
        f"geq=lum='255*({expr})'[env];"
        f"[bg][orig][person]maskedmerge[cutout];"
        f"[orig][cutout][env]maskedmerge,format=yuv420p[v]"
    )
