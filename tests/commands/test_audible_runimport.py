"""The config-driven audible.run_import entry point used by `books import`."""

from books.commands.audible import command as audible_cmd
from books.core.config import AudibleConfig


def test_run_import_dry_run_uses_config_transcriber(tmp_path, monkeypatch):
    calls = {}

    def fake_run(vault, **kw):
        calls.update(kw)
        return {"matched": 0, "new": 0, "est_seconds": 0}

    monkeypatch.setattr(audible_cmd, "run", fake_run)
    monkeypatch.setattr(audible_cmd, "_build_client", lambda quality: object())

    cfg = AudibleConfig(transcriber="openai", select="all")
    stats = audible_cmd.run_import(tmp_path, cfg, dry_run=True)

    assert stats["matched"] == 0
    assert calls["dry_run"] is True
    assert calls["show_cost"] is True  # openai → cost shown
