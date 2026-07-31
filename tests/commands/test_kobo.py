"""Tests for the Kobo exporter (Obsidian mode + row mapping)."""

import sqlite3
from pathlib import Path

import pytest

from books.commands import kobo as ke
from books.core import store


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
    conn.execute(
        "INSERT INTO content VALUES (?,?,?,?,?,?,?)",
        ("book1", 6, "The Great Gatsby", None, "F. Scott Fitzgerald", None, "9780743273565"),
    )
    conn.execute(
        "INSERT INTO content VALUES (?,?,?,?,?,?,?)",
        ("book1-ch2", 899, "The Valley of Ashes", None, None, 2, None),
    )
    conn.execute(
        "INSERT INTO Bookmark VALUES (?,?,?,?,?,?,?,?)",
        (
            "book1",
            "book1-ch2",
            0.42,
            "First highlight",
            "my note",
            "2026-07-01",
            r"span#kobo\.17\.5",
            "false",
        ),
    )
    conn.execute(
        "INSERT INTO Bookmark VALUES (?,?,?,?,?,?,?,?)",
        (
            "book1",
            "book1-ch2",
            0.55,
            "Second highlight",
            None,
            "2026-07-02",
            r"span#kobo\.20\.1",
            "false",
        ),
    )
    conn.commit()
    conn.close()


def test_row_to_highlight_maps_fields():
    class R(dict):
        def __getitem__(self, k):
            return dict.get(self, k)

    row = R(
        chapter_index=2,
        chapter="Chapter 2",
        chapter_progress=0.42,
        container_path=r"span#kobo\.17\.5",
        highlight="Hi",
        note="note",
        date_created="2026-07-01",
    )
    h = ke.row_to_highlight(row)
    assert h.text == "Hi" and h.note == "note"
    assert h.chapter_index == 2 and h.block == "17" and h.segment == "5"
    assert abs(h.progress - 0.42) < 1e-9


_GATSBY_ID = "The Great Gatsby - F. Scott Fitzgerald"


def _seed_gatsby_catalog(vault: Path) -> None:
    """Seed books.csv with the Gatsby book (as calibre/goodreads + merge would)."""
    store.write_books_csv(
        vault,
        [
            store.BookRow(
                book_id=_GATSBY_ID,
                title="The Great Gatsby",
                authors=["F. Scott Fitzgerald"],
                isbn="9780743273565",
            )
        ],
    )


def test_kobo_writes_highlights_to_store(tmp_path):
    vault = tmp_path / "vault"
    _seed_gatsby_catalog(vault)
    db = tmp_path / "KoboReader.sqlite"
    _make_db(db)

    stats = ke.export_obsidian(db, vault)

    rows = store.read_highlights(vault, _GATSBY_ID)
    assert len(rows) == 2  # _make_db seeds two highlights
    assert all(r.source == "kobo" for r in rows)
    # reading order: 0.42 then 0.55
    assert rows[0].text == "First highlight"
    assert rows[0].location == "42" and rows[0].location_kind == "percent"
    assert rows[1].text == "Second highlight"
    assert stats == {"books": 1, "entries": 2, "skipped": 0}


def test_kobo_two_titles_same_book_id_keeps_all(tmp_path):
    """Two Kobo titles resolving to the same catalog book must accumulate --
    the second title's highlights must not wipe the first's."""
    vault = tmp_path / "vault"
    _seed_gatsby_catalog(vault)  # catalog title: "The Great Gatsby"
    db = tmp_path / "KoboReader.sqlite"
    conn = sqlite3.connect(db)
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
    # Two device "books" with title variants that both fuzzy-match the catalog
    # entry (subtitle-stripped): a bare title and a subtitled one, same author.
    conn.execute(
        "INSERT INTO content VALUES (?,?,?,?,?,?,?)",
        ("bookA", 6, "The Great Gatsby", None, "F. Scott Fitzgerald", None, None),
    )
    conn.execute(
        "INSERT INTO content VALUES (?,?,?,?,?,?,?)",
        ("bookB", 6, "The Great Gatsby: A Novel", None, "F. Scott Fitzgerald", None, None),
    )
    conn.execute(
        "INSERT INTO Bookmark VALUES (?,?,?,?,?,?,?,?)",
        ("bookA", "bookA", 0.10, "from A", None, "2026-07-01", r"span#kobo\.1\.0", "false"),
    )
    conn.execute(
        "INSERT INTO Bookmark VALUES (?,?,?,?,?,?,?,?)",
        ("bookB", "bookB", 0.20, "from B", None, "2026-07-02", r"span#kobo\.2\.0", "false"),
    )
    conn.commit()
    conn.close()

    stats = ke.export_obsidian(db, vault)

    rows = store.read_highlights(vault, _GATSBY_ID)
    assert {r.text for r in rows} == {"from A", "from B"}
    assert stats == {"books": 1, "entries": 2, "skipped": 0}


