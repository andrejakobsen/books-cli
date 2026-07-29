"""Unit tests for the shared Obsidian helpers."""

from books.renderers import obsidian as ob


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


def test_format_rating():
    assert ob.format_rating(3) == "⭐⭐⭐"
    assert ob.format_rating(5) == "⭐⭐⭐⭐⭐"
    assert ob.format_rating(3.5) == "⭐⭐⭐⭐"   # rounds to nearest whole star
    assert ob.format_rating(0) == "⭐"           # present 0 -> one star
    assert ob.format_rating(0.4) == "⭐"         # rounds down to 0 -> one star
    assert ob.format_rating(None) == ""          # unrated -> blank


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


def test_render_marked_section_inserts_when_absent():
    note = '---\ntype: book\n---\n\nBody.\n'
    out = ob.render_marked_section(note, "Highlights", "highlights", "> quote one\n")
    assert "## Highlights" in out
    assert "%% books:highlights:start %%" in out
    assert "%% books:highlights:end %%" in out
    assert "> quote one" in out
    assert "Body." in out


def test_render_marked_section_replaces_only_between_markers():
    note = (
        '---\ntype: book\n---\n\n'
        '## Review\nMy own words.\n\n'
        '## Highlights\n%% books:highlights:start %%\nOLD\n%% books:highlights:end %%\n'
    )
    out = ob.render_marked_section(note, "Highlights", "highlights", "NEW\n")
    assert "NEW" in out
    assert "OLD" not in out
    assert "My own words." in out            # content outside markers untouched
    assert out.count("## Highlights") == 1    # heading not duplicated
    assert out.count("%% books:highlights:start %%") == 1


def test_render_marked_section_idempotent():
    note = '---\ntype: book\n---\n'
    once = ob.render_marked_section(note, "Highlights", "highlights", "A\n")
    twice = ob.render_marked_section(once, "Highlights", "highlights", "A\n")
    assert once == twice


def test_ensure_section_appends_once():
    note = '---\ntype: book\n---\n\nBody.\n'
    out = ob.ensure_section(note, "Review", "My review.\n")
    assert "## Review" in out
    assert "My review." in out
    # Write-once: a second call with different content is a no-op.
    again = ob.ensure_section(out, "Review", "Different.\n")
    assert again == out
    assert "Different." not in again


def test_ensure_top_embed_inserts_after_frontmatter():
    note = '---\ntype: book\ntitle: "T"\n---\n\nDescription here.\n'
    out = ob.ensure_top_embed(note, "![[Covers/T.jpg|150]]")
    lines = out.splitlines()
    # Embed appears immediately after the closing frontmatter fence.
    fence = lines.index("---", 1)
    assert lines[fence + 1] == "" and lines[fence + 2] == "![[Covers/T.jpg|150]]"
    assert "Description here." in out


def test_ensure_top_embed_noop_when_present():
    note = '---\ntype: book\n---\n\n![[Covers/T.jpg|150]]\n\nBody.\n'
    assert ob.ensure_top_embed(note, "![[Covers/T.jpg|150]]") == note


def test_cover_path_is_flat_keyed_to_note_stem(tmp_path):
    note_path = tmp_path / "Books" / "Napoleon - Andrew Roberts.md"
    assert ob.cover_path(note_path) == tmp_path / "Covers" / "Napoleon - Andrew Roberts.jpg"


def test_cover_refs_builds_vault_relative_wikilinks_with_width(tmp_path):
    note_path = tmp_path / "Books" / "Napoleon - Andrew Roberts.md"
    fm, embed = ob.cover_refs(note_path)
    assert fm == '"[[Covers/Napoleon - Andrew Roberts.jpg]]"'
    assert embed == "![[Covers/Napoleon - Andrew Roberts.jpg|150]]"


def test_property_order_uses_topics_not_genres():
    assert "topics" in ob.BOOK_PROPERTY_ORDER
    assert "genres" not in ob.BOOK_PROPERTY_ORDER
    assert "notes" not in ob.BOOK_PROPERTY_ORDER


