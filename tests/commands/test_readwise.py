"""Tests for the Readwise -> CSV highlights-store importer."""

from pathlib import Path

import typer
from typer.testing import CliRunner

from books.commands import readwise
from books.commands import readwise as rw
from books.core import store

HEADER = ("Highlight,Book Title,Book Author,Amazon Book ID,Note,Color,Tags,"
          "Location Type,Location,Highlighted at,Document tags\n")
ROWS = (
    '"First passage.","Stalin: Volume I (Stalin #1)",Stephen Kotkin,B00INIXPYE,'
    'my note,,history,page,3,2026-07-17 14:00:25+00:00,favorites\n'
    '"Second passage.","Stalin: Volume I (Stalin #1)",Stephen Kotkin,B00INIXPYE,'
    ',,,,page,10,2026-07-19 17:36:30+00:00,favorites\n'
)


def write_csv(tmp_path: Path) -> Path:
    p = tmp_path / "readwise-data.csv"
    p.write_text(HEADER + ROWS, encoding="utf-8")
    return p


def seed_books(vault: Path, rows: list[store.BookRow]) -> None:
    """Seed books.csv (as calibre/goodreads + merge would) so Catalog can match."""
    store.write_books_csv(vault, rows)


def seed_stalin(vault: Path) -> None:
    seed_books(vault, [store.BookRow(
        book_id="Stalin - Stephen Kotkin", title="Stalin",
        authors=["Stephen Kotkin"], amazon="B00INIXPYE")])


# --- CSV parsing / mapping helpers (unchanged, store-agnostic) ----------------

def test_split_series_extracts_name_and_index():
    title, series, index = rw.split_series(
        "Stalin: Volume I: Paradoxes of Power, 1878-1928 (Stalin #1)")
    assert title == "Stalin: Volume I: Paradoxes of Power, 1878-1928"
    assert series == "Stalin"
    assert index == "1"


def test_split_series_decimal_index():
    title, series, index = rw.split_series("Some Book (Saga #2.5)")
    assert title == "Some Book"
    assert series == "Saga"
    assert index == "2.5"


def test_split_series_no_suffix_is_verbatim():
    title, series, index = rw.split_series("The Landscape of History")
    assert title == "The Landscape of History"
    assert series is None
    assert index is None


def test_split_series_ignores_non_numbered_parenthetical():
    # A trailing parenthetical without "#N" must NOT be treated as a series.
    title, series, index = rw.split_series(
        "The Landscape of History: How Historians Map the Past (Inaugural Lectures)")
    assert title == "The Landscape of History: How Historians Map the Past (Inaugural Lectures)"
    assert series is None and index is None


def test_row_to_highlight_page_location():
    h = rw.row_to_highlight({
        "Highlight": "A passage", "Note": "my note",
        "Location Type": "page", "Location": "3",
        "Highlighted at": "2026-07-17 14:00:25.470174+00:00", "Tags": ""})
    assert h.text == "A passage"
    assert h.note == "my note"
    assert h.page == "3"
    assert h.location_label is None
    assert h.date == "2026-07-17 14:00:25.470174+00:00"


def test_row_to_highlight_kindle_location():
    h = rw.row_to_highlight({
        "Highlight": "x", "Location Type": "location", "Location": "1234"})
    assert h.page == "1234"
    assert h.location_label == "loc."


def test_row_to_highlight_order_has_no_page():
    h = rw.row_to_highlight({
        "Highlight": "x", "Location Type": "order", "Location": "7"})
    assert h.page is None
    assert h.location_label is None


def test_row_to_highlight_blank_note_is_none():
    h = rw.row_to_highlight({"Highlight": "x", "Note": "", "Location Type": "page",
                             "Location": "1"})
    assert h.note is None


def test_row_to_highlight_splits_and_dedupes_tags():
    h = rw.row_to_highlight({"Highlight": "x", "Tags": "Stalin, USSR, stalin"})
    assert h.tags == ["stalin", "ussr"]


def test_row_to_highlight_splits_links_from_tags():
    h = rw.row_to_highlight({"Highlight": "x", "Tags": "history, @War Commisar"})
    assert h.tags == ["history"]
    assert h.links == ["War Commisar"]


