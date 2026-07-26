"""Unit tests for the shared Obsidian helpers."""

from booktools import obsidian as ob


def test_safe_filename_replaces_illegal_chars():
    assert ob.safe_filename("A: B / C?") == "A_ B _ C_"
    assert ob.safe_filename("  spaced  out  ") == "spaced out"
    assert ob.safe_filename("trailing. ") == "trailing"
    assert ob.safe_filename("///") == "___"
    assert ob.safe_filename("") == "Untitled"


def test_yaml_quote_and_links():
    assert ob.yaml_quote('he said "hi"') == '"he said \\"hi\\""'
    assert ob.wikilink("A|B#C") == "[[A-BC]]"
    assert ob.link_list(["X", "Y"]) == '["[[X]]", "[[Y]]"]'
    assert ob.plain_list(["read", "fiction"]) == '["read", "fiction"]'


def test_update_frontmatter_fills_blank_only():
    note = '---\ntype: book\ntitle: "Keep"\nrating:\n---\n\nbody text\n'
    out = ob.update_frontmatter(note, {
        "title": ob.yaml_quote("New"),   # existing non-empty -> untouched
        "rating": "5",                   # existing blank -> filled
        "status": ob.yaml_quote("read"), # absent -> added
    })
    assert 'title: "Keep"' in out
    assert "rating: 5" in out
    assert 'status: "read"' in out
    assert "body text" in out  # body preserved


def test_update_frontmatter_no_frontmatter_prepends_block():
    out = ob.update_frontmatter("just a body\n", {"title": ob.yaml_quote("T")})
    assert out.startswith("---\n")
    assert 'title: "T"' in out
    assert "just a body" in out


def test_update_frontmatter_empty_update_adds_placeholder():
    out = ob.update_frontmatter("---\ntype: book\n---\n", {"pages": ""})
    assert "pages:" in out


def test_frontmatter_values_and_extractors():
    note = '---\ntype: book\ntitle: "Napoleon: A Life"\nisbn: "9780698176287"\nauthors: ["[[Andrew Roberts]]"]\n---\nbody\n'
    fm = ob.frontmatter_values(note)
    assert ob.unquote(fm["title"]) == "Napoleon: A Life"
    assert ob.unquote(fm["isbn"]) == "9780698176287"
    assert ob.extract_wikilinks(fm["authors"]) == ["Andrew Roberts"]


def test_html_to_markdown_list():
    md = ob.html_to_markdown("<p>Intro</p><ul><li>one</li><li>two</li></ul>")
    assert "Intro" in md and "- one" in md and "- two" in md


def test_ensure_embed_section_adds_when_absent():
    note = '---\ntype: book\n---\n\nBody.\n'
    out = ob.ensure_embed_section(note, "Highlights", "Highlights.md")
    assert "## Highlights" in out
    assert "![](Highlights.md)" in out
    assert "Body." in out


def test_ensure_embed_section_noop_when_present():
    note = '---\ntype: book\n---\n\n## Highlights\n![](Highlights.md)\n'
    assert ob.ensure_embed_section(note, "Highlights", "Highlights.md") == note


def test_vaultindex_creates_new_note_with_stub(tmp_path):
    idx = ob.VaultIndex(tmp_path)
    ref = ob.BookRef(title="Napoleon: A Life", authors=["Andrew Roberts"], isbn=None)
    note, created = idx.find_or_create(ref)
    assert created is True
    assert note == tmp_path / "Andrew Roberts" / "Napoleon_ A Life" / "Napoleon_ A Life.md"
    text = note.read_text()
    assert "type: book" in text
    assert 'title: "Napoleon: A Life"' in text
    assert "[[Andrew Roberts]]" in text


def test_vaultindex_matches_existing_by_title_author(tmp_path):
    book_dir = tmp_path / "Andrew Roberts" / "Napoleon A Life"
    book_dir.mkdir(parents=True)
    note = book_dir / "Napoleon A Life.md"
    note.write_text(
        '---\ntype: book\ntitle: "Napoleon - A Life"\n'
        'authors: ["[[Andrew Roberts]]"]\n---\nBody.\n', encoding="utf-8")
    idx = ob.VaultIndex(tmp_path)
    found, created = idx.find_or_create(
        ob.BookRef(title="Napoleon: A Life", authors=["Andrew Roberts"], isbn=None))
    assert created is False
    assert found == note


def test_write_leaf_with_embed_overwrites_and_embeds(tmp_path):
    note = tmp_path / "Book" / "Book.md"
    note.parent.mkdir(parents=True)
    note.write_text('---\ntype: book\n---\n\nBody.\n', encoding="utf-8")
    wrote = ob.write_leaf_with_embed(note, "Highlights.md", "content v1\n", "Highlights")
    assert wrote is True
    assert (note.parent / "Highlights.md").read_text() == "content v1\n"
    assert "![](Highlights.md)" in note.read_text()
    # Second call overwrites the leaf but does not duplicate the embed.
    ob.write_leaf_with_embed(note, "Highlights.md", "content v2\n", "Highlights")
    assert (note.parent / "Highlights.md").read_text() == "content v2\n"
    assert note.read_text().count("## Highlights") == 1


def test_write_leaf_with_embed_no_overwrite_keeps_existing(tmp_path):
    note = tmp_path / "Book" / "Book.md"
    note.parent.mkdir(parents=True)
    note.write_text('---\ntype: book\n---\n', encoding="utf-8")
    (note.parent / "Review.md").write_text("original\n", encoding="utf-8")
    wrote = ob.write_leaf_with_embed(note, "Review.md", "new\n", "Review", overwrite=False)
    assert wrote is False
    assert (note.parent / "Review.md").read_text() == "original\n"  # not clobbered
    assert "![](Review.md)" in note.read_text()  # embed still ensured


def test_with_source_prepends_frontmatter():
    from booktools import obsidian as ob
    out = ob.with_source("kobo", "> [!quote]+ p. 4\n> Hi\n^p4\n")
    assert out.startswith("---\nsource: kobo\n---\n")
    assert "> [!quote]+ p. 4" in out
    assert "^p4" in out


def test_with_source_frontmatter_has_no_book_type():
    from booktools import obsidian as ob
    out = ob.with_source("highlighted", "body\n")
    # A leaf must not look like a book note to the vault index.
    assert ob.unquote(ob.frontmatter_values(out).get("type", "")) != "book"
    assert ob.frontmatter_values(out).get("source") == "highlighted"


def test_source_in_property_order():
    from booktools import obsidian as ob
    assert "source" in ob.BOOK_PROPERTY_ORDER


def test_source_never_overwrites_existing():
    # "First metadata importer wins" on a shared note (spec addendum).
    from booktools import obsidian as ob
    note = "---\ntype: book\nsource: calibre\n---\n\nBody.\n"
    out = ob.update_frontmatter(note, {"source": "goodreads"})
    assert "source: calibre" in out
    assert "source: goodreads" not in out
