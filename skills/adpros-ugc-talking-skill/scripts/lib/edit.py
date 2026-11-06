"""Silence cuts, filler removal, timeline remap, captions, and hook suggestion.

Times are seconds on the source timeline unless a field is explicitly remapped.
Silences are removed only when they are strictly longer than `min_silence`
(default 0.4s). Each cut keeps `padding` seconds (default 0.05) of the
original gap on both sides so the edit does not clip the word edge.
"""

from __future__ import annotations

import re
from typing import Iterable

PUNCT = ".!?…"
STANDALONE_GAP = 0.18
# Breaths tighter than this are swallowed into a filler cut so we don't
# leave a click on either side of "um" / "eh".
FILLER_BREATH = 0.12

GREETINGS = {
    "en": {"hi", "hey", "hello", "yo", "hiya", "howdy"},
    "es": {"hola", "buenas", "buenos", "hey", "ey", "qué", "que"},
}

RESULT_WORDS = {
    "en": {
        "save", "saves", "stop", "never", "always", "secret", "mistake",
        "free", "fastest", "only", "error", "don't", "dont", "why", "how",
    },
    "es": {
        "ahorra", "ahorrar", "ahorras", "nunca", "siempre", "secreto",
        "error", "gratis", "truco", "cómo", "como", "evita", "evitar",
        "mejor", "deja", "hoy",
    },
}

