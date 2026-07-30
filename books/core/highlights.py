"""Source-agnostic highlight model, marker parsing (#tag/@link), and ordering."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


@dataclass
class Highlight:
    text: str
    note: str | None = None
    chapter_index: int | None = None
    chapter_title: str | None = None
    progress: float | None = None  # 0.0-1.0 within the chapter
    block: str | None = None  # stable location component (e.g. KoboSpan block)
    segment: str | None = None  # secondary location component
    page: str | None = None  # human page/location (physical books), e.g. "45-49"
    location_label: str | None = None  # display prefix for `page`; defaults to "p." when None
    date: str | None = None
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    source: str | None = None  # provenance (kobo | readwise | ...) for grouping


def sanitize_tag(raw: str | None) -> str | None:
    """Normalize a raw tag into a valid Obsidian inline tag, or None if empty.

    Strips surrounding whitespace and a single leading '#', collapses internal
    whitespace runs to a single '-' (Obsidian inline tags cannot contain
    spaces), and lowercases the result. Returns None when nothing is left.
    """
    if raw is None:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("#"):
        cleaned = cleaned[1:].strip()
    cleaned = re.sub(r"\s+", "-", cleaned).lower()
    return cleaned or None


# Lowercased "small words" that stay lowercase mid-title (unless first/last word).
_TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "but",
    "by",
    "for",
    "in",
    "nor",
    "of",
    "on",
    "or",
    "the",
    "to",
    "vs",
}


def _title_case(name: str) -> str:
    """Title-case *name*, keeping small stopwords lowercase except first/last word."""
    words = name.split(" ")
    last = len(words) - 1
    out: list[str] = []
    for i, w in enumerate(words):
        if not w:
            continue
        lower = w.lower()
        if lower in _TITLE_STOPWORDS and 0 < i < last:
            out.append(lower)
        else:
            out.append(lower[:1].upper() + lower[1:])
    return " ".join(out)


def sanitize_link(raw: str | None) -> str | None:
    """Normalize a raw ``@link`` into a wikilink display name, or None if empty.

    Strips surrounding whitespace and a single leading '@', turns '-'/'_' separators
    into spaces, collapses whitespace runs, and applies title casing (small stopwords
    stay lowercase unless first/last). So ``@battle-of-warsaw`` -> ``Battle of Warsaw``.
    Returns None when nothing is left.
    """
    if raw is None:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("@"):
        cleaned = cleaned[1:].strip()
    cleaned = re.sub(r"[\s_-]+", " ", cleaned).strip()
    if not cleaned:
        return None
    return _title_case(cleaned)


# A marker span: '@' or '#' followed by everything up to the next marker or newline.
_MARKER_RE = re.compile(r"([@#])([^@#\n]*)")


def parse_markers(text: str | None) -> tuple[str | None, list[str], list[str]]:
    """Split inline ``@link`` and ``#tag`` markers out of free-form note text.

    Each marker ('@' or '#') captures everything until the next marker or a newline
    (the "end of line" convention). Returns ``(clean_text, links, tags)``: links are
    sanitized via :func:`sanitize_link`, tags via :func:`sanitize_tag`, both
    de-duplicated in first-seen order; clean_text is the note with all marker spans
    removed and whitespace collapsed (None if nothing readable remains).
    """
    if not text:
        return None, [], []
    links: list[str] = []
    tags: list[str] = []
    for kind, body in _MARKER_RE.findall(text):
        if kind == "@":
            link = sanitize_link(body)
            if link and link not in links:
                links.append(link)
        else:
            tag = sanitize_tag(body)
            if tag and tag not in tags:
                tags.append(tag)
    clean = _MARKER_RE.sub("", text)
    clean = re.sub(r"\s+", " ", clean).strip()
    return (clean or None), links, tags


def split_tag_column(raw: str | None) -> tuple[list[str], list[str]]:
    """Split a comma-separated tag column into ``(links, tags)``.

    An entry prefixed with '@' becomes a link (:func:`sanitize_link`); any other
    entry becomes a tag (:func:`sanitize_tag`). Both lists are de-duplicated in
    first-seen order. Used by CSV sources (Highlighted, Readwise) whose exports
    carry a single free-form tag column.
    """
    links: list[str] = []
    tags: list[str] = []
    for part in (raw or "").split(","):
        if part.strip().startswith("@"):
            link = sanitize_link(part)
            if link and link not in links:
                links.append(link)
        else:
            tag = sanitize_tag(part)
            if tag and tag not in tags:
                tags.append(tag)
    return links, tags


def _leading_int(value: str | None) -> float:
    """First integer in *value* (e.g. "45-49" -> 45), or +inf when none/absent.

    Missing locations sort last so located highlights lead the reading order.
    """
    if value is None:
        return math.inf
    m = re.search(r"\d+", str(value))
    return int(m.group()) if m else math.inf


def sort_key(h: Highlight) -> tuple:
    """Reading-order sort key: chapter, then % within chapter, then page/block.

    Ordered so a source using either scheme sorts correctly (missing components
    are +inf, so they don't interfere): chapter-based sources (Kobo) sort by
    ``chapter_index`` then ``progress`` then KoboSpan ``block``/``segment``;
    page-based sources (Highlighted, Readwise) sort by the leading page number.
    Equal keys keep their original order under a stable sort.
    """
    return (
        h.chapter_index if h.chapter_index is not None else math.inf,
        h.progress if h.progress is not None else math.inf,
        _leading_int(h.page),
        _leading_int(h.block),
        _leading_int(h.segment),
    )
