"""Unit tests for the source-agnostic highlights layer."""

from booktools import highlights as hl


def test_build_anchors_chapter_and_location():
    hs = [hl.Highlight(text="a", chapter_index=2, block="17", segment="5")]
    assert hl.build_anchors(hs) == ["ch2-b17-5"]


def test_build_anchors_missing_chapter_drops_prefix():
    hs = [hl.Highlight(text="a", block="17", segment="5")]
    assert hl.build_anchors(hs) == ["b17-5"]


def test_build_anchors_missing_location_uses_counter():
    hs = [
        hl.Highlight(text="a", chapter_index=2),
        hl.Highlight(text="b", chapter_index=2),
    ]
    assert hl.build_anchors(hs) == ["ch2-hl1", "ch2-hl2"]


def test_build_anchors_dedupes_collisions():
    hs = [
        hl.Highlight(text="a", chapter_index=2, block="17", segment="5"),
        hl.Highlight(text="b", chapter_index=2, block="17", segment="5"),
    ]
    assert hl.build_anchors(hs) == ["ch2-b17-5", "ch2-b17-5-2"]


def test_render_single_highlight_no_note():
    hs = [hl.Highlight(text="A line", chapter_index=2, progress=0.42,
                       block="17", segment="5")]
    out = hl.render_highlights(hs)
    assert "> [!quote]+ ch. 2 · 42%" in out
    assert "> A line" in out
    assert "^ch2-b17-5" in out
    assert "[!note]" not in out  # no annotation -> no note callout


def test_render_highlight_with_note():
    hs = [hl.Highlight(text="A line", note="my thought", chapter_index=2,
                       progress=0.5, block="1", segment="0")]
    out = hl.render_highlights(hs)
    assert "> [!note]-" in out
    assert "> my thought" in out
    assert "^ch2-b1-0-note" in out


def test_render_multiline_text_prefixes_each_line():
    hs = [hl.Highlight(text="line one\nline two", chapter_index=1, block="3")]
    out = hl.render_highlights(hs)
    assert "> line one" in out
    assert "> line two" in out


def test_render_label_falls_back_to_chapter_title_then_percent():
    hs = [hl.Highlight(text="x", chapter_title="Intro", progress=0.1, block="2")]
    out = hl.render_highlights(hs)
    assert "> [!quote]+ Intro · 10%" in out
    hs2 = [hl.Highlight(text="y", progress=0.9, block="2")]
    assert "> [!quote]+ 90%" in hl.render_highlights(hs2)


def test_page_label_and_anchor_single():
    hs = [hl.Highlight(text="x", page="4")]
    out = hl.render_highlights(hs)
    assert "> [!quote]+ p. 4" in out
    assert "^p4" in out


def test_page_label_range_uses_en_dash_anchor_keeps_hyphen():
    hs = [hl.Highlight(text="x", page="45-49")]
    out = hl.render_highlights(hs)
    assert "> [!quote]+ p. 45–49" in out   # en dash in label
    assert "^p45-49" in out                 # hyphen in anchor


def test_page_same_page_collisions_dedupe():
    hs = [hl.Highlight(text="a", page="45-49"), hl.Highlight(text="b", page="45-49")]
    assert hl.build_anchors(hs) == ["p45-49", "p45-49-2"]


def test_page_none_is_unchanged():
    hs = [hl.Highlight(text="a", chapter_index=2, block="17", segment="5")]
    assert hl.build_anchors(hs) == ["ch2-b17-5"]
    assert "p. " not in hl.render_highlights(hs)


def test_sanitize_tag_whitespace_to_hyphen():
    assert hl.sanitize_tag("Cold War") == "cold-war"


def test_sanitize_tag_lowercases():
    assert hl.sanitize_tag("#USSR") == "ussr"
    assert hl.sanitize_tag("Cold WAR") == "cold-war"


def test_sanitize_tag_strips_leading_hash():
    assert hl.sanitize_tag("#Stalin") == "stalin"


def test_sanitize_tag_trims_surrounding_whitespace():
    assert hl.sanitize_tag("  spaced  ") == "spaced"


def test_sanitize_tag_empty_returns_none():
    assert hl.sanitize_tag("") is None
    assert hl.sanitize_tag("   ") is None
    assert hl.sanitize_tag("#") is None


def test_sanitize_tag_none_returns_none():
    assert hl.sanitize_tag(None) is None


def test_highlight_tags_defaults_to_empty_list():
    h = hl.Highlight(text="x")
    assert h.tags == []


def test_render_tags_inside_quote_callout_above_anchor():
    hs = [hl.Highlight(text="A line", chapter_index=2, block="17", segment="5",
                       tags=["Stalin", "USSR"])]
    out = hl.render_highlights(hs)
    # tag line lives inside the callout (prefixed with "> ")
    assert "> #Stalin #USSR" in out
    # ...above the block anchor, below the quoted text
    quote_block = out.split("^ch2-b17-5")[0]
    assert quote_block.index("> A line") < quote_block.index("> #Stalin #USSR")


def test_render_no_tags_callout_unchanged():
    hs = [hl.Highlight(text="A line", chapter_index=2, block="17", segment="5")]
    out = hl.render_highlights(hs)
    assert "#" not in out.split("^ch2-b17-5")[0]  # no tag line in the quote block


