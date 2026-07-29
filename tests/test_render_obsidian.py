import frontmatter

from books import render_obsidian as R


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
