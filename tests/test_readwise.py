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
