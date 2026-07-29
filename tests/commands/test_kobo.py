"""Tests for the Kobo exporter (Obsidian mode + row mapping)."""

import sqlite3
from pathlib import Path

import pytest

from books.commands import kobo as ke


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
                 ("book1-ch2", 899, "The Valley of Ashes", None, None, 2, None))
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


def _seed_gatsby(vault: Path) -> Path:
    """Pre-create the book note (as calibre/goodreads would) so kobo can match."""
    books = vault / "Books"
    books.mkdir(parents=True, exist_ok=True)
    note = books / "The Great Gatsby - F. Scott Fitzgerald.md"
    note.write_text(
        '---\ntype: book\ntitle: "The Great Gatsby"\n'
        'authors: ["[[F. Scott Fitzgerald]]"]\nisbn: "9780743273565"\n---\n\n',
        encoding="utf-8")
    return note


def test_export_obsidian_skips_book_without_existing_note(tmp_path):
    db = tmp_path / "KoboReader.sqlite"
    _make_db(db)
    vault = tmp_path / "Obsidian"
    stats = ke.export_obsidian(db, vault)
    assert stats["books"] == 0
    assert stats["entries"] == 0
    assert stats["skipped"] == 1
    assert not (vault / "Books" / "The Great Gatsby - F. Scott Fitzgerald.md").exists()


def test_export_obsidian_writes_highlights_and_embed(tmp_path):
    db = tmp_path / "KoboReader.sqlite"
    _make_db(db)
    vault = tmp_path / "Obsidian"
    _seed_gatsby(vault)
    stats = ke.export_obsidian(db, vault)
    assert stats["books"] == 1 and stats["entries"] == 2

    note = (vault / "Books" / "The Great Gatsby - F. Scott Fitzgerald.md").read_text()
    # Highlights are an inline, marker-wrapped '## Highlights' section.
    assert "## Highlights" in note
    assert "%% books:highlights:start %%" in note
    assert "%% books:highlights:end %%" in note
    assert "source: kobo" in note                # provenance frontmatter
    assert "### The Valley of Ashes" in note     # chapter title header (level 3)
    assert "%% Kobo ch." not in note             # hidden reading-order comment removed
    assert "> [!quote]+ Kobo ch. 2 · 42%" in note  # locator keeps the chapter
    assert "^ch2-42" in note                      # anchor mirrors the locator
    assert ">> my note" in note                  # first highlight's note as nested quote
    assert "[!note]" not in note                 # no separate note callout


def test_export_obsidian_regenerates_highlights_wholesale(tmp_path):
    db = tmp_path / "KoboReader.sqlite"
    _make_db(db)
    vault = tmp_path / "Obsidian"
    _seed_gatsby(vault)
    ke.export_obsidian(db, vault)
    note_path = vault / "Books" / "The Great Gatsby - F. Scott Fitzgerald.md"
    # Simulate a hand edit to the book note body; it must survive re-export.
    note_path.write_text(note_path.read_text() + "\nMy own paragraph.\n", encoding="utf-8")
    ke.export_obsidian(db, vault)
    assert "My own paragraph." in note_path.read_text()
    assert note_path.read_text().count("## Highlights") == 1


def test_export_obsidian_idempotent(tmp_path):
    db = tmp_path / "KoboReader.sqlite"
    _make_db(db)
    vault = tmp_path / "Obsidian"
    _seed_gatsby(vault)
    ke.export_obsidian(db, vault)
    before = {p: p.read_text() for p in vault.rglob("*.md")}
    ke.export_obsidian(db, vault)  # second run
    after = {p: p.read_text() for p in vault.rglob("*.md")}
    assert before == after


class _R(dict):
    """Row stub matching the kobo module's row access (missing keys -> None)."""
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


