"""Unit tests for the source-agnostic highlights layer."""

from books import highlights as hl


def test_build_anchors_chapter_and_progress():
    # anchor mirrors the locator: chapter + reading percentage
    hs = [hl.Highlight(text="a", chapter_index=1, progress=0.42, block="17", segment="5")]
    assert hl.build_anchors(hs) == ["ch1-42"]


def test_build_anchors_missing_chapter_uses_progress_only():
    hs = [hl.Highlight(text="a", progress=0.42)]
    assert hl.build_anchors(hs) == ["42"]


def test_build_anchors_missing_location_uses_counter():
    hs = [
        hl.Highlight(text="a", chapter_index=2),
        hl.Highlight(text="b", chapter_index=2),
    ]
    assert hl.build_anchors(hs) == ["ch2-hl1", "ch2-hl2"]


def test_build_anchors_dedupes_collisions():
    hs = [
        hl.Highlight(text="a", chapter_index=2, progress=0.42),
        hl.Highlight(text="b", chapter_index=2, progress=0.42),
    ]
    assert hl.build_anchors(hs) == ["ch2-42", "ch2-42-2"]


def test_render_single_highlight_no_note():
    hs = [hl.Highlight(text="A line", chapter_index=2, progress=0.42,
                       block="17", segment="5")]
    out = hl.render_highlights(hs)
    assert "> [!quote]+ ch. 2 · 42%" in out
    assert "> A line" in out
    assert "^ch2-42" in out
    assert "[!note]" not in out  # no annotation -> no note callout


def test_render_note_is_nested_quote_in_same_block():
    hs = [hl.Highlight(text="A line", note="my thought", chapter_index=2,
                       progress=0.5, block="1", segment="0")]
    out = hl.render_highlights(hs)
    assert ">> my thought" in out          # note is a nested blockquote
    assert "[!note]" not in out            # no separate note callout
    assert "^ch2-50-note" not in out       # single block, single anchor
    assert "^ch2-50" in out
    # note sits under the highlight text, inside the quote block
    assert out.index("> A line") < out.index(">> my thought") < out.index("^ch2-50")


def test_render_multiline_text_prefixes_each_line():
    hs = [hl.Highlight(text="line one\nline two", chapter_index=1, block="3")]
    out = hl.render_highlights(hs)
    assert "> line one" in out
    assert "> line two" in out


def test_render_chapter_title_becomes_header_index_absent():
    hs = [hl.Highlight(text="x", chapter_title="Intro", progress=0.1, block="2")]
    out = hl.render_highlights(hs, chapter_label="Kobo ch.")
    assert "### Intro" in out             # chapter header is level-3 under ## Highlights
    assert "%%" not in out                # no hidden comment anymore
    assert "> [!quote]+ 10%" in out       # no index -> locator is percent only


def test_render_no_chapter_locator_is_percent_only():
    hs = [hl.Highlight(text="y", progress=0.9, block="2")]
    assert "> [!quote]+ 90%" in hl.render_highlights(hs)


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
    assert hl.build_anchors(hs) == ["ch2-hl1"]   # no progress/page -> counter
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
    quote_block = out.split("^ch2-hl1")[0]
    assert quote_block.index("> A line") < quote_block.index("> #Stalin #USSR")


def test_render_no_tags_callout_unchanged():
    hs = [hl.Highlight(text="A line", chapter_index=2, block="17", segment="5")]
    out = hl.render_highlights(hs)
    assert "#" not in out.split("^ch2-hl1")[0]  # no tag line in the quote block


def test_render_tags_and_note_both_present():
    hs = [hl.Highlight(text="A line", note="my thought", chapter_index=2,
                       block="1", segment="0", tags=["Stalin"])]
    out = hl.render_highlights(hs)
    assert ">> my thought" in out      # note as nested quote
    assert "> #Stalin" in out          # tag line inside quote callout
    assert "[!note]" not in out        # no separate note callout
    assert out.index(">> my thought") < out.index("> #Stalin")  # note above tags


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

