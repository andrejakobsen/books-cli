import typer
from typer.testing import CliRunner

from books.commands import merge
from books.core import store


def _invoke(args):
    """Invoke the (now-unregistered) merge command via a local Typer app."""
    local = typer.Typer()
    merge.register(local)
    return CliRunner().invoke(local, args)


def test_merge_command_builds_books_csv(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(
        vault,
        "calibre",
        [
            store.BookRow(
                title="The Deluge", authors=["Adam Tooze"], format="ebook", isbn="9780141032184"
            )
        ],
    )

    result = _invoke(["--output", str(vault)])
    assert result.exit_code == 0, result.output

    rows = store.read_books_csv(vault)
    assert len(rows) == 1
    assert rows[0].book_id == "The Deluge - Adam Tooze"


def test_merge_command_errors_without_layers(tmp_path):
    result = _invoke(["--output", str(tmp_path / "vault")])
    assert result.exit_code != 0
