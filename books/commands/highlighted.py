#!/usr/bin/env python3
"""Add Highlighted app CSV highlights to the CSV highlights store.

Highlighted captures highlights from *physical* books (OCR). This importer maps
each CSV row into the shared source-agnostic Highlight model and writes them to
the per-book highlights store (Data/Highlights/<book_id>.csv, source "highlighted").
Each book is resolved to a book_id via the merged catalog (Data/books.csv); a book
with no catalog match is skipped and counted, so run ``merge``/``sync`` first. The
store keeps each source's rows separate, so highlights accumulate alongside any
other source without clobbering; ``render`` later turns the store into the notes.

CSV columns: Highlight, Title, Author, ISBN, Collections, Reading Status,
Book Added Date, Location, Tags, Note, Date, Favorite. Location is a page number
or range (e.g. "45-49"); Tags is comma-separated and split by the #tag / @link
convention -- an entry prefixed with '@' renders as an Obsidian [[wikilink]],
otherwise as an inline #tag; Collections/Reading Status/Favorite are ignored.

Standard library only.
"""

from __future__ import annotations

import csv as _csv
from pathlib import Path

import typer

from books.core import config, store
from books.core.highlights import Highlight, split_tag_column
from books.core.matching import BookRef
from books.core.paths import resolve_path


def parse_csv(path: Path) -> list[dict]:
    """Read the Highlighted CSV export into a list of row dicts."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(_csv.DictReader(fh))


def resolve_csv_paths(csv_path: Path) -> list[Path]:
    """Resolve --csv into a list of CSV files.

    A file yields ``[csv_path]``; a directory yields its sorted top-level
    ``*.csv`` files (non-recursive). An empty directory raises BadParameter.
    """
    if csv_path.is_dir():
        paths = sorted(csv_path.glob("*.csv"))
        if not paths:
            raise typer.BadParameter(f"no CSV files found in {csv_path}", param_hint="--csv")
        return paths
    return [csv_path]


def row_to_highlight(row: dict) -> Highlight:
    """Map a Highlighted CSV row to a source-agnostic Highlight."""
    links, tags = split_tag_column(row.get("Tags"))
    return Highlight(
        text=(row.get("Highlight") or "").strip(),
        note=(row.get("Note") or "").strip() or None,
        page=(row.get("Location") or "").strip() or None,
        date=(row.get("Date") or "").strip() or None,
        tags=tags,
        links=links,
    )


def convert(csv_path: Path, output: Path) -> dict:
    """Write every highlight, grouped by book, into the per-book store.

    Each book is resolved to a ``book_id`` via ``store.Catalog`` (built by the
    metadata importers + merge); a book with no catalog match is skipped and
    counted. Returns {"books": int, "entries": int, "skipped": int}.
    """
    output.mkdir(parents=True, exist_ok=True)

    def _ref(row: dict) -> BookRef:
        author = (row.get("Author") or "").strip()
        return BookRef(
            title=(row.get("Title") or "").strip(),
            authors=[author] if author else [],
            isbn=(row.get("ISBN") or "").strip() or None,
        )

    # Group rows by book (ISBN when present, else title), preserving CSV order.
    return store.group_and_import(
        output,
        "highlighted",
        parse_csv(csv_path),
        key_of=lambda r: (r.get("ISBN") or "").strip() or (r.get("Title") or "").strip(),
        ref_of=_ref,
        to_highlight=row_to_highlight,
    )


def highlighted_to_obsidian(
    csv: Path | None = typer.Option(
        None,
        "--csv",
        "-c",
        help="Path to a Highlighted CSV export, or a folder of CSV exports (every "
        "top-level *.csv is imported). Defaults to "
        "<vault>/Data/Imports/highlighted. "
        "Relative paths resolve against the current directory.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
) -> None:
    """Add Highlighted CSV highlights to the CSV highlights store.

    Highlights are written into the per-book highlights store for later rendering
    by ``render``; this command never creates book notes itself. Every highlight is
    imported (regardless of reading status). Books are resolved to a book_id via
    the merged catalog (Data/books.csv) by ISBN, then by a strict Author/Title
    comparison; a book with no catalog match is skipped and counted, so run
    ``merge``/``sync`` first. Each source's rows are kept separate in the store.

    When --csv is a folder, every top-level '*.csv' file in it is imported in
    sorted order; a file that fails to parse is skipped and reported.
    """
    if csv is None:
        csv = config.resolve_imports("highlighted", output)
    else:
        csv = resolve_path(csv, Path.cwd())
    output = config.resolve_vault(output)

    if not csv.is_file() and not csv.is_dir():
        raise typer.BadParameter(f"CSV not found: {csv}", param_hint="--csv")

    csv_paths = resolve_csv_paths(csv)

    output.mkdir(parents=True, exist_ok=True)

    totals = {"books": 0, "entries": 0, "skipped": 0}
    skipped = 0
    for path in csv_paths:
        try:
            stats = convert(path, output)
        except Exception as exc:  # noqa: BLE001 - skip and continue on any bad file
            skipped += 1
            typer.echo(f"Skipped {path.name}: {exc}", err=True)
            continue
        totals["books"] += stats["books"]
        totals["entries"] += stats["entries"]
        totals["skipped"] += stats["skipped"]

    files = len(csv_paths)
    files_word = "file" if files == 1 else "files"
    bad_files_note = f" ({skipped} skipped)" if skipped else ""
    no_note = store.skipped_note(totals["skipped"])
    typer.echo(
        f"Done. {files} {files_word}{bad_files_note}, {totals['books']} books{no_note}, "
        f"{totals['entries']} highlights.\n"
        f"Output: {output}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("highlighted")(highlighted_to_obsidian)
