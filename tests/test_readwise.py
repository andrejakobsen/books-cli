"""Tests for the Readwise -> Obsidian importer."""

from pathlib import Path

import typer
from typer.testing import CliRunner

from booktools import readwise_obsidian as rw

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


def test_convert_writes_highlights_and_frontmatter(tmp_path):
    out = tmp_path / "Obsidian"
    stats = rw.convert(write_csv(tmp_path), out)
    assert stats["books"] == 1 and stats["entries"] == 2
    note = out / "Books" / "Stalin_ Volume I.md"
    assert note.exists()
    note_text = note.read_text()
    assert "![[Exports/Stephen Kotkin/Stalin_ Volume I/Highlights.md]]" in note_text
    assert 'amazon: "B00INIXPYE"' in note_text
    assert 'series: "Stalin"' in note_text
    assert "series_index: 1" in note_text
    assert 'shelves: ["favorites"]' in note_text
    highlights_md = (out / "Exports" / "Stephen Kotkin" / "Stalin_ Volume I"
                     / "Highlights.md").read_text()
    assert "source: readwise" in highlights_md
    assert "> [!quote]+ p. 3" in highlights_md
    assert "First passage." in highlights_md
    assert "#history" in highlights_md


def test_convert_merges_into_existing_note_by_amazon(tmp_path):
    out = tmp_path / "Obsidian"
    books = out / "Books"
    books.mkdir(parents=True)
    note = books / "Existing.md"
    note.write_text(
        '---\ntype: book\ntitle: "Stalin"\namazon: "B00INIXPYE"\n'
        'status: read\n---\n\nMy body.\n', encoding="utf-8")
    stats = rw.convert(write_csv(tmp_path), out)
    assert stats["books"] == 1
    updated = note.read_text()
    assert "status: read" in updated       # existing value untouched
    assert "My body." in updated           # body preserved
    assert "![[Exports/Stephen Kotkin/Stalin_ Volume I/Highlights.md]]" in updated


def test_convert_idempotent(tmp_path):
    out = tmp_path / "Obsidian"
    rw.convert(write_csv(tmp_path), out)
    before = {p: p.read_text() for p in out.rglob("*.md")}
    rw.convert(write_csv(tmp_path), out)
    after = {p: p.read_text() for p in out.rglob("*.md")}
    assert before == after


def test_readwise_command_end_to_end(tmp_path):
    app = typer.Typer()
    rw.register(app)
    out = tmp_path / "Obsidian"
    result = CliRunner().invoke(
        app, ["--csv", str(write_csv(tmp_path)), "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "Books" / "Stalin_ Volume I.md").exists()
    assert "2 highlights" in result.output


def test_readwise_missing_csv_errors(tmp_path):
    app = typer.Typer()
    rw.register(app)
    result = CliRunner().invoke(
        app, ["--csv", str(tmp_path / "nope.csv"), "--output", str(tmp_path / "o")])
    assert result.exit_code != 0


def test_convert_same_title_different_authors_no_amazon_stay_separate(tmp_path):
    out = tmp_path / "Obsidian"
    csv = tmp_path / "rw.csv"
    csv.write_text(
        "Highlight,Book Title,Book Author,Amazon Book ID,Note,Color,Tags,"
        "Location Type,Location,Highlighted at,Document tags\n"
        '"From A.","Selected Essays",Author A,,,,,page,1,2026-01-01 00:00:00+00:00,\n'
        '"From B.","Selected Essays",Author B,,,,,page,2,2026-01-02 00:00:00+00:00,\n',
        encoding="utf-8")
    stats = rw.convert(csv, out)
    assert stats["books"] == 2
    assert (out / "Exports" / "Author A" / "Selected Essays" / "Highlights.md").exists()
    assert (out / "Exports" / "Author B" / "Selected Essays" / "Highlights.md").exists()


def test_convert_same_amazon_different_title_rows_group_together(tmp_path):
    # Same Amazon id groups rows even if a later row's title differs slightly.
    out = tmp_path / "Obsidian"
    csv = tmp_path / "rw.csv"
    csv.write_text(
        "Highlight,Book Title,Book Author,Amazon Book ID,Note,Color,Tags,"
        "Location Type,Location,Highlighted at,Document tags\n"
        '"One.","Book (Series #1)",Kotkin,B00INIXPYE,,,,page,1,2026-01-01 00:00:00+00:00,\n'
        '"Two.","Book (Series #1)",Kotkin,B00INIXPYE,,,,page,2,2026-01-02 00:00:00+00:00,\n',
        encoding="utf-8")
    stats = rw.convert(csv, out)
    assert stats["books"] == 1 and stats["entries"] == 2


def test_split_series_ignores_non_numbered_parenthetical():
    # A trailing parenthetical without "#N" must NOT be treated as a series.
    title, series, index = rw.split_series(
        "The Landscape of History: How Historians Map the Past (Inaugural Lectures)")
    assert title == "The Landscape of History: How Historians Map the Past (Inaugural Lectures)"
    assert series is None and index is None


def test_convert_empty_csv_creates_nothing(tmp_path):
    out = tmp_path / "Obsidian"
    csv = tmp_path / "rw.csv"
    csv.write_text(
        "Highlight,Book Title,Book Author,Amazon Book ID,Note,Color,Tags,"
        "Location Type,Location,Highlighted at,Document tags\n",
        encoding="utf-8")
    stats = rw.convert(csv, out)
    assert stats == {"books": 0, "entries": 0, "authors": set()}