def test_kobo_copies_from_mounted_device(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner
    from books.commands import kobo as ke
    from books.core import config

    vault = tmp_path / "Vault"
    device = tmp_path / "device" / "KoboReader.sqlite"
    device.parent.mkdir(parents=True)
    _make_db(device)
    monkeypatch.setattr(ke, "KOBO_DEVICE_DB", device)
    monkeypatch.setattr(config, "resolve_imports",
                        lambda name, output=None: vault / ".imports" / name)

    out_zip = tmp_path / "out.zip"
    app = typer.Typer()
    ke.register(app)
    result = CliRunner().invoke(app, ["--output", str(out_zip)])

    assert result.exit_code == 0, result.output
    assert out_zip.exists()
    assert (vault / ".imports" / "kobo" / "KoboReader.sqlite").is_file()
    assert device.is_file()


def test_safe_copy_db_removes_partial_snapshot_on_failure(tmp_path):
    src = tmp_path / "device.sqlite"
    _make_db(src)
    dest = tmp_path / "imports" / "kobo" / "KoboReader.sqlite"

    class _Boom(sqlite3.Connection):
        def backup(self, *a, **k):
            raise sqlite3.OperationalError("device yanked mid-backup")

    orig_connect = sqlite3.connect

    def fake_connect(target, *a, **k):
        # source.backup(target) is called on the read-only source (uri=True);
        # make that connection's backup() boom mid-copy.
        if k.get("uri"):
            return orig_connect(target, *a, factory=_Boom, **k)
        return orig_connect(target, *a, **k)

    import unittest.mock as mock
    with mock.patch.object(sqlite3, "connect", fake_connect):
        with pytest.raises(sqlite3.OperationalError):
            ke._safe_copy_db(src, dest)

    assert not dest.exists()


def test_kobo_uses_existing_imports_copy_when_no_device(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner
    from books.commands import kobo as ke
    from books.core import config

    vault = tmp_path / "Vault"
    folder = vault / ".imports" / "kobo"
    folder.mkdir(parents=True)
    _make_db(folder / "KoboReader.sqlite")
    monkeypatch.setattr(ke, "KOBO_DEVICE_DB", tmp_path / "nope" / "KoboReader.sqlite")
    monkeypatch.setattr(config, "resolve_imports",
                        lambda name, output=None: vault / ".imports" / name)

    out_zip = tmp_path / "out.zip"
    app = typer.Typer()
    ke.register(app)
    result = CliRunner().invoke(app, ["--output", str(out_zip)])

    assert result.exit_code == 0, result.output
    assert out_zip.exists()


def test_kobo_csv_mode_default_ignores_zip_output_for_imports(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner
    from books.commands import kobo as ke
    from books.core import config

    vault = tmp_path / "Vault"
    folder = vault / ".imports" / "kobo"
    folder.mkdir(parents=True)
    _make_db(folder / "KoboReader.sqlite")
    monkeypatch.setattr(ke, "KOBO_DEVICE_DB", tmp_path / "nope" / "KoboReader.sqlite")

    seen = {}

    def fake_resolve_imports(name, output=None):
        seen["output"] = output
        return folder

    monkeypatch.setattr(config, "resolve_imports", fake_resolve_imports)

    out_zip = tmp_path / "out.zip"
    app = typer.Typer()
    ke.register(app)
    result = CliRunner().invoke(app, ["--output", str(out_zip)])  # CSV mode (default)

    assert result.exit_code == 0, result.output
    assert seen["output"] is None  # zip path NOT forwarded as the vault


def test_kobo_obsidian_mode_default_forwards_output_for_imports(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner
    from books.commands import kobo as ke
    from books.core import config

    vault = tmp_path / "Vault"
    folder = vault / ".imports" / "kobo"
    folder.mkdir(parents=True)
    _make_db(folder / "KoboReader.sqlite")
    monkeypatch.setattr(ke, "KOBO_DEVICE_DB", tmp_path / "nope" / "KoboReader.sqlite")

    seen = {}

    def fake_resolve_imports(name, output=None):
        seen["output"] = output
        return folder

    monkeypatch.setattr(config, "resolve_imports", fake_resolve_imports)

    app = typer.Typer()
    ke.register(app)
    result = CliRunner().invoke(app, ["--obsidian", "--output", str(vault)])

    assert result.exit_code == 0, result.output
    assert seen["output"] == vault  # vault path forwarded in obsidian mode


def test_kobo_default_missing_everything_errors(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner
    from books.commands import kobo as ke
    from books.core import config

    vault = tmp_path / "Vault"
    monkeypatch.setattr(ke, "KOBO_DEVICE_DB", tmp_path / "nope" / "KoboReader.sqlite")
    monkeypatch.setattr(config, "resolve_imports",
                        lambda name, output=None: vault / ".imports" / name)

    app = typer.Typer()
    ke.register(app)
    result = CliRunner().invoke(app, [])

    assert result.exit_code != 0


def test_kobo_sets_highlighted_true(tmp_path):
    db = tmp_path / "KoboReader.sqlite"
    _make_db(db)
    vault = tmp_path / "Obsidian"
    note_path = _seed_gatsby(vault)
    ke.export_obsidian(db, vault)
    assert "highlighted: true" in note_path.read_text(encoding="utf-8")
