"""Tests for the format-agnostic identity helpers in ``books.core.matching``."""

from __future__ import annotations

import pytest

from books.core.matching import author_key, title_similar


def test_title_similar_merges_bare_title_with_comma_date_subtitle():
    # Goodreads "The Romanovs, 1613-1917" vs Audible "The Romanovs" are one book.
    assert title_similar("The Romanovs, 1613-1917", "The Romanovs")


def test_title_similar_keeps_distinct_date_range_volumes_apart():
    # Two different date-range volumes both carry a subtitle -> full compare.
    assert not title_similar("The Second World War, 1939-1945", "The First World War, 1914-1918")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Adam Tooze", ("adam", "tooze")),
        ("Tooze, Adam", ("adam", "tooze")),
        # Glued initials must key the same as spaced ones (S.C.M. == S. C. M.).
        ("S. C. M. Paine", ("s", "paine")),
        ("S.C.M. Paine", ("s", "paine")),
        ("J.R.R. Tolkien", ("j", "tolkien")),
        ("J. R. R. Tolkien", ("j", "tolkien")),
        ("Paine, S.C.M.", ("s", "paine")),
    ],
)
def test_author_key_normalizes_initial_spacing(name, expected):
    assert author_key(name) == expected
