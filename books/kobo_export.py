#!/usr/bin/env python3
"""Export Kobo highlights & notes to per-book CSV files inside a zip archive.

Reads a KoboReader.sqlite database and, for every book that has highlights or
notes, writes a CSV containing:

    Book Title, Author, Chapter Number, Chapter, Highlight, Note,
    Location in Chapter (%), KoboSpan Block (N), KoboSpan Segment (M),
    Date Created

All CSVs are bundled into a single compressed .zip archive. With --obsidian the
highlights are instead written into existing Obsidian book notes (created by the
calibre/goodreads importers); a book with no matching note is skipped and counted.

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

from books.core import config
from books.core.paths import resolve_path
from books.highlights import Highlight, parse_markers, render_highlights
from books.renderers.obsidian import (
    AUTHORS_DIRNAME,
    BookRef,
    VaultIndex,
    link_list,
    render_marked_section,
    safe_filename,
    update_frontmatter,
    write_stub,
    yaml_quote,
)


KOBO_DEVICE_DB = Path("/Volumes/KOBOeReader/.kobo/KoboReader.sqlite")


def _safe_copy_db(src: Path, dest: Path) -> Path:
    """Snapshot a Kobo sqlite DB to *dest* via SQLite's backup API.

    Opens *src* read-only (``mode=ro``) so the device file is never modified, and
    produces a consistent copy even with an active WAL. Returns *dest*.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    src_uri = f"file:{src}?mode=ro"
    source = sqlite3.connect(src_uri, uri=True)
    try:
        target = sqlite3.connect(dest)
        try:
            source.backup(target)
        except BaseException:
            # A backup that fails partway leaves a corrupt snapshot; remove it so
            # a later run doesn't try to read a half-written DB.
            target.close()
            dest.unlink(missing_ok=True)
            raise
        finally:
            target.close()
    finally:
        source.close()
    return dest


def _default_kobo_db(output: Path | None) -> Path:
    """Resolve the Kobo DB under <vault>/.imports/kobo.

    If the Kobo device is mounted (``KOBO_DEVICE_DB`` exists), safely copy its DB
    into the imports folder and use the copy. Otherwise fall back to an existing
    KoboReader.sqlite, then the newest *.sqlite. Raises typer.BadParameter naming
    the folder when nothing is available.
    """
    folder = config.resolve_imports("kobo", output)
    dest = folder / "KoboReader.sqlite"
    if KOBO_DEVICE_DB.is_file():
        return _safe_copy_db(KOBO_DEVICE_DB, dest)
    if dest.is_file():
        return dest
    if folder.is_dir():
        sqlites = list(folder.glob("*.sqlite"))
        if sqlites:
            return max(sqlites, key=lambda p: p.stat().st_mtime)
    raise typer.BadParameter(
        f"no Kobo device mounted and no KoboReader.sqlite (or *.sqlite) found in "
        f"{folder}", param_hint="DB")


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
    """Export Kobo highlights into existing Obsidian book notes.

    Highlights are written only into notes that already exist (created by the
    calibre/goodreads importers); a book with no matching note is skipped and
    counted. Returns {"books": int, "entries": int, "skipped": int}. Raises
    FileNotFoundError if the db is missing.
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
    authors_dir = vault / AUTHORS_DIRNAME

    # Group rows by book, preserving the query's reading order.
    books: dict[str, list] = {}
    for r in rows:
        books.setdefault(r["book_title"] or "Untitled", []).append(r)

    entries = 0
    written = 0
    skipped = 0
    for title, book_rows in books.items():
        author = (book_rows[0]["author"] or "").strip()
        authors = [author] if author else []
        isbn = (book_rows[0]["isbn"] or "").strip() or None
        ref = BookRef(title=title, authors=authors, isbn=isbn)

        dest = index.find(ref)
        if dest is None:
            skipped += 1
            continue

        updates = {
            "title": yaml_quote(title),
            "authors": link_list(authors) if authors else "",
            "isbn": yaml_quote(isbn) if isbn else "",
            "source": "kobo",
            "highlighted": "true",
        }
        base = dest.note_path.read_text(encoding="utf-8")
        dest.note_path.write_text(update_frontmatter(base, updates), encoding="utf-8")

        highlights = [row_to_highlight(r) for r in book_rows]
        text = dest.note_path.read_text(encoding="utf-8")
        text = render_marked_section(
            text, "Highlights", "highlights",
            render_highlights(highlights, chapter_label="Kobo ch."))
        dest.note_path.write_text(text, encoding="utf-8")
        for a in authors:
            write_stub(authors_dir, a, "author")
        entries += len(highlights)
        written += 1

    return {"books": written, "entries": entries, "skipped": skipped}


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
             "directory. When omitted, a mounted Kobo's DB "
             "(/Volumes/KOBOeReader/.kobo/KoboReader.sqlite) is safely copied into "
             "<vault>/.imports/kobo/ and used; otherwise the existing copy there is "
             "used. [default: <vault>/.imports/kobo/KoboReader.sqlite]",
    ),
    input_path: Path | None = typer.Option(
        None, "--input", "-i", help="Alternative way to specify the sqlite path."
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o",
        help="Output path. CSV mode: a .zip [default: ./kobo_highlights.zip]. "
             "Obsidian mode: a vault directory "
             "[default: the vault from ~/.config/books/config.toml]. "
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
             "[default: the vault from ~/.config/books/config.toml].",
    ),
) -> None:
    """Export Kobo highlights & notes to per-book CSV files inside a zip archive.

    INPUT (DB argument, or --input): a KoboReader.sqlite database (found in the
    .kobo folder on your Kobo device). Opened read-only, so the original file is
    never modified. Relative paths resolve against the current directory. When no
    path is given, a mounted Kobo's DB is safely snapshotted (via SQLite's
    read-only backup API — the device file is never modified) into
    <vault>/.imports/kobo/ and read from there; otherwise the existing snapshot
    there is used.

    OUTPUT (--csv, --output): with --csv (the default), writes a .zip archive.
    Relative paths resolve against the current directory; default:
    ./kobo_highlights.zip. It contains one CSV per book that has highlights or
    notes, with columns: Book Title, Author, Chapter Number, Chapter, Highlight,
    Note, Location in Chapter (%), KoboSpan Block (N), KoboSpan Segment (M),
    Date Created. Rows are ordered by book reading order.

    With --obsidian, writes highlights into existing Obsidian book notes instead
    (never creating notes — a book with no matching note is skipped and counted);
    --output is then the vault directory (default: the vault from
    ~/.config/books/config.toml).
    """
    explicit = input_path or db
    if explicit is None:
        db_path = _default_kobo_db(output if obsidian else None)
    else:
        db_path = resolve_path(explicit, Path.cwd())

    if obsidian:
        vault = config.resolve_vault(output)
        try:
            stats = export_obsidian(db_path, vault)
        except FileNotFoundError:
            raise typer.BadParameter(f"database not found: {db_path}", param_hint="DB")
        skipped = stats.get("skipped", 0)
        skip_note = (f" ({skipped} book(s) skipped — no book note)"
                     if skipped else "")
        if stats["entries"] == 0:
            if skipped:
                typer.echo(
                    f"No highlights written{skip_note}. Import these books with "
                    f"calibre/goodreads first.")
            else:
                typer.echo("No highlights or notes found.")
            return
        typer.echo(
            f"Exported {stats['entries']} highlights from {stats['books']} book(s)"
            f"{skip_note} -> {vault}")
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
