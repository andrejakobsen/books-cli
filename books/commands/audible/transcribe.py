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
            "to cut and decrypt Audible clips."
        )


def cut_clip(audio: DownloadedAudio, start_ms: int, end_ms: int, dest: Path) -> Path:
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
        "-i",
        str(audio.path),
        "-ss",
        f"{start_ms / 1000:.3f}",
        "-to",
        f"{end_ms / 1000:.3f}",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return dest


_TERMINATORS = ".!?"
# closing punctuation that belongs to the sentence it follows (straight + curly)
_CLOSERS = "\"')]”’»"
# a leading fragment shorter than this (in words) is treated as a mid-sentence catch
_LEADING_FRAGMENT_MAX_WORDS = 5


def _first_terminator(text: str) -> int:
    for i, ch in enumerate(text):
        if ch in _TERMINATORS:
            return i
    return -1


def _last_terminator(text: str) -> int:
    for i in range(len(text) - 1, -1, -1):
        if text[i] in _TERMINATORS:
            return i
    return -1


def clean_transcript(text: str) -> str:
    """Trim dangling partial sentences from the start/end of a clip transcript.

    Clips are cut on time boundaries, so a transcription often begins mid-sentence
    and ends on a half-started one. Two trims are applied to the stripped text:

    - **Leading (only if partial):** if the first letter is lowercase *and* the
      fragment ending at the first ``.``/``!``/``?`` has fewer than five words, drop
      that fragment (plus any trailing closing quote/bracket and whitespace). An
      uppercase start or a long lowercase fragment is kept — it is likely a real
      sentence.
    - **Trailing (always):** drop everything after the last terminator, keeping the
      terminator plus any immediately-following closing quote/bracket.

    Each trim only applies when a terminator exists and the result stays non-empty,
    so a fragment with no terminator at all is returned untouched. Idempotent.
    """
    s = text.strip()
    if not s:
        return s

    # Leading trim.
    first_letter = next((c for c in s if c.isalpha()), "")
    if first_letter and first_letter.islower():
        idx = _first_terminator(s)
        if idx != -1 and len(s[:idx].split()) < _LEADING_FRAGMENT_MAX_WORDS:
            j = idx + 1
            while j < len(s) and (s[j] in _CLOSERS or s[j].isspace()):
                j += 1
            remainder = s[j:]
            if remainder.strip():
                s = remainder

    # Trailing trim.
    idx = _last_terminator(s)
    if idx != -1:
        j = idx + 1
        while j < len(s) and s[j] in _CLOSERS:
            j += 1
        head = s[:j]
        if head.strip():
            s = head

    return s.strip()


def make_transcriber(kind: str, model: str = "small"):
    """Return a ``transcribe(clip_path) -> str`` callable for the chosen backend.

    Every backend's raw output is passed through :func:`clean_transcript` so the
    stored highlight text does not start or end mid-sentence.
    """
    if kind == "local":
        base = _local_transcriber(model)
    elif kind == "openai":
        base = _openai_transcriber(model)
    elif kind == "google":
        base = _google_transcriber()
    else:
        raise ValueError(f"unknown transcriber: {kind!r} (expected 'local', 'openai', or 'google')")
    return lambda path: clean_transcript(base(path))


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
            result = client.audio.transcriptions.create(model="whisper-1", file=fh)
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
