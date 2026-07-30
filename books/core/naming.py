"""Format-agnostic note-stem/filename identity.

The stem ``<Title> - <Author>`` is the book's stable id in the CSV store and,
for the Obsidian renderer, also its note/cover/notes filename. Keeping this
logic in ``core`` lets the store assign ids without depending on a renderer.
"""

from __future__ import annotations

import re

_ILLEGAL_FS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')

# A trailing ", <year>" or ", <year>-<year>" is a subtitle (common in history
# titles, e.g. "The Romanovs, 1613-1917"). Requiring digits keeps place-name
# commas ("Berlin, Alexanderplatz") intact.
_TRAILING_DATE_SUBTITLE = re.compile(r",\s*\d{3,4}(?:\s*[-–—]\s*\d{3,4})?\s*$")


def safe_filename(name: str) -> str:
    """Make *name* safe to use as a single path segment."""
    cleaned = _ILLEGAL_FS.sub("_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(". ")
    return cleaned or "Untitled"


def strip_subtitle(title: str) -> str:
    """Drop everything after the first ':' (the subtitle), for tidy filenames.

    ``"The Deluge: The Great War..."`` -> ``"The Deluge"``. A trailing
    comma-delimited date range is also treated as a subtitle
    (``"The Romanovs, 1613-1917"`` -> ``"The Romanovs"``). Falls back to the
    full (stripped) title when nothing precedes the subtitle.
    """
    head = (title or "").split(":", 1)[0].strip()
    head = _TRAILING_DATE_SUBTITLE.sub("", head).strip()
    return head or (title or "").strip()


def stem_for(title: str, author: str) -> str:
    """Join *title* + *author* into a sanitized note stem: ``<Title> - <Author>``.

    The single place the store/renderer/merge derive a stem from a (title,
    author) pair, so the CSV ``book_id``, the merge sort key, and the on-disk note
    filename all agree. Author-less titles collapse to just the title.
    """
    return safe_filename(f"{title} - {author}" if author else title)


def next_free_stem(title: str, author: str, used_lower: set[str]) -> str:
    """Return a unique note stem for (title, author) given already-used stems.

    Ladder: clean stem (subtitle dropped) -> restore subtitle (':' -> ',')
    -> numeric '(n)' suffix. *used_lower* holds already-taken stems lowercased;
    membership is tested case-insensitively (matching case-insensitive
    filesystems). The chosen stem is NOT added to used_lower -- the caller does
    that so it can also map the stem to a path/id.
    """
    short = stem_for(strip_subtitle(title), author)
    if short.lower() not in used_lower:
        return short

    full = stem_for(title.replace(":", ","), author)
    if full.lower() not in used_lower:
        return full

    n = 2
    while f"{full} ({n})".lower() in used_lower:
        n += 1
    return safe_filename(f"{full} ({n})")
