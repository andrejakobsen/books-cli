#!/usr/bin/env python3
"""Export Kobo highlights & notes to per-book CSV files inside a zip archive.

Reads a KoboReader.sqlite database and, for every book that has highlights or
notes, writes a CSV containing:

    Book Title, Author, Chapter Number, Chapter, Highlight, Note,
    Location in Chapter (%), KoboSpan Block (N), KoboSpan Segment (M),
    Date Created

All CSVs are bundled into a single compressed .zip archive. With --obsidian the
highlights are written into an Obsidian vault (flat note + Exports/) instead.

Usage:
    python kobo_export.py                       # uses ~/KoboReader.sqlite
    python kobo_export.py /path/to/KoboReader.sqlite
    python kobo_export.py -i in.sqlite -o kobo_highlights.zip
    python kobo_export.py --obsidian -o ./Obsidian
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
import zipfile
from pathlib import Path

import typer

from booktools import config, resolve_path
from booktools.highlights import Highlight, parse_markers, render_highlights
from booktools.obsidian import (
    BookRef,
    VaultIndex,
    safe_filename,
    with_source,
    write_leaf_with_embed,
    write_stub,
)


# One row per highlight/note. Kobo stores chapters as content rows
# (ContentType=899) whose ContentID is the bookmark's ContentID plus a "-N"
# suffix; the `matched` CTE resolves each bookmark to its chapter row by prefix
# (shortest = closest match). That chapter carries a VolumeIndex (reading order
# in the book), used to sort highlights into book reading order, plus its title.
QUERY = """
WITH matched AS (
    SELECT
        b.VolumeID       AS volume_id,
        b.ChapterProgress AS chapter_progress,
        b.Text           AS highlight,
        b.Annotation     AS note,
        b.DateCreated    AS date_created,
        b.StartContainerPath AS container_path,
        (SELECT ch.ContentID FROM content ch
         WHERE ch.ContentType = 899
           AND ch.ContentID LIKE b.ContentID || '%'
         ORDER BY length(ch.ContentID) LIMIT 1) AS chapter_id
    FROM Bookmark b
    WHERE LOWER(CAST(COALESCE(b.Hidden, 'false') AS TEXT)) NOT IN ('true', '1')
      AND (TRIM(COALESCE(b.Text, '')) <> '' OR TRIM(COALESCE(b.Annotation, '')) <> '')
)
SELECT
    COALESCE(book.Title, book.BookTitle, '') AS book_title,
    COALESCE(book.Attribution, '')           AS author,
    COALESCE(book.ISBN, '')                  AS isbn,
    ch.VolumeIndex                           AS chapter_index,
    COALESCE(ch.Title, '')                   AS chapter,
    m.chapter_progress                       AS chapter_progress,
    m.container_path                         AS container_path,
    COALESCE(m.highlight, '')                AS highlight,
    COALESCE(m.note, '')                     AS note,
    COALESCE(m.date_created, '')             AS date_created
FROM matched m
LEFT JOIN content book ON book.ContentID = m.volume_id
LEFT JOIN content ch   ON ch.ContentID   = m.chapter_id
ORDER BY book_title,
         chapter_index IS NULL, chapter_index,  -- reading order within the book
         m.chapter_progress,
         m.date_created
