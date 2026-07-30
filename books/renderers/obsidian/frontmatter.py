"""Book-note frontmatter: the canonical property schema + a split helper."""

from __future__ import annotations

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


# --- Frontmatter reading ----------------------------------------------------


def _split_frontmatter(text: str) -> tuple[list[str], str]:
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
