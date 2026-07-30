"""Tests for the shared `books` Typer CLI (books.cli).

Exercises the command surface: that every capability is registered, that
removed commands are gone, and that `--help` works for the app and each
subcommand.
"""

from typer.testing import CliRunner

from books.cli import app

runner = CliRunner()


# --- Registration / help ----------------------------------------------------


def test_all_capabilities_registered():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("import", "export", "reset"):
        assert command in result.output


def test_removed_commands_are_gone():
    result = runner.invoke(app, ["--help"])
    for command in (
        "calibre",
        "goodreads",
        "merge",
        "kobo",
        "highlighted",
        "readwise",
        "audible",
        "covers",
        "render",
        "sync",
    ):
        assert command not in result.output


def test_capabilities_count_matches_module_list():
    from books.cli import CAPABILITIES

    assert len(CAPABILITIES) == 3


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    # no_args_is_help=True -> prints help; exit code 0 or 2 depending on Typer.
    assert "import" in result.output and "export" in result.output


def test_subcommand_help():
    for command in ("import", "export", "reset"):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, command
        assert command in result.output or "Usage" in result.output
