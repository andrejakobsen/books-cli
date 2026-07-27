#!/usr/bin/env python3
"""Add Highlighted app CSV highlights to existing Obsidian book notes.

Highlighted captures highlights from *physical* books (OCR). This importer maps
each CSV row into the shared source-agnostic Highlight model and embeds them under
a marker-wrapped "## Highlights" heading of the matching book note. It only
enriches notes created by the calibre/goodreads importers -- it never creates book
notes. Books are matched to existing notes by ISBN, then by a strict Author/Title
comparison; a book with no matching note is skipped and counted. Highlights thus
accumulate alongside any Calibre/Goodreads data without clobbering.

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

from books import config, resolve_path
from books.highlights import Highlight, render_highlights, split_tag_column
from books.obsidian import (
    AUTHORS_DIRNAME,
    BookRef,
    VaultIndex,
    link_list,
    render_marked_section,
    update_frontmatter,
    write_stub,
    yaml_quote,
)


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
            raise typer.BadParameter(
                f"no CSV files found in {csv_path}", param_hint="--csv")
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
    """Import every highlight, grouped by book, into the Obsidian vault."""
    stats = {"books": 0, "entries": 0, "authors": set(), "skipped": 0}
    index = VaultIndex(output)
    authors_dir = output / AUTHORS_DIRNAME

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
        dest = index.find(ref)
        if dest is None:
            stats["skipped"] += 1
            continue

        base = dest.note_path.read_text(encoding="utf-8")
        dest.note_path.write_text(update_frontmatter(base, {
            "title": yaml_quote(group["title"]),
            "authors": link_list(authors) if authors else "",
            "isbn": yaml_quote(group["isbn"]) if group["isbn"] else "",
            "source": "highlighted",
            "highlighted": "true",
        }), encoding="utf-8")

        highlights = [row_to_highlight(r) for r in group["rows"]]
        text = dest.note_path.read_text(encoding="utf-8")
        text = render_marked_section(
            text, "Highlights", "highlights", render_highlights(highlights))
        dest.note_path.write_text(text, encoding="utf-8")

        for author in authors:
            write_stub(authors_dir, author, "author")
            stats["authors"].add(author)
        stats["books"] += 1
        stats["entries"] += len(highlights)

    return stats


def highlighted_to_obsidian(
    csv: Path | None = typer.Option(
        None,
        "--csv", "-c",
        help="Path to a Highlighted CSV export, or a folder of CSV exports (every "
             "top-level *.csv is imported). Defaults to <vault>/.imports/highlighted. "
             "Relative paths resolve against the current directory.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output", "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
             "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
) -> None:
    """Add Highlighted CSV highlights to existing Obsidian book notes.

    Highlights enrich book notes created by the calibre/goodreads importers; this
    command never creates book notes itself. Every highlight is imported
    (regardless of reading status) and embedded under a marker-wrapped
    '## Highlights' heading. Books are matched to existing notes by ISBN, then by
    a strict Author/Title comparison; a book with no matching note is skipped and
    counted. Existing notes are never overwritten.

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

    totals = {"books": 0, "entries": 0, "authors": set(), "skipped": 0}
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
        totals["authors"].update(stats["authors"])
        totals["skipped"] += stats["skipped"]

    files = len(csv_paths)
    files_word = "file" if files == 1 else "files"
    skipped_note = f" ({skipped} skipped)" if skipped else ""
    no_note = (f" ({totals['skipped']} skipped — no book note)"
               if totals["skipped"] else "")
    typer.echo(
        f"Done. {files} {files_word}{skipped_note}, {totals['books']} books{no_note}, "
        f"{totals['entries']} highlights, {len(totals['authors'])} authors.\n"
        f"Output: {output}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("highlighted")(highlighted_to_obsidian)


def main() -> None:
    """Standalone entry point so the shim script keeps working on its own."""
    typer.run(highlighted_to_obsidian)


if __name__ == "__main__":
    main()
