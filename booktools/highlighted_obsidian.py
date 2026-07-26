#!/usr/bin/env python3
"""Convert a Highlighted app CSV export into an Obsidian book vault.

Highlighted captures highlights from *physical* books (OCR). This importer maps
each CSV row into the shared source-agnostic Highlight model and writes a per-book
"Highlights.md" under "Exports/<Author>/<Title>/", embedded into the flat note
under a "## Highlights" heading. Books are matched to existing notes by ISBN, then
by a strict Author/Title comparison, so highlights accumulate alongside any
Calibre/Goodreads data without clobbering.

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

from booktools import config, resolve_path
from booktools.highlights import Highlight, render_highlights, split_tag_column
from booktools.obsidian import (
    BookRef,
    VaultIndex,
    link_list,
    update_frontmatter,
    with_source,
    write_leaf_with_embed,
    write_stub,
    yaml_quote,
)


def parse_csv(path: Path) -> list[dict]:
    """Read the Highlighted CSV export into a list of row dicts."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(_csv.DictReader(fh))


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
    """Import every highlight, grouped by book, into the Obsidian vault."""
    stats = {"books": 0, "entries": 0, "authors": set()}
    index = VaultIndex(output)
    authors_dir = output / "Authors"

    # Group rows by book (ISBN when present, else title), preserving CSV order.
    groups: dict[str, dict] = {}
    for row in parse_csv(csv_path):
        title = (row.get("Title") or "").strip()
        if not title:
            continue
        isbn = (row.get("ISBN") or "").strip() or None
        author = (row.get("Author") or "").strip()
        key = isbn or title
        group = groups.setdefault(
            key, {"title": title, "author": author, "isbn": isbn, "rows": []})
        group["rows"].append(row)

    for group in groups.values():
        authors = [group["author"]] if group["author"] else []
        ref = BookRef(title=group["title"], authors=authors, isbn=group["isbn"])
        dest = index.find_or_create(ref)

        base = dest.note_path.read_text(encoding="utf-8")
        dest.note_path.write_text(update_frontmatter(base, {
            "title": yaml_quote(group["title"]),
            "authors": link_list(authors) if authors else "",
            "isbn": yaml_quote(group["isbn"]) if group["isbn"] else "",
        }), encoding="utf-8")

        highlights = [row_to_highlight(r) for r in group["rows"]]
        write_leaf_with_embed(
            dest.note_path, dest.export_dir, "Highlights.md",
            with_source("highlighted", render_highlights(highlights)), "Highlights")

        for author in authors:
            write_stub(authors_dir, author, "author")
            stats["authors"].add(author)
        stats["books"] += 1
        stats["entries"] += len(highlights)

    return stats


def highlighted_to_obsidian(
    csv: Path = typer.Option(
        ...,
        "--csv", "-c",
        help="Path to the Highlighted CSV export. Relative paths resolve against the current directory.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output", "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
             "(~/.config/booktools/config.toml). Relative paths resolve against the current directory.",
    ),
) -> None:
    """Convert a Highlighted CSV export into Obsidian book notes.

    Every highlight is imported (regardless of reading status). For each book a
    'Highlights.md' is written into 'Exports/<Author>/<Title>/' and embedded into
    the flat note under a '## Highlights' heading; books are matched to existing
    notes by ISBN, then by a strict Author/Title comparison. Existing notes are
    never overwritten.
    """
    csv = resolve_path(csv, Path.cwd())
    output = config.resolve_vault(output)

    if not csv.is_file():
        raise typer.BadParameter(f"CSV not found: {csv}", param_hint="--csv")

    output.mkdir(parents=True, exist_ok=True)
    stats = convert(csv, output)
    typer.echo(
        f"Done. {stats['books']} books, {stats['entries']} highlights, "
        f"{len(stats['authors'])} authors.\nOutput: {output}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("highlighted")(highlighted_to_obsidian)


def main() -> None:
    """Standalone entry point so the shim script keeps working on its own."""
    typer.run(highlighted_to_obsidian)


if __name__ == "__main__":
    main()