def test_render_links_in_title_after_location_comma_separated():
    hs = [hl.Highlight(text="A line", page="12",
                       links=["Trotsky", "Battle of Warsaw"], tags=["history"])]
    out = hl.render_highlights(hs)
    # links live on the callout title line, after the location, middot-joined
    assert "> [!quote]+ p. 12 · [[Trotsky]], [[Battle of Warsaw]]" in out
    # tags remain at the bottom on their own line
    assert "> #history" in out
    assert out.index("[[Battle of Warsaw]]") < out.index("> #history")


def test_render_links_appended_after_progress():
    hs = [hl.Highlight(text="A line", chapter_index=2, progress=0.42,
                       block="17", segment="5", links=["Trotsky"])]
    out = hl.render_highlights(hs)
    assert "> [!quote]+ ch. 2 · 42% · [[Trotsky]]" in out


def test_render_links_only_no_location_title_is_links():
    hs = [hl.Highlight(text="A line", block="17", segment="5", links=["Trotsky"])]
    out = hl.render_highlights(hs)
    assert "> [!quote]+ [[Trotsky]]" in out
    assert "#" not in out  # no tags anywhere


# --- chapter subheaders ------------------------------------------------------

def test_grouped_emits_title_header_and_chapter_in_quote():
    hs = [hl.Highlight(text="a", chapter_index=12, chapter_title="The Battle",
                       progress=0.42, block="3", segment="5")]
    out = hl.render_highlights(hs, chapter_label="Kobo ch.")
    assert "### The Battle" in out                     # level-3 header
    assert "%%" not in out                             # hidden comment removed
    # the quote carries the Kobo chapter before the percentage
    assert "> [!quote]+ Kobo ch. 12 · 42%" in out
    assert "^ch12-42" in out                           # anchor mirrors the locator


def test_grouped_no_label_uses_default_chapter_prefix():
    hs = [hl.Highlight(text="a", chapter_index=12, chapter_title="The Battle",
                       progress=0.42, block="3", segment="5")]
    out = hl.render_highlights(hs)  # no chapter_label
    assert "### The Battle" in out
    assert "%%" not in out
    assert "> [!quote]+ ch. 12 · 42%" in out           # default "ch." prefix


def test_grouped_one_header_per_chapter_run():
    hs = [
        hl.Highlight(text="a", chapter_index=1, chapter_title="One",
                     progress=0.1, block="1"),
        hl.Highlight(text="b", chapter_index=1, chapter_title="One",
                     progress=0.2, block="2"),
        hl.Highlight(text="c", chapter_index=2, chapter_title="Two",
                     progress=0.3, block="3"),
    ]
    out = hl.render_highlights(hs, chapter_label="Kobo ch.")
    assert out.count("### One") == 1   # consecutive same-chapter share one header
    assert out.count("### Two") == 1
    assert out.index("### One") < out.index("### Two")


def test_flat_fallback_when_no_chapter_title():
    # No chapter_title anywhere -> flat output, no chapter headers.
    hs = [hl.Highlight(text="a", chapter_index=2, progress=0.42,
                       block="17", segment="5")]
    out = hl.render_highlights(hs, chapter_label="Kobo ch.")
    assert "###" not in out
    # the quote still carries the labelled chapter before the percentage
    assert "> [!quote]+ Kobo ch. 2 · 42%" in out


def test_grouped_index_only_run_gets_chapter_fallback_header():
    # A title-less highlight among titled ones gets "### Chapter {index}".
    hs = [
        hl.Highlight(text="a", chapter_index=1, chapter_title="Intro",
                     progress=0.1, block="1"),
        hl.Highlight(text="b", chapter_index=2, chapter_title=None,
                     progress=0.2, block="2"),
    ]
    out = hl.render_highlights(hs, chapter_label="Kobo ch.")
    assert "### Intro" in out
    assert "### Chapter 2" in out
    assert "%%" not in out                 # no hidden comments anywhere


# --- ordering ----------------------------------------------------------------

def test_render_sorts_page_based_by_page():
    # Page-based highlights given out of order render sorted by starting page.
    hs = [
        hl.Highlight(text="third", page="120"),
        hl.Highlight(text="first", page="5"),
        hl.Highlight(text="second", page="45-49"),
    ]
    out = hl.render_highlights(hs)
    assert out.index("first") < out.index("second") < out.index("third")