def test_render_tags_and_note_both_present():
    hs = [hl.Highlight(text="A line", note="my thought", chapter_index=2,
                       block="1", segment="0", tags=["Stalin"])]
    out = hl.render_highlights(hs)
    assert "> #Stalin" in out          # tag inside quote callout
    assert "> [!note]-" in out         # note callout still rendered
    assert out.index("> #Stalin") < out.index("> [!note]-")


def test_location_label_defaults_to_page_prefix():
    hs = [hl.Highlight(text="x", page="123")]
    assert "> [!quote]+ p. 123" in hl.render_highlights(hs)


def test_location_label_overrides_prefix():
    hs = [hl.Highlight(text="x", page="123", location_label="loc.")]
    out = hl.render_highlights(hs)
    assert "> [!quote]+ loc. 123" in out
    assert "p. 123" not in out


def test_location_label_ignored_without_page():
    hs = [hl.Highlight(text="x", location_label="loc.")]
    out = hl.render_highlights(hs)
    assert "loc." not in out


# --- sanitize_link -----------------------------------------------------------

def test_sanitize_link_keeps_case_and_spaces():
    assert hl.sanitize_link("War Commisar") == "War Commisar"


def test_sanitize_link_strips_leading_at():
    assert hl.sanitize_link("@Trotsky") == "Trotsky"


def test_sanitize_link_collapses_internal_whitespace():
    assert hl.sanitize_link("One   Two") == "One Two"


def test_sanitize_link_trims_surrounding_whitespace():
    assert hl.sanitize_link("  @Lenin  ") == "Lenin"


def test_sanitize_link_empty_returns_none():
    assert hl.sanitize_link("") is None
    assert hl.sanitize_link("   ") is None
    assert hl.sanitize_link("@") is None


def test_sanitize_link_none_returns_none():
    assert hl.sanitize_link(None) is None


def test_sanitize_link_dashes_to_spaces_title_case():
    assert hl.sanitize_link("@battle-of-warsaw") == "Battle of Warsaw"


def test_sanitize_link_stopwords_lowercased_midword():
    assert hl.sanitize_link("war-and-peace") == "War and Peace"


def test_sanitize_link_stopword_first_word_capitalized():
    assert hl.sanitize_link("the-gulag") == "The Gulag"


def test_sanitize_link_stopword_last_word_capitalized():
    assert hl.sanitize_link("day-of") == "Day Of"


# --- Highlight.links ---------------------------------------------------------

def test_highlight_links_defaults_to_empty_list():
    h = hl.Highlight(text="x")
    assert h.links == []


# --- parse_markers -----------------------------------------------------------

def test_parse_markers_splits_link_tag_and_clean_text():
    clean, links, tags = hl.parse_markers("Great chapter. @One Two #history #russia")
    assert clean == "Great chapter."
    assert links == ["One Two"]
    assert tags == ["history", "russia"]


def test_parse_markers_link_captures_until_next_marker():
    clean, links, tags = hl.parse_markers("@War Commisar #history")
    assert links == ["War Commisar"]
    assert tags == ["history"]
    assert clean is None


def test_parse_markers_link_captures_until_newline():
    clean, links, tags = hl.parse_markers("@One Two\nmore text")
    assert links == ["One Two"]
    assert clean == "more text"


def test_parse_markers_dedupes_first_seen():
    _, links, tags = hl.parse_markers("@Lenin @Lenin #ussr #ussr")
    assert links == ["Lenin"]
    assert tags == ["ussr"]


def test_parse_markers_no_markers_returns_text_and_empty_lists():
    clean, links, tags = hl.parse_markers("just a note")
    assert clean == "just a note"
    assert links == []
    assert tags == []


def test_parse_markers_none_input():
    assert hl.parse_markers(None) == (None, [], [])


def test_parse_markers_only_markers_clean_is_none():
    clean, links, tags = hl.parse_markers("#history @Lenin")
    assert clean is None
    assert links == ["Lenin"]
    assert tags == ["history"]


# --- split_tag_column --------------------------------------------------------

def test_split_tag_column_separates_links_and_tags():
    links, tags = hl.split_tag_column("history, @War Commisar, Cold War")
    assert links == ["War Commisar"]
    assert tags == ["history", "cold-war"]


def test_split_tag_column_empty_and_none():
    assert hl.split_tag_column("") == ([], [])
    assert hl.split_tag_column(None) == ([], [])


def test_split_tag_column_dedupes_first_seen():
    links, tags = hl.split_tag_column("@Lenin, @Lenin, ussr, ussr")
    assert links == ["Lenin"]
    assert tags == ["ussr"]


def test_split_tag_column_dashed_link_title_cased():
    links, _ = hl.split_tag_column("@battle-of-warsaw")
    assert links == ["Battle of Warsaw"]


# --- render links ------------------------------------------------------------

def test_render_links_as_wikilinks_before_tags():
    hs = [hl.Highlight(text="A line", chapter_index=2, block="17", segment="5",
                       links=["War Commisar"], tags=["history"])]
    out = hl.render_highlights(hs)
    assert "> [[War Commisar]] #history" in out


def test_render_links_only_no_tags():
    hs = [hl.Highlight(text="A line", chapter_index=2, block="17", segment="5",
                       links=["Trotsky"])]
    out = hl.render_highlights(hs)
    assert "> [[Trotsky]]" in out
    assert "#" not in out.split("^ch2-b17-5")[0]  # no tag markers in quote block
