"""Tests for the Highlighted -> Obsidian importer."""

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from booktools import highlighted_obsidian as hi
from booktools.cli import app

runner = CliRunner()

HEADER = ("Highlight,Title,Author,ISBN,Collections,Reading Status,"
          "Book Added Date,Location,Tags,Note,Date,Favorite\n")
ROWS = (
    '"Fear is the mind-killer",Stalin,Stephen Kotkin,9781594203794,,Reading,'
    '2026-07-24,4,Stalin,That is true,2026-07-24 10:37:51,N\n'
    '"A longer passage.",Stalin,Stephen Kotkin,9781594203794,,Reading,'
    '2026-07-24,45-49,Stalin,,2026-07-24 11:15:47,N\n'
)

# A second book, distinct ISBN, for the multi-file folder test.
ROWS_TROTSKY = (
    '"Ideas are more powerful than guns.",The Prophet Armed,Isaac Deutscher,'
    '9781781683118,,Read,2026-07-25,88,Trotsky,,2026-07-25 09:00:00,N\n'
)


def write_csv(tmp_path: Path) -> Path:
    p = tmp_path / "Highlights for Stalin.csv"
    p.write_text(HEADER + ROWS, encoding="utf-8")
    return p


def test_resolve_csv_paths_single_file(tmp_path):
    p = write_csv(tmp_path)
    assert hi.resolve_csv_paths(p) == [p]


def test_resolve_csv_paths_folder_sorted(tmp_path):
    (tmp_path / "b.csv").write_text(HEADER + ROWS, encoding="utf-8")
    (tmp_path / "a.csv").write_text(HEADER + ROWS, encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    result = hi.resolve_csv_paths(tmp_path)
    assert [p.name for p in result] == ["a.csv", "b.csv"]


def test_resolve_csv_paths_empty_folder_raises(tmp_path):
    with pytest.raises(typer.BadParameter):
        hi.resolve_csv_paths(tmp_path)


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


def test_row_to_highlight_splits_links_from_tags():
    h = hi.row_to_highlight({"Highlight": "x", "Tags": "history, @War Commisar"})
    assert h.tags == ["history"]
    assert h.links == ["War Commisar"]


def test_convert_writes_highlights_and_embed(tmp_path):
    out = tmp_path / "Obsidian"
    stats = hi.convert(write_csv(tmp_path), out)
    assert stats["books"] == 1 and stats["entries"] == 2
    note = out / "Books" / "Stalin - Stephen Kotkin.md"
    assert note.exists()
    note_text = note.read_text()
    # Highlights are an inline, marker-wrapped '## Highlights' section.
    assert "## Highlights" in note_text
    assert "%% books:highlights:start %%" in note_text
    assert "%% books:highlights:end %%" in note_text
    assert 'isbn: "9781594203794"' in note_text     # ISBN persisted for matching
    assert "source: highlighted" in note_text              # provenance frontmatter
    assert "> [!quote]+ p. 4" in note_text
    assert "^p45-49" in note_text
    assert "Fear is the mind-killer" in note_text
    assert "#stalin" in note_text   # tag rendered inside the note


def test_convert_merges_into_existing_note_by_isbn(tmp_path):
    out = tmp_path / "Obsidian"
    book_dir = out / "Books"
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
    assert "## Highlights" in updated
    assert "%% books:highlights:start %%" in updated


def test_convert_idempotent(tmp_path):
    out = tmp_path / "Obsidian"
    hi.convert(write_csv(tmp_path), out)
    before = {p: p.read_text() for p in out.rglob("*.md")}
    hi.convert(write_csv(tmp_path), out)
    after = {p: p.read_text() for p in out.rglob("*.md")}
    assert before == after


def test_cli_folder_imports_all_and_sums(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "stalin.csv").write_text(HEADER + ROWS, encoding="utf-8")
    (src / "trotsky.csv").write_text(HEADER + ROWS_TROTSKY, encoding="utf-8")
    out = tmp_path / "Obsidian"
    result = runner.invoke(app, ["highlighted", "-c", str(src), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "2 files" in result.output
    assert (out / "Books" / "Stalin - Stephen Kotkin.md").exists()
    assert (out / "Books" / "The Prophet Armed - Isaac Deutscher.md").exists()
    # books/entries summed across both files
    assert "2 books" in result.output
    assert "3 highlights" in result.output


def test_cli_folder_same_book_last_file_wins(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.csv").write_text(HEADER + ROWS, encoding="utf-8")
    # same ISBN -> confirmed same book; the later file's highlights win
    (src / "b.csv").write_text(
        HEADER + '"Another line.",Stalin,Stephen Kotkin,9781594203794,,Reading,'
        '2026-07-24,60,Stalin,,2026-07-24 12:00:00,N\n', encoding="utf-8")
    out = tmp_path / "Obsidian"
    result = runner.invoke(app, ["highlighted", "-c", str(src), "-o", str(out)])
    assert result.exit_code == 0, result.output
    # exactly one Stalin note (matched by ISBN, no duplicate)
    stalin_notes = list((out / "Books").glob("Stalin*"))
    assert len(stalin_notes) == 1
    hl = stalin_notes[0].read_text()
    # last file (b.csv) wins: its highlight is present, the earlier file's is gone
    assert "Another line." in hl
    assert "Fear is the mind-killer" not in hl


def test_cli_folder_skips_bad_csv(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "good.csv").write_text(HEADER + ROWS, encoding="utf-8")
    # bytes that are not valid UTF-8, so parse_csv raises inside convert
    (src / "bad.csv").write_bytes(b"\xff\xfe\x00not a valid utf-8 csv\x00")
    out = tmp_path / "Obsidian"
    result = runner.invoke(app, ["highlighted", "-c", str(src), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "1 skipped" in result.output
    assert (out / "Books" / "Stalin - Stephen Kotkin.md").exists()


def test_cli_single_file_shows_one_file(tmp_path):
    csv = write_csv(tmp_path)
    out = tmp_path / "Obsidian"
    result = runner.invoke(app, ["highlighted", "-c", str(csv), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "1 file" in result.output
    assert (out / "Books" / "Stalin - Stephen Kotkin.md").exists()


def test_cli_empty_folder_errors(tmp_path):
    src = tmp_path / "empty"
    src.mkdir()
    out = tmp_path / "Obsidian"
    result = runner.invoke(app, ["highlighted", "-c", str(src), "-o", str(out)])
    assert result.exit_code != 0


def test_highlighted_defaults_csv_to_imports(monkeypatch, tmp_path):
    from booktools import config

    vault = tmp_path / "Vault"
    folder = vault / ".imports" / "highlighted"
    folder.mkdir(parents=True)
    (folder / "export.csv").write_text(
        "Highlight,Title,Author,ISBN,Collections,Reading Status,"
        "Book Added Date,Location,Tags,Note,Date,Favorite\n"
        '"A line.","The Deluge","Adam Tooze",,,,,42,,,,\n',
        encoding="utf-8")
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)
    monkeypatch.setattr(config, "resolve_imports",
                        lambda name, output=None: vault / ".imports" / name)

    app = typer.Typer()
    hi.register(app)
    result = CliRunner().invoke(app, [])

    assert result.exit_code == 0, result.output
    assert (vault / "Books" / "The Deluge - Adam Tooze.md").exists()