class _R(dict):
    """Row stub matching the kobo module's row access (missing keys -> None)."""

    def __getitem__(self, k):
        return dict.get(self, k)


def _hl(note):
    row = _R(
        chapter_index=1,
        chapter="Ch",
        chapter_progress=0.1,
        container_path=r"span#kobo\.1\.0",
        highlight="Hi",
        note=note,
        date_created="2026-07-01",
    )
    return ke.row_to_highlight(row)


def test_kobo_extracts_links_and_tags():
    # Kobo wires the shared parse_markers helper (exhaustively covered in
    # tests/core/test_highlights.py); this smoke proves the wiring only.
    h = _hl("Great point. @War Commisar #history")
    assert h.note == "Great point."
    assert h.links == ["War Commisar"]
    assert h.tags == ["history"]


def test_kobo_copies_from_mounted_device(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner

    from books.commands import kobo as ke
    from books.core import config

    vault = tmp_path / "Vault"
    _seed_gatsby_catalog(vault)
    device = tmp_path / "device" / "KoboReader.sqlite"
    device.parent.mkdir(parents=True)
    _make_db(device)
    monkeypatch.setattr(ke, "KOBO_DEVICE_DB", device)
    monkeypatch.setattr(
        config, "resolve_imports", lambda name, output=None: vault / ".imports" / name
    )
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)

    app = typer.Typer()
    ke.register(app)
    result = CliRunner().invoke(app, ["--output", str(vault)])

    assert result.exit_code == 0, result.output
    # The device DB is snapshotted into the imports folder and read from there,
    # and its highlights land in the store (the device file is left intact).
    assert (vault / ".imports" / "kobo" / "KoboReader.sqlite").is_file()
    assert device.is_file()
    assert len(store.read_highlights(vault, _GATSBY_ID)) == 2


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
    _seed_gatsby_catalog(vault)
    folder = vault / ".imports" / "kobo"
    folder.mkdir(parents=True)
    _make_db(folder / "KoboReader.sqlite")
    monkeypatch.setattr(ke, "KOBO_DEVICE_DB", tmp_path / "nope" / "KoboReader.sqlite")
    monkeypatch.setattr(
        config, "resolve_imports", lambda name, output=None: vault / ".imports" / name
    )
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)

    app = typer.Typer()
    ke.register(app)
    result = CliRunner().invoke(app, ["--output", str(vault)])

    assert result.exit_code == 0, result.output
    assert len(store.read_highlights(vault, _GATSBY_ID)) == 2


def test_kobo_explicit_db_option(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner

    from books.commands import kobo as ke
    from books.core import config

    vault = tmp_path / "Vault"
    _seed_gatsby_catalog(vault)
    db = tmp_path / "elsewhere" / "KoboReader.sqlite"
    db.parent.mkdir(parents=True)
    _make_db(db)
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)

    app = typer.Typer()
    ke.register(app)
    result = CliRunner().invoke(app, ["--db", str(db), "--output", str(vault)])

    assert result.exit_code == 0, result.output
    assert len(store.read_highlights(vault, _GATSBY_ID)) == 2


def test_kobo_default_missing_everything_errors(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner

    from books.commands import kobo as ke
    from books.core import config

    vault = tmp_path / "Vault"
    monkeypatch.setattr(ke, "KOBO_DEVICE_DB", tmp_path / "nope" / "KoboReader.sqlite")
    monkeypatch.setattr(
        config, "resolve_imports", lambda name, output=None: vault / ".imports" / name
    )

    app = typer.Typer()
    ke.register(app)
    result = CliRunner().invoke(app, [])

    assert result.exit_code != 0
