#!/usr/bin/env python3
"""`merge` — cluster the source layers into the derived books.csv catalog.

Reads every ``Data/Sources/<source>.csv`` layer, clusters rows into books by
ISBN → Amazon id → author + fuzzy title, coalesces each field by source
precedence, assigns a stable ``book_id``, and writes ``Data/books.csv``. Run it
after the metadata importers and before the highlight importers + ``render``.
"""

from __future__ import annotations

from pathlib import Path

import typer

from books.core import config, store


def merge_command(
    output: Path | None = typer.Option(
        None, "--output", "-o",
        help="Obsidian vault. Defaults to the vault from your config file "
             "(~/.config/books/config.toml). Relative paths resolve against the "
             "current directory.",
    ),
) -> None:
    """Merge the source layers into Data/books.csv."""
    vault = config.resolve_vault(output)
    if not store.sources_dir(vault).is_dir() or not any(
            store.sources_dir(vault).glob("*.csv")):
        raise typer.BadParameter(
            f"no source layers under {store.sources_dir(vault)} — run the "
            f"metadata importers (calibre/goodreads) first",
            param_hint="--output",
        )
    catalog = store.merge(vault)
    typer.echo(f"Merged {len(catalog)} books -> {store.books_csv_path(vault)}")


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("merge")(merge_command)


def main() -> None:
    typer.run(merge_command)


if __name__ == "__main__":
    main()
