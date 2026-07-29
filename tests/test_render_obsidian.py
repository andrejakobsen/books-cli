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


def test_render_body_cover_review_and_highlights(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"],
                        review="My review", cover="[[Covers/X - A.jpg]]")
    hls = [store.HighlightRow(source="kobo", annotation_id="1", text="quote one",
                              location="42", location_kind="percent")]
    body = R.render_body("", row, note, hls)
    assert "![[Covers/X - A.jpg|150]]" in body
    assert "## Review" in body and "My review" in body
    assert "## Highlights" in body and "quote one" in body
    assert "%% books:highlights:start %%" in body


def test_render_body_review_is_write_once(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"], review="My review")
    once = R.render_body("", row, note, [])
    twice = R.render_body(once, row, note, [])
    assert twice.count("## Review") == 1


def test_render_body_mixed_source_groups(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"])
    hls = [
        store.HighlightRow(source="kobo", annotation_id="1", text="k",
                           location="10", location_kind="percent"),
        store.HighlightRow(source="readwise", annotation_id="2", text="r",
                           location="20", location_kind="percent"),
    ]
    body = R.render_body("", row, note, hls)
    assert "### Kobo" in body
    assert "### Readwise" in body


def test_render_body_preserves_existing_content(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"])
    body = R.render_body("My own paragraph.", row, note, [])
    assert "My own paragraph." in body


def test_render_note_creates_note_at_book_id_path(tmp_path):
    vault = tmp_path / "vault"
    row = store.BookRow(book_id="The Deluge - Adam Tooze", title="The Deluge",
                        authors=["Adam Tooze"], format="ebook")
    path = R.render_note(vault, row, [])
    assert path == vault / "Books" / "The Deluge - Adam Tooze.md"
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    assert post["title"] == "The Deluge"
    assert post["format"] == "ebook"
    assert post["highlighted"] is False


def test_render_note_is_idempotent(tmp_path):
    vault = tmp_path / "vault"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"], format="ebook",
                        review="A review")
    hls = [store.HighlightRow(source="kobo", annotation_id="1", text="hi",
                              location="10", location_kind="percent")]
    path = R.render_note(vault, row, hls)
    first = path.read_text(encoding="utf-8")
    R.render_note(vault, row, hls)
    assert path.read_text(encoding="utf-8") == first   # render twice == identical


def test_render_note_preserves_topics_and_manual_body(tmp_path):
    vault = tmp_path / "vault"
    note = vault / "Books" / "X - A.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        '---\ntype: book\ntitle: X\ntopics:\n- "[[History]]"\n---\n\n'
        'My own paragraph.\n', encoding="utf-8")
    row = store.BookRow(book_id="X - A", title="X", authors=["A"], format="ebook")
    R.render_note(vault, row, [])
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert post["topics"] == ["[[History]]"]     # user-owned, preserved
    assert post["format"] == "ebook"             # refreshed from the row
    assert "My own paragraph." in post.content   # manual body preserved
