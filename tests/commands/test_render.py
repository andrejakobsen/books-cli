import frontmatter
from typer.testing import CliRunner

from books.cli import app
from books.commands import render as R
from books.core import store


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


def test_book_frontmatter_cover_when_cover_file_exists(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    cover = tmp_path / "Data" / "Covers" / "X - A.jpg"
    cover.parent.mkdir(parents=True)
    cover.write_bytes(b"\xff\xd8\xff\xe0IMG")
    row = store.BookRow(book_id="X - A", title="X", authors=["A"])
    meta = R.book_frontmatter(row, note, existing={}, has_highlights=False)
    assert meta["cover"] == "[[Data/Covers/X - A.jpg]]"


def test_book_frontmatter_no_cover_when_file_missing(tmp_path):
    # A row that records a staged cover path whose materialized file is absent
    # must NOT emit a dangling cover reference.
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"],
                        cover="Data/Sources/_covers/calibre/0.jpg")
    meta = R.book_frontmatter(row, note, existing={}, has_highlights=False)
    assert meta["cover"] is None


def test_render_body_cover_review_and_highlights(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    cover = tmp_path / "Data" / "Covers" / "X - A.jpg"
    cover.parent.mkdir(parents=True)
    cover.write_bytes(b"\xff\xd8\xff\xe0IMG")
    row = store.BookRow(book_id="X - A", title="X", authors=["A"],
                        review="My review")
    hls = [store.HighlightRow(source="kobo", annotation_id="1", text="quote one",
                              location="42", location_kind="percent")]
    body = R.render_body("", row, note, hls)
    assert "![[Data/Covers/X - A.jpg|150]]" in body
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


def test_render_writes_notes_from_store(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "calibre", [
        store.BookRow(title="The Deluge", authors=["Adam Tooze"], format="ebook",
                      isbn="9780141032184"),
    ])
    store.merge(vault)
    bid = "The Deluge - Adam Tooze"
    store.write_highlights(vault, bid, "kobo", [
        store.HighlightRow(source="kobo", annotation_id="1", text="an insight",
                           location="42", location_kind="percent"),
    ])
    stats = R.render(vault)
    note = vault / "Books" / f"{bid}.md"
    assert note.is_file()
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert post["title"] == "The Deluge"
    assert post["highlighted"] is True
    assert "an insight" in post.content
    assert stats == {"notes": 1, "highlights": 1, "reviews": 0, "failed": 0}


def test_render_empty_catalog_is_noop(tmp_path):
    assert R.render(tmp_path / "vault") == {
        "notes": 0, "highlights": 0, "reviews": 0, "failed": 0}


def test_render_continues_past_a_corrupted_note(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "calibre", [
        store.BookRow(title="Good", authors=["A"], format="ebook"),
        store.BookRow(title="Bad", authors=["B"], format="ebook"),
    ])
    store.merge(vault)
    # Corrupt the "Bad" note's frontmatter so load_note/render_note raises.
    bad = vault / "Books" / "Bad - B.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("---\ntopics: [unclosed\n---\n\nbody\n", encoding="utf-8")
    stats = R.render(vault)
    assert stats["failed"] == 1
    assert stats["notes"] == 1
    assert (vault / "Books" / "Good - A.md").is_file()


def test_render_command_renders_vault(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "calibre",
                      [store.BookRow(title="X", authors=["A"], format="ebook")])
    store.merge(vault)
    result = CliRunner().invoke(app, ["render", "--output", str(vault)])
    assert result.exit_code == 0, result.output
    assert (vault / "Books" / "X - A.md").is_file()


def test_render_command_errors_without_books_csv(tmp_path):
    result = CliRunner().invoke(app, ["render", "--output", str(tmp_path / "vault")])
    assert result.exit_code != 0


def test_render_command_no_obsidian_errors(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "calibre",
                      [store.BookRow(title="X", authors=["A"], format="ebook")])
    store.merge(vault)
    result = CliRunner().invoke(app, ["render", "--no-obsidian", "--output", str(vault)])
    assert result.exit_code != 0


def test_book_frontmatter_preserves_aliases_and_cssclasses(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"])
    existing = {"topics": ["[[History]]"], "aliases": ["The X Book"],
                "cssclasses": ["book"]}
    meta = R.book_frontmatter(row, note, existing=existing, has_highlights=False)
    assert meta["aliases"] == ["The X Book"]
    assert meta["cssclasses"] == ["book"]
    keys = list(meta.keys())
    assert keys.index("topics") < keys.index("aliases") < keys.index("cssclasses")


def test_book_frontmatter_omits_absent_aliases_cssclasses(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"])
    meta = R.book_frontmatter(row, note, existing={}, has_highlights=False)
    assert "aliases" not in meta
    assert "cssclasses" not in meta


def test_render_materializes_staged_cover(tmp_path):
    vault = tmp_path / "vault"
    staged = store.sources_dir(vault) / "_covers" / "calibre" / "0.jpg"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"\xff\xd8\xff\xe0IMG")
    row = store.BookRow(
        book_id="The Deluge - Adam Tooze", title="The Deluge",
        authors=["Adam Tooze"], format="ebook",
        cover="Data/Sources/_covers/calibre/0.jpg",
    )
    R.render_note(vault, row, [])

    dest = vault / "Data" / "Covers" / "The Deluge - Adam Tooze.jpg"
    assert dest.is_file()
    assert dest.read_bytes() == b"\xff\xd8\xff\xe0IMG"

    note_text = (vault / "Books" / "The Deluge - Adam Tooze.md").read_text(
        encoding="utf-8")
    assert "![[Data/Covers/The Deluge - Adam Tooze.jpg|150]]" in note_text

    # Idempotent: a second render doesn't error and leaves the cover unchanged.
    R.render_note(vault, row, [])
    assert dest.read_bytes() == b"\xff\xd8\xff\xe0IMG"


def test_render_note_preserves_aliases_across_rerender(tmp_path):
    vault = tmp_path / "vault"
    note = vault / "Books" / "X - A.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        '---\ntype: book\ntitle: X\ntopics: []\naliases:\n- Alt Name\n'
        'cssclasses:\n- book\n---\n\nManual.\n', encoding="utf-8")
    row = store.BookRow(book_id="X - A", title="X", authors=["A"], format="ebook")
    R.render_note(vault, row, [])
    first = note.read_text(encoding="utf-8")
    import frontmatter
    post = frontmatter.loads(first)
    assert post["aliases"] == ["Alt Name"]
    assert post["cssclasses"] == ["book"]
    R.render_note(vault, row, [])            # idempotent with preserved keys
    assert note.read_text(encoding="utf-8") == first
