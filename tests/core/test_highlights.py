"""Unit tests for the source-agnostic highlights layer."""

from books.core import highlights as hl


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
