"""Tests for the Kindle My Clippings.txt parser."""

from datetime import datetime

from books.commands.kindle import parser

LOCATION_RECORD = (
    "﻿The Autobiography of Malcolm X (X, Malcolm)\n"
    "- Your Highlight at location 472-473 | Added on Friday, 31 July 2015 00:17:35\n"
    "\n"
    "they starved. The day was to come when our family was so poor.\n"
)

PAGE_RECORD = (
    "Some Physical Book (Jane Doe)\n"
    "- Your Highlight on page 94-94 | Added on Monday, 1 June 2020 12:00:00\n"
    "\n"
    "A page-based highlight.\n"
)

PAGE_AND_LOCATION_RECORD = (
    "Mixed Book (John Roe)\n"
    "- Your Highlight on page 157 | location 3043-3045 | Added on Tuesday, 2 June 2020 09:30:15\n"
    "\n"
    "Both page and location.\n"
)

NOTE_RECORD = (
    "Critique of the Gotha Programme (Karl Marx)\n"
    "- Your Note at location 364 | Added on Thursday, 10 September 2015 14:40:55\n"
    "\n"
    "funny\n"
)

BOOKMARK_RECORD = (
    "The Origin of the Family (Frederick Engels)\n"
    "- Your Bookmark at location 11 | Added on Thursday, 30 July 2015 01:36:01\n"
    "\n"
    "\n"
)


def _file(*records: str) -> str:
    return "==========\n".join(records) + "==========\n"


def test_parses_location_highlight():
    (entry,) = parser.parse_clippings(_file(LOCATION_RECORD))
    assert entry.kind == "highlight"
    assert entry.title == "The Autobiography of Malcolm X"
    assert entry.author == "X, Malcolm"
    assert entry.location == "472-473"
    assert entry.page is None
    assert entry.loc_start == 472
    assert entry.loc_end == 473
    assert entry.added == datetime(2015, 7, 31, 0, 17, 35)
    assert entry.text == "they starved. The day was to come when our family was so poor."


def test_strips_bom_from_title():
    (entry,) = parser.parse_clippings(_file(LOCATION_RECORD))
    assert not entry.title.startswith("﻿")


def test_parses_page_highlight():
    (entry,) = parser.parse_clippings(_file(PAGE_RECORD))
    assert entry.page == "94-94"
    assert entry.location is None
    assert entry.loc_start == 94
    assert entry.loc_end == 94


def test_page_and_location_prefers_location_for_range():
    (entry,) = parser.parse_clippings(_file(PAGE_AND_LOCATION_RECORD))
    assert entry.page == "157"
    assert entry.location == "3043-3045"
    assert entry.loc_start == 3043
    assert entry.loc_end == 3045


def test_parses_note_kind():
    (entry,) = parser.parse_clippings(_file(NOTE_RECORD))
    assert entry.kind == "note"
    assert entry.text == "funny"


def test_parses_bookmark_with_empty_text():
    (entry,) = parser.parse_clippings(_file(BOOKMARK_RECORD))
    assert entry.kind == "bookmark"
    assert entry.text == ""


def test_parses_multiple_records():
    entries = parser.parse_clippings(_file(LOCATION_RECORD, PAGE_RECORD, NOTE_RECORD))
    assert [e.kind for e in entries] == ["highlight", "highlight", "note"]


def test_unparseable_date_is_none():
    record = "Book (Author)\n- Your Highlight at location 5-6 | Added on garbage date\n\ntext\n"
    (entry,) = parser.parse_clippings(_file(record))
    assert entry.added is None


def test_malformed_record_is_skipped():
    good = _file(LOCATION_RECORD)
    bad = "not a real record with no metadata line\n==========\n"
    entries = parser.parse_clippings(good + bad)
    assert len(entries) == 1
