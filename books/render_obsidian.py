#!/usr/bin/env python3
"""Render the CSV store (Plan A) into flat Obsidian book notes under ``Books/``.

Reads ``Data/books.csv`` + per-book ``Data/Highlights/<book-id>.csv`` and
writes/updates one self-contained note per book. Frontmatter is written
*authoritatively* from the merged row for every schema key, except:

- ``topics`` -- 100%-user-owned: preserved verbatim on an existing note, empty
  (``[]``) on a brand-new one. Never written from data.
- ``highlighted`` / ``reviewed`` -- derived: true iff the book has highlights /
  a review.

The body carries the cover embed, a write-once ``## Review`` section, and a
marker-wrapped ``## Highlights`` section; anything outside those managed regions
is left untouched. Frontmatter round-trips via python-frontmatter (read) +
ruamel.yaml (write).
"""

from __future__ import annotations

import io
from pathlib import Path

import frontmatter
from ruamel.yaml import YAML

from books.obsidian import BOOK_PROPERTY_ORDER, COVERS_DIRNAME, format_rating, wikilink
from books.store import BookRow

# The note frontmatter schema: the canonical order minus the retired ``source``
# key (a merged book has many contributing sources; a single value is meaningless).
NOTE_PROPERTY_ORDER = tuple(k for k in BOOK_PROPERTY_ORDER if k != "source")


def _yaml() -> YAML:
    y = YAML()
    y.default_flow_style = False
    y.allow_unicode = True       # keep ⭐ and accented names literal, not \uXXXX
    y.width = 4096               # never line-wrap long titles / values
    return y


def dump_frontmatter(meta: dict) -> str:
    """Serialize an ordered frontmatter dict to a YAML block (trailing newline)."""
    buf = io.StringIO()
    _yaml().dump(meta, buf)
    return buf.getvalue()


def load_note(path: Path) -> tuple[dict, str]:
    """Return (frontmatter dict, body) for an existing note, or ({}, "")."""
    if not path.is_file():
        return {}, ""
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    return dict(post.metadata), post.content


def render_rating(raw: str) -> str:
    """Render a stored rating: numeric -> stars (:func:`format_rating`), else raw."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        return format_rating(float(raw))
    except ValueError:
        return raw


def _scalar(value):
    """Empty/whitespace strings -> None (bare ``key:``); other scalars unchanged."""
    if isinstance(value, str):
        value = value.strip()
    return value or None


def _cover_value(row: BookRow, note_path: Path):
    """The ``cover:`` frontmatter wikilink for a note, or None when no cover.

    Present when the row records a cover OR the flat ``Covers/<stem>.jpg`` file
    already exists (kept in lockstep with the note stem = book_id).
    """
    stem = note_path.stem
    cover_file = note_path.parents[1] / COVERS_DIRNAME / f"{stem}.jpg"
    if (row.cover or "").strip() or cover_file.is_file():
        return f"[[{COVERS_DIRNAME}/{stem}.jpg]]"
    return None


def book_frontmatter(row: BookRow, note_path: Path, existing: dict,
                     has_highlights: bool) -> dict:
    """Build the authoritative, canonically-ordered frontmatter dict for a book.

    Every key comes from *row* except: ``type`` (always ``book``), ``topics``
    (preserved from *existing*, ``[]`` when absent), and ``highlighted`` /
    ``reviewed`` (derived booleans).
    """
    meta = {
        "type": "book",
        "title": _scalar(row.title),
        "authors": [wikilink(a) for a in row.authors],
        "topics": existing.get("topics", []) if existing else [],
        "series": _scalar(row.series),
        "series_index": _scalar(row.series_index),
        "publisher": _scalar(row.publisher),
        "published": _scalar(row.published),
        "language": _scalar(row.language),
        "format": _scalar(row.format),
        "pages": _scalar(row.pages),
        "status": _scalar(row.status),
        "highlighted": bool(has_highlights),
        "reviewed": bool((row.review or "").strip()),
        "shelves": list(row.shelves),
        "rating": _scalar(render_rating(row.rating)),
        "isbn": _scalar(row.isbn),
        "amazon": _scalar(row.amazon),
        "google": _scalar(row.google),
        "goodreads": _scalar(row.goodreads),
        "uuid": _scalar(row.uuid),
        "calibre_id": _scalar(row.calibre_id),
        "date_added": _scalar(row.date_added),
        "date_read": _scalar(row.date_read),
        "cover": _cover_value(row, note_path),
    }
    return {k: meta[k] for k in NOTE_PROPERTY_ORDER if k in meta}
