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
