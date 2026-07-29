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

from books.obsidian import BOOK_PROPERTY_ORDER, format_rating

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
