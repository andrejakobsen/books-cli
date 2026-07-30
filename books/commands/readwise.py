#!/usr/bin/env python3
"""Add Readwise CSV highlights to the CSV highlights store.

Readwise exports one row per highlight with columns: Highlight, Book Title,
Book Author, Amazon Book ID, Note, Color, Tags, Location Type, Location,
Highlighted at, Document tags. Each row maps into the shared source-agnostic
Highlight model and is written to the per-book highlights store
(Data/Highlights/<book_id>.csv, source "readwise"). Each book is resolved to a
book_id via the merged catalog (Data/books.csv) by Amazon id, then by a strict
Author/Title comparison (using a title with any "(Series #N)" suffix removed); a
book with no catalog match is skipped and counted, so run ``merge``/``sync``
first. The store keeps each source's rows separate; ``render`` turns the store
into the notes.

Standard library only.
"""

from __future__ import annotations

import csv as _csv
import re
from pathlib import Path

import typer

from books.core import config, store, ui
from books.core.highlights import Highlight, split_tag_column
from books.core.matching import BookRef

# Trailing "(Series #N)" or "(Series #N.M)" suffix on a Readwise book title.
_SERIES_RE = re.compile(r"\s*\(([^()]+?)\s+#(\d+(?:\.\d+)?)\)\s*$")


def strip_series(title: str) -> str:
    """Strip a trailing "(Series #N)" suffix off *title* for grouping/matching.

    Series metadata is not persisted by this importer (highlights only), so only
    the cleaned title is returned; a title with no suffix is returned verbatim.
    """
    m = _SERIES_RE.search(title or "")
    if not m:
        return (title or "").strip()
    return (title[: m.start()]).strip()


def row_to_highlight(row: dict) -> Highlight:
    """Map a Readwise CSV row to a source-agnostic Highlight.

    Location Type drives the location label: "page" -> "p." (default), "location"
    -> "loc." (Kindle), anything else (e.g. "order") -> no location recorded.
    """
    loc_type = (row.get("Location Type") or "").strip().lower()
    location = (row.get("Location") or "").strip() or None
    page: str | None = None
    label: str | None = None
    if location and loc_type == "page":
        page = location
    elif location and loc_type == "location":
        page, label = location, "loc."
    links, tags = split_tag_column(row.get("Tags"))
    return Highlight(
        text=(row.get("Highlight") or "").strip(),
        note=(row.get("Note") or "").strip() or None,
        page=page,
        location_label=label,
        date=(row.get("Highlighted at") or "").strip() or None,
        tags=tags,
        links=links,
    )


def parse_csv(path: Path) -> list[dict]:
    """Read the Readwise CSV export into a list of row dicts."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(_csv.DictReader(fh))


def convert(csv_path: Path, output: Path) -> dict:
    """Write every highlight, grouped by book, into the per-book store.

    Each book is resolved to a ``book_id`` via ``store.Catalog`` (built by the
    metadata importers + merge); a book with no catalog match is skipped and
    counted. Returns {"books": int, "entries": int, "skipped": int}.

    A trailing "(Series #N)" suffix is still split off the title for grouping and
    matching, but series/amazon/shelves metadata is no longer persisted -- this
    importer writes highlights only.
    """
    output.mkdir(parents=True, exist_ok=True)

    def _key(row: dict) -> str | None:
        raw_title = (row.get("Book Title") or "").strip()
        if not raw_title:
            return None
        amazon = (row.get("Amazon Book ID") or "").strip() or None
        author = (row.get("Book Author") or "").strip()
        return amazon or f"{strip_series(raw_title)}\x00{author}"

    def _ref(row: dict) -> BookRef:
        author = (row.get("Book Author") or "").strip()
        return BookRef(
            title=strip_series((row.get("Book Title") or "").strip()),
            authors=[author] if author else [],
            amazon=(row.get("Amazon Book ID") or "").strip() or None,
        )

    # Group rows by book (Amazon id when present, else standardized title),
    # preserving CSV order.
    return store.group_and_import(
        output,
        "readwise",
        parse_csv(csv_path),
        key_of=_key,
        ref_of=_ref,
        to_highlight=row_to_highlight,
    )


def readwise_to_obsidian(
    csv: Path | None = typer.Option(
        None,
        "--csv",
        "-c",
        help="Path to a Readwise CSV export, or a folder of exports (the newest "
        "*.csv is used). Defaults to <vault>/Data/Imports/readwise. Relative "
        "paths resolve against the current directory.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
) -> None:
    """Add Readwise CSV highlights to the CSV highlights store.

    Highlights are written into the per-book highlights store for later rendering
    by ``render``; this command never creates book notes itself. Every highlight is
    imported. Books are resolved to a book_id via the merged catalog
    (Data/books.csv) by Amazon id, then by a strict Author/Title comparison (using
    the title with any '(Series #N)' suffix removed); a book with no catalog match
    is skipped and counted, so run ``merge``/``sync`` first. Each source's rows are
    kept separate in the store.
    """
    try:
        csv = config.resolve_csv_arg(csv, "readwise", output)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc), param_hint="--csv") from exc
    output = config.resolve_vault(output)

    if not csv.is_file():
        raise typer.BadParameter(f"CSV not found: {csv}", param_hint="--csv")

    output.mkdir(parents=True, exist_ok=True)
    stats = convert(csv, output)
    no_note = store.skipped_note(stats["skipped"])
    ui.info(
        f"Done. {stats['books']} books{no_note}, {stats['entries']} highlights.\nOutput: {output}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("readwise")(readwise_to_obsidian)
