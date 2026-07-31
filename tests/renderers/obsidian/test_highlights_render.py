"""Unit tests for the Obsidian highlights renderer (anchors + callouts)."""

from books.core.highlights import Highlight
from books.renderers.obsidian import build_anchors, render_highlights


def test_build_anchors_chapter_and_progress():
    # anchor mirrors the locator: chapter + reading percentage
    hs = [Highlight(text="a", chapter_index=1, progress=0.42, block="17", segment="5")]
    assert build_anchors(hs) == ["ch1-42"]


def test_build_anchors_missing_chapter_uses_progress_only():
    hs = [Highlight(text="a", progress=0.42)]
    assert build_anchors(hs) == ["42"]


def test_build_anchors_missing_location_uses_counter():
    hs = [
        Highlight(text="a", chapter_index=2),
        Highlight(text="b", chapter_index=2),
    ]
    assert build_anchors(hs) == ["ch2-hl1", "ch2-hl2"]


def test_build_anchors_dedupes_collisions():
    hs = [
        Highlight(text="a", chapter_index=2, progress=0.42),
        Highlight(text="b", chapter_index=2, progress=0.42),
    ]
    assert build_anchors(hs) == ["ch2-42", "ch2-42-2"]


def test_render_single_highlight_no_note():
    hs = [Highlight(text="A line", chapter_index=2, progress=0.42, block="17", segment="5")]
    out = render_highlights(hs)
    assert "> [!quote]+ ch. 2 · 42%" in out
    assert "> A line" in out
    assert "^ch2-42" in out
    assert "[!note]" not in out  # no annotation -> no note callout


def test_render_note_is_nested_quote_in_same_block():
    hs = [
        Highlight(
            text="A line", note="my thought", chapter_index=2, progress=0.5, block="1", segment="0"
        )
    ]
    out = render_highlights(hs)
    assert ">> my thought" in out  # note is a nested blockquote
    assert "[!note]" not in out  # no separate note callout
    assert "^ch2-50-note" not in out  # single block, single anchor
    assert "^ch2-50" in out
    # note sits under the highlight text, inside the quote block
    assert out.index("> A line") < out.index(">> my thought") < out.index("^ch2-50")


def test_render_multiline_text_prefixes_each_line():
    hs = [Highlight(text="line one\nline two", chapter_index=1, block="3")]
    out = render_highlights(hs)
    assert "> line one" in out
    assert "> line two" in out


def test_render_chapter_title_becomes_header_index_absent():
    hs = [Highlight(text="x", chapter_title="Intro", progress=0.1, block="2")]
    out = render_highlights(hs, chapter_label="Kobo ch.")
    assert "### Intro" in out  # chapter header is level-3 under ## Highlights
    assert "%%" not in out  # no hidden comment anymore
    assert "> [!quote]+ 10%" in out  # no index -> locator is percent only


def test_render_no_chapter_locator_is_percent_only():
    hs = [Highlight(text="y", progress=0.9, block="2")]
    assert "> [!quote]+ 90%" in render_highlights(hs)


def test_page_label_and_anchor_single():
    hs = [Highlight(text="x", page="4")]
    out = render_highlights(hs)
    assert "> [!quote]+ p. 4" in out
    assert "^p4" in out


def test_page_label_range_uses_en_dash_anchor_keeps_hyphen():
    hs = [Highlight(text="x", page="45-49")]
    out = render_highlights(hs)
    assert "> [!quote]+ p. 45–49" in out  # en dash in label
    assert "^p45-49" in out  # hyphen in anchor


def test_page_same_page_collisions_dedupe():
    hs = [Highlight(text="a", page="45-49"), Highlight(text="b", page="45-49")]
    assert build_anchors(hs) == ["p45-49", "p45-49-2"]


def test_page_none_is_unchanged():
    hs = [Highlight(text="a", chapter_index=2, block="17", segment="5")]
    assert build_anchors(hs) == ["ch2-hl1"]  # no progress/page -> counter
    assert "p. " not in render_highlights(hs)


def test_render_tags_inside_quote_callout_above_anchor():
    hs = [
        Highlight(text="A line", chapter_index=2, block="17", segment="5", tags=["Stalin", "USSR"])
    ]
    out = render_highlights(hs)
    # tag line lives inside the callout (prefixed with "> ")
    assert "> #Stalin #USSR" in out
    # ...above the block anchor, below the quoted text
    quote_block = out.split("^ch2-hl1")[0]
    assert quote_block.index("> A line") < quote_block.index("> #Stalin #USSR")


