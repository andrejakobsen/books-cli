"""ffmpeg clip-cutting + a pluggable speech-to-text transcriber factory.

ffmpeg decrypts (AAXC via -audible_key/-audible_iv) and cuts each clip in one
pass. The transcriber is chosen at runtime: `local` (faster-whisper, no key,
offline), `openai` (OpenAI audio API, needs OPENAI_API_KEY), or `google`
(SpeechRecognition's free recognizer). Every backend's heavy import is lazy so the
rest of the CLI never loads them; a missing dependency raises a clear install hint.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from books.commands.audible.models import DownloadedAudio

_MISSING = (
    "Audible support needs extra dependencies. Install them with:\n"
    "  uv tool install '.[audible]'    (or: pip install 'books[audible]')"
)


def check_ffmpeg() -> None:
    """Raise RuntimeError with an install hint if ffmpeg is not on PATH."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found on PATH — install it (e.g. `brew install ffmpeg`) "
            "to cut and decrypt Audible clips.")


def cut_clip(audio: DownloadedAudio, start_ms: int, end_ms: int,
             dest: Path) -> Path:
    """Cut [start_ms, end_ms) of *audio* into a 16 kHz mono WAV at *dest*.

    When the source is DRM-protected AAXC, the voucher key/iv are passed as input
    options (before -i) so ffmpeg decrypts on the fly. Returns *dest*.
    """
    cmd = ["ffmpeg", "-nostdin", "-y"]
    if audio.key and audio.iv:
        cmd += ["-audible_key", audio.key, "-audible_iv", audio.iv]
    # -ss/-to are placed AFTER -i (output-side seek) so -to is measured on the
    # original timeline and the cut is frame-accurate. Trade-off: ffmpeg decodes
    # from the file start for each clip, so cuts deep into a long audiobook are
    # slower than input-side seeking would be. Accuracy is preferred here.
    cmd += [
        "-i", str(audio.path),
        "-ss", f"{start_ms / 1000:.3f}",
        "-to", f"{end_ms / 1000:.3f}",
        "-ac", "1", "-ar", "16000",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return dest


def make_transcriber(kind: str, model: str = "small"):
    """Return a ``transcribe(clip_path) -> str`` callable for the chosen backend."""
    if kind == "local":
        return _local_transcriber(model)
    if kind == "openai":
        return _openai_transcriber(model)
    if kind == "google":
        return _google_transcriber()
    raise ValueError(f"unknown transcriber: {kind!r} "
                     "(expected 'local', 'openai', or 'google')")


def _local_transcriber(model: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(_MISSING) from exc
    whisper = WhisperModel(model)

    def transcribe(path: Path) -> str:
        segments, _ = whisper.transcribe(str(path))
        return " ".join(seg.text.strip() for seg in segments).strip()

    return transcribe


def _openai_transcriber(model: str):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(_MISSING) from exc
    client = OpenAI()

    def transcribe(path: Path) -> str:
        with open(path, "rb") as fh:
            result = client.audio.transcriptions.create(
                model="whisper-1", file=fh)
        return (result.text or "").strip()

    return transcribe


def _google_transcriber():
    try:
        import speech_recognition as sr
        from pydub import AudioSegment
    except ImportError as exc:
        raise RuntimeError(_MISSING) from exc
    recognizer = sr.Recognizer()

    def transcribe(path: Path) -> str:
        wav = Path(path).with_suffix(".google.wav")
        AudioSegment.from_file(path).export(wav, format="wav")
        with sr.AudioFile(str(wav)) as source:
            audio = recognizer.record(source)
        try:
            return recognizer.recognize_google(audio).strip()
        except sr.UnknownValueError:
            return ""

    return transcribe
