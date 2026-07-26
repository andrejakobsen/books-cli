"""Source-agnostic highlight model + Obsidian rendering.

A *Highlight* is a reading annotation independent of the app it came from (Kobo,
Kindle, Apple Books, ...). Each source maps its own storage into this model; all
Obsidian formatting (callouts, stable block anchors) lives here so every source
shares one output format.

Standard library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


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
    date: str | None = None


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
        parts.append(f"p. {h.page.replace('-', '–')}")
    if h.progress is not None:
        parts.append(f"{round(h.progress * 100)}%")
    return " · ".join(parts)


def _callout(kind: str, title: str, body: str, expanded: bool) -> str:
    marker = "+" if expanded else "-"
    head = f"> [!{kind}]{marker}"
    if title:
        head += f" {title}"
    body_lines = "\n".join(f"> {ln}" if ln.strip() else ">"
                           for ln in body.split("\n"))
    return f"{head}\n{body_lines}"


def render_highlights(highlights: list[Highlight]) -> str:
    """Render an ordered list of highlights as an Obsidian ``Highlights.md`` body."""
    anchors = build_anchors(highlights)
    blocks: list[str] = []
    for h, anchor in zip(highlights, anchors):
        block = f"{_callout('quote', _label(h), h.text, expanded=True)}\n^{anchor}"
        if h.note and h.note.strip():
            note = _callout("note", "", h.note, expanded=False)
            block += f"\n\n{note}\n^{anchor}-note"
        blocks.append(block)
    return "\n\n".join(blocks) + "\n"