def test_render_no_tags_callout_unchanged():
    hs = [Highlight(text="A line", chapter_index=2, block="17", segment="5")]
    out = render_highlights(hs)
    assert "#" not in out.split("^ch2-hl1")[0]  # no tag line in the quote block


def test_render_tags_and_note_both_present():
    hs = [
        Highlight(
            text="A line",
            note="my thought",
            chapter_index=2,
            block="1",
            segment="0",
            tags=["Stalin"],
        )
    ]
    out = render_highlights(hs)
    assert ">> my thought" in out  # note as nested quote
    assert "> #Stalin" in out  # tag line inside quote callout
    assert "[!note]" not in out  # no separate note callout
    assert out.index(">> my thought") < out.index("> #Stalin")  # note above tags


def test_location_label_defaults_to_page_prefix():
    hs = [Highlight(text="x", page="123")]
    assert "> [!quote]+ p. 123" in render_highlights(hs)


def test_location_label_overrides_prefix():
    hs = [Highlight(text="x", page="123", location_label="loc.")]
    out = render_highlights(hs)
    assert "> [!quote]+ loc. 123" in out
    assert "p. 123" not in out


def test_location_label_ignored_without_page():
    hs = [Highlight(text="x", location_label="loc.")]
    out = render_highlights(hs)
    assert "loc." not in out


# --- render links ------------------------------------------------------------


def test_render_links_in_title_after_location_comma_separated():
    hs = [
        Highlight(text="A line", page="12", links=["Trotsky", "Battle of Warsaw"], tags=["history"])
    ]
    out = render_highlights(hs)
    # links live on the callout title line, after the location, middot-joined
    assert "> [!quote]+ p. 12 · [[Trotsky]], [[Battle of Warsaw]]" in out
    # tags remain at the bottom on their own line
    assert "> #history" in out
    assert out.index("[[Battle of Warsaw]]") < out.index("> #history")


def test_render_links_appended_after_progress():
    hs = [
        Highlight(
            text="A line",
            chapter_index=2,
            progress=0.42,
            block="17",
            segment="5",
            links=["Trotsky"],
        )
    ]
    out = render_highlights(hs)
    assert "> [!quote]+ ch. 2 · 42% · [[Trotsky]]" in out


def test_render_links_only_no_location_title_is_links():
    hs = [Highlight(text="A line", block="17", segment="5", links=["Trotsky"])]
    out = render_highlights(hs)
    assert "> [!quote]+ [[Trotsky]]" in out
    assert "#" not in out  # no tags anywhere


# --- chapter subheaders ------------------------------------------------------


def test_grouped_emits_title_header_and_chapter_in_quote():
    hs = [
        Highlight(
            text="a",
            chapter_index=12,
            chapter_title="The Battle",
            progress=0.42,
            block="3",
            segment="5",
        )
    ]
    out = render_highlights(hs, chapter_label="Kobo ch.")
    assert "### The Battle" in out  # level-3 header
    assert "%%" not in out  # hidden comment removed
    # the quote carries the Kobo chapter before the percentage
    assert "> [!quote]+ Kobo ch. 12 · 42%" in out
    assert "^ch12-42" in out  # anchor mirrors the locator


def test_grouped_one_header_per_chapter_run():
    hs = [
        Highlight(text="a", chapter_index=1, chapter_title="One", progress=0.1, block="1"),
        Highlight(text="b", chapter_index=1, chapter_title="One", progress=0.2, block="2"),
        Highlight(text="c", chapter_index=2, chapter_title="Two", progress=0.3, block="3"),
    ]
    out = render_highlights(hs, chapter_label="Kobo ch.")
    assert out.count("### One") == 1  # consecutive same-chapter share one header
    assert out.count("### Two") == 1
    assert out.index("### One") < out.index("### Two")


def test_flat_fallback_when_no_chapter_title():
    # No chapter_title anywhere -> flat output, no chapter headers.
    hs = [Highlight(text="a", chapter_index=2, progress=0.42, block="17", segment="5")]
    out = render_highlights(hs, chapter_label="Kobo ch.")
    assert "###" not in out
    # the quote still carries the labelled chapter before the percentage
    assert "> [!quote]+ Kobo ch. 2 · 42%" in out