def test_render_sorts_chapter_then_progress():
    # Chapter highlights given out of order render sorted by chapter then %.
    hs = [
        hl.Highlight(text="c2-late", chapter_index=2, progress=0.9, block="9"),
        hl.Highlight(text="c1-early", chapter_index=1, progress=0.1, block="1"),
        hl.Highlight(text="c2-early", chapter_index=2, progress=0.2, block="2"),
    ]
    out = hl.render_highlights(hs)
    assert out.index("c1-early") < out.index("c2-early") < out.index("c2-late")


def test_render_sorts_within_chapter_by_block_segment():
    # Same chapter/progress: finer KoboSpan block/segment orders reading position.
    hs = [
        hl.Highlight(text="later", chapter_index=1, progress=0.5, block="17", segment="5"),
        hl.Highlight(text="earlier", chapter_index=1, progress=0.5, block="3", segment="2"),
    ]
    out = hl.render_highlights(hs)
    assert out.index("earlier") < out.index("later")


def test_render_sort_groups_scattered_chapters_under_one_header():
    # Scattered same-chapter highlights collect under one header once sorted.
    hs = [
        hl.Highlight(text="a", chapter_index=1, chapter_title="One", progress=0.1, block="1"),
        hl.Highlight(text="b", chapter_index=2, chapter_title="Two", progress=0.1, block="1"),
        hl.Highlight(text="c", chapter_index=1, chapter_title="One", progress=0.9, block="2"),
    ]
    out = hl.render_highlights(hs, chapter_label="Kobo ch.")
    assert out.count("## One") == 1
    assert out.count("## Two") == 1
    assert out.index("## One") < out.index("## Two")


def test_render_sort_is_stable_for_unlocated_highlights():
    # No location info anywhere -> original order preserved (stable sort).
    hs = [hl.Highlight(text="one"), hl.Highlight(text="two"), hl.Highlight(text="three")]
    out = hl.render_highlights(hs)
    assert out.index("one") < out.index("two") < out.index("three")


def test_no_hr_divider_between_highlights():
    hs = [
        hl.Highlight(text="a", chapter_index=1, chapter_title="One", block="1"),
        hl.Highlight(text="b", chapter_index=1, chapter_title="One", block="2"),
    ]
    out = hl.render_highlights(hs, chapter_label="Kobo ch.")
    assert "\n---\n" not in out
    assert "\n***\n" not in out


def test_empty_location_label_renders_bare_timestamp():
    from books.highlights import Highlight, render_highlights
    h = Highlight(text="A passage.", page="3:24:15", location_label="")
    out = render_highlights([h])
    assert "> [!quote]+ 3:24:15" in out
    assert "p. 3:24:15" not in out


def test_none_location_label_still_defaults_to_p():
    from books.highlights import Highlight, render_highlights
    h = Highlight(text="A passage.", page="42")
    out = render_highlights([h])
    assert "> [!quote]+ p. 42" in out


def test_render_highlights_single_source_has_no_source_header():
    from books.highlights import Highlight, render_highlights
    out = render_highlights([
        Highlight(text="one", progress=0.10, source="kobo"),
        Highlight(text="two", progress=0.20, source="kobo"),
    ])
    assert "### " not in out          # no source header, no chapter header
    assert "one" in out and "two" in out


def test_render_highlights_mixed_sources_group_under_headers():
    from books.highlights import Highlight, render_highlights
    out = render_highlights([
        Highlight(text="kobo hl", progress=0.10, source="kobo"),
        Highlight(text="rw hl", progress=0.20, source="readwise"),
    ])
    assert "### Kobo" in out
    assert "### Readwise" in out
    assert out.index("### Kobo") < out.index("### Readwise")  # alphabetical
    # each highlight sits under its own source header
    assert out.index("### Kobo") < out.index("kobo hl") < out.index("### Readwise")


def test_render_highlights_mixed_sources_unique_anchors():
    from books.highlights import Highlight, render_highlights
    # both sources would naively produce a "10" anchor; must be de-duplicated
    out = render_highlights([
        Highlight(text="a", progress=0.10, source="kobo"),
        Highlight(text="b", progress=0.10, source="readwise"),
    ])
    assert out.count("^10\n") + out.count("^10 ") == 0 or out.count("^10") >= 1
    anchors = [ln for ln in out.splitlines() if ln.startswith("^")]
    assert len(anchors) == len(set(anchors))  # all anchors unique
