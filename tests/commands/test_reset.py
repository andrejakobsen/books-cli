"""Tests for the `reset` derived-store rebuild command."""

from typer.testing import CliRunner

from books.cli import app
from books.commands import reset
from books.core import store


def _seed(vault):
    store.write_books_csv(vault, [store.BookRow(title="X", authors=["A"])])
    store.write_highlights(vault, "X - A", "kobo", [store.HighlightRow(text="hi", source="kobo")])


def test_reset_dry_run_deletes_nothing(tmp_path):
    vault = tmp_path / "vault"
    _seed(vault)

    result = CliRunner().invoke(app, ["reset", "--output", str(vault), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert store.books_csv_path(vault).exists()
    assert store.highlights_dir(vault).exists()


def test_reset_yes_deletes(tmp_path):
    vault = tmp_path / "vault"
    _seed(vault)

    result = CliRunner().invoke(app, ["reset", "--output", str(vault), "--yes"])

    assert result.exit_code == 0, result.output
    assert not store.books_csv_path(vault).exists()
    assert not store.highlights_dir(vault).exists()


def test_reset_non_tty_without_yes_errors(tmp_path):
    vault = tmp_path / "vault"
    _seed(vault)

    # Under CliRunner ui.console.is_terminal is False (not a real terminal).
    result = CliRunner().invoke(app, ["reset", "--output", str(vault)])

    assert result.exit_code != 0
    assert store.books_csv_path(vault).exists()


def test_reset_confirm_yes_deletes(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _seed(vault)
    monkeypatch.setattr(reset, "_is_interactive", lambda: True)
    monkeypatch.setattr(reset.ui, "confirm", lambda *a, **k: True)

    result = CliRunner().invoke(app, ["reset", "--output", str(vault)])

    assert result.exit_code == 0, result.output
    assert not store.books_csv_path(vault).exists()


def test_reset_confirm_no_aborts(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _seed(vault)
    monkeypatch.setattr(reset, "_is_interactive", lambda: True)
    monkeypatch.setattr(reset.ui, "confirm", lambda *a, **k: False)

    result = CliRunner().invoke(app, ["reset", "--output", str(vault)])

    assert result.exit_code == 0, result.output
    assert store.books_csv_path(vault).exists()


def test_reset_noop_when_empty(tmp_path):
    vault = tmp_path / "vault"

    result = CliRunner().invoke(app, ["reset", "--output", str(vault), "--yes"])

    assert result.exit_code == 0, result.output
