"""Tests for the Goodreads -> CSV store writer."""

from pathlib import Path

from books.commands import goodreads as gr
from books.core import store

HEADER = (
    "Book Id,Title,Author,Author l-f,Additional Authors,ISBN,ISBN13,My Rating,"
    "Publisher,Binding,Number of Pages,Year Published,Original Publication Year,"
    "Date Read,Date Added,Bookshelves,Bookshelves with positions,Exclusive Shelf,"
    "My Review,Spoiler,Private Notes,Read Count,Owned Copies\n"
)

# A read book with review, a to-read book, and a currently-reading book.
ROWS = (
    '1,"Napoleon: A Life",Andrew Roberts,"Roberts, Andrew",,'
    '"=""0141032014""","=""9780141032016""",5.0,Penguin,Paperback,976,2015,2014,'
    "2026/07/17,2026/05/04,history,history (#1),read,"
    '"Great book.<br/><br/>Loved it.",,note-to-self,1,0\n'
    '2,"The Cold War: A New History",John Lewis Gaddis,"Gaddis, John Lewis",,'
    '"=""0143038273""","=""9780143038276""",0,Penguin,Paperback,352,2006,2005,,'
    "2026/07/14,to-read,to-read (#2),to-read,,,,0,0\n"
    '3,"Stalin: Paradoxes of Power",Stephen Kotkin,"Kotkin, Stephen",,'
    '"=""1594203792""","=""9781594203794""",0,Penguin,Hardcover,976,2014,2014,,'
    "2026/04/30,,,currently-reading,,,,1,0\n"
)


def write_csv(tmp_path: Path) -> Path:
    p = tmp_path / "goodreads_library_export.csv"
    p.write_text(HEADER + ROWS, encoding="utf-8")
    return p


# --- Pure parsing helpers ---------------------------------------------------


def test_parse_csv_fields(tmp_path):
    books = gr.parse_csv(write_csv(tmp_path))
    assert len(books) == 3
    nap = books[0]
    assert nap.title == "Napoleon: A Life"
    assert nap.book_id == "1"
    assert nap.authors == ["Andrew Roberts"]
    assert nap.isbn13 == "9780141032016"
    assert nap.isbn == "0141032014"
    assert nap.rating == 5
    assert nap.pages == "976"
    assert nap.status == "read"
    assert nap.date_read == "2026-07-17"
    assert nap.date_added == "2026-05-04"
    assert nap.shelves == ["history"]
    assert "Great book." in nap.review

    unrated = books[1]
    assert unrated.rating is None  # My Rating 0 -> unrated
    assert unrated.status == "to-read"

    reading = books[2]
    assert reading.status == "reading"  # currently-reading normalized


def test_normalization_helpers():
    from books.core import matching as m

    assert m.norm_isbn('="9780698176287"') == "9780698176287"
    assert m.norm_title("The Cold War: A New History") == m.norm_title(
        "The Cold War - A New History"
    )
    assert m.author_key("Terry Martin") == m.author_key("Terry L. Martin")
    assert m.author_key("Roberts, Andrew") == m.author_key("Andrew Roberts")
    assert m.author_key("Broué, Pierre") == m.author_key("Pierre Broue")


def test_norm_format_maps_bindings():
    assert gr._norm_format("Paperback") == "physical"
    assert gr._norm_format("Hardcover") == "physical"
    assert gr._norm_format("Mass Market Paperback") == "physical"
    assert gr._norm_format("Kindle Edition") == "ebook"
    assert gr._norm_format("ebook") == "ebook"
    assert gr._norm_format("Audiobook") == "audiobook"
    assert gr._norm_format(None) == "physical"  # unknown/missing -> physical
    assert gr._norm_format("") == "physical"


# --- CSV store writer -------------------------------------------------------

_CSV = (
    "Title,Author,Additional Authors,ISBN,ISBN13,My Rating,Publisher,"
    "Number of Pages,Year Published,Binding,Date Read,Date Added,Exclusive Shelf,"
    "Bookshelves,My Review,Private Notes,Book Id\n"
    'The Deluge,Adam Tooze,,="",="9780141032184",4,Penguin,720,2014,Paperback,'
    "2020/01/02,2019/12/01,read,history,Great book,,12345\n"
    'Wanted,Some Author,,="",="",0,,,,,,,to-read,wishlist,,,999\n'
)


def _write_csv(tmp_path: Path) -> Path:
    p = tmp_path / "goodreads.csv"
    p.write_text(_CSV, encoding="utf-8")
    return p