def test_parse_csv_reads_rows(tmp_path):
    rows = rw.parse_csv(write_csv(tmp_path))
    assert len(rows) == 2
    assert rows[0]["Book Title"] == "Stalin: Volume I (Stalin #1)"


# --- convert -> CSV highlights store ------------------------------------------

_RW_CSV = (
    "Highlight,Book Title,Book Author,Amazon Book ID,Note,Color,Tags,"
    "Location Type,Location,Highlighted at,Document tags\n"
    "insight,The Deluge (History #1),Adam Tooze,B00XYZ,,,,page,120,2020-01-01,\n"
)


def _seed_deluge(vault: Path) -> None:
    seed_books(vault, [store.BookRow(
        book_id="The Deluge - Adam Tooze", title="The Deluge",
        authors=["Adam Tooze"], amazon="B00XYZ")])


def test_readwise_writes_highlights_to_store(tmp_path):
    vault = tmp_path / "vault"
    _seed_deluge(vault)
    csv = tmp_path / "rw.csv"
    csv.write_text(_RW_CSV, encoding="utf-8")

    stats = readwise.convert(csv, vault)

    rows = store.read_highlights(vault, "The Deluge - Adam Tooze")
    assert len(rows) == 1
    assert rows[0].source == "readwise"
    assert rows[0].text == "insight"
    assert rows[0].location == "120" and rows[0].location_kind == "page"
    assert stats["books"] == 1 and stats["entries"] == 1 and stats["skipped"] == 0


def test_readwise_skips_unmatched(tmp_path):
    vault = tmp_path / "vault"
    store.write_books_csv(vault, [])
    csv = tmp_path / "rw.csv"
    csv.write_text(_RW_CSV, encoding="utf-8")
    stats = readwise.convert(csv, vault)
    assert stats["skipped"] == 1 and stats["books"] == 0


def test_convert_writes_two_highlights_to_store(tmp_path):
    vault = tmp_path / "vault"
    seed_stalin(vault)
    stats = rw.convert(write_csv(tmp_path), vault)
    assert stats["books"] == 1 and stats["entries"] == 2
    rows = store.read_highlights(vault, "Stalin - Stephen Kotkin")
    assert [r.text for r in rows] == ["First passage.", "Second passage."]
    assert all(r.source == "readwise" for r in rows)
    # First row's Tags column ("history") becomes a #tag.
    assert rows[0].tags == ["history"]


def test_convert_rerun_replaces_own_rows(tmp_path):
    vault = tmp_path / "vault"
    seed_stalin(vault)
    rw.convert(write_csv(tmp_path), vault)
    rw.convert(write_csv(tmp_path), vault)  # re-run
    assert len(store.read_highlights(vault, "Stalin - Stephen Kotkin")) == 2


def test_convert_same_title_different_authors_no_amazon_stay_separate(tmp_path):
    vault = tmp_path / "vault"
    csv = tmp_path / "rw.csv"
    csv.write_text(
        HEADER +
        '"From A.","Selected Essays",Author A,,,,,page,1,2026-01-01 00:00:00+00:00,\n'
        '"From B.","Selected Essays",Author B,,,,,page,2,2026-01-02 00:00:00+00:00,\n',
        encoding="utf-8")
    seed_books(vault, [
        store.BookRow(book_id="Selected Essays - Author A",
                      title="Selected Essays", authors=["Author A"]),
        store.BookRow(book_id="Selected Essays - Author B",
                      title="Selected Essays", authors=["Author B"]),
    ])
    stats = rw.convert(csv, vault)
    assert stats["books"] == 2
    assert len(store.read_highlights(vault, "Selected Essays - Author A")) == 1
    assert len(store.read_highlights(vault, "Selected Essays - Author B")) == 1


def test_convert_same_amazon_different_title_rows_group_together(tmp_path):
    # Same Amazon id groups rows even if a later row's title differs slightly.
    vault = tmp_path / "vault"
    csv = tmp_path / "rw.csv"
    csv.write_text(
        HEADER +
        '"One.","Book (Series #1)",Kotkin,B00INIXPYE,,,,page,1,2026-01-01 00:00:00+00:00,\n'
        '"Two.","Book (Series #1)",Kotkin,B00INIXPYE,,,,page,2,2026-01-02 00:00:00+00:00,\n',
        encoding="utf-8")
    seed_books(vault, [store.BookRow(
        book_id="Book - Kotkin", title="Book", authors=["Kotkin"],
        amazon="B00INIXPYE")])
    stats = rw.convert(csv, vault)
    assert stats["books"] == 1 and stats["entries"] == 2


