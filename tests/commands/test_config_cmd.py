"""Tests for the `books config export` command (registration + off-tty flow)."""

from typer.testing import CliRunner

from books.cli import app
from books.core import config

runner = CliRunner()


def test_config_group_registered():
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0
    assert "export" in result.output


def test_export_help():
    result = runner.invoke(app, ["config", "export", "--help"])
    assert result.exit_code == 0


def test_offtty_selection_writes_config(monkeypatch, tmp_path):
    # Point config + templates at a temp dir via XDG_CONFIG_HOME.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # CliRunner is non-tty, so the command takes the numbered fallback path.
    result = runner.invoke(app, ["config", "export"], input="blockquote\n")
    assert result.exit_code == 0
    cfg = config.load_config(config.config_path())
    assert cfg.export.obsidian.highlights_template.endswith("blockquote.md.jinja")


def test_offtty_default_selects_first(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Empty input -> accept the default (first template alphabetically).
    result = runner.invoke(app, ["config", "export"], input="\n")
    assert result.exit_code == 0
    cfg = config.load_config(config.config_path())
    assert cfg.export.obsidian.highlights_template.endswith(".md.jinja")
