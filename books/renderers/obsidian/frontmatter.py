"""Book-note frontmatter: the canonical schema, ordering, and YAML round-trip.

Owns *all* Obsidian frontmatter knowledge — the property schema, the render-time
key order (including the user-owned extras), reading an existing note, and
serializing an ordered dict back to a YAML block. The renderer builds on these;
nothing here leaks out of the Obsidian package.
"""

from __future__ import annotations

import io
from pathlib import Path

import frontmatter as _pyfm
from ruamel.yaml import YAML

# --- Canonical property schema ---------------------------------------------

# Order in which book-note frontmatter keys are emitted. Every book note carries
# all of these (empty when unknown) so any field can be filled later by the other
# importer or by hand.
BOOK_PROPERTY_ORDER = (
    "type",
    "title",
    "authors",
    "topics",
    "series",
    "series_index",
    "publisher",
    "published",
    "language",
    "format",
    "pages",
    "status",
    "highlighted",
    "reviewed",
    "shelves",
    "rating",
    "isbn",
    "amazon",
    "google",
    "goodreads",
    "uuid",
    "calibre_id",
    "date_added",
    "date_read",
    "source",
    "cover",
)

# The note frontmatter schema: the canonical order minus the retired ``source``
# key (a merged book has many contributing sources; a single value is meaningless).
NOTE_PROPERTY_ORDER = tuple(k for k in BOOK_PROPERTY_ORDER if k != "source")

# Non-schema keys that Obsidian itself writes and the user owns. Preserved
# verbatim from an existing note (like ``topics``) but never fabricated: emitted
# only when the existing note already carries them, positioned after ``topics``.
PRESERVED_EXTRA_KEYS = ("aliases", "cssclasses")


def _insert_after(order: tuple, anchor: str, extra: tuple) -> tuple:
    """Return *order* with *extra* keys inserted right after *anchor*."""
    out: list = []
    for key in order:
        out.append(key)
        if key == anchor:
            out.extend(extra)
    return tuple(out)


# Render-time key order: schema keys plus the preserved extras after ``topics``.
RENDER_KEY_ORDER = _insert_after(NOTE_PROPERTY_ORDER, "topics", PRESERVED_EXTRA_KEYS)


# --- Frontmatter reading ----------------------------------------------------


def split_frontmatter(text: str) -> tuple[list[str], str]:
    """Return (frontmatter_lines, body); lines exclude the '---' fences.

    If *text* has no leading frontmatter block, returns ([], text).
    """
    if not text.startswith("---"):
        return [], text
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1 :])
    return [], text


def load_note(path: Path) -> tuple[dict, str]:
    """Return (frontmatter dict, body) for an existing note, or ({}, "")."""
    if not path.is_file():
        return {}, ""
    post = _pyfm.loads(path.read_text(encoding="utf-8"))
    return dict(post.metadata), post.content


# --- Frontmatter writing ----------------------------------------------------


def _yaml() -> YAML:
    y = YAML()
    y.default_flow_style = False
    y.allow_unicode = True  # keep ⭐ and accented names literal, not \uXXXX
    y.width = 4096  # never line-wrap long titles / values
    return y


def dump_frontmatter(meta: dict) -> str:
    """Serialize an ordered frontmatter dict to a YAML block (trailing newline)."""
    buf = io.StringIO()
    _yaml().dump(meta, buf)
    return buf.getvalue()
