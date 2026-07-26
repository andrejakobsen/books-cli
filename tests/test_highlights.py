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