def test_convert_two_groups_same_book_id_keeps_all(tmp_path):
    """Two groups (one keyed by Amazon id, one by title/author) resolving to the
    same book must accumulate -- the second group must not wipe the first."""
    vault = tmp_path / "vault"
    _seed_deluge(vault)
    csv = tmp_path / "rw.csv"
    # Row 1 carries the Amazon id (group key = amazon); row 2 omits it (group
    # key = title\x00author). Both resolve to "The Deluge - Adam Tooze".
    csv.write_text(
        HEADER +
        '"with amazon","The Deluge",Adam Tooze,B00XYZ,,,,page,1,2020-01-01 00:00:00+00:00,\n'
        '"no amazon","The Deluge",Adam Tooze,,,,,page,2,2020-01-02 00:00:00+00:00,\n',
        encoding="utf-8")

    stats = rw.convert(csv, vault)

    rows = store.read_highlights(vault, "The Deluge - Adam Tooze")
    assert {r.text for r in rows} == {"with amazon", "no amazon"}
    assert stats["books"] == 1 and stats["entries"] == 2


def test_convert_empty_csv_creates_nothing(tmp_path):
    vault = tmp_path / "vault"
    csv = tmp_path / "rw.csv"
    csv.write_text(HEADER, encoding="utf-8")
    stats = rw.convert(csv, vault)
    assert stats == {"books": 0, "entries": 0, "skipped": 0}


# --- CLI ----------------------------------------------------------------------

def test_readwise_command_end_to_end(tmp_path):
    app = typer.Typer()
    rw.register(app)
    vault = tmp_path / "Vault"
    seed_stalin(vault)
    result = CliRunner().invoke(
        app, ["--csv", str(write_csv(tmp_path)), "--output", str(vault)])
    assert result.exit_code == 0, result.output
    assert "2 highlights" in result.output
    assert "authors" not in result.output   # echo drops authors
    rows = store.read_highlights(vault, "Stalin - Stephen Kotkin")
    assert [r.text for r in rows] == ["First passage.", "Second passage."]


def test_readwise_missing_csv_errors(tmp_path):
    app = typer.Typer()
    rw.register(app)
    result = CliRunner().invoke(
        app, ["--csv", str(tmp_path / "nope.csv"), "--output", str(tmp_path / "o")])
    assert result.exit_code != 0


def test_readwise_defaults_csv_to_imports_newest(monkeypatch, tmp_path):
    from books.core import config

    vault = tmp_path / "Vault"
    folder = vault / ".imports" / "readwise"
    folder.mkdir(parents=True)
    (folder / "export.csv").write_text(HEADER + ROWS, encoding="utf-8")
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)
    monkeypatch.setattr(config, "resolve_imports",
                        lambda name, output=None: vault / ".imports" / name)
    seed_stalin(vault)

    app = typer.Typer()
    rw.register(app)
    result = CliRunner().invoke(app, [])

    assert result.exit_code == 0, result.output
    assert len(store.read_highlights(vault, "Stalin - Stephen Kotkin")) == 2


def test_readwise_folder_arg_picks_newest(monkeypatch, tmp_path):
    import os

    from books.core import config

    vault = tmp_path / "Vault"
    folder = tmp_path / "exports"
    folder.mkdir()
    old = folder / "old.csv"
    old.write_text(HEADER, encoding="utf-8")
    (folder / "new.csv").write_text(HEADER + ROWS, encoding="utf-8")
    os.utime(old, (1000, 1000))
    os.utime(folder / "new.csv", (2000, 2000))
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)
    seed_stalin(vault)

    app = typer.Typer()
    rw.register(app)
    result = CliRunner().invoke(app, ["--csv", str(folder), "--output", str(vault)])

    assert result.exit_code == 0, result.output
    assert len(store.read_highlights(vault, "Stalin - Stephen Kotkin")) == 2
