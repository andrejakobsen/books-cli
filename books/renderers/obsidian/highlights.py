"""Render highlights as an Obsidian `## Highlights` body (callouts + chapter headers)."""

from __future__ import annotations

import re

from books.core.highlights import Highlight, sort_key
from books.renderers.obsidian.format import wikilink


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
    sources_in_use = {h.source for h in highlights}
    distinct_sources = sorted(s for s in sources_in_use if s is not None)
    if len(distinct_sources) > 1:
        group_keys = ([None] if None in sources_in_use else []) + distinct_sources
        ordered_groups = [
            (src, sorted([h for h in highlights if h.source == src], key=sort_key))
            for src in group_keys
        ]
    else:
        ordered_groups = [(None, sorted(highlights, key=sort_key))]

    # Anchors are computed over the full, final-order sequence so block ids are
    # unique across every source group.
    flat = [h for _src, group in ordered_groups for h in group]
    anchors = build_anchors(flat)
    anchor_by_id = {id(h): a for h, a in zip(flat, anchors, strict=True)}

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
