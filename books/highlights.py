"""Source-agnostic highlight model + Obsidian rendering.

A *Highlight* is a reading annotation independent of the app it came from (Kobo,
Kindle, Apple Books, ...). Each source maps its own storage into this model; all
Obsidian formatting (callouts, stable block anchors) lives here so every source
shares one output format.

Standard library only.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from books.obsidian import wikilink


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
    source: str | None = None          # provenance (kobo | readwise | ...) for grouping


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


def build_anchors(highlights: list[Highlight]) -> list[str]:
    """Compute a unique Obsidian block-id per highlight, mirroring its locator.

    Base is ``ch<index>`` (when known) joined with a location component that
    matches the callout title: the reading ``<percent>`` within the chapter when
    a progress is set (e.g. ``ch1-42`` for 42%), else the page ``p<page>``
    (physical books). When neither is available a per-list counter ``hl<n>`` is
    used. Collisions get a ``-2``, ``-3`` suffix so ids are always unique.
    """
    seen: set[str] = set()
    anchors: list[str] = []
    for i, h in enumerate(highlights, start=1):
        chapter = f"ch{h.chapter_index}" if h.chapter_index is not None else ""
        page = re.sub(r"[^0-9-]", "", h.page) if h.page else ""
        if h.progress is not None:
            loc = str(round(h.progress * 100))
        elif page:
            loc = f"p{page}"
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


def _label(h: Highlight, chapter_prefix: str = "ch.") -> str:
    parts: list[str] = []
    if h.chapter_index is not None:
        parts.append(f"{chapter_prefix} {h.chapter_index}")
    if h.page:
        label = h.page.replace('-', '–')
        # location_label is "p." by default; an explicit "" suppresses the prefix
        # (used for audio timestamps like "3:24:15" that carry no unit).
        prefix = h.location_label if h.location_label is not None else "p."
        parts.append(f"{prefix} {label}" if prefix else label)
    if h.progress is not None:
        parts.append(f"{round(h.progress * 100)}%")
    return " · ".join(parts)


def _chapter_key(h: Highlight) -> tuple:
    """Identity of the chapter a highlight belongs to, for consecutive-run grouping."""
    if h.chapter_title:
        return ("title", h.chapter_title)
    if h.chapter_index is not None:
        return ("index", h.chapter_index)
    return ("none",)


def _chapter_header(h: Highlight) -> str | None:
    """Markdown header for a chapter run.

    ``### {title}`` when a title is known (``###`` because the whole block sits
    under a ``## Highlights`` section); a title-less run with only an index falls
    back to ``### Chapter {index}``. Returns None when the run has neither.
    """
    if h.chapter_title:
        return f"### {h.chapter_title}"
    if h.chapter_index is not None:
        return f"### Chapter {h.chapter_index}"
    return None


def _quote_lines(text: str, prefix: str) -> list[str]:
    """Prefix each line of *text* for a callout body; blank lines keep the bare marker."""
    return [f"{prefix} {ln}" if ln.strip() else prefix.rstrip()
            for ln in text.split("\n")]


def _callout(h: Highlight, anchor: str, chapter_prefix: str) -> str:
    """Render one highlight as a single expanded ``[!quote]+`` callout block."""
    title_parts = [p for p in (_label(h, chapter_prefix),) if p]
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
    return "\n".join(lines)


def render_highlights(highlights: list[Highlight],
                      chapter_label: str | None = None) -> str:
    """Render a list of highlights as an Obsidian ``## Highlights`` body.

    Highlights are sorted into reading order (see :func:`sort_key`) before
    rendering, so output is always ordered by chapter + ``%`` (or by page for
    physical books) regardless of input order; this also makes chapter grouping
    robust against scattered input.

    **Source grouping:** when the input mixes *two or more* distinct
    ``Highlight.source`` values the output is split into per-source groups, each
    introduced by a small ``### <Source>`` header (sources in alphabetical
    order), with the usual chapter subheaders and reading-order sort applied
    *within* each group. When all highlights share one source (or none carry a
    source) no source header is emitted and single-source output is unchanged.

    When any highlight in a group carries a ``chapter_title`` that group is
    *chapter-grouped*: a ``### {title}`` header is emitted at each chapter change.
    Each callout's locator keeps the chapter, prefixed by ``chapter_label`` when
    given (else ``"ch."``). Block anchors are unique across the whole section.
    """
    chapter_prefix = chapter_label or "ch."
    distinct_sources = sorted({h.source for h in highlights if h.source})
    if len(distinct_sources) > 1:
        ordered_groups = [
            (src, sorted([h for h in highlights if (h.source or "") == src],
                         key=sort_key))
            for src in distinct_sources
        ]
    else:
        ordered_groups = [(None, sorted(highlights, key=sort_key))]

    # Anchors are computed over the full, final-order sequence so block ids are
    # unique across every source group.
    flat = [h for _src, group in ordered_groups for h in group]
    anchors = build_anchors(flat)
    anchor_by_id = {id(h): a for h, a in zip(flat, anchors)}

    blocks: list[str] = []
    for src, group in ordered_groups:
        if src is not None:
            blocks.append(f"### {src.title()}")
        grouped = any(h.chapter_title for h in group)
        prev_key = None
        for h in group:
            if grouped:
                key = _chapter_key(h)
                if key != prev_key:
                    header = _chapter_header(h)
                    if header:
                        blocks.append(header)
                    prev_key = key
            blocks.append(_callout(h, anchor_by_id[id(h)], chapter_prefix))
    return "\n\n".join(blocks) + "\n"
