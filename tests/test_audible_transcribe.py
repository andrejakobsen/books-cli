"""Tests for the Audible ffmpeg cutter + transcriber factory."""

import subprocess

import pytest

from books import audible_obsidian as ao
from books import audible_transcribe as at


def test_check_ffmpeg_raises_when_missing(monkeypatch):
    monkeypatch.setattr(at.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        at.check_ffmpeg()


def test_check_ffmpeg_ok_when_present(monkeypatch):
    monkeypatch.setattr(at.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    at.check_ffmpeg()   # no raise


def test_cut_clip_builds_plain_ffmpeg_command(monkeypatch, tmp_path):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(at.subprocess, "run", fake_run)
    audio = ao.DownloadedAudio(path=tmp_path / "b.aaxc", key=None, iv=None)
    dest = tmp_path / "clip.wav"
    assert at.cut_clip(audio, 60_000, 90_000, dest) == dest
    cmd = calls["cmd"]
    assert cmd[0] == "ffmpeg"
    assert "-ss" in cmd and "60.000" in cmd
    assert "-to" in cmd and "90.000" in cmd
    assert "-audible_key" not in cmd            # no DRM key -> no decrypt flags
    assert str(dest) in cmd


def test_cut_clip_passes_audible_key_iv_when_present(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(at.subprocess, "run",
                        lambda cmd, **k: calls.setdefault("cmd", cmd))
    audio = ao.DownloadedAudio(path=tmp_path / "b.aaxc", key="KEY", iv="IV")
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
    monkeypatch.setattr(at, "_local_transcriber", lambda model: "LOCAL")
    monkeypatch.setattr(at, "_openai_transcriber", lambda model: "OPENAI")
    monkeypatch.setattr(at, "_google_transcriber", lambda: "GOOGLE")
    assert at.make_transcriber("local") == "LOCAL"
    assert at.make_transcriber("openai") == "OPENAI"
    assert at.make_transcriber("google") == "GOOGLE"
