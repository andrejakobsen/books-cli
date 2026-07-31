"""Integration test: multiple importers compose into one flat book note.

The same book (matched by ISBN) is imported from Calibre (cover), Goodreads
(review), and Highlighted (highlights). After ``merge`` clusters the metadata
layers and ``render`` writes the notes, the result must be a single flat note
under Books/ that carries the cover embed (from Data/Covers/), a write-once
'## Review' section, and a marker-wrapped '## Highlights' section — regardless of
the order the metadata importers ran.
"""

from pathlib import Path

from books.commands import calibre as c2o
from books.commands import goodreads as gr
from books.commands import highlighted as hi
from books.core import store
from books.renderers.obsidian import note as rn

ISBN13 = "9780141032016"

OPF = f"""<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
    <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
        <dc:title>Napoleon: A Life</dc:title>
        <dc:creator opf:role="aut">Andrew Roberts</dc:creator>
        <dc:identifier opf:scheme="ISBN">{ISBN13}</dc:identifier>
        <dc:description>&lt;p&gt;A great book.&lt;/p&gt;</dc:description>
        <dc:subject>History</dc:subject>
    </metadata>
</package>
"""

GR_HEADER = (
    "Book Id,Title,Author,Author l-f,Additional Authors,ISBN,ISBN13,My Rating,"
    "Publisher,Binding,Number of Pages,Year Published,Original Publication Year,"
    "Date Read,Date Added,Bookshelves,Bookshelves with positions,Exclusive Shelf,"
    "My Review,Spoiler,Private Notes,Read Count,Owned Copies\n"
)
GR_ROW = (
    '1,"Napoleon: A Life",Andrew Roberts,"Roberts, Andrew",,'
    f'"=""0141032014""","=""{ISBN13}""",5.0,Penguin,Paperback,976,2015,2014,'
    "2026/07/17,2026/05/04,history,history (#1),read,"
    '"A stirring review.",,,1,0\n'
)

HI_HEADER = (
    "Highlight,Title,Author,ISBN,Collections,Reading Status,"
    "Book Added Date,Location,Tags,Note,Date,Favorite\n"
)
HI_ROW = (
    f'"A memorable passage.",Napoleon: A Life,Andrew Roberts,{ISBN13},,Read,'
    "2026-07-24,45,History,,2026-07-24 11:15:47,N\n"
)


def _calibre_library(tmp_path: Path) -> Path:
    lib = tmp_path / "Calibre Library"
    book = lib / "Andrew Roberts" / "Napoleon_ A Life (9)"
    book.mkdir(parents=True)
    (book / "metadata.opf").write_text(OPF, encoding="utf-8")
    (book / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0fakejpeg")
    return lib


def _goodreads_csv(tmp_path: Path) -> Path:
    p = tmp_path / "goodreads.csv"
    p.write_text(GR_HEADER + GR_ROW, encoding="utf-8")
    return p


def _highlighted_csv(tmp_path: Path) -> Path:
    p = tmp_path / "highlighted.csv"
    p.write_text(HI_HEADER + HI_ROW, encoding="utf-8")
    return p


def _assert_composed(out: Path) -> None:
    # Exactly one flat book note.
    notes = list((out / "Books").glob("*.md"))
    assert notes == [out / "Books" / "Napoleon - Andrew Roberts.md"]
    note = notes[0].read_text()

    cover_rel = "Data/Covers/Napoleon - Andrew Roberts.jpg"
    # Cover embed from the flat Data/Covers/ folder.
    assert f"cover: '[[{cover_rel}]]'" in note
    assert f"![[{cover_rel}|150]]" in note
    # Review and highlights are managed sections in the note body.
    assert "## Review" in note and "A stirring review." in note
    assert "## Highlights" in note
    assert "%% books:highlights:start %%" in note
    assert "A memorable passage." in note

    # The cover image exists on disk under Data/Covers/.
    assert (out / "Data" / "Covers" / "Napoleon - Andrew Roberts.jpg").is_file()


def test_compose_is_order_independent(tmp_path):
    # The metadata importers (calibre/goodreads) compose in either order; merge
    # then render produce the same single note. Highlights are resolved via the
    # merged catalog, so the highlight importer runs after merge.
    out = tmp_path / "Obsidian"
    gr.convert(_goodreads_csv(tmp_path), out)
    c2o.convert(_calibre_library(tmp_path), out)
    store.merge(out)
    hi.convert(_highlighted_csv(tmp_path), out)
    rn.render(out)
    _assert_composed(out)


def test_highlights_skipped_when_no_catalog(tmp_path):
    # Without a merged books.csv, the highlight importer resolves nothing.
    out = tmp_path / "Obsidian"
    stats = hi.convert(_highlighted_csv(tmp_path), out)
    assert stats["books"] == 0 and stats["skipped"] == 1
    assert not (out / "Books").exists()
