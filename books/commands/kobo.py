#!/usr/bin/env python3
"""Import Kobo highlights & notes into the CSV highlights store.

Reads a KoboReader.sqlite database and, for every book that has highlights or
notes, writes them into the per-book highlights store
(``Data/Highlights/<book_id>.csv``, source ``kobo``), resolving each book to a
``book_id`` via the merged catalog (``Data/books.csv``). A book with no catalog
match is skipped and counted, so run ``merge`` (or ``sync``) first.

Usage:
    books kobo                       # uses the mounted device or the Data/Imports copy
    books kobo --db /path/to/KoboReader.sqlite
    books kobo -o ./Obsidian
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import typer

from books.core import config, store, ui
from books.core.highlights import Highlight, parse_markers
from books.core.matching import BookRef
from books.core.paths import resolve_path

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


def default_kobo_db(output: Path | None) -> Path:
    """Resolve the Kobo DB under <vault>/Data/Imports/kobo.

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
        f"no Kobo device mounted and no KoboReader.sqlite (or *.sqlite) found in {folder}",
        param_hint="--db",
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
    """Write Kobo highlights into the per-book highlights store.

    Each book is resolved to a ``book_id`` via ``store.Catalog`` (built by the
    metadata importers + merge); a book with no catalog match is skipped and
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

    def _ref(r: sqlite3.Row) -> BookRef:
        author = (r["author"] or "").strip()
        return BookRef(
            title=r["book_title"] or "Untitled",
            authors=[author] if author else [],
            isbn=(r["isbn"] or "").strip() or None,
        )

    # Group rows by book, preserving the query's reading order.
    return store.group_and_import(
        vault,
        "kobo",
        rows,
        key_of=lambda r: r["book_title"] or "Untitled",
        ref_of=_ref,
        to_highlight=row_to_highlight,
    )


def kobo_import(
    db: Path | None = typer.Option(
        None,
        "--db",
        "-d",
        help="Path to KoboReader.sqlite. Relative paths resolve against the current "
        "directory. When omitted, a mounted Kobo's DB "
        "(/Volumes/KOBOeReader/.kobo/KoboReader.sqlite) is safely copied into "
        "<vault>/Data/Imports/kobo/ and used; otherwise the existing copy there "
        "is used. [default: <vault>/Data/Imports/kobo/KoboReader.sqlite]",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the "
        "current directory.",
    ),
) -> None:
    """Import Kobo highlights & notes into the CSV highlights store.

    Reads a KoboReader.sqlite database (found in the .kobo folder on your Kobo
    device), opened read-only so the original file is never modified. When no
    --db is given, a mounted Kobo's DB is safely snapshotted (via SQLite's
    read-only backup API — the device file is never modified) into
    <vault>/Data/Imports/kobo/ and read from there; otherwise the existing
    snapshot there is used.

    Highlights are written into the per-book highlights store, resolved to a
    book_id via the merged Data/books.csv (a book with no catalog match is
    skipped and counted — run ``merge``/``sync`` first). --output selects the
    vault (default: the vault from ~/.config/books/config.toml).
    """
    db_path = resolve_path(db, Path.cwd()) if db is not None else default_kobo_db(output)

    vault = config.resolve_vault(output)
    try:
        stats = export_obsidian(db_path, vault)
    except FileNotFoundError as exc:
        raise typer.BadParameter(f"database not found: {db_path}", param_hint="--db") from exc

    skipped = stats.get("skipped", 0)
    skip_note = store.skipped_note(skipped)
    if stats["entries"] == 0:
        if skipped:
            ui.info(
                f"No highlights written{skip_note}. Import these books with "
                f"calibre/goodreads first."
            )
        else:
            ui.warn("No highlights or notes found.")
        return
    ui.info(
        f"Imported {stats['entries']} highlights from {stats['books']} book(s)"
        f"{skip_note} -> {vault}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("kobo")(kobo_import)
