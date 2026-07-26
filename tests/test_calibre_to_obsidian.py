"""Tests for calibre_to_obsidian using a synthetic Calibre library fixture."""

import textwrap
from pathlib import Path

from booktools import calibre_obsidian as c2o


OPF_WITH_COVER = """<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
        <dc:identifier opf:scheme="calibre" id="calibre_id">9</dc:identifier>
        <dc:identifier opf:scheme="uuid" id="uuid_id">abc-123</dc:identifier>
        <dc:title>Napoleon: A Life</dc:title>
        <dc:creator opf:role="aut">Andrew Roberts</dc:creator>
        <dc:date>2014-11-03T23:00:00+00:00</dc:date>
        <dc:description>&lt;div&gt;&lt;p&gt;A &lt;b&gt;great&lt;/b&gt; book.&lt;/p&gt;&lt;/div&gt;</dc:description>
        <dc:publisher>Penguin</dc:publisher>
        <dc:identifier opf:scheme="ISBN">9780698176287</dc:identifier>
        <dc:identifier opf:scheme="GOOGLE">rjVBAwAAQBAJ</dc:identifier>
        <dc:language>eng</dc:language>
        <dc:subject>Biography &amp; Autobiography</dc:subject>
        <dc:subject>Military</dc:subject>
        <meta name="calibre:rating" content="8"/>
        <meta name="calibre:timestamp" content="2026-06-04T07:48:08+00:00"/>
    </metadata>
</package>
"""

OPF_NO_COVER = """<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
        <dc:title>No Cover Book</dc:title>
        <dc:creator opf:role="aut">Jane Doe</dc:creator>
        <dc:subject>Fiction</dc:subject>
    </metadata>
</package>
"""


def make_library(tmp_path: Path) -> Path:
    lib = tmp_path / "Calibre Library"
    b1 = lib / "Andrew Roberts" / "Napoleon_ A Life (9)"
    b1.mkdir(parents=True)
    (b1 / "metadata.opf").write_text(OPF_WITH_COVER, encoding="utf-8")
    (b1 / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    (b1 / "Napoleon.epub").write_bytes(b"PK\x03\x04ebook")  # must be ignored

    b2 = lib / "Jane Doe" / "No Cover Book (5)"
    b2.mkdir(parents=True)
    (b2 / "metadata.opf").write_text(OPF_NO_COVER, encoding="utf-8")

    # Calibre internals that must be ignored.
    (lib / ".caltrash").mkdir()
    (lib / ".caltrash" / "metadata.opf").write_text(OPF_NO_COVER, encoding="utf-8")
    (lib / "metadata.db").write_bytes(b"sqlite")
    return lib


def test_full_conversion(tmp_path):
    lib = make_library(tmp_path)
    out = tmp_path / "Obsidian"
    stats = c2o.convert(lib, out)

    assert stats["books"] == 2
    assert stats["covers"] == 1

    note = (out / "Books" / "Napoleon - Andrew Roberts.md").read_text()
    cover_rel = "Covers/Napoleon - Andrew Roberts.jpg"
    # Frontmatter values
    assert "type: book" in note
    assert 'title: "Napoleon: A Life"' in note
    assert 'authors: ["[[Andrew Roberts]]"]' in note
    assert '"[[Biography & Autobiography]]"' in note
    assert '"[[Military]]"' in note
    assert 'publisher: "Penguin"' in note
    assert "published: 2014-11-03" in note
    assert "language: eng" in note
    assert "format: ebook" in note  # Calibre books default to ebook
    assert "rating: ⭐⭐⭐⭐" in note  # 8/2 -> 4 stars
    assert 'isbn: "9780698176287"' in note
    assert 'google: "rjVBAwAAQBAJ"' in note
    assert "date_added: 2026-06-04" in note
    assert "source: calibre" in note
    assert f'cover: "[[{cover_rel}]]"' in note
    # Body (cover embed carries the fixed display width)
    assert f"![[{cover_rel}|150]]" in note
    assert "**great**" in note

    # Cover copied into the flat Covers/ folder
    assert (out / "Covers" / "Napoleon - Andrew Roberts.jpg").is_file()


def test_missing_cover(tmp_path):
    lib = make_library(tmp_path)
    out = tmp_path / "Obsidian"
    c2o.convert(lib, out)

    note = (out / "Books" / "No Cover Book - Jane Doe.md").read_text()
    assert "cover:\n" in note or note.rstrip().endswith("cover:")  # empty placeholder
    assert "cover.jpg" not in note                                 # no body embed / ref
    assert "rating:" in note  # empty rating still present
    assert not (out / "Covers" / "No Cover Book - Jane Doe.jpg").exists()


def test_book_note_has_goodreads_placeholders(tmp_path):
    lib = make_library(tmp_path)
    out = tmp_path / "Obsidian"
    c2o.convert(lib, out)
    note = (out / "Books" / "Napoleon - Andrew Roberts.md").read_text()
    for key in ("pages:", "status:", "shelves:", "date_read:"):
        assert key in note


def test_rerun_preserves_book_note_edits(tmp_path):
    lib = make_library(tmp_path)
    out = tmp_path / "Obsidian"
    c2o.convert(lib, out)
    note = out / "Books" / "Napoleon - Andrew Roberts.md"
    note.write_text(note.read_text().replace("status:", "status: reading"), encoding="utf-8")

    c2o.convert(lib, out)  # re-run must not clobber the manual edit
    assert "status: reading" in note.read_text()
    assert 'title: "Napoleon: A Life"' in note.read_text()


def test_ebook_and_internals_ignored(tmp_path):
    lib = make_library(tmp_path)
    out = tmp_path / "Obsidian"
    c2o.convert(lib, out)

    copied = [p.name for p in out.rglob("*")]
    assert "Napoleon.epub" not in copied
    assert "metadata.db" not in copied
    # .caltrash book should not have produced a note
    assert not (out / ".caltrash").exists()


def test_stub_hub_notes(tmp_path):
    lib = make_library(tmp_path)
    out = tmp_path / "Obsidian"
    c2o.convert(lib, out)

    author = (out / "Authors" / "Andrew Roberts.md").read_text()
    assert "type: author" in author
    topic = (out / "Topics" / "Biography & Autobiography.md").read_text()
    assert "type: topic" in topic


def test_rerun_preserves_user_files(tmp_path):
    lib = make_library(tmp_path)
    out = tmp_path / "Obsidian"
    c2o.convert(lib, out)

    # User adds a personal note and edits an author stub.
    note = out / "Notes" / "Napoleon - Andrew Roberts.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("# My thoughts\n- a point", encoding="utf-8")
    author_stub = out / "Authors" / "Andrew Roberts.md"
    author_stub.write_text("---\ntype: author\n---\nMy notes on Roberts.", encoding="utf-8")

    c2o.convert(lib, out)  # re-run

    assert note.read_text() == "# My thoughts\n- a point"
    assert "My notes on Roberts." in author_stub.read_text()


def test_calibre_defaults_library_to_home_calibre_library(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner
    from pathlib import Path as _Path
    from booktools import calibre_obsidian as cal, config

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


def test_html_to_markdown_list():
    html = "<p>Intro</p><ul><li>one</li><li>two</li></ul>"
    md = c2o.html_to_markdown(html)
    assert "Intro" in md
    assert "- one" in md
    assert "- two" in md
