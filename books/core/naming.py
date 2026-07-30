"""Format-agnostic note-stem/filename identity.

The stem ``<Title> - <Author>`` is the book's stable id in the CSV store and,
for the Obsidian renderer, also its note/cover/notes filename. Keeping this
logic in ``core`` lets the store assign ids without depending on a renderer.
"""

from __future__ import annotations

import re

_ILLEGAL_FS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def safe_filename(name: str) -> str:
    """Make *name* safe to use as a single path segment."""
    cleaned = _ILLEGAL_FS.sub("_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(". ")
    return cleaned or "Untitled"


def strip_subtitle(title: str) -> str:
    """Drop everything after the first ':' (the subtitle), for tidy filenames.

    ``"The Deluge: The Great War..."`` -> ``"The Deluge"``. Falls back to the
    full (stripped) title when nothing precedes the colon.
    """
    head = (title or "").split(":", 1)[0].strip()
    return head or (title or "").strip()


def next_free_stem(title: str, author: str, used_lower: set[str]) -> str:
    """Return a unique note stem for (title, author) given already-used stems.

    Ladder: clean stem (subtitle dropped) -> restore subtitle (':' -> ',')
    -> numeric '(n)' suffix. *used_lower* holds already-taken stems lowercased;
    membership is tested case-insensitively (matching case-insensitive
    filesystems). The chosen stem is NOT added to used_lower -- the caller does
    that so it can also map the stem to a path/id.
    """

    def stem_for(t: str) -> str:
        return safe_filename(f"{t} - {author}" if author else t)

    short = stem_for(strip_subtitle(title))
    if short.lower() not in used_lower:
        return short

    full = stem_for(title.replace(":", ","))
    if full.lower() not in used_lower:
        return full

    n = 2
    while f"{full} ({n})".lower() in used_lower:
        n += 1
    return safe_filename(f"{full} ({n})")
