"""Tests for the shared `books` Typer CLI (books.cli).

Exercises the command surface: that every capability is registered, that
`--help` works for the app and each subcommand, that argument/error paths exit
non-zero, and that a couple of commands run end-to-end against tmp fixtures.
"""

from pathlib import Path

from typer.testing import CliRunner

from books.cli import CAPABILITIES, app

runner = CliRunner()


MINIMAL_OPF = """<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
        <dc:title>Napoleon: A Life</dc:title>
        <dc:creator opf:role="aut">Andrew Roberts</dc:creator>
        <dc:subject>History</dc:subject>
    </metadata>
</package>
"""

CSV_HEADER = (
    "Book Id,Title,Author,Author l-f,Additional Authors,ISBN,ISBN13,My Rating,"
    "Publisher,Binding,Number of Pages,Year Published,Original Publication Year,"
    "Date Read,Date Added,Bookshelves,Bookshelves with positions,Exclusive Shelf,"
    "My Review,Spoiler,Private Notes,Read Count,Owned Copies\n"
)
CSV_ROW = (
    '1,"Napoleon: A Life",Andrew Roberts,"Roberts, Andrew",,'
    '"=""0141032014""","=""9780141032016""",5.0,Penguin,Paperback,976,2015,2014,'
    "2026/07/17,2026/05/04,history,history (#1),read,,,,,1,0\n"
)


def _calibre_library(tmp_path: Path) -> Path:
    lib = tmp_path / "Calibre Library"
    book = lib / "Andrew Roberts" / "Napoleon_ A Life (9)"
    book.mkdir(parents=True)
    (book / "metadata.opf").write_text(MINIMAL_OPF, encoding="utf-8")
    return lib


def _goodreads_csv(tmp_path: Path) -> Path:
    p = tmp_path / "goodreads_library_export.csv"
    p.write_text(CSV_HEADER + CSV_ROW, encoding="utf-8")
    return p


# --- Registration / help ----------------------------------------------------


def test_all_capabilities_registered():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "calibre",
        "goodreads",
        "highlighted",
        "kobo",
        "merge",
        "readwise",
        "render",
        "reset",
        "sync",
    ):
        assert command in result.output


def test_capabilities_count_matches_module_list():
    # One command name per registered capability module.
    assert len(CAPABILITIES) == 11


def test_no_args_shows_help():
    result = runner.invoke(app, [])
    # no_args_is_help=True -> prints help; exit code 0 or 2 depending on Typer.
    assert "calibre" in result.output and "goodreads" in result.output


def test_subcommand_help():
    for command in ("calibre", "goodreads", "highlighted", "kobo", "readwise"):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, command
        assert command in result.output or "Usage" in result.output


# --- Error paths ------------------------------------------------------------


def test_calibre_missing_library_errors(tmp_path):
    result = runner.invoke(
        app, ["calibre", "--library", str(tmp_path / "nope"), "--output", str(tmp_path / "out")]
    )
    assert result.exit_code != 0


def test_goodreads_requires_csv_option():
    result = runner.invoke(app, ["goodreads"])
    assert result.exit_code != 0  # --csv is a required option


def test_goodreads_missing_csv_errors(tmp_path):
    result = runner.invoke(
        app,
        ["goodreads", "--csv", str(tmp_path / "missing.csv"), "--output", str(tmp_path / "out")],
    )
    assert result.exit_code != 0


def test_kobo_removed_csv_flag_rejected(tmp_path):
    # kobo is store-only now; the old --csv/--no-csv toggle is gone.
    result = runner.invoke(app, ["kobo", "--no-csv", "--output", str(tmp_path / "vault")])
    assert result.exit_code != 0


def test_kobo_missing_db_errors(tmp_path):
    db = tmp_path / "KoboReader.sqlite"
    result = runner.invoke(app, ["kobo", "--db", str(db), "--output", str(tmp_path / "out")])
    assert result.exit_code != 0


# --- End-to-end -------------------------------------------------------------


def test_calibre_end_to_end(tmp_path):
    from books.core import store

    lib = _calibre_library(tmp_path)
    out = tmp_path / "Obsidian"
    result = runner.invoke(app, ["calibre", "--library", str(lib), "--output", str(out)])
    assert result.exit_code == 0, result.output
    # Writes the calibre metadata layer (no note yet — merge + render do that).
    rows = store.read_layer(out, "calibre")
    assert len(rows) == 1
    assert rows[0].title == "Napoleon: A Life"
    assert rows[0].format == "ebook"
    assert not (out / "Books").exists()