_TOKEN_RE = re.compile(r"[^\wáéíóúüñ]+", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d")


def normalize_token(word: str) -> str:
    text = word.strip().lower().replace("¿", "").replace("¡", "")
    text = _TOKEN_RE.sub("", text)
    return text


def display_word(word: str) -> str:
    return " ".join(word.strip().split())


def _active_patterns(table: dict, language: str, mode: str) -> list[dict]:
    lang = table.get(language) or {}
    grouped: dict[tuple[str, ...], dict] = {}
    tiers = ["clear"] if mode != "aggressive" else ["clear", "aggressive"]
    for tier in tiers:
        for pattern in lang.get(tier, []):
            tokens = tuple(pattern["tokens"])
            current = grouped.get(tokens)
            # A single `standalone: false` entry wins: the phrase is always a filler.
            standalone = bool(pattern.get("standalone", True))
            if current is None or (current["standalone"] and not standalone):
                grouped[tokens] = {"tokens": list(tokens), "standalone": standalone, "tier": tier}
    patterns = list(grouped.values())
    patterns.sort(key=lambda item: len(item["tokens"]), reverse=True)
    return patterns


def _is_standalone(words: list[dict], start: int, end: int) -> bool:
    if start == 0:
        before = True
    else:
        gap = words[start]["start"] - words[start - 1]["end"]
        prev = display_word(words[start - 1]["word"])
        before = gap >= STANDALONE_GAP or (prev[-1:] in PUNCT if prev else False)
    if end == len(words) - 1:
        after = True
    else:
        gap = words[end + 1]["start"] - words[end]["end"]
        cur = display_word(words[end]["word"])
        after = gap >= STANDALONE_GAP or (cur[-1:] in PUNCT if cur else False)
    return before and after


def find_filler_spans(words: list[dict], language: str, mode: str, table: dict) -> list[dict]:
    if language not in ("en", "es"):
        return []
    patterns = _active_patterns(table, language, mode)
    tokens = [normalize_token(word["word"]) for word in words]
    spans: list[dict] = []
    index = 0
    while index < len(tokens):
        matched = None
        for pattern in patterns:
            size = len(pattern["tokens"])
            if tokens[index : index + size] != pattern["tokens"]:
                continue
            if pattern["standalone"] and not _is_standalone(words, index, index + size - 1):
                continue
            matched = pattern
            break
        if not matched:
            index += 1
            continue
        size = len(matched["tokens"])
        piece = words[index : index + size]
        spans.append(
            {
                "start_idx": index,
                "end_idx": index + size - 1,
                "text": " ".join(display_word(word["word"]) for word in piece),
                "start": piece[0]["start"],
                "end": piece[-1]["end"],
                "tier": matched["tier"],
            }
        )
        index += size
    if spans and len(spans) == len(words):
        # Never delete the entire clip. The caller also checks this.
        return []
    return spans


def silence_cuts_from_words(
    words: list[dict],
    duration: float,
    min_silence: float,
    padding: float,
) -> list[tuple[float, float]]:
    """Cut gaps strictly longer than `min_silence`, leaving `padding` on each side."""
    cuts: list[tuple[float, float]] = []
    if duration <= 0:
        return cuts
    if not words:
        if duration > min_silence:
            return [(0.0, duration)]
        return cuts
    lead = words[0]["start"]
    if lead > min_silence:
        end = words[0]["start"] - padding
        if end > 0:
            cuts.append((0.0, end))
    for left, right in zip(words, words[1:]):
        gap = right["start"] - left["end"]
        if gap > min_silence:
            start = left["end"] + padding
            end = right["start"] - padding
            if end - start > 0.02:
                cuts.append((start, end))
    tail = duration - words[-1]["end"]
    if tail > min_silence:
        start = words[-1]["end"] + padding
        if duration - start > 0.02:
            cuts.append((start, duration))
    return cuts


def filler_cut_intervals(words: list[dict], spans: list[dict]) -> list[tuple[float, float]]:
    cuts: list[tuple[float, float]] = []
    for span in spans:
        start = span["start"]
        end = span["end"]
        if span["start_idx"] > 0:
            prev = words[span["start_idx"] - 1]
            if start - prev["end"] < FILLER_BREATH:
                start = prev["end"]
            start = max(start, prev["end"])
        if span["end_idx"] < len(words) - 1:
            nxt = words[span["end_idx"] + 1]
            if nxt["start"] - end < FILLER_BREATH:
                end = nxt["start"]
            end = min(end, nxt["start"])
        if end - start > 0.02:
            cuts.append((start, end))
    return cuts


def merge_intervals(cuts: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    ordered = sorted((float(a), float(b)) for a, b in cuts if b - a > 0.02)
    if not ordered:
        return []
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        prev_s, prev_e = merged[-1]
        if start <= prev_e + 0.01:
            merged[-1] = (prev_s, max(prev_e, end))
        else:
            merged.append((start, end))
    return merged


def subtract_intervals(
    cuts: list[tuple[float, float]],
    protected: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Drop any part of `cuts` that overlaps a protected interval (a spoken word)."""
    remaining = merge_intervals(cuts)
    for prot_s, prot_e in protected:
        nxt: list[tuple[float, float]] = []
        for start, end in remaining:
            if prot_e <= start or prot_s >= end:
                nxt.append((start, end))
                continue
            if start < prot_s:
                nxt.append((start, min(end, prot_s)))
            if prot_e < end:
                nxt.append((max(start, prot_e), end))
        remaining = [(a, b) for a, b in nxt if b - a > 0.02]
    return merge_intervals(remaining)


def invert_cuts(duration: float, cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    kept: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in merge_intervals(cuts):
        start = max(0.0, start)
        end = min(duration, end)
        if start > cursor + 0.02:
            kept.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration - 0.02:
        kept.append((cursor, duration))
    return kept


def _word_mid(word: dict) -> float:
    return (word["start"] + word["end"]) / 2.0


def drop_empty_slivers(
    kept: list[tuple[float, float]],
    words: list[dict],
    filler_indexes: set[int],
    min_len: float = 0.2,
) -> list[tuple[float, float]]:
    """Drop wordless scraps left between a filler cut and the next word.

    Longer wordless ranges stay. Those are pauses the silence rule chose to keep,
    or audio the transcript missed.
    """
    usable = []
    for start, end in kept:
        holds_word = False
        for index, word in enumerate(words):
            if index in filler_indexes:
                continue
            if start <= _word_mid(word) < end:
                holds_word = True
                break
        if holds_word or (end - start) >= min_len:
            usable.append((start, end))
    return usable


def kept_with_dest(ranges: list[tuple[float, float]]) -> list[dict]:
    cursor = 0.0
    out = []
    for src_start, src_end in ranges:
        length = src_end - src_start
        out.append(
            {
                "src_start": src_start,
                "src_end": src_end,
                "dst_start": cursor,
                "dst_end": cursor + length,
            }
        )
        cursor += length
    return out


def remap_words(words: list[dict], ranges: list[dict], filler_indexes: set[int]) -> list[dict]:
    remapped = []
    for index, word in enumerate(words):
        if index in filler_indexes:
            continue
        mid = _word_mid(word)
        for block in ranges:
            if block["src_start"] <= mid < block["src_end"]:
                shift = block["dst_start"] - block["src_start"]
                start = max(block["dst_start"], word["start"] + shift)
                end = min(block["dst_end"], word["end"] + shift)
                if end - start >= 0.01:
                    remapped.append(
                        {
                            "word": display_word(word["word"]),
                            "start": start,
                            "end": end,
                            "probability": word.get("probability"),
                        }
                    )
                break
    return remapped


def _ends_sentence(word: str) -> bool:
    text = display_word(word)
    return bool(text) and text[-1] in PUNCT


def group_captions(words: list[dict], max_words: int = 3) -> list[dict]:
    """Group remapped words into 2–3 word cards. A 1-word card is merged when it can be."""
    if max_words < 1:
        max_words = 3
    raw: list[dict] = []
    bucket: list[dict] = []

    def flush() -> None:
        if not bucket:
            return
        raw.append(
            {
                "start": bucket[0]["start"],
                "end": bucket[-1]["end"],
                "words": [
                    {"text": word["word"], "start": word["start"], "end": word["end"]}
                    for word in bucket
                ],
            }
        )
        bucket.clear()

    for index, word in enumerate(words):
        bucket.append(word)
        gap = 0.0
        if index + 1 < len(words):
            gap = words[index + 1]["start"] - word["end"]
        if _ends_sentence(word["word"]) or len(bucket) >= max_words or gap > 0.45:
            flush()
    flush()

    merged: list[dict] = []
    for card in raw:
        if (
            merged
            and len(merged[-1]["words"]) < 2
            and len(merged[-1]["words"]) + len(card["words"]) <= max_words
            and card["start"] - merged[-1]["end"] < 0.4
            and not _ends_sentence(merged[-1]["words"][-1]["text"])
        ):
            merged[-1]["words"].extend(card["words"])
            merged[-1]["end"] = card["end"]
            continue
        merged.append(card)
    return merged


def _sentences(words: list[dict]) -> list[list[dict]]:
    sentences: list[list[dict]] = []
    bucket: list[dict] = []
    for index, word in enumerate(words):
        bucket.append(word)
        gap = 0.0
        if index + 1 < len(words):
            gap = words[index + 1]["start"] - word["end"]
        if _ends_sentence(word["word"]) or gap > 0.45 or index == len(words) - 1:
            if bucket:
                sentences.append(bucket)
            bucket = []
    return sentences


def _trim_hook(text: str, max_chars: int, max_words: int) -> str:
    parts = text.split()
    parts = parts[:max_words]
    while parts and len(" ".join(parts)) > max_chars:
        parts.pop()
    while parts and normalize_token(parts[-1]) in {"y", "and", "o", "de", "a", "the", "to", "que"}:
        parts.pop()
    return " ".join(parts).strip()


def suggest_hooks(
    words: list[dict],
    language: str,
    max_chars: int = 42,
    max_words: int = 8,
) -> dict:
    greetings = GREETINGS.get(language, set())
    results = RESULT_WORDS.get(language, set())
    ranked: list[tuple[float, str]] = []
    for position, sentence in enumerate(_sentences(words)):
        raw = " ".join(word["word"] for word in sentence)
        tokens = [normalize_token(word["word"]) for word in sentence]
        content = [token for token in tokens if token]
        if not content:
            continue
        if all(token in greetings for token in content):
            continue
        if content[0] in greetings and len(content) < 5:
            continue
        text = _trim_hook(raw, max_chars, max_words)
        if len(text.split()) < 2:
            continue
        score = 0.0
        if position < 3:
            score += 1
        if 4 <= len(text.split()) <= 10:
            score += 2
        if any(token in results for token in content):
            score += 2
        if _NUMBER_RE.search(raw):
            score += 3
        if raw.endswith("?"):
            score += 1
        if content[0] in greetings:
            score -= 2
        ranked.append((score, text))
    ranked.sort(key=lambda item: item[0], reverse=True)
    unique: list[tuple[float, str]] = []
    seen = set()
    for score, text in ranked:
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append((score, text))
    if not unique:
        fallback = _trim_hook(" ".join(word["word"] for word in words), max_chars, max_words)
        return {
            "text": fallback,
            "alternates": [],
            "reason": "fallback_opening",
            "start": 0.0,
            "end": 3.0,
        }
    reason = "early_claim"
    top_tokens = {normalize_token(part) for part in unique[0][1].split()}
    if top_tokens & results:
        reason = "result_word"
    if _NUMBER_RE.search(unique[0][1]):
        reason = "number"
    alternates = [text for _, text in unique[1:3]]
    return {
        "text": unique[0][1],
        "alternates": alternates,
        "reason": reason,
        "start": 0.0,
        "end": 3.0,
    }


def build_timeline(
    words: list[dict],
    duration: float,
    language: str,
    mode: str,
    filler_table: dict,
    min_silence: float,
    padding: float,
    external_silence: list[tuple[float, float]] | None = None,
) -> dict:
    """Build kept ranges.

    `external_silence` comes from auto-editor and is already padded by `--margin`.
    When it is None, silence comes from gaps between words.
    """
    spans = find_filler_spans(words, language, mode, filler_table)
    filler_indexes = {index for span in spans for index in range(span["start_idx"], span["end_idx"] + 1)}
    # If filler detection would erase every word, keep the words and warn upstream.
    if words and len(filler_indexes) >= len(words):
        spans = []
        filler_indexes = set()
    fcuts = filler_cut_intervals(words, spans)
    if external_silence is None:
        scuts = silence_cuts_from_words(words, duration, min_silence, padding)
        engine_note = "words"
    else:
        # auto-editor already inset the cut by --margin. Do not also shrink it
        # to Whisper word edges: those edges often spill into the pause and
        # would put the silence back. A word whose midpoint lands inside a cut
        # is dropped at remap time.
        scuts = merge_intervals(external_silence)
        engine_note = "auto-editor"
    cuts = merge_intervals([*scuts, *fcuts])
    kept = drop_empty_slivers(invert_cuts(duration, cuts), words, filler_indexes)
    ranges = kept_with_dest(kept)
    remapped = remap_words(words, ranges, filler_indexes)
    silence_seconds = sum(end - start for start, end in scuts)
    filler_seconds = sum(end - start for start, end in fcuts)
    removed = sum(end - start for start, end in cuts)
    return {
        "silence_engine": engine_note,
        "silence_cuts": [{"start": a, "end": b} for a, b in scuts],
        "filler_items": [
            {"text": span["text"], "start": span["start"], "end": span["end"], "tier": span["tier"]}
            for span in spans
        ],
        "silence_removed_seconds": silence_seconds,
        "filler_removed_seconds": filler_seconds,
        "removed_seconds": removed,
        "kept_ranges": ranges,
        "words": remapped,
        "output_duration": ranges[-1]["dst_end"] if ranges else 0.0,
    }


def auto_editor_chunks_to_cuts(
    chunks: list[list[float]],
    fps: float,
    min_silence: float,
    margin: float,
) -> list[tuple[float, float]]:
    """Convert an auto-editor v1 timeline into source-time cuts.

    auto-editor 29.3.1 has no minimum-cut flag (`--smooth` is rejected).
    Chunks with speed >= 1000 are the silent pieces it would remove, already
    shortened by `--margin`. Add the margin back to estimate the original
    silence and keep the cut only when that silence is longer than min_silence.
    """
    if fps <= 0:
        return []
    total = chunks[-1][1] if chunks else 0
    cuts: list[tuple[float, float]] = []
    for start, end, speed in chunks:
        if speed < 1000:
            continue
        dur = (end - start) / fps
        if dur <= 0.02:
            continue
        edge = start == 0 or end == total
        implied = dur + (margin if edge else margin * 2)
        if implied > min_silence:
            cuts.append((start / fps, end / fps))
    return cuts


def srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    whole = int(seconds)
    millis = int(round((seconds - whole) * 1000))
    if millis == 1000:
        whole += 1
        millis = 0
    hours, rem = divmod(whole, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def cues_to_srt(cues: list[dict]) -> str:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        text = cue["text"].strip()
        if not text:
            continue
        blocks.append(
            f"{index}\n{srt_timestamp(cue['start'])} --> {srt_timestamp(cue['end'])}\n{text}\n"
        )
    return "\n".join(blocks) + ("\n" if blocks else "")


def segments_to_srt(segments: list[dict]) -> str:
    return cues_to_srt(
        [{"start": seg["start"], "end": seg["end"], "text": seg["text"]} for seg in segments]
    )


def words_to_sentence_cues(words: list[dict]) -> list[dict]:
    cues = []
    for sentence in _sentences(words):
        cues.append(
            {
                "start": sentence[0]["start"],
                "end": sentence[-1]["end"],
                "text": " ".join(word["word"] for word in sentence),
            }
        )
    return cues


def ass_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def hex_to_ass_bgr(color: str) -> str:
    raw = color.strip().lstrip("#")
    if len(raw) != 6:
        raw = "FFFFFF"
    red, green, blue = raw[0:2], raw[2:4], raw[4:6]
    return f"&H00{blue}{green}{red}&".upper()


def build_ass(
    captions: list[dict],
    font_name: str,
    font_size: int,
    color: str,
    highlight: str,
    highlight_enabled: bool,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
) -> str:
    primary = hex_to_ass_bgr(color)
    hi = hex_to_ass_bgr(highlight)
    # Alignment 5 is middle-center. Margins keep the line inside the side safe zone.
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font_name},{font_size},{primary},&H000000FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,8,0,5,80,140,80,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header.rstrip("\n")]
    for card in captions:
        words = card["words"]
        if not words:
            continue
        if not highlight_enabled:
            text = ass_escape(" ".join(word["text"] for word in words))
            lines.append(
                f"Dialogue: 0,{ass_timestamp(card['start'])},{ass_timestamp(card['end'])},Caption,,0,0,0,,{text}"
            )
            continue
        for index, word in enumerate(words):
            start = card["start"] if index == 0 else word["start"]
            end = words[index + 1]["start"] if index + 1 < len(words) else card["end"]
            if end <= start:
                end = start + 0.05
            parts = []
            for inner, token in enumerate(words):
                escaped = ass_escape(token["text"])
                if inner == index:
                    parts.append(f"{{\\c{hi}}}{escaped}{{\\c{primary}}}")
                else:
                    parts.append(escaped)
            text = " ".join(parts)
            lines.append(
                f"Dialogue: 0,{ass_timestamp(start)},{ass_timestamp(end)},Caption,,0,0,0,,{text}"
            )
    return "\n".join(lines) + "\n"
