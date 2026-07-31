"""Tests for the calibre CSV-store writer using synthetic Calibre fixtures."""

from pathlib import Path

from books.commands import calibre
from books.core import store


def _make_calibre_book(root: Path, folder: str, opf: str, cover: bytes | None = None) -> None:
    book_dir = root / folder
    book_dir.mkdir(parents=True)
    (book_dir / "metadata.opf").write_text(opf, encoding="utf-8")
    if cover is not None:
        (book_dir / "cover.jpg").write_bytes(cover)


_OPF = """<?xml version='1.0'?>
<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>The Deluge</dc:title>
    <dc:creator opf:role="aut">Adam Tooze</dc:creator>
    <dc:identifier opf:scheme="ISBN">9780141032184</dc:identifier>
    <dc:subject>History</dc:subject>
    <meta name="calibre:rating" content="8"/>
  </metadata>
</package>
"""


def test_calibre_writes_layer_csv(tmp_path):
    lib = tmp_path / "lib"
    _make_calibre_book(lib, "Adam Tooze/The Deluge (1)", _OPF)
    vault = tmp_path / "vault"

    stats = calibre.convert(lib, vault)

    rows = store.read_layer(vault, "calibre")
    assert len(rows) == 1
    row = rows[0]
    assert row.title == "The Deluge"
    assert row.authors == ["Adam Tooze"]
    assert row.isbn == "9780141032184"
    assert row.format == "ebook"
    assert row.rating == "4"  # calibre 8/2 = 4.0 -> "4"
    assert stats["books"] == 1


def test_calibre_does_not_write_notes(tmp_path):
    lib = tmp_path / "lib"
    _make_calibre_book(lib, "Adam Tooze/The Deluge (1)", _OPF)
    vault = tmp_path / "vault"

    calibre.convert(lib, vault)

    # No book notes are created by calibre anymore (it is a pure CSV writer).
    assert not (vault / "Books").exists()


def test_calibre_stages_cover_and_records_path(tmp_path):
    lib = tmp_path / "lib"
    _make_calibre_book(lib, "Adam Tooze/The Deluge (1)", _OPF, cover=b"\xff\xd8\xff\xe0JPEGDATA")
    vault = tmp_path / "vault"

    stats = calibre.convert(lib, vault)

    row = store.read_layer(vault, "calibre")[0]
    staged = vault / row.cover
    assert staged.is_file()
    assert staged.read_bytes() == b"\xff\xd8\xff\xe0JPEGDATA"
    assert row.cover.startswith("Data/Sources/_covers/calibre/")
    assert stats["covers"] == 1


def test_calibre_rerun_replaces_layer(tmp_path):
    lib = tmp_path / "lib"
    _make_calibre_book(lib, "Adam Tooze/The Deluge (1)", _OPF)
    vault = tmp_path / "vault"
    calibre.convert(lib, vault)
    calibre.convert(lib, vault)  # re-run
    assert len(store.read_layer(vault, "calibre")) == 1  # not duplicated


def test_calibre_defaults_library_to_home_calibre_library(monkeypatch, tmp_path):
    from pathlib import Path as _Path

    import typer
    from typer.testing import CliRunner

    from books.commands import calibre as cal
    from books.core import config

    # Real config; only the config path is faked so resolve_vault has a vault.
    cfg = tmp_path / "config.toml"
    cfg.write_text('imports = ".imports"\n', encoding="utf-8")
    monkeypatch.setattr(config, "config_path", lambda: cfg)

    # Fake home so the default library resolves to <home>/Calibre Library.
    home = tmp_path / "home"
    monkeypatch.setattr(_Path, "home", classmethod(lambda cls: home))
    lib = home / "Calibre Library"
    lib.mkdir(parents=True)  # empty library -> convert() finds no books

    vault = tmp_path / "Vault"
    app = typer.Typer()
    cal.register(app)
    result = CliRunner().invoke(app, ["--output", str(vault)])

    # The default library must be ~/Calibre Library, independent of the vault.
    assert result.exit_code == 0, result.output
    assert "0 books" in result.output
