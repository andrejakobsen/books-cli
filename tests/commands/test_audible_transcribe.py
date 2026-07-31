"""Tests for the Audible ffmpeg cutter + transcriber factory."""

import subprocess

import pytest

from books.commands.audible import transcribe as at


def test_check_ffmpeg_raises_when_missing(monkeypatch):
    monkeypatch.setattr(at.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        at.check_ffmpeg()


def test_cut_clip_builds_plain_ffmpeg_command(monkeypatch, tmp_path):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(at.subprocess, "run", fake_run)
    audio = at.DownloadedAudio(path=tmp_path / "b.aaxc", key=None, iv=None)
    dest = tmp_path / "clip.wav"
    assert at.cut_clip(audio, 60_000, 90_000, dest) == dest
    cmd = calls["cmd"]
    assert cmd[0] == "ffmpeg"
    assert "-ss" in cmd and "60.000" in cmd
    assert "-to" in cmd and "90.000" in cmd
    assert "-audible_key" not in cmd  # no DRM key -> no decrypt flags
    assert str(dest) in cmd


def test_cut_clip_passes_audible_key_iv_when_present(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(at.subprocess, "run", lambda cmd, **k: calls.setdefault("cmd", cmd))
    audio = at.DownloadedAudio(path=tmp_path / "b.aaxc", key="KEY", iv="IV")
    at.cut_clip(audio, 0, 5_000, tmp_path / "c.wav")
    cmd = calls["cmd"]
    assert "-audible_key" in cmd and "KEY" in cmd
    assert "-audible_iv" in cmd and "IV" in cmd
    # decrypt flags must precede -i so ffmpeg applies them to the input
    assert cmd.index("-audible_key") < cmd.index("-i")


def test_make_transcriber_rejects_unknown_backend():
    with pytest.raises(ValueError, match="unknown transcriber"):
        at.make_transcriber("bogus")


def test_make_transcriber_dispatches(monkeypatch):
    monkeypatch.setattr(at, "_local_transcriber", lambda model: lambda p: "LOCAL")
    monkeypatch.setattr(at, "_openai_transcriber", lambda model: lambda p: "OPENAI")
    monkeypatch.setattr(at, "_google_transcriber", lambda: lambda p: "GOOGLE")
    assert at.make_transcriber("local")("x") == "LOCAL"
    assert at.make_transcriber("openai")("x") == "OPENAI"
    assert at.make_transcriber("google")("x") == "GOOGLE"


def test_make_transcriber_cleans_backend_output(monkeypatch):
    monkeypatch.setattr(
        at, "_local_transcriber", lambda model: lambda p: "and then he left. A new day began."
    )
    # leading short lowercase fragment trimmed via clean_transcript
    assert at.make_transcriber("local")("x") == "A new day began."


class TestCleanTranscript:
    def test_trims_short_lowercase_leading_fragment(self):
        text = "and then he left. A new day began."
        assert at.clean_transcript(text) == "A new day began."

    def test_keeps_long_lowercase_leading_fragment(self):
        # 6-word fragment before the first terminator -> likely a real sentence
        text = "well now i really must be going. So I did."
        assert at.clean_transcript(text) == "well now i really must be going. So I did."

    def test_preserves_uppercase_start(self):
        text = "The morning was cold. And then"
        assert at.clean_transcript(text) == "The morning was cold."

    def test_drops_trailing_fragment_after_last_terminator(self):
        text = "She opened the door. Then he star"
        assert at.clean_transcript(text) == "She opened the door."

    def test_trailing_closing_quote_is_kept(self):
        text = '"Run!" she cried. and he st'
        assert at.clean_transcript(text) == '"Run!" she cried.'

    def test_leading_closing_quote_is_skipped(self):
        text = 'talking." She left the room.'
        assert at.clean_transcript(text) == "She left the room."

    def test_no_punctuation_passthrough(self):
        text = "just one continuous fragment with no end"
        assert at.clean_transcript(text) == "just one continuous fragment with no end"

    def test_empty_input(self):
        assert at.clean_transcript("") == ""
        assert at.clean_transcript("   ") == ""

    def test_ellipsis_counts_as_complete(self):
        text = "The story goes on..."
        assert at.clean_transcript(text) == "The story goes on..."

    def test_idempotent(self):
        text = "and then he left. A new day began. Then he wal"
        once = at.clean_transcript(text)
        assert at.clean_transcript(once) == once
        assert once == "A new day began."
