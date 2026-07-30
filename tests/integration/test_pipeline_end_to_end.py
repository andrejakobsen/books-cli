"""End-to-end integration test for the two-phase pipeline.

Builds synthetic sources for a single book (a Calibre library with a cover, a
Goodreads CSV carrying a review, and a Kobo sqlite with one highlight) and runs
the whole pipeline the way `sync` does:

    calibre → goodreads → merge → kobo → render

then asserts the fully-rendered note: authoritative frontmatter, a materialized
cover + embed, an ``Authors/`` stub, the write-once ``## Review`` (from
Goodreads), and the marked ``## Highlights`` section (from Kobo). Finally it
re-renders and asserts the note bytes are unchanged (idempotence).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from books.cli import app
from books.core import store

runner = CliRunner()

BOOK_ID = "The Deluge - Adam Tooze"
ISBN = "9780141032184"

# A minimal 1x1 JPEG (valid header) so the cover is a real image file.
_JPEG = (
    bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb00430008060607060508070707090908")
    + b"\x00" * 16
    + b"\xff\xd9"
)

OPF = f"""<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
              xmlns:opf="http://www.idpf.org/2007/opf">
        <dc:title>The Deluge: The Great War and the Remaking of Global Order</dc:title>
        <dc:creator opf:role="aut">Adam Tooze</dc:creator>
        <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
        <dc:language>eng</dc:language>
    </metadata>
</package>
"""

GOODREADS_HEADER = (
    "Book Id,Title,Author,Author l-f,Additional Authors,ISBN,ISBN13,My Rating,"
    "Publisher,Binding,Number of Pages,Year Published,Original Publication Year,"
    "Date Read,Date Added,Bookshelves,Bookshelves with positions,Exclusive Shelf,"
    "My Review,Spoiler,Private Notes,Read Count,Owned Copies\n"
)
GOODREADS_ROW = (
    '42,"The Deluge",Adam Tooze,"Tooze, Adam",,'
    f'"=""""","=""{ISBN}""",5.0,Penguin,Paperback,672,2014,2014,'
    "2026/07/17,2026/05/04,history,history (#1),read,"
    '"A magisterial account of the postwar order.",,,1,0\n'
)


def _calibre_library(root: Path) -> Path:
    lib = root / "Calibre Library"
    book = lib / "Adam Tooze" / "The Deluge (1)"
    book.mkdir(parents=True)
    (book / "metadata.opf").write_text(OPF, encoding="utf-8")
    (book / "cover.jpg").write_bytes(_JPEG)
    return lib


def _goodreads_csv(root: Path) -> Path:
    p = root / "goodreads_export.csv"
    p.write_text(GOODREADS_HEADER + GOODREADS_ROW, encoding="utf-8")
    return p


def _kobo_db(root: Path) -> Path:
    db = root / "KoboReader.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE content (
            ContentID TEXT, ContentType INTEGER, Title TEXT, BookTitle TEXT,
            Attribution TEXT, VolumeIndex INTEGER, ISBN TEXT);
        CREATE TABLE Bookmark (
            VolumeID TEXT, ContentID TEXT, ChapterProgress REAL, Text TEXT,
            Annotation TEXT, DateCreated TEXT, StartContainerPath TEXT, Hidden TEXT);
        """
    )
    conn.execute(
        "INSERT INTO content VALUES (?,?,?,?,?,?,?)",
        ("b1", 6, "The Deluge", None, "Adam Tooze", None, ISBN),
    )
    conn.execute(
        "INSERT INTO content VALUES (?,?,?,?,?,?,?)",
        ("b1-c1", 899, "July 1914", None, None, 1, None),
    )
    conn.execute(
        "INSERT INTO Bookmark VALUES (?,?,?,?,?,?,?,?)",
        (
            "b1",
            "b1-c1",
            0.12,
            "The war made the United States the arbiter.",
            "pivotal @Woodrow Wilson #geopolitics",
            "2026-07-01",
            r"span#kobo\.3\.0",
            "false",
        ),
    )
    conn.commit()
    conn.close()
    return db


def _run(args: list[str]) -> None:
    result = runner.invoke(app, args)
    assert result.exit_code == 0, f"{args[0]} failed: {result.output}"


def test_full_pipeline_end_to_end(tmp_path):
    vault = tmp_path / "Vault"
    lib = _calibre_library(tmp_path)
    gr = _goodreads_csv(tmp_path)
    db = _kobo_db(tmp_path)

    # Phase A: metadata layers → merged catalog.
    _run(["calibre", "--library", str(lib), "--output", str(vault)])
    _run(["goodreads", "--csv", str(gr), "--output", str(vault)])
    _run(["merge", "--output", str(vault)])

    # One merged book with the expected id.
    catalog = store.read_books_csv(vault)
    assert [r.book_id for r in catalog] == [BOOK_ID]

    # Phase B: highlights → render.
    _run(["kobo", str(db), "--obsidian", "--output", str(vault)])
    _run(["render", "--output", str(vault)])

    note = vault / "Books" / f"{BOOK_ID}.md"
    assert note.exists()
    text = note.read_text(encoding="utf-8")

    # Frontmatter merged from calibre (isbn/language) + goodreads (format/rating).
    assert "title: The Deluge" in text
    assert f"isbn: '{ISBN}'" in text
    assert "format: physical" in text  # goodreads Paperback wins
    assert "highlighted: true" in text  # kobo highlight flipped it
    assert "reviewed: true" in text  # goodreads review flipped it

    # Cover: staged by calibre, materialized by render, embedded in the body.
    cover = vault / "Data" / "Covers" / f"{BOOK_ID}.jpg"
    assert cover.is_file()
    assert cover.read_bytes() == _JPEG
    assert f"![[Data/Covers/{BOOK_ID}.jpg|150]]" in text
    assert f"cover: '[[Data/Covers/{BOOK_ID}.jpg]]'" in text

    # Author stub created from the catalog.
    assert (vault / "Authors" / "Adam Tooze.md").is_file()

    # Write-once review from Goodreads.
    assert "## Review" in text
    assert "A magisterial account of the postwar order." in text

    # Marked highlights section from Kobo (text + link + tag).
    assert "## Highlights" in text
    assert "%% books:highlights:start %%" in text
    assert "The war made the United States the arbiter." in text
    assert "[[Woodrow Wilson]]" in text
    assert "#geopolitics" in text

    # Idempotence: a second render produces byte-identical output.
    before = note.read_bytes()
    _run(["render", "--output", str(vault)])
    assert note.read_bytes() == before
