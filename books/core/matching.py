"""Format-agnostic book identity: title/ISBN/author normalization + BookRef.

These helpers reduce titles, ISBNs, Amazon ids, and author names to canonical
forms so the same book can be matched across sources (and across any renderer).
They carry no Obsidian/markdown knowledge.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import isbnlib
from rapidfuzz import fuzz

from books.core.naming import strip_subtitle


@dataclass
class BookRef:
    """Source-neutral book identity used for matching and note creation."""

    title: str
    authors: list[str] = field(default_factory=list)
    isbn: str | None = None
    amazon: str | None = None


def fold(text: str) -> str:
    """Lowercase and strip accents (NFKD + drop combining marks)."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def norm_title(title: str) -> str:
    """Normalized title for matching: folded, punctuation collapsed to spaces."""
    return re.sub(r"[^a-z0-9]+", " ", fold(title)).strip()


def norm_isbn(isbn: str | None) -> str | None:
    """Digits-only ISBN (keeps a trailing X check digit); None if empty."""
    if not isbn:
        return None
    return re.sub(r"[^0-9x]", "", fold(isbn)).upper() or None


def norm_amazon(amazon: str | None) -> str | None:
    """Alphanumeric-only, uppercased Amazon id (ASIN); None if empty."""
    if not amazon:
        return None
    return re.sub(r"[^a-z0-9]", "", fold(amazon)).upper() or None


def author_key(name: str) -> tuple[str, str]:
    """Reduce an author name to (first, last), ignoring middle names/initials.

    Handles both "First Last" and "Last, First" orderings.
    """
    name = fold(name)
    # Split glued initials so "S.C.M. Paine" tokenizes like "S. C. M. Paine".
    name = name.replace(".", ". ")
    if "," in name:
        last, _, first = name.partition(",")
        tokens = first.split() + last.split()
    else:
        tokens = name.split()
    tokens = [re.sub(r"[^a-z0-9]", "", t) for t in tokens]
    tokens = [t for t in tokens if t]
    if not tokens:
        return ("", "")
    if len(tokens) == 1:
        return (tokens[0], tokens[0])
    return (tokens[0], tokens[-1])


TITLE_MATCH_THRESHOLD = 90  # rapidfuzz ratio 0-100; conservative to avoid false merges


def canonical_isbn(isbn: str | None) -> str | None:
    """Canonical ISBN-13 for matching, or None. Falls back to digit-normalization."""
    if not isbn:
        return None
    c = isbnlib.canonical(str(isbn))
    if c and isbnlib.is_isbn10(c):
        c = isbnlib.to_isbn13(c) or c
    return c or norm_isbn(isbn)


def _has_subtitle(title: str) -> bool:
    return strip_subtitle(title).strip().casefold() != (title or "").strip().casefold()


def title_similar(t1: str, t2: str) -> bool:
    """Subtitle-aware fuzzy title match with the symmetric ``fuzz.ratio``.

    When both titles carry a subtitle, compare them in full (differing subtitles
    separate distinct volumes); otherwise compare the subtitle-stripped bases (a
    bare title merges with the subtitled edition of the same book). Never uses
    ``partial_ratio`` -- it would merge "Dune"/"Dune Messiah" and the like.
    """
    if _has_subtitle(t1) and _has_subtitle(t2):
        left, right = norm_title(t1), norm_title(t2)
    else:
        left, right = norm_title(strip_subtitle(t1)), norm_title(strip_subtitle(t2))
    return fuzz.ratio(left, right) >= TITLE_MATCH_THRESHOLD