def test_goodreads_writes_layer_for_every_shelf(tmp_path):
    vault = tmp_path / "vault"
    stats = gr.convert(_write_csv(tmp_path), vault)

    rows = {r.title: r for r in store.read_layer(vault, "goodreads")}
    assert set(rows) == {"The Deluge", "Wanted"}  # to-read included
    assert stats["books"] == 2


def test_goodreads_row_fields_and_review(tmp_path):
    vault = tmp_path / "vault"
    gr.convert(_write_csv(tmp_path), vault)

    row = next(r for r in store.read_layer(vault, "goodreads") if r.title == "The Deluge")
    assert row.authors == ["Adam Tooze"]
    assert row.isbn == "9780141032184"
    assert row.rating == "4"
    assert row.format == "physical"
    assert row.shelves == ["history"]
    assert row.review == "Great book"
    assert row.goodreads == "https://www.goodreads.com/book/show/12345"
    assert row.date_read == "2020-01-02"


def test_goodreads_unrated_book_has_empty_rating(tmp_path):
    vault = tmp_path / "vault"
    gr.convert(_write_csv(tmp_path), vault)
    row = next(r for r in store.read_layer(vault, "goodreads") if r.title == "Wanted")
    assert row.rating == ""  # My Rating 0 -> unrated -> ""
    assert row.shelves == ["wishlist"]


def test_goodreads_keeps_review_and_private_notes_as_separate_data(tmp_path):
    # The importer is a pure data writer: review and private notes are stored
    # verbatim in their own columns; the renderer composes the markdown section.
    vault = tmp_path / "vault"
    (tmp_path / "pn.csv").write_text(
        "Title,Author,My Review,Private Notes,Book Id\n"
        "The Deluge,Adam Tooze,Great book,secret thoughts,1\n",
        encoding="utf-8",
    )
    gr.convert(tmp_path / "pn.csv", vault)
    row = store.read_layer(vault, "goodreads")[0]
    assert row.review == "Great book"
    assert row.private_notes == "secret thoughts"


def test_goodreads_skips_titleless_or_authorless(tmp_path):
    vault = tmp_path / "vault"
    (tmp_path / "g.csv").write_text("Title,Author,Book Id\n,,1\nOnly Title,,2\n", encoding="utf-8")
    stats = gr.convert(tmp_path / "g.csv", vault)
    assert stats["skipped"] == 2
    assert store.read_layer(vault, "goodreads") == []


def test_goodreads_rerun_replaces_layer(tmp_path):
    vault = tmp_path / "vault"
    gr.convert(_write_csv(tmp_path), vault)
    gr.convert(_write_csv(tmp_path), vault)  # re-run
    assert len(store.read_layer(vault, "goodreads")) == 2  # not duplicated


# --- CLI wiring -------------------------------------------------------------


def _minimal_goodreads_csv(path):
    path.write_text(
        "Title,Author,ISBN,ISBN13,My Rating,Average Rating,Number of Pages,"
        "Original Publication Year,Date Read,Date Added,Bookshelves,"
        "Exclusive Shelf,My Review\n"
        '"The Deluge","Adam Tooze",,,,,,,,,,read,\n',
        encoding="utf-8",
    )


def test_goodreads_defaults_csv_to_imports_newest(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner

    from books.commands import goodreads as gr
    from books.core import config

    vault = tmp_path / "Vault"
    folder = vault / ".imports" / "goodreads"
    folder.mkdir(parents=True)
    _minimal_goodreads_csv(folder / "export.csv")
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)
    monkeypatch.setattr(
        config, "resolve_imports", lambda name, output=None: vault / ".imports" / name
    )

    app = typer.Typer()
    gr.register(app)
    result = CliRunner().invoke(app, [])

    assert result.exit_code == 0, result.output
    rows = {r.title for r in store.read_layer(vault, "goodreads")}
    assert "The Deluge" in rows


def test_goodreads_folder_arg_picks_newest(monkeypatch, tmp_path):
    import os

    import typer
    from typer.testing import CliRunner

    from books.commands import goodreads as gr
    from books.core import config

    vault = tmp_path / "Vault"
    folder = tmp_path / "exports"
    folder.mkdir()
    old = folder / "old.csv"
    old.write_text("Title,Author,Exclusive Shelf\n", encoding="utf-8")
    _minimal_goodreads_csv(folder / "new.csv")
    os.utime(old, (1000, 1000))
    os.utime(folder / "new.csv", (2000, 2000))
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)

    app = typer.Typer()
    gr.register(app)
    result = CliRunner().invoke(app, ["--csv", str(folder), "--output", str(vault)])

    assert result.exit_code == 0, result.output
    rows = {r.title for r in store.read_layer(vault, "goodreads")}
    assert "The Deluge" in rows