def test_grouped_index_only_run_gets_chapter_fallback_header():
    # A title-less highlight among titled ones gets "### Chapter {index}".
    hs = [
        Highlight(text="a", chapter_index=1, chapter_title="Intro", progress=0.1, block="1"),
        Highlight(text="b", chapter_index=2, chapter_title=None, progress=0.2, block="2"),
    ]
    out = render_highlights(hs, chapter_label="Kobo ch.")
    assert "### Intro" in out
    assert "### Chapter 2" in out
    assert "%%" not in out  # no hidden comments anywhere


# --- ordering ----------------------------------------------------------------


def test_render_sorts_page_based_by_page():
    # Page-based highlights given out of order render sorted by starting page.
    hs = [
        Highlight(text="third", page="120"),
        Highlight(text="first", page="5"),
        Highlight(text="second", page="45-49"),
    ]
    out = render_highlights(hs)
    assert out.index("first") < out.index("second") < out.index("third")


def test_render_sorts_chapter_then_progress():
    # Chapter highlights given out of order render sorted by chapter then %.
    hs = [
        Highlight(text="c2-late", chapter_index=2, progress=0.9, block="9"),
        Highlight(text="c1-early", chapter_index=1, progress=0.1, block="1"),
        Highlight(text="c2-early", chapter_index=2, progress=0.2, block="2"),
    ]
    out = render_highlights(hs)
    assert out.index("c1-early") < out.index("c2-early") < out.index("c2-late")


def test_render_sorts_within_chapter_by_block_segment():
    # Same chapter/progress: finer KoboSpan block/segment orders reading position.
    hs = [
        Highlight(text="later", chapter_index=1, progress=0.5, block="17", segment="5"),
        Highlight(text="earlier", chapter_index=1, progress=0.5, block="3", segment="2"),
    ]
    out = render_highlights(hs)
    assert out.index("earlier") < out.index("later")


def test_render_sort_groups_scattered_chapters_under_one_header():
    # Scattered same-chapter highlights collect under one header once sorted.
    hs = [
        Highlight(text="a", chapter_index=1, chapter_title="One", progress=0.1, block="1"),
        Highlight(text="b", chapter_index=2, chapter_title="Two", progress=0.1, block="1"),
        Highlight(text="c", chapter_index=1, chapter_title="One", progress=0.9, block="2"),
    ]
    out = render_highlights(hs, chapter_label="Kobo ch.")
    assert out.count("## One") == 1
    assert out.count("## Two") == 1
    assert out.index("## One") < out.index("## Two")


def test_render_sort_is_stable_for_unlocated_highlights():
    # No location info anywhere -> original order preserved (stable sort).
    hs = [Highlight(text="one"), Highlight(text="two"), Highlight(text="three")]
    out = render_highlights(hs)
    assert out.index("one") < out.index("two") < out.index("three")


def test_no_hr_divider_between_highlights():
    hs = [
        Highlight(text="a", chapter_index=1, chapter_title="One", block="1"),
        Highlight(text="b", chapter_index=1, chapter_title="One", block="2"),
    ]
    out = render_highlights(hs, chapter_label="Kobo ch.")
    assert "\n---\n" not in out
    assert "\n***\n" not in out


def test_empty_location_label_renders_bare_timestamp():
    h = Highlight(text="A passage.", page="3:24:15", location_label="")
    out = render_highlights([h])
    assert "> [!quote]+ 3:24:15" in out
    assert "p. 3:24:15" not in out


def test_render_highlights_single_source_has_no_source_header():
    out = render_highlights(
        [
            Highlight(text="one", progress=0.10, source="kobo"),
            Highlight(text="two", progress=0.20, source="kobo"),
        ]
    )
    assert "### " not in out  # no source header, no chapter header
    assert "one" in out and "two" in out


def test_render_highlights_mixed_sources_group_under_headers():
    out = render_highlights(
        [
            Highlight(text="kobo hl", progress=0.10, source="kobo"),
            Highlight(text="rw hl", progress=0.20, source="readwise"),
        ]
    )
    assert "### Kobo" in out
    assert "### Readwise" in out
    assert out.index("### Kobo") < out.index("### Readwise")  # alphabetical
    # each highlight sits under its own source header
    assert out.index("### Kobo") < out.index("kobo hl") < out.index("### Readwise")