def test_vaultindex_creates_new_note_with_stub(tmp_path):
    idx = ob.VaultIndex(tmp_path)
    ref = ob.BookRef(title="Napoleon: A Life", authors=["Andrew Roberts"], isbn=None)
    bn = idx.find_or_create(ref)
    assert bn.created is True
    # Filename drops the subtitle after ':' and appends '- <Author>'...
    assert bn.note_path == tmp_path / "Books" / "Napoleon - Andrew Roberts.md"
    text = bn.note_path.read_text()
    assert "type: book" in text
    assert 'title: "Napoleon: A Life"' in text
    assert "[[Andrew Roberts]]" in text
    # The book note no longer carries a personal-notes wikilink.
    assert "notes:" not in text


def test_vaultindex_matches_existing_by_title_author(tmp_path):
    books = tmp_path / "Books"
    books.mkdir(parents=True)
    note = books / "Napoleon A Life.md"
    note.write_text(
        '---\ntype: book\ntitle: "Napoleon - A Life"\n'
        'authors: ["[[Andrew Roberts]]"]\n---\nBody.\n', encoding="utf-8")
    idx = ob.VaultIndex(tmp_path)
    bn = idx.find_or_create(
        ob.BookRef(title="Napoleon: A Life", authors=["Andrew Roberts"], isbn=None))
    assert bn.created is False
    assert bn.note_path == note


def test_vaultindex_disambiguates_same_title_different_book(tmp_path):
    idx = ob.VaultIndex(tmp_path)
    a = idx.find_or_create(ob.BookRef(title="Selected Poems", authors=["W. H. Auden"]))
    b = idx.find_or_create(ob.BookRef(title="Selected Poems", authors=["Emily Dickinson"]))
    assert a.created and b.created
    # Author is always in the filename, so same-title different-author never collide.
    assert a.note_path == tmp_path / "Books" / "Selected Poems - W. H. Auden.md"
    assert b.note_path == tmp_path / "Books" / "Selected Poems - Emily Dickinson.md"


def test_new_note_filename_strips_subtitle_and_appends_author(tmp_path):
    idx = ob.VaultIndex(tmp_path)
    bn = idx.find_or_create(
        ob.BookRef(title="The Deluge: The Great War and the Remaking of Global Order",
                   authors=["Adam Tooze"]))
    assert bn.note_path.name == "The Deluge - Adam Tooze.md"


def test_new_note_filename_without_author_uses_title_only(tmp_path):
    idx = ob.VaultIndex(tmp_path)
    bn = idx.find_or_create(ob.BookRef(title="Beowulf: A New Translation"))
    assert bn.note_path.name == "Beowulf.md"


def test_new_note_filename_collision_keeps_subtitle_colon_as_comma(tmp_path):
    # Two Kotkin "Stalin" volumes both declutter to "Stalin - Stephen Kotkin".
    # The first claims the clean name; the colliding second keeps its subtitle,
    # with the illegal ':' rendered as ','.
    idx = ob.VaultIndex(tmp_path)
    a = idx.find_or_create(ob.BookRef(
        title="Stalin: Paradoxes of Power, 1878-1928",
        authors=["Stephen Kotkin"], isbn="111"))
    b = idx.find_or_create(ob.BookRef(
        title="Stalin: Waiting for Hitler, 1929-1941",
        authors=["Stephen Kotkin"], isbn="222"))
    assert a.note_path.name == "Stalin - Stephen Kotkin.md"
    assert b.note_path.name == "Stalin, Waiting for Hitler, 1929-1941 - Stephen Kotkin.md"


def test_new_note_filename_counter_when_full_title_also_collides(tmp_path):
    # Three authorless books with the same full title: short name, then
    # colon-as-comma full name, then a numeric suffix as last resort. (Authorless
    # so title/author matching never fuses them into one note.)
    idx = ob.VaultIndex(tmp_path)
    a = idx.find_or_create(ob.BookRef(title="Poems: Selected"))
    b = idx.find_or_create(ob.BookRef(title="Poems: Selected"))
    c = idx.find_or_create(ob.BookRef(title="Poems: Selected"))
    assert a.note_path.name == "Poems.md"
    assert b.note_path.name == "Poems, Selected.md"
    assert c.note_path.name == "Poems, Selected (2).md"


