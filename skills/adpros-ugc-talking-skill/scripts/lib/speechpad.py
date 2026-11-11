"""Keep a little air around each cut so word endings are not chopped off.

The plan already leaves `padding` seconds. This pass measures the source audio
at each join and, if that point is still speech, moves the join into the gap.
"""

from __future__ import annotations

import math
import struct
import subprocess
from pathlib import Path

SPEECH_DB = -36.0
PAD_STEP = 0.04
MAX_EXTRA = 0.16


def window_db(samples: list[float], rate: int, moment: float, duration: float = 0.04) -> float:
    if rate <= 0 or not samples:
        return -100.0
    start = max(0, int(moment * rate))
    end = min(len(samples), int((moment + duration) * rate))
    chunk = samples[start:end]
    if not chunk:
        return -100.0
    mean_sq = sum(sample * sample for sample in chunk) / len(chunk)
    if mean_sq <= 1e-12:
        return -100.0
    return 10.0 * math.log10(mean_sq)


def load_pcm16k(src: Path) -> tuple[list[float], int]:
    """One decode of the source audio. Returns mono float samples at 16 kHz."""
    completed = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "f32le",
            "pipe:1",
        ],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0 or not completed.stdout:
        return [], 16000
    count = len(completed.stdout) // 4
    return list(struct.unpack(f"<{count}f", completed.stdout[: count * 4])), 16000


def _retarget(ranges: list[dict]) -> list[dict]:
    cursor = 0.0
    out = []
    for item in ranges:
        duration = max(0.0, float(item["src_end"]) - float(item["src_start"]))
        out.append({**item, "dst_start": cursor, "dst_end": cursor + duration})
        cursor += duration
    return out


def widen_ranges(
    ranges: list[dict],
    energy_at,
    words: list[dict] | None = None,
    speech_db: float = SPEECH_DB,
    step: float = PAD_STEP,
    max_extra: float = MAX_EXTRA,
    duration: float | None = None,
) -> tuple[list[dict], list[str]]:
    """Move a boundary that still contains speech into the neighbouring gap."""
    if not ranges:
        return [], []
    current = [dict(item) for item in ranges]
    notes: list[str] = []
    for index, item in enumerate(current):
        for edge in ("src_end", "src_start"):
            added = 0.0
            while added < max_extra - 1e-6:
                moment = float(item[edge])
                if edge == "src_start" and moment <= 0.03:
                    break
                if edge == "src_end" and duration is not None and moment >= float(duration) - 0.03:
                    break
                speech = energy_at(moment) > speech_db
                crossing = _word_crossing(words or [], moment)
                if not speech and crossing is None:
                    break
                if edge == "src_end":
                    limit = current[index + 1]["src_start"] - 0.02 if index + 1 < len(current) else moment + max_extra
                    target = crossing[1] + 0.02 if crossing else moment + step
                    grow = min(step, max_extra - added, target - moment, limit - moment)
                    if grow <= 0.005:
                        break
                    item["src_end"] = moment + grow
                else:
                    limit = current[index - 1]["src_end"] + 0.02 if index > 0 else 0.0
                    target = crossing[0] - 0.02 if crossing else moment - step
                    grow = min(step, max_extra - added, moment - target, moment - limit)
                    if grow <= 0.005:
                        break
                    item["src_start"] = moment - grow
                added += grow
            if added > 0:
                notes.append(f"{edge} of range {index} moved by {added:.3f}s")
    return _retarget(current), notes


def _word_crossing(words: list[dict], moment: float) -> tuple[float, float] | None:
    for word in words:
        start = float(word.get("start") or 0)
        end = float(word.get("end") or 0)
        if start < moment < end:
            return start, end
    return None


def shift_plan_times(plan: dict, old_ranges: list[dict], new_ranges: list[dict]) -> None:
    """Keep captions on the same spoken words after a range grows."""

    def shift(moment: float) -> float:
        for old, new in zip(old_ranges, new_ranges):
            if moment <= float(old["dst_end"]) + 1e-3:
                return float(new["dst_start"]) + (moment - float(old["dst_start"]))
        if new_ranges:
            return float(new_ranges[-1]["dst_end"])
        return moment

    for word in plan.get("words") or []:
        word["start"] = shift(float(word["start"]))
        word["end"] = shift(float(word["end"]))
    for card in plan.get("captions") or []:
        card["start"] = shift(float(card["start"]))
        card["end"] = shift(float(card["end"]))
        for word in card.get("words") or []:
            word["start"] = shift(float(word["start"]))
            word["end"] = shift(float(word["end"]))
    if new_ranges:
        plan["output_duration"] = float(new_ranges[-1]["dst_end"])
