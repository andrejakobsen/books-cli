"""Source-agnostic highlight model + Obsidian rendering.

A *Highlight* is a reading annotation independent of the app it came from (Kobo,
Kindle, Apple Books, ...). Each source maps its own storage into this model; all
Obsidian formatting (callouts, stable block anchors) lives here so every source
shares one output format.

Standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from booktools.obsidian import wikilink


@dataclass
class Highlight:
    text: str
    note: str | None = None
    chapter_index: int | None = None
    chapter_title: str | None = None
    progress: float | None = None      # 0.0-1.0 within the chapter
    block: str | None = None           # stable location component (e.g. KoboSpan block)
    segment: str | None = None         # secondary location component
    page: str | None = None            # human page/location (physical books), e.g. "45-49"
    location_label: str | None = None  # display prefix for `page`; defaults to "p." when None
    date: str | None = None
    tags: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


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
    "a", "an", "and", "as", "at", "but", "by", "for", "in", "nor", "of",
    "on", "or", "the", "to", "vs",
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


def build_anchors(highlights: list[Highlight]) -> list[str]:
    """Compute a unique Obsidian block-id per highlight.

    Base is ``ch<index>`` (when known) joined with a location component: the page
    ``p<page>`` (physical books) when set, else ``b<block>-<seg>`` (e.g. KoboSpan).
    When no location is available a per-list counter ``hl<n>`` is used instead.
    Collisions get a ``-2``, ``-3`` suffix so ids are always unique in the file.
    """
    seen: set[str] = set()
    anchors: list[str] = []
    for i, h in enumerate(highlights, start=1):
        chapter = f"ch{h.chapter_index}" if h.chapter_index is not None else ""
        page = re.sub(r"[^0-9-]", "", h.page) if h.page else ""
        if page:
            loc = f"p{page}"
        elif h.block:
            loc = f"b{h.block}" + (f"-{h.segment}" if h.segment else "")
        else:
            loc = f"hl{i}"
        base = "-".join(p for p in (chapter, loc) if p)
        anchor = base
        n = 2
        while anchor in seen:
            anchor = f"{base}-{n}"
            n += 1
        seen.add(anchor)
        anchors.append(anchor)
    return anchors


def _label(h: Highlight) -> str:
    parts: list[str] = []
    if h.chapter_index is not None:
        parts.append(f"ch. {h.chapter_index}")
    elif h.chapter_title:
        parts.append(h.chapter_title)
    if h.page:
        prefix = h.location_label or "p."
        parts.append(f"{prefix} {h.page.replace('-', '–')}")
    if h.progress is not None:
        parts.append(f"{round(h.progress * 100)}%")
    return " · ".join(parts)


def _quote_lines(text: str, prefix: str) -> list[str]:
    """Prefix each line of *text* for a callout body; blank lines keep the bare marker."""
    return [f"{prefix} {ln}" if ln.strip() else prefix.rstrip()
            for ln in text.split("\n")]


def render_highlights(highlights: list[Highlight]) -> str:
    """Render an ordered list of highlights as an Obsidian ``Highlights.md`` body.

    Each highlight is a single expanded ``[!quote]`` callout (one block anchor).
    The title line carries the locator plus the ``@links`` as comma-separated
    ``[[wikilinks]]`` (middot-joined after the location, so people/events are
    scannable from the header). The body holds the quoted text, then the author's
    note as a nested blockquote (``>> ...``), then the ``#tags`` on a trailing line.
    """
    anchors = build_anchors(highlights)
    blocks: list[str] = []
    for h, anchor in zip(highlights, anchors):
        title_parts = [p for p in (_label(h),) if p]
        if h.links:
            title_parts.append(", ".join(wikilink(name) for name in h.links))
        title = " · ".join(title_parts)
        lines = ["> [!quote]+" + (f" {title}" if title else "")]
        lines += _quote_lines(h.text, ">")
        if h.note and h.note.strip():
            lines.append(">")
            lines += _quote_lines(h.note, ">>")
        if h.tags:
            lines.append(">")
            lines.append("> " + " ".join(f"#{t}" for t in h.tags))
        lines.append(f"^{anchor}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"
