"""Tests for the Kobo exporter (Obsidian mode + row mapping)."""

import sqlite3
from pathlib import Path

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

    folder = vault / "F. Scott Fitzgerald" / "The Great Gatsby"
    highlights = (folder / "Highlights.md").read_text()
    assert "> [!quote]+ ch. 2 · 42%" in highlights
    assert "^ch2-b17-5" in highlights
    assert "> [!note]-" in highlights          # first highlight has an annotation
    assert highlights.count("[!note]") == 1    # second has none

    note = (folder / "The Great Gatsby.md").read_text()
    assert "![](Highlights.md)" in note


def test_export_obsidian_regenerates_highlights_wholesale(tmp_path):
    db = tmp_path / "KoboReader.sqlite"
    _make_db(db)
    vault = tmp_path / "Obsidian"
    ke.export_obsidian(db, vault)
    note_path = vault / "F. Scott Fitzgerald" / "The Great Gatsby" / "The Great Gatsby.md"
    # Simulate a hand edit to the book note body; it must survive re-export.
    note_path.write_text(note_path.read_text() + "\nMy own paragraph.\n", encoding="utf-8")
    ke.export_obsidian(db, vault)
    assert "My own paragraph." in note_path.read_text()
    assert note_path.read_text().count("## Highlights") == 1
