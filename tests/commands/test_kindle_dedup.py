"""Tests for Kindle highlight dedup + note attachment."""

from datetime import datetime

from books.commands.kindle.dedup import to_highlights
from books.commands.kindle.parser import Entry


def _hl(loc_start, loc_end, added, text, kind="highlight", location=None, page=None):
    if location is None and page is None:
        location = f"{loc_start}-{loc_end}"
    return Entry(
        kind=kind,
        title="Book",
        author="Author",
        page=page,
        location=location,
        loc_start=loc_start,
        loc_end=loc_end,
        added=added,
        text=text,
    )


def test_same_start_keeps_latest():
    entries = [
        _hl(472, 473, datetime(2015, 7, 31, 0, 17), "old text"),
        _hl(472, 475, datetime(2015, 7, 31, 0, 18), "new longer text"),
    ]
    result = to_highlights(entries)
    assert len(result) == 1
    assert result[0].text == "new longer text"


def test_same_end_keeps_latest():
    entries = [
        _hl(470, 473, datetime(2020, 1, 1, 0, 0), "first"),
        _hl(472, 473, datetime(2020, 1, 1, 0, 5), "second"),
    ]
    result = to_highlights(entries)
    assert len(result) == 1
    assert result[0].text == "second"


def test_contained_range_merges():
    entries = [
        _hl(100, 200, datetime(2020, 1, 1, 0, 0), "big"),
        _hl(120, 150, datetime(2020, 1, 1, 0, 1), "inside"),
    ]
    result = to_highlights(entries)
    assert len(result) == 1
    assert result[0].text == "inside"


def test_non_overlapping_kept_separate():
    entries = [
        _hl(10, 20, datetime(2020, 1, 1, 0, 0), "a"),
        _hl(30, 40, datetime(2020, 1, 1, 0, 1), "b"),
    ]
    result = to_highlights(entries)
    assert {h.text for h in result} == {"a", "b"}


def test_timestamp_tie_prefers_file_order():
    same = datetime(2020, 1, 1, 0, 0)
    entries = [
        _hl(10, 20, same, "earlier in file"),
        _hl(10, 20, same, "later in file"),
    ]
    result = to_highlights(entries)
    assert len(result) == 1
    assert result[0].text == "later in file"


def test_location_label_and_date():
    entries = [_hl(472, 473, datetime(2015, 7, 31, 0, 17), "text")]
    (h,) = to_highlights(entries)
    assert h.page == "472-473"
    assert h.location_label == "loc."
    assert h.date == "2015-07-31T00:17:00"
    assert h.source == "kindle"


def test_page_based_highlight_uses_default_label():
    entries = [_hl(94, 94, datetime(2020, 1, 1), "p", location=None, page="94-94")]
    (h,) = to_highlights(entries)
    assert h.page == "94-94"
    assert h.location_label is None


def test_note_attached_to_overlapping_highlight():
    entries = [
        _hl(100, 110, datetime(2020, 1, 1, 0, 0), "the highlight"),
        _hl(100, 100, datetime(2020, 1, 1, 0, 1), "my thought", kind="note"),
    ]
    result = to_highlights(entries)
    assert len(result) == 1
    assert result[0].text == "the highlight"
    assert result[0].note == "my thought"


def test_standalone_note_becomes_textless_highlight():
    entries = [
        _hl(100, 110, datetime(2020, 1, 1, 0, 0), "the highlight"),
        _hl(500, 500, datetime(2020, 1, 1, 0, 1), "orphan note", kind="note"),
    ]
    result = to_highlights(entries)
    assert len(result) == 2
    orphan = [h for h in result if h.text == ""]
    assert len(orphan) == 1
    assert orphan[0].note == "orphan note"


def test_note_dedup_keeps_latest():
    entries = [
        _hl(100, 110, datetime(2020, 1, 1, 0, 0), "the highlight"),
        _hl(100, 100, datetime(2020, 1, 1, 0, 1), "old note", kind="note"),
        _hl(100, 100, datetime(2020, 1, 1, 0, 2), "new note", kind="note"),
    ]
    result = to_highlights(entries)
    assert len(result) == 1
    assert result[0].note == "new note"


def test_bookmarks_dropped():
    entries = [
        _hl(10, 20, datetime(2020, 1, 1, 0, 0), "a highlight"),
        _hl(11, 11, datetime(2020, 1, 1, 0, 1), "", kind="bookmark"),
    ]
    result = to_highlights(entries)
    assert len(result) == 1
    assert result[0].text == "a highlight"
