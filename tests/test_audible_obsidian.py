"""Tests for the Audible clips importer."""

from pathlib import Path

from typer.testing import CliRunner

from books import audible_obsidian as ao
from books.cli import app

runner = CliRunner()


def test_command_is_registered():
    result = runner.invoke(app, ["audible", "--help"])
    assert result.exit_code == 0, result.output
    assert "audible" in result.output.lower()
