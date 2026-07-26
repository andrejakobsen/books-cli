"""Tests for the Kobo exporter (Obsidian mode + row mapping)."""

import sqlite3
from pathlib import Path

import pytest

from booktools import kobo_export as ke


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE content (
            ContentID TEXT, ContentType INTEGER, Title TEXT, BookTitle TEXT,
            Attribution TEXT, VolumeIndex INTEGER, ISBN TEXT
        );
        CREATE TABLE Bookmark (
            VolumeID TEXT, ContentID TEXT, ChapterProgress REAL, Text TEXT,
            Annotation TEXT, DateCreated TEXT, StartContainerPath TEXT, Hidden TEXT
        );
        """
    )
    # One book, one chapter (ContentType 899), two highlights (one annotated).
    conn.execute("INSERT INTO content VALUES (?,?,?,?,?,?,?)",
                 ("book1", 6, "The Great Gatsby", None, "F. Scott Fitzgerald", None, "9780743273565"))
    conn.execute("INSERT INTO content VALUES (?,?,?,?,?,?,?)",
                 ("book1-ch2", 899, "Chapter 2", None, None, 2, None))
    conn.execute("INSERT INTO Bookmark VALUES (?,?,?,?,?,?,?,?)",
                 ("book1", "book1-ch2", 0.42, "First highlight", "my note",
                  "2026-07-01", r"span#kobo\.17\.5", "false"))
    conn.execute("INSERT INTO Bookmark VALUES (?,?,?,?,?,?,?,?)",
                 ("book1", "book1-ch2", 0.55, "Second highlight", None,
                  "2026-07-02", r"span#kobo\.20\.1", "false"))
    conn.commit()
    conn.close()


def test_row_to_highlight_maps_fields():
    class R(dict):
        def __getitem__(self, k):
            return dict.get(self, k)
    row = R(chapter_index=2, chapter="Chapter 2", chapter_progress=0.42,
            container_path=r"span#kobo\.17\.5", highlight="Hi", note="note",
            date_created="2026-07-01")
    h = ke.row_to_highlight(row)
    assert h.text == "Hi" and h.note == "note"
    assert h.chapter_index == 2 and h.block == "17" and h.segment == "5"
    assert abs(h.progress - 0.42) < 1e-9


def test_export_obsidian_writes_highlights_and_embed(tmp_path):
    db = tmp_path / "KoboReader.sqlite"
    _make_db(db)
    vault = tmp_path / "Obsidian"
    stats = ke.export_obsidian(db, vault)
    assert stats["books"] == 1 and stats["entries"] == 2

    export_dir = vault / "Exports" / "F. Scott Fitzgerald" / "The Great Gatsby"
    highlights = (export_dir / "Highlights.md").read_text()
    assert "source: kobo" in highlights          # provenance frontmatter
    assert "## Chapter 2" in highlights          # chapter title header
    assert "%% Kobo ch. 2 %%" in highlights      # hidden reading-order comment
    assert "> [!quote]+ 42%" in highlights       # locator drops the chapter
    assert "^ch2-b17-5" in highlights
    assert ">> my note" in highlights          # first highlight's note as nested quote
    assert "[!note]" not in highlights         # no separate note callout

    note = (vault / "Books" / "The Great Gatsby.md").read_text()
    assert "![[Exports/F. Scott Fitzgerald/The Great Gatsby/Highlights.md]]" in note


def test_export_obsidian_regenerates_highlights_wholesale(tmp_path):
    db = tmp_path / "KoboReader.sqlite"
    _make_db(db)
    vault = tmp_path / "Obsidian"
    ke.export_obsidian(db, vault)
    note_path = vault / "Books" / "The Great Gatsby.md"
    # Simulate a hand edit to the book note body; it must survive re-export.
    note_path.write_text(note_path.read_text() + "\nMy own paragraph.\n", encoding="utf-8")
    ke.export_obsidian(db, vault)
    assert "My own paragraph." in note_path.read_text()
    assert note_path.read_text().count("## Highlights") == 1


class _R(dict):
    """Row stub matching kobo_export's row access (missing keys -> None)."""
    def __getitem__(self, k):
        return dict.get(self, k)


def _hl(note):
    row = _R(chapter_index=1, chapter="Ch", chapter_progress=0.1,
             container_path=r"span#kobo\.1\.0", highlight="Hi", note=note,
             date_created="2026-07-01")
    return ke.row_to_highlight(row)


@pytest.mark.parametrize("note", [
    "Note. #tag1 #tag2",
    "Note.#tag1 #tag2",
    "Note. #tag1#tag2",
])
def test_kobo_extracts_tags_and_strips_note(note):
    h = _hl(note)
    assert h.note == "Note."
    assert h.tags == ["tag1", "tag2"]


def test_kobo_note_only_tags_becomes_none():
    h = _hl("#tag1 #tag2")
    assert h.note is None
    assert h.tags == ["tag1", "tag2"]


def test_kobo_no_tags_note_verbatim():
    h = _hl("Just a plain note.")
    assert h.note == "Just a plain note."
    assert h.tags == []


def test_kobo_dedupes_tags_preserving_order():
    h = _hl("Note. #tag1 #tag2 #tag1")
    assert h.note == "Note."
    assert h.tags == ["tag1", "tag2"]


def test_kobo_preserves_nested_and_hyphen_tags():
    h = _hl("#history/ussr #cold-war")
    assert h.tags == ["history/ussr", "cold-war"]


def test_kobo_extracts_links_and_tags():
    h = _hl("Great point. @War Commisar #history")
    assert h.note == "Great point."
    assert h.links == ["War Commisar"]
    assert h.tags == ["history"]


def test_kobo_note_only_markers_becomes_none():
    h = _hl("@Trotsky #history")
    assert h.note is None
    assert h.links == ["Trotsky"]
    assert h.tags == ["history"]