def test_render_highlights_mixed_sources_unique_anchors():
    # both sources would naively produce a "10" anchor; must be de-duplicated
    out = render_highlights(
        [
            Highlight(text="a", progress=0.10, source="kobo"),
            Highlight(text="b", progress=0.10, source="readwise"),
        ]
    )
    anchors = [ln for ln in out.splitlines() if ln.startswith("^")]
    assert len(anchors) == len(set(anchors))  # all anchors unique


def test_render_highlights_multi_source_keeps_unsourced_highlights():
    out = render_highlights(
        [
            Highlight(text="kobo hl", progress=0.10, source="kobo"),
            Highlight(text="rw hl", progress=0.20, source="readwise"),
            Highlight(text="orphan hl", progress=0.30, source=None),
        ]
    )
    # the unsourced highlight is not dropped in multi-source mode
    assert "orphan hl" in out
    # it renders in the headerless leading group, before the first ### header
    assert out.index("orphan hl") < out.index("### Kobo")


def test_render_date_line_shows_local_time():
    hs = [Highlight(text="A", chapter_index=1, progress=0.1, date="2024-07-15T12:30:00Z")]
    out = render_highlights(hs, timezone="Europe/Oslo")
    # July -> Oslo UTC+2 -> 14:30
    assert "> [[2024-07-15]] · 14:30" in out


def test_render_date_line_day_shift():
    hs = [Highlight(text="A", chapter_index=1, progress=0.1, date="2024-01-15T23:30:00Z")]
    out = render_highlights(hs, timezone="Europe/Oslo")
    assert "> [[2024-01-16]] · 00:30" in out


def test_render_no_date_emits_no_line():
    hs = [Highlight(text="A", chapter_index=1, progress=0.1)]
    out = render_highlights(hs)
    assert "[[" not in out


def test_render_all_midnight_source_is_link_only():
    hs = [
        Highlight(text="A", page="10", date="2024-03-15T00:00:00Z", source="kindle"),
        Highlight(text="B", page="20", date="2024-03-16T00:00:00Z", source="kindle"),
    ]
    out = render_highlights(hs, timezone="Europe/Oslo")
    assert "> [[2024-03-15]]" in out
    assert "> [[2024-03-16]]" in out
    assert "·" not in out.split("[[2024-03-15]]")[1].split("\n")[0]  # no time on that line


def test_render_real_midnight_shown_when_group_has_other_times():
    hs = [
        Highlight(text="A", page="10", date="2024-03-15T00:00:00Z", source="readwise"),
        Highlight(text="B", page="20", date="2024-03-15T12:00:00Z", source="readwise"),
    ]
    out = render_highlights(hs, timezone="Europe/Oslo")
    # midnight UTC -> Oslo 01:00 (winter, UTC+1); real time is shown
    assert "> [[2024-03-15]] · 01:00" in out
    assert "> [[2024-03-15]] · 13:00" in out


def test_render_invalid_timezone_falls_back(capsys):
    hs = [Highlight(text="A", chapter_index=1, progress=0.1, date="2024-07-15T12:30:00Z")]
    out = render_highlights(hs, timezone="Not/AZone")
    # falls back to Europe/Oslo -> 14:30
    assert "> [[2024-07-15]] · 14:30" in out


def test_render_mixed_sources_suppress_per_group():
    hs = [
        Highlight(text="K", page="10", date="2024-03-15T00:00:00Z", source="kindle"),
        Highlight(text="R", page="20", date="2024-03-15T12:00:00Z", source="readwise"),
    ]
    out = render_highlights(hs, timezone="Europe/Oslo")
    # kindle group is all-midnight -> link only (no time)
    kindle_part = out.split("### Kindle")[1].split("### Readwise")[0]
    assert "[[2024-03-15]]" in kindle_part
    assert "·" not in kindle_part.split("[[2024-03-15]]")[1].split("\n")[0]
    # readwise group has a real time -> show it (12:00Z -> Oslo 13:00 winter)
    readwise_part = out.split("### Readwise")[1]
    assert "[[2024-03-15]] · 13:00" in readwise_part
