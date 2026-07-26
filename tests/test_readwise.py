"""Tests for the Readwise -> Obsidian importer."""

from pathlib import Path

from booktools import readwise_obsidian as rw


def test_split_series_extracts_name_and_index():
    title, series, index = rw.split_series(
        "Stalin: Volume I: Paradoxes of Power, 1878-1928 (Stalin #1)")
    assert title == "Stalin: Volume I: Paradoxes of Power, 1878-1928"
    assert series == "Stalin"
    assert index == "1"


def test_split_series_decimal_index():
    title, series, index = rw.split_series("Some Book (Saga #2.5)")
    assert title == "Some Book"
    assert series == "Saga"
    assert index == "2.5"


def test_split_series_no_suffix_is_verbatim():
    title, series, index = rw.split_series("The Landscape of History")
    assert title == "The Landscape of History"
    assert series is None
    assert index is None


def test_row_to_highlight_page_location():
    h = rw.row_to_highlight({
        "Highlight": "A passage", "Note": "my note",
        "Location Type": "page", "Location": "3",
        "Highlighted at": "2026-07-17 14:00:25.470174+00:00", "Tags": ""})
    assert h.text == "A passage"
    assert h.note == "my note"
    assert h.page == "3"
    assert h.location_label is None
    assert h.date == "2026-07-17 14:00:25.470174+00:00"


def test_row_to_highlight_kindle_location():
    h = rw.row_to_highlight({
        "Highlight": "x", "Location Type": "location", "Location": "1234"})
    assert h.page == "1234"
    assert h.location_label == "loc."


def test_row_to_highlight_order_has_no_page():
    h = rw.row_to_highlight({
        "Highlight": "x", "Location Type": "order", "Location": "7"})
    assert h.page is None
    assert h.location_label is None


def test_row_to_highlight_blank_note_is_none():
    h = rw.row_to_highlight({"Highlight": "x", "Note": "", "Location Type": "page",
                             "Location": "1"})
    assert h.note is None


def test_row_to_highlight_splits_and_dedupes_tags():
    h = rw.row_to_highlight({"Highlight": "x", "Tags": "Stalin, USSR, stalin"})
    assert h.tags == ["stalin", "ussr"]