def test_goodreads_end_to_end(tmp_path):
    from books.core import store

    csv_path = _goodreads_csv(tmp_path)
    out = tmp_path / "Obsidian"
    result = runner.invoke(app, ["goodreads", "--csv", str(csv_path), "--output", str(out)])
    assert result.exit_code == 0, result.output
    # Writes the goodreads metadata layer (Paperback binding -> physical).
    rows = store.read_layer(out, "goodreads")
    assert len(rows) == 1
    assert rows[0].title == "Napoleon: A Life"
    assert rows[0].format == "physical"
    assert not (out / "Books").exists()


def _kobo_db(tmp_path: Path) -> Path:
    import sqlite3

    db = tmp_path / "KoboReader.sqlite"
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
        ("b1", 6, "Dune", None, "Frank Herbert", None, None),
    )
    conn.execute(
        "INSERT INTO content VALUES (?,?,?,?,?,?,?)", ("b1-c1", 899, "One", None, None, 1, None)
    )
    conn.execute(
        "INSERT INTO Bookmark VALUES (?,?,?,?,?,?,?,?)",
        (
            "b1",
            "b1-c1",
            0.1,
            "Fear is the mind-killer",
            None,
            "2026-07-01",
            r"span#kobo\.3\.0",
            "false",
        ),
    )
    conn.commit()
    conn.close()
    return db


def test_kobo_obsidian_end_to_end(tmp_path):
    from books.core import store

    db = _kobo_db(tmp_path)
    out = tmp_path / "Obsidian"
    # Seed the catalog (as calibre/goodreads + merge would) so kobo can resolve.
    store.write_books_csv(
        out,
        [store.BookRow(book_id="Dune - Frank Herbert", title="Dune", authors=["Frank Herbert"])],
    )
    result = runner.invoke(app, ["kobo", "--db", str(db), "--output", str(out)])
    assert result.exit_code == 0, result.output
    rows = store.read_highlights(out, "Dune - Frank Herbert")
    assert len(rows) == 1
    assert rows[0].source == "kobo"
    assert rows[0].text == "Fear is the mind-killer"


def _highlighted_csv(tmp_path: Path) -> Path:
    header = (
        "Highlight,Title,Author,ISBN,Collections,Reading Status,"
        "Book Added Date,Location,Tags,Note,Date,Favorite\n"
    )
    row = (
        '"Fear is the mind-killer",Stalin,Stephen Kotkin,9781594203794,,'
        "Reading,2026-07-24,45-49,Stalin,,2026-07-24 11:15:47,N\n"
    )
    p = tmp_path / "Highlights for Stalin.csv"
    p.write_text(header + row, encoding="utf-8")
    return p


def test_highlighted_end_to_end(tmp_path):
    from books.core import store

    csv_path = _highlighted_csv(tmp_path)
    out = tmp_path / "Obsidian"
    store.write_books_csv(
        out,
        [
            store.BookRow(
                book_id="Stalin - Stephen Kotkin",
                title="Stalin",
                authors=["Stephen Kotkin"],
                isbn="9781594203794",
            )
        ],
    )
    result = runner.invoke(app, ["highlighted", "--csv", str(csv_path), "--output", str(out)])
    assert result.exit_code == 0, result.output
    rows = store.read_highlights(out, "Stalin - Stephen Kotkin")
    assert len(rows) == 1
    assert rows[0].source == "highlighted"
    assert rows[0].text == "Fear is the mind-killer"
    assert rows[0].location == "45-49" and rows[0].location_kind == "page"


def _readwise_csv(tmp_path: Path) -> Path:
    p = tmp_path / "readwise-data.csv"
    p.write_text(
        "Highlight,Book Title,Book Author,Amazon Book ID,Note,Color,Tags,"
        "Location Type,Location,Highlighted at,Document tags\n"
        '"A passage.","Stalin (Stalin #1)",Stephen Kotkin,B00INIXPYE,,,,'
        "page,3,2026-07-17 14:00:25+00:00,\n",
        encoding="utf-8",
    )
    return p


def test_readwise_end_to_end(tmp_path):
    from books.core import store

    csv_path = _readwise_csv(tmp_path)
    out = tmp_path / "Obsidian"
    store.write_books_csv(
        out,
        [
            store.BookRow(
                book_id="Stalin - Stephen Kotkin",
                title="Stalin",
                authors=["Stephen Kotkin"],
                amazon="B00INIXPYE",
            )
        ],
    )
    result = runner.invoke(app, ["readwise", "--csv", str(csv_path), "--output", str(out)])
    assert result.exit_code == 0, result.output
    rows = store.read_highlights(out, "Stalin - Stephen Kotkin")
    assert len(rows) == 1
    assert rows[0].source == "readwise"
    assert rows[0].text == "A passage."
    assert rows[0].location == "3" and rows[0].location_kind == "page"
