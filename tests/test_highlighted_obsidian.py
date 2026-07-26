"""Tests for the Highlighted -> Obsidian importer."""

from pathlib import Path

from booktools import highlighted_obsidian as hi

HEADER = ("Highlight,Title,Author,ISBN,Collections,Reading Status,"
          "Book Added Date,Location,Tags,Note,Date,Favorite\n")
ROWS = (
    '"Fear is the mind-killer",Stalin,Stephen Kotkin,9781594203794,,Reading,'
    '2026-07-24,4,Stalin,That is true,2026-07-24 10:37:51,N\n'
    '"A longer passage.",Stalin,Stephen Kotkin,9781594203794,,Reading,'
    '2026-07-24,45-49,Stalin,,2026-07-24 11:15:47,N\n'
)


def write_csv(tmp_path: Path) -> Path:
    p = tmp_path / "Highlights for Stalin.csv"
    p.write_text(HEADER + ROWS, encoding="utf-8")
    return p


def test_parse_and_map(tmp_path):
    rows = hi.parse_csv(write_csv(tmp_path))
    assert len(rows) == 2
    h0 = hi.row_to_highlight(rows[0])
    assert h0.text == "Fear is the mind-killer"
    assert h0.note == "That is true"
    assert h0.page == "4"
    h1 = hi.row_to_highlight(rows[1])
    assert h1.note is None          # blank Note -> None
    assert h1.page == "45-49"


def test_row_to_highlight_splits_tags_on_comma():
    h = hi.row_to_highlight({"Highlight": "x", "Tags": "Stalin, USSR"})
    assert h.tags == ["stalin", "ussr"]


def test_row_to_highlight_single_tag():
    h = hi.row_to_highlight({"Highlight": "x", "Tags": "Stalin"})
    assert h.tags == ["stalin"]


def test_row_to_highlight_no_tags():
    assert hi.row_to_highlight({"Highlight": "x", "Tags": ""}).tags == []
    assert hi.row_to_highlight({"Highlight": "x"}).tags == []


def test_row_to_highlight_sanitizes_tag_whitespace():
    h = hi.row_to_highlight({"Highlight": "x", "Tags": "Cold War, USSR"})
    assert h.tags == ["cold-war", "ussr"]


def test_row_to_highlight_dedupes_tags_preserving_order():
    h = hi.row_to_highlight({"Highlight": "x", "Tags": "Stalin, USSR, stalin"})
    assert h.tags == ["stalin", "ussr"]


def test_convert_writes_highlights_and_embed(tmp_path):
    out = tmp_path / "Obsidian"
    stats = hi.convert(write_csv(tmp_path), out)
    assert stats["books"] == 1 and stats["entries"] == 2
    note = out / "Stephen Kotkin" / "Stalin" / "Stalin.md"
    assert note.exists()
    note_text = note.read_text()
    assert "![](Highlights.md)" in note_text
    assert 'isbn: "9781594203794"' in note_text     # ISBN persisted for matching
    highlights_md = (note.parent / "Highlights.md").read_text()
    assert "source: highlighted" in highlights_md          # provenance frontmatter
    assert "> [!quote]+ p. 4" in highlights_md
    assert "^p45-49" in highlights_md
    assert "Fear is the mind-killer" in highlights_md
    assert "#stalin" in highlights_md   # tag rendered inside the note


def test_convert_merges_into_existing_note_by_isbn(tmp_path):
    out = tmp_path / "Obsidian"
    book_dir = out / "Stephen Kotkin" / "Stalin"
    book_dir.mkdir(parents=True)
    note = book_dir / "Stalin.md"
    note.write_text(
        '---\ntype: book\ntitle: "Stalin"\nisbn: "9781594203794"\n'
        'status: read\n---\n\nMy body.\n', encoding="utf-8")
    stats = hi.convert(write_csv(tmp_path), out)
    assert stats["books"] == 1
    updated = note.read_text()
    assert "status: read" in updated       # existing value untouched
    assert "My body." in updated           # body preserved
    assert "![](Highlights.md)" in updated


def test_convert_idempotent(tmp_path):
    out = tmp_path / "Obsidian"
    hi.convert(write_csv(tmp_path), out)
    before = {p: p.read_text() for p in out.rglob("*.md")}
    hi.convert(write_csv(tmp_path), out)
    after = {p: p.read_text() for p in out.rglob("*.md")}
    assert before == after
