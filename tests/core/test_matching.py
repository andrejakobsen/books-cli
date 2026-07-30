"""Tests for the format-agnostic identity helpers in ``books.core.matching``."""

from __future__ import annotations

import pytest

from books.core.matching import author_key


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
