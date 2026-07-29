import frontmatter

from books import render_obsidian as R
from books import store


def test_render_rating_numeric_and_passthrough():
    assert R.render_rating("4") == "⭐⭐⭐⭐"
    assert R.render_rating("") == ""
    assert R.render_rating("physical") == "physical"   # non-numeric passes through


def test_dump_frontmatter_roundtrips_wikilinks_and_unicode():
    meta = {
        "type": "book",
        "title": "Café",
        "authors": ["[[Adam Tooze]]"],
        "highlighted": True,
        "rating": "⭐⭐⭐",
        "series": None,
    }
    text = "---\n" + R.dump_frontmatter(meta) + "---\n\nbody\n"
    post = frontmatter.loads(text)
    assert post["title"] == "Café"
    assert post["authors"] == ["[[Adam Tooze]]"]   # wikilink survives quoting
    assert post["highlighted"] is True
    assert post["rating"] == "⭐⭐⭐"                 # emoji not escaped
    assert post.content.strip() == "body"


def test_load_note_missing_returns_empty(tmp_path):
    assert R.load_note(tmp_path / "none.md") == ({}, "")


def test_note_property_order_drops_source():
    assert "source" not in R.NOTE_PROPERTY_ORDER
    assert R.NOTE_PROPERTY_ORDER[0] == "type"
    assert "topics" in R.NOTE_PROPERTY_ORDER


def test_book_frontmatter_authoritative_and_derived(tmp_path):
    note = tmp_path / "Books" / "The Deluge - Adam Tooze.md"
    row = store.BookRow(
        book_id="The Deluge - Adam Tooze", title="The Deluge",
        authors=["Adam Tooze"], format="ebook", shelves=["read"],
        rating="4", review="Great book",
    )
    meta = R.book_frontmatter(row, note, existing={}, has_highlights=True)
    assert meta["type"] == "book"
    assert meta["authors"] == ["[[Adam Tooze]]"]
    assert meta["highlighted"] is True     # derived from has_highlights
    assert meta["reviewed"] is True        # derived from row.review
    assert meta["rating"] == "⭐⭐⭐⭐"
    assert meta["shelves"] == ["read"]
    assert list(meta.keys())[0] == "type"  # canonical order
    assert "source" not in meta


def test_book_frontmatter_preserves_existing_topics(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"])
    meta = R.book_frontmatter(
        row, note, existing={"topics": ["[[History]]"]}, has_highlights=False)
    assert meta["topics"] == ["[[History]]"]
    assert meta["highlighted"] is False
    assert meta["reviewed"] is False


def test_book_frontmatter_new_note_gets_empty_topics(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"])
    meta = R.book_frontmatter(row, note, existing={}, has_highlights=False)
    assert meta["topics"] == []


def test_book_frontmatter_cover_when_row_has_cover(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"],
                        cover="[[Covers/X - A.jpg]]")
    meta = R.book_frontmatter(row, note, existing={}, has_highlights=False)
    assert meta["cover"] == "[[Covers/X - A.jpg]]"
