"""Unit tests for the shared Obsidian helpers."""

from books.core.matching import norm_amazon
from books.core.naming import safe_filename
from books.renderers import obsidian as ob


def test_safe_filename_replaces_illegal_chars():
    assert safe_filename("A: B / C?") == "A_ B _ C_"
    assert safe_filename("  spaced  out  ") == "spaced out"
    assert safe_filename("trailing. ") == "trailing"
    assert safe_filename("///") == "___"
    assert safe_filename("") == "Untitled"


def test_wikilink_sanitizes_illegal_chars():
    assert ob.wikilink("A|B#C") == "[[A-BC]]"


def test_format_rating():
    assert ob.format_rating(3) == "⭐⭐⭐"
    assert ob.format_rating(5) == "⭐⭐⭐⭐⭐"
    assert ob.format_rating(3.5) == "⭐⭐⭐⭐"  # rounds to nearest whole star
    assert ob.format_rating(0) == "⭐"  # present 0 -> one star
    assert ob.format_rating(0.4) == "⭐"  # rounds down to 0 -> one star
    assert ob.format_rating(None) == ""  # unrated -> blank


def test_render_marked_section_inserts_when_absent():
    note = "---\ntype: book\n---\n\nBody.\n"
    out = ob.render_marked_section(note, "Highlights", "highlights", "> quote one\n")
    assert "## Highlights" in out
    assert "%% books:highlights:start %%" in out
    assert "%% books:highlights:end %%" in out
    assert "> quote one" in out
    assert "Body." in out


def test_render_marked_section_replaces_only_between_markers():
    note = (
        "---\ntype: book\n---\n\n"
        "## Review\nMy own words.\n\n"
        "## Highlights\n%% books:highlights:start %%\nOLD\n%% books:highlights:end %%\n"
    )
    out = ob.render_marked_section(note, "Highlights", "highlights", "NEW\n")
    assert "NEW" in out
    assert "OLD" not in out
    assert "My own words." in out  # content outside markers untouched
    assert out.count("## Highlights") == 1  # heading not duplicated
    assert out.count("%% books:highlights:start %%") == 1


def test_render_marked_section_idempotent():
    note = "---\ntype: book\n---\n"
    once = ob.render_marked_section(note, "Highlights", "highlights", "A\n")
    twice = ob.render_marked_section(once, "Highlights", "highlights", "A\n")
    assert once == twice


def test_ensure_section_appends_once():
    note = "---\ntype: book\n---\n\nBody.\n"
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
    note = "---\ntype: book\n---\n\n![[Covers/T.jpg|150]]\n\nBody.\n"
    assert ob.ensure_top_embed(note, "![[Covers/T.jpg|150]]") == note


def test_property_order_uses_topics_not_genres():
    assert "topics" in ob.BOOK_PROPERTY_ORDER
    assert "genres" not in ob.BOOK_PROPERTY_ORDER
    assert "notes" not in ob.BOOK_PROPERTY_ORDER


def test_source_in_property_order():
    assert "source" in ob.BOOK_PROPERTY_ORDER


def test_norm_amazon_uppercases_and_strips():
    assert norm_amazon(" b00inixpye ") == "B00INIXPYE"
    assert norm_amazon("B00-INIX_PYE") == "B00INIXPYE"


def test_norm_amazon_empty_is_none():
    assert norm_amazon("") is None
    assert norm_amazon(None) is None


def test_property_order_includes_flags_after_status():
    order = ob.BOOK_PROPERTY_ORDER
    assert "highlighted" in order
    assert "reviewed" in order
    assert order.index("highlighted") == order.index("status") + 1
    assert order.index("reviewed") == order.index("status") + 2
