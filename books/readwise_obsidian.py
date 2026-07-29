#!/usr/bin/env python3
"""Add Readwise CSV highlights to existing Obsidian book notes.

Readwise exports one row per highlight with columns: Highlight, Book Title,
Book Author, Amazon Book ID, Note, Color, Tags, Location Type, Location,
Highlighted at, Document tags. Each row maps into the shared source-agnostic
Highlight model and is embedded under a marker-wrapped "## Highlights" heading of
the matching book note. It only enriches notes created by the calibre/goodreads
importers -- it never creates book notes. Books are matched to existing notes by
Amazon id, then by a strict Author/Title comparison (using a title with any
"(Series #N)" suffix removed); a book with no matching note is skipped and
counted. Highlights thus accumulate alongside Calibre/Goodreads data without
clobbering.

Standard library only.
"""

from __future__ import annotations

import csv as _csv
import re
from pathlib import Path

import typer

from books.core import config
from books.core.highlights import Highlight, split_tag_column
from books.renderers.obsidian import (
    AUTHORS_DIRNAME,
    BookRef,
    VaultIndex,
    link_list,
    plain_list,
    render_highlights,
    render_marked_section,
    update_frontmatter,
    write_stub,
    yaml_quote,
)

# Trailing "(Series #N)" or "(Series #N.M)" suffix on a Readwise book title.
_SERIES_RE = re.compile(r"\s*\(([^()]+?)\s+#(\d+(?:\.\d+)?)\)\s*$")


def split_series(title: str) -> tuple[str, str | None, str | None]:
    """Split a trailing "(Series #N)" off *title*.

    Returns (clean_title, series_name, series_index). When no suffix is present
    the title is returned verbatim with (None, None) for the series fields.
    """
    m = _SERIES_RE.search(title or "")
    if not m:
        return (title or "").strip(), None, None
    clean = (title[: m.start()]).strip()
    return clean, m.group(1).strip(), m.group(2).strip()


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
    """Import every highlight, grouped by book, into the Obsidian vault."""
    stats = {"books": 0, "entries": 0, "authors": set(), "skipped": 0}
    index = VaultIndex(output)
    authors_dir = output / AUTHORS_DIRNAME

    # Group rows by book (Amazon id when present, else standardized title),
    # preserving CSV order.
    groups: dict[str, dict] = {}
    for row in parse_csv(csv_path):
        raw_title = (row.get("Book Title") or "").strip()
        if not raw_title:
            continue
        title, series, series_index = split_series(raw_title)
        amazon = (row.get("Amazon Book ID") or "").strip() or None
        author = (row.get("Book Author") or "").strip()
        doc_tags = [t.strip() for t in (row.get("Document tags") or "").split(",")
                    if t.strip()]
        key = amazon or f"{title}\x00{author}"
        group = groups.setdefault(key, {
            "title": title, "author": author, "amazon": amazon,
            "series": series, "series_index": series_index,
            "shelves": doc_tags, "rows": []})
        group["rows"].append(row)

    for group in groups.values():
        authors = [group["author"]] if group["author"] else []
        ref = BookRef(title=group["title"], authors=authors, amazon=group["amazon"])
        dest = index.find(ref)
        if dest is None:
            stats["skipped"] += 1
            continue

        updates = {
            "title": yaml_quote(group["title"]),
            "authors": link_list(authors) if authors else "",
            "amazon": yaml_quote(group["amazon"]) if group["amazon"] else "",
            "shelves": plain_list(group["shelves"]) if group["shelves"] else "",
            "source": "readwise",
            "highlighted": "true",
        }
        if group["series"]:
            updates["series"] = yaml_quote(group["series"])
        if group["series_index"]:
            updates["series_index"] = group["series_index"]
        base = dest.note_path.read_text(encoding="utf-8")
        dest.note_path.write_text(update_frontmatter(base, updates), encoding="utf-8")

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


def readwise_to_obsidian(
    csv: Path | None = typer.Option(
        None,
        "--csv", "-c",
        help="Path to a Readwise CSV export, or a folder of exports (the newest "
             "*.csv is used). Defaults to <vault>/.imports/readwise. Relative "
             "paths resolve against the current directory.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output", "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
             "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
) -> None:
    """Add Readwise CSV highlights to existing Obsidian book notes.

    Highlights enrich book notes created by the calibre/goodreads importers; this
    command never creates book notes itself. Every highlight is imported and
    embedded under a marker-wrapped '## Highlights' heading. Books are matched to
    existing notes by Amazon id, then by a strict Author/Title comparison (using
    the title with any '(Series #N)' suffix removed); a book with no matching note
    is skipped and counted. Existing notes are never overwritten.
    """
    try:
        csv = config.resolve_csv_arg(csv, "readwise", output)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc), param_hint="--csv")
    output = config.resolve_vault(output)

    if not csv.is_file():
        raise typer.BadParameter(f"CSV not found: {csv}", param_hint="--csv")

    output.mkdir(parents=True, exist_ok=True)
    stats = convert(csv, output)
    no_note = (f" ({stats['skipped']} skipped — no book note)"
               if stats["skipped"] else "")
    typer.echo(
        f"Done. {stats['books']} books{no_note}, {stats['entries']} highlights, "
        f"{len(stats['authors'])} authors.\nOutput: {output}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("readwise")(readwise_to_obsidian)


def main() -> None:
    """Standalone entry point so the shim script keeps working on its own."""
    typer.run(readwise_to_obsidian)


if __name__ == "__main__":
    main()