"""

CSV_HEADER = [
    "Book Title", "Author", "Chapter Number", "Chapter",
    "Highlight", "Note",
    "Location in Chapter (%)", "KoboSpan Block (N)", "KoboSpan Segment (M)",
    "Date Created",
]


def pct(value: float | None) -> str:
    """Format a 0.0-1.0 fraction as a whole-number percentage string ("42")."""
    if value is None:
        return ""
    return str(round(float(value) * 100))


def parse_container(path: str | None) -> tuple[str, str]:
    """Split a Kobo StartContainerPath into (block_index, segment_in_block).

    Paths look like "span#kobo\\.3\\.5" (dots escaped) and reference an injected
    "KoboSpan" element. The first number is the block index within the chapter
    (usually a paragraph, but also headings/list items/etc.); the second is the
    segment (roughly a sentence) within that block. Returns ("", "") when the
    path is missing or unrecognised.
    """
    if not path:
        return "", ""
    nums = re.findall(r"\d+", path.split("kobo", 1)[-1])
    block = nums[0] if len(nums) >= 1 else ""
    segment = nums[1] if len(nums) >= 2 else ""
    return block, segment


def row_to_highlight(row: sqlite3.Row) -> Highlight:
    """Map a Kobo query row to a source-agnostic Highlight."""
    block, segment = parse_container(row["container_path"])
    idx = row["chapter_index"]
    note, links, tags = parse_markers((row["note"] or "").strip() or None)
    return Highlight(
        text=(row["highlight"] or "").strip(),
        note=note,
        chapter_index=None if idx is None else int(idx),
        chapter_title=(row["chapter"] or "").strip() or None,
        progress=None if row["chapter_progress"] is None else float(row["chapter_progress"]),
        block=block or None,
        segment=segment or None,
        date=(row["date_created"] or "").strip() or None,
        tags=tags,
        links=links,
    )


def export_obsidian(db_path: Path, vault: Path) -> dict:
    """Export Kobo highlights into an Obsidian vault (flat note + Exports/).

    Writes a per-book Highlights.md and embeds it in the canonical note. Returns
    {"books": int, "entries": int}. Raises FileNotFoundError if the db is missing.
    """
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(QUERY).fetchall()
    finally:
        conn.close()

    vault.mkdir(parents=True, exist_ok=True)
    index = VaultIndex(vault)
    authors_dir = vault / "Authors"

    # Group rows by book, preserving the query's reading order.
    books: dict[str, list] = {}
    for r in rows:
        books.setdefault(r["book_title"] or "Untitled", []).append(r)

    entries = 0
    for title, book_rows in books.items():
        author = (book_rows[0]["author"] or "").strip()
        authors = [author] if author else []
        isbn = (book_rows[0]["isbn"] or "").strip() or None
        ref = BookRef(title=title, authors=authors, isbn=isbn)

        dest = index.find_or_create(ref)
        highlights = [row_to_highlight(r) for r in book_rows]
        write_leaf_with_embed(
            dest.note_path, dest.export_dir, "Highlights.md",
            with_source("kobo", render_highlights(highlights, chapter_label="Kobo ch.")),
            "Highlights")
        for a in authors:
            write_stub(authors_dir, a, "author")
        entries += len(highlights)

    return {"books": len(books), "entries": entries}


def export(db_path: Path, out_path: Path) -> dict:
    """Export Kobo highlights/notes to per-book CSVs bundled in a zip.

    Returns a stats dict: {"books": int, "entries": int, "files": [(name, count)]}.
    Raises FileNotFoundError if the database is missing.
    """
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    # Read-only connection so we never touch the original database.
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(QUERY).fetchall()
    finally:
        conn.close()

    if not rows:
        return {"books": 0, "entries": 0, "files": []}

    # Group rows by book.
    books: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        title = r["book_title"] or "Untitled"
        books.setdefault(title, []).append(r)

    # De-duplicate CSV filenames across books with the same title.
    used_names: set[str] = set()
    total_entries = 0
    files: list[tuple[str, int]] = []

    with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for title, book_rows in books.items():
            stem = safe_filename(title)[:120]
            fname = f"{stem}.csv"
            n = 2
            while fname.lower() in used_names:
                fname = f"{stem} ({n}).csv"
                n += 1
            used_names.add(fname.lower())

            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(CSV_HEADER)
            for r in book_rows:
                block, segment = parse_container(r["container_path"])
                writer.writerow([
                    r["book_title"],
                    r["author"],
                    "" if r["chapter_index"] is None else int(r["chapter_index"]),
                    r["chapter"],
                    r["highlight"],
                    r["note"],
                    pct(r["chapter_progress"]),
                    block,
                    segment,
                    r["date_created"],
                ])
                total_entries += 1

            # utf-8-sig so titles with accents open cleanly in Excel.
            zf.writestr(fname, buf.getvalue().encode("utf-8-sig"))
            files.append((fname, len(book_rows)))

    return {"books": len(books), "entries": total_entries, "files": files}


def kobo_export(
    db: Path | None = typer.Argument(
        None,
        help="Path to KoboReader.sqlite. Relative paths resolve against the current "
             "directory. [default: KoboReader.sqlite]",
    ),
    input_path: Path | None = typer.Option(
        None, "--input", "-i", help="Alternative way to specify the sqlite path."
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o",
        help="Output path. CSV mode: a .zip [default: ./kobo_highlights.zip]. "
             "Obsidian mode: a vault directory "
             "[default: the vault from ~/.config/booktools/config.toml]. "
             "Relative paths resolve against the current directory.",
    ),
    csv_out: bool = typer.Option(
        True, "--csv",
        help="Export highlights as per-book CSV files bundled in a zip. This is "
             "the default output mode; pass --obsidian to write an Obsidian vault "
             "instead.",
    ),
    obsidian: bool = typer.Option(
        False, "--obsidian",
        help="Write highlights into an Obsidian vault (flat note + Exports/) instead "
             "of CSV/zip. In this mode --output is the vault directory "
             "[default: the vault from ~/.config/booktools/config.toml].",
    ),
) -> None:
    """Export Kobo highlights & notes to per-book CSV files inside a zip archive.

    INPUT (DB argument, or --input): a KoboReader.sqlite database (found in the
    .kobo folder on your Kobo device). Opened read-only, so the original file is
    never modified. Relative paths resolve against the current directory;
    default: ./KoboReader.sqlite.

    OUTPUT (--csv, --output): with --csv (the default), writes a .zip archive.
    Relative paths resolve against the current directory; default:
    ./kobo_highlights.zip. It contains one CSV per book that has highlights or
    notes, with columns: Book Title, Author, Chapter Number, Chapter, Highlight,
    Note, Location in Chapter (%), KoboSpan Block (N), KoboSpan Segment (M),
    Date Created. Rows are ordered by book reading order.

    With --obsidian, writes highlights into an Obsidian vault (flat note + Exports/)
    instead; --output is then the vault directory (default: the vault from
    ~/.config/booktools/config.toml).
    """
    db_path = resolve_path(input_path or db or Path("KoboReader.sqlite"), Path.cwd())

    if obsidian:
        vault = config.resolve_vault(output)
        try:
            stats = export_obsidian(db_path, vault)
        except FileNotFoundError:
            raise typer.BadParameter(f"database not found: {db_path}", param_hint="DB")
        if stats["entries"] == 0:
            typer.echo("No highlights or notes found.")
            return
        typer.echo(
            f"Exported {stats['entries']} highlights from {stats['books']} book(s) "
            f"-> {vault}")
        return

    if not csv_out:
        raise typer.BadParameter(
            "CSV is currently the only non-Obsidian output mode; drop --no-csv "
            "or pass --obsidian.",
            param_hint="--csv",
        )

    out_path = resolve_path(output or Path("kobo_highlights.zip"), Path.cwd())
    try:
        stats = export(db_path, out_path)
    except FileNotFoundError:
        raise typer.BadParameter(f"database not found: {db_path}", param_hint="DB")

    if stats["entries"] == 0:
        typer.echo("No highlights or notes found.")
        return

    for fname, count in stats["files"]:
        typer.echo(f"  {fname}: {count} entries")
    typer.echo(
        f"\nExported {stats['entries']} entries from {stats['books']} book(s) "
        f"-> {out_path}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("kobo")(kobo_export)


def main() -> None:
    """Standalone entry point so the shim script keeps working on its own."""
    typer.run(kobo_export)


if __name__ == "__main__":
    main()