def test_vaultindex_find_returns_none_when_no_match(tmp_path):
    # find() is match-only: no existing note means None and nothing is created.
    idx = ob.VaultIndex(tmp_path)
    bn = idx.find(ob.BookRef(title="Napoleon: A Life", authors=["Andrew Roberts"]))
    assert bn is None
    assert not (tmp_path / "Books").exists()


def test_vaultindex_find_returns_existing_note(tmp_path):
    books = tmp_path / "Books"
    books.mkdir(parents=True)
    note = books / "Napoleon A Life.md"
    note.write_text(
        '---\ntype: book\ntitle: "Napoleon - A Life"\n'
        'authors: ["[[Andrew Roberts]]"]\n---\nBody.\n', encoding="utf-8")
    idx = ob.VaultIndex(tmp_path)
    bn = idx.find(
        ob.BookRef(title="Napoleon: A Life", authors=["Andrew Roberts"]))
    assert bn is not None
    assert bn.created is False
    assert bn.note_path == note


def test_source_in_property_order():
    from books.renderers import obsidian as ob
    assert "source" in ob.BOOK_PROPERTY_ORDER


def test_source_never_overwrites_existing():
    # "First metadata importer wins" on a shared note (spec addendum).
    from books.renderers import obsidian as ob
    note = "---\ntype: book\nsource: calibre\n---\n\nBody.\n"
    out = ob.update_frontmatter(note, {"source": "goodreads"})
    assert "source: calibre" in out
    assert "source: goodreads" not in out


def test_norm_amazon_uppercases_and_strips():
    assert ob.norm_amazon(" b00inixpye ") == "B00INIXPYE"
    assert ob.norm_amazon("B00-INIX_PYE") == "B00INIXPYE"


def test_norm_amazon_empty_is_none():
    assert ob.norm_amazon("") is None
    assert ob.norm_amazon(None) is None


def test_vaultindex_matches_existing_note_by_amazon(tmp_path):
    vault = tmp_path / "Obsidian"
    books = vault / "Books"
    books.mkdir(parents=True)
    (books / "Stalin.md").write_text(
        '---\ntype: book\ntitle: "Stalin"\namazon: "B00INIXPYE"\n---\n\nBody.\n',
        encoding="utf-8")
    index = ob.VaultIndex(vault)
    dest = index.find_or_create(
        ob.BookRef(title="Totally Different Title", authors=["Someone Else"],
                   amazon="b00inixpye"))
    assert dest.created is False
    assert dest.note_path.name == "Stalin.md"


def test_property_order_includes_flags_after_status():
    order = ob.BOOK_PROPERTY_ORDER
    assert "highlighted" in order
    assert "reviewed" in order
    assert order.index("highlighted") == order.index("status") + 1
    assert order.index("reviewed") == order.index("status") + 2


def test_overwrite_key_true_flips_existing_false():
    note = "---\ntype: book\nhighlighted: false\n---\n"
    out = ob.update_frontmatter(note, {"highlighted": "true"})
    assert "highlighted: true" in out
    assert "highlighted: false" not in out


def test_overwrite_key_false_default_does_not_downgrade_true():
    note = "---\ntype: book\nhighlighted: true\n---\n"
    out = ob.update_frontmatter(note, {"highlighted": "false"})
    assert "highlighted: true" in out
    assert "highlighted: false" not in out


def test_overwrite_key_false_default_appends_when_absent():
    note = "---\ntype: book\n---\n"
    out = ob.update_frontmatter(note, {"reviewed": "false"})
    assert "reviewed: false" in out


def test_non_overwrite_key_still_never_overwrites():
    note = '---\ntype: book\ntitle: "Keep"\n---\n'
    out = ob.update_frontmatter(note, {"title": ob.yaml_quote("New")})
    assert 'title: "Keep"' in out


def test_new_stub_carries_flag_defaults(tmp_path):
    idx = ob.VaultIndex(tmp_path)
    bn = idx.find_or_create(ob.BookRef(title="A Book", authors=["An Author"]))
    text = bn.note_path.read_text(encoding="utf-8")
    assert "highlighted: false" in text
    assert "reviewed: false" in text
