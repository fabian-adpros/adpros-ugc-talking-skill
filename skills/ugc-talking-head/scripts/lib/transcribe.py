"""Word-level transcription.

WhisperX is preferred when its CLI is installed. faster-whisper is the
fallback and the path exercised on CPU. Neither engine is reliable about
fillers: pass a short initial_prompt that contains them, and leave VAD off.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .config import FILLER_PROMPTS
from .edit import cues_to_srt, segments_to_srt
from .media import extract_wav
from .util import UGCError, dump_json


def detect_device() -> tuple[str, str]:
    """Return (device, compute_type). CUDA only when CTranslate2 can see a GPU."""
    try:
        import ctranslate2
    except ImportError:
        return "cpu", "int8"
    try:
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def default_model(device: str, override: str | None) -> str:
    if override:
        return override
    return "large-v3" if device == "cuda" else "small"


def _prompt_for(language: str | None) -> str:
    if language in FILLER_PROMPTS:
        return FILLER_PROMPTS[language]
    return FILLER_PROMPTS["auto"]


def whisperx_bin() -> str | None:
    return shutil.which("whisperx")


def _whisperx_help(binary: str) -> str:
    completed = subprocess.run(
        [binary, "--help"],
        text=True,
        capture_output=True,
        check=False,
    )
    return (completed.stdout or "") + (completed.stderr or "")


def transcribe_whisperx(
    wav: Path,
    workdir: Path,
    model: str,
    language: str | None,
    device: str,
    compute_type: str,
) -> dict:
    binary = whisperx_bin()
    if not binary:
        raise UGCError("whisperx is not installed.", "whisperx no está instalado.")
    help_text = _whisperx_help(binary)
    if "--model" not in help_text:
        raise UGCError(
            "whisperx --help did not list --model. Refusing to guess flags.",
            "whisperx --help no mostró --model. No adivino los flags.",
        )
    out_dir = workdir / "whisperx"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [binary, str(wav), "--model", model, "--output_dir", str(out_dir)]
    if "--output_format" in help_text:
        cmd += ["--output_format", "json"]
    if language and "--language" in help_text:
        cmd += ["--language", language]
    if "--device" in help_text:
        cmd += ["--device", device]
    if "--compute_type" in help_text:
        cmd += ["--compute_type", compute_type]
    if "--initial_prompt" in help_text:
        cmd += ["--initial_prompt", _prompt_for(language)]
    # VAD on by default in some builds drops short fillers. Only disable it
    # when the flag we can see in --help exists.
    if "--vad_method" in help_text:
        cmd += ["--vad_method", "silero"]
    completed = subprocess.run(cmd, text=True, capture_output=True, check=False)
    (workdir / "whisperx.command.txt").write_text(" ".join(cmd) + "\n", encoding="utf-8")
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "")[-2000:]
        raise UGCError(
            f"whisperx failed.\n{tail}",
            f"whisperx falló.\n{tail}",
        )
    json_files = sorted(out_dir.glob("*.json"))
    if not json_files:
        raise UGCError(
            "whisperx wrote no JSON.",
            "whisperx no escribió JSON.",
        )
    payload = json.loads(json_files[0].read_text(encoding="utf-8"))
    segments = []
    words = []
    for segment in payload.get("segments", []):
        segments.append(
            {
                "start": float(segment.get("start") or 0),
                "end": float(segment.get("end") or 0),
                "text": (segment.get("text") or "").strip(),
            }
        )
        for word in segment.get("words") or []:
            if word.get("start") is None or word.get("end") is None:
                continue
            token = (word.get("word") or "").strip()
            if not token:
                continue
            words.append(
                {
                    "word": token,
                    "start": float(word["start"]),
                    "end": float(word["end"]),
                    "probability": word.get("score", word.get("probability")),
                }
            )
    lang = (payload.get("language") or language or "auto").lower()
    return _package(
        language=lang,
        engine="whisperx",
        model=model,
        device=device,
        compute_type=compute_type,
        segments=segments,
        words=words,
        duration=_duration(words, segments),
        prompt=_prompt_for(language),
    )


def _load_wav_16k(path: Path):
    """Load the ffmpeg-produced 16 kHz mono WAV as float32.

    faster-whisper 1.2.1 calls av.open(..., metadata_errors=\"ignore\"). PyAV 19
    dropped that keyword. Feeding a numpy array skips that path. ffmpeg already
    decoded the file.
    """
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
        sample_width = handle.getsampwidth()
        frames = handle.readframes(handle.getnframes())
    if channels != 1 or rate != 16000 or sample_width != 2:
        raise UGCError(
            f"Expected 16 kHz mono PCM, got {rate} Hz, {channels} ch, {sample_width * 8} bit.",
            f"Se esperaba PCM mono a 16 kHz y llegó {rate} Hz, {channels} canales.",
        )
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe_faster_whisper(
    wav: Path,
    model: str,
    language: str | None,
    device: str,
    compute_type: str,
    vad_filter: bool,
    beam_size: int,
) -> dict:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise UGCError(
            "faster-whisper is not installed in this Python.",
            "faster-whisper no está instalado en este Python.",
        ) from exc
    audio = _load_wav_16k(wav)
    audio_seconds = float(len(audio) / 16000.0)
    whisper = WhisperModel(model, device=device, compute_type=compute_type)
    prompt = _prompt_for(language)

    def once(active_prompt: str | None) -> tuple[list[dict], list[dict], object]:
        kwargs = {
            "word_timestamps": True,
            "vad_filter": vad_filter,
            "beam_size": beam_size,
            "temperature": 0.0,
            "condition_on_previous_text": True,
            "initial_prompt": active_prompt,
        }
        if language and language != "auto":
            kwargs["language"] = language
        segments_iter, info = whisper.transcribe(audio, **kwargs)
        segments: list[dict] = []
        words: list[dict] = []
        for segment in segments_iter:
            segments.append(
                {
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "text": (segment.text or "").strip(),
                }
            )
            for word in segment.words or []:
                token = (word.word or "").strip()
                if not token:
                    continue
                words.append(
                    {
                        "word": token,
                        "start": float(word.start),
                        "end": float(word.end),
                        "probability": float(word.probability) if word.probability is not None else None,
                    }
                )
        return segments, words, info

    segments, words, info = once(prompt)
    dropped_prompt = False
    # A filler prompt can make the decoder stop early. If the last word lands
    # well before the end of the file, retry without it and keep the longer take.
    if words and audio_seconds > 0 and words[-1]["end"] < audio_seconds * 0.72:
        retry_segments, retry_words, retry_info = once(None)
        if retry_words and retry_words[-1]["end"] > words[-1]["end"] + 0.4:
            segments, words, info = retry_segments, retry_words, retry_info
            prompt = None
            dropped_prompt = True
    detected = (getattr(info, "language", None) or language or "auto").lower()
    probability = getattr(info, "language_probability", None)
    warnings = []
    if dropped_prompt:
        warnings.append(
            "The filler initial_prompt truncated the transcript, so it was retried without that prompt."
        )
    return _package(
        language=detected,
        language_probability=probability,
        engine="faster-whisper",
        model=model,
        device=device,
        compute_type=compute_type,
        segments=segments,
        words=words,
        duration=audio_seconds,
        prompt=prompt,
        warnings=warnings,
    )


def _duration(words: list[dict], segments: list[dict]) -> float:
    if words:
        return float(words[-1]["end"])
    if segments:
        return float(segments[-1]["end"])
    return 0.0


def _package(**kwargs: object) -> dict:
    return dict(kwargs)


def transcribe(
    video: Path,
    workdir: Path,
    engine: str,
    model: str | None,
    language: str | None,
    device_pref: str,
    vad_filter: bool,
    beam_size: int,
) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    wav = workdir / "audio.wav"
    extract_wav(video, wav)
    if device_pref == "auto":
        device, compute = detect_device()
    elif device_pref == "cuda":
        device, compute = "cuda", "float16"
    else:
        device, compute = "cpu", "int8"
    chosen_model = default_model(device, model)
    lang = None if not language or language == "auto" else language
    order = ["whisperx", "faster-whisper"] if engine == "auto" else [engine]
    errors: list[str] = []
    result = None
    for name in order:
        try:
            if name == "whisperx":
                if engine == "auto" and not whisperx_bin():
                    errors.append("whisperx not installed")
                    continue
                result = transcribe_whisperx(wav, workdir, chosen_model, lang, device, compute)
            elif name == "faster-whisper":
                result = transcribe_faster_whisper(
                    wav, chosen_model, lang, device, compute, vad_filter, beam_size
                )
            else:
                raise UGCError(
                    f"Unknown transcription engine: {name}",
                    f"Motor de transcripción desconocido: {name}",
                )
            break
        except UGCError as exc:
            errors.append(exc.en)
            if engine != "auto":
                raise
            result = None
    if result is None:
        raise UGCError(
            "No transcription engine succeeded. " + " | ".join(errors),
            "Ningún motor de transcripción funcionó. " + " | ".join(errors),
        )
    if not result["words"]:
        raise UGCError(
            "Transcription produced no words. Check the audio and the language.",
            "La transcripción no produjo palabras. Revisa el audio y el idioma.",
        )
    result["source"] = str(video.resolve())
    result["warnings"] = list(result.get("warnings") or [])
    if engine == "auto" and result["engine"] != "whisperx":
        result["warnings"].append(
            "WhisperX was not used (" + "; ".join(errors) + "). faster-whisper produced the words."
        )
    words_path = workdir / "words.json"
    dump_json(words_path, result)
    (workdir / "raw.srt").write_text(segments_to_srt(result["segments"]), encoding="utf-8")
    (workdir / "transcript.txt").write_text(
        " ".join(word["word"] for word in result["words"]) + "\n",
        encoding="utf-8",
    )
    # Sentence SRT is raw.srt. Also keep a word-level SRT for debugging.
    word_cues = [
        {"start": word["start"], "end": word["end"], "text": word["word"]} for word in result["words"]
    ]
    (workdir / "words.srt").write_text(cues_to_srt(word_cues), encoding="utf-8")
    return result
