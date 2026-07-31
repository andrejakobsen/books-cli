"""Unit tests for the source-agnostic highlights layer."""

from zoneinfo import ZoneInfo

import pytest

from books.core import highlights as hl
from books.core.highlights import is_utc_midnight, local_datetime, normalize_date


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2024-03-15T14:30:00.000", "2024-03-15T14:30:00Z"),  # kobo (real, ms)
        ("2026-07-01", "2026-07-01T00:00:00Z"),  # kobo/highlighted date-only
        ("2026-07-24 11:15:47", "2026-07-24T11:15:47Z"),  # highlighted (space, naive)
        ("2026-07-17 14:00:25.470174+00:00", "2026-07-17T14:00:25Z"),  # readwise (offset)
        ("2015-07-31T00:17:35", "2015-07-31T00:17:35Z"),  # kindle (isoformat, naive)
        ("2026-07-28 07:38:09.0", "2026-07-28T07:38:09Z"),  # audible (.0 tenths)
    ],
)
def test_normalize_date_canonicalizes_each_source_shape(raw, expected):
    assert normalize_date(raw) == expected


def test_normalize_date_converts_offset_to_utc():
    # +02:00 wall clock 14:30 -> 12:30 UTC
    assert normalize_date("2024-03-15 14:30:00+02:00") == "2024-03-15T12:30:00Z"


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_normalize_date_empty_returns_none(raw):
    assert normalize_date(raw) is None


def test_normalize_date_unparseable_returns_none():
    assert normalize_date("not a date") is None


def test_normalize_date_is_idempotent():
    assert normalize_date("2024-03-15T14:30:00Z") == "2024-03-15T14:30:00Z"


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


# --- local_datetime ----------------------------------------------------------


def test_local_datetime_converts_utc_to_oslo_winter():
    dt = local_datetime("2024-01-15T12:30:00Z", ZoneInfo("Europe/Oslo"))
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2024, 1, 15, 13, 30)


def test_local_datetime_converts_utc_to_oslo_dst():
    # July -> Oslo is UTC+2
    dt = local_datetime("2024-07-15T12:30:00Z", ZoneInfo("Europe/Oslo"))
    assert (dt.hour, dt.minute) == (14, 30)


def test_local_datetime_day_shift_across_midnight():
    # 23:30Z on the 15th -> 00:30 local on the 16th (UTC+1)
    dt = local_datetime("2024-01-15T23:30:00Z", ZoneInfo("Europe/Oslo"))
    assert (dt.day, dt.hour, dt.minute) == (16, 0, 30)


def test_local_datetime_naive_is_assumed_utc():
    dt = local_datetime("2024-01-15T12:30:00", ZoneInfo("Europe/Oslo"))
    assert (dt.hour, dt.minute) == (13, 30)


def test_local_datetime_none_and_empty_and_unparseable():
    tz = ZoneInfo("Europe/Oslo")
    assert local_datetime(None, tz) is None
    assert local_datetime("   ", tz) is None
    assert local_datetime("not a date", tz) is None


# --- is_utc_midnight ---------------------------------------------------------


def test_is_utc_midnight():
    assert is_utc_midnight("2024-03-15T00:00:00Z") is True
    assert is_utc_midnight("2024-03-15T12:00:00Z") is False
    assert is_utc_midnight(None) is False
    assert is_utc_midnight("garbage") is False
