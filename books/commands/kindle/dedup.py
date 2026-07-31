#!/usr/bin/env python3
"""Deduplicate adjusted Kindle highlights and attach notes to them.

Kindle logs one record per event, so resizing a highlight (or editing a note)
appends a fresh record. This module collapses overlapping consecutive highlight
events to their latest version, does the same for notes, then attaches each
surviving note to the highlight it overlaps (a note matching no highlight becomes
a standalone text-less highlight carrying the note). Bookmarks are dropped.
Standard library only.
"""

from __future__ import annotations

from datetime import datetime

from books.commands.kindle.parser import Entry
from books.core.highlights import Highlight


def _overlap(a: Entry, b: Entry) -> bool:
    """True when two located entries share a start/end or one contains the other."""
    if a.loc_start is None or b.loc_start is None:
        return False
    if a.loc_start == b.loc_start or a.loc_end == b.loc_end:
        return True
    return (a.loc_start <= b.loc_start <= a.loc_end) or (b.loc_start <= a.loc_start <= b.loc_end)


def _pick_latest(cluster: list[tuple[int, Entry]]) -> Entry:
    """Return the cluster's latest entry (by ``added``; tie -> later file order).

    ``added is None`` sorts oldest so a dated event always wins over an undated one.
    """

    def key(item: tuple[int, Entry]) -> tuple:
        idx, entry = item
        return (entry.added is not None, entry.added or datetime.min, idx)

    return max(cluster, key=key)[1]


def _dedup(entries: list[Entry]) -> list[Entry]:
    """Collapse overlapping entries to their latest, preserving unlocated ones."""
    located = [(i, e) for i, e in enumerate(entries) if e.loc_start is not None]
    unlocated = [e for e in entries if e.loc_start is None]
    located.sort(key=lambda ie: (ie[1].loc_start, ie[1].loc_end))

    result: list[Entry] = []
    cluster: list[tuple[int, Entry]] = []
    cluster_end: int | None = None
    for idx, entry in located:
        if cluster and cluster_end is not None and entry.loc_start <= cluster_end:
            cluster.append((idx, entry))
            cluster_end = max(cluster_end, entry.loc_end)
        else:
            if cluster:
                result.append(_pick_latest(cluster))
            cluster = [(idx, entry)]
            cluster_end = entry.loc_end
    if cluster:
        result.append(_pick_latest(cluster))
    return result + unlocated


def _to_highlight(entry: Entry) -> Highlight:
    """Map a surviving highlight ``Entry`` to a source-agnostic ``Highlight``."""
    if entry.location is not None:
        page, label = entry.location, "loc."
    elif entry.page is not None:
        page, label = entry.page, None
    else:
        page, label = None, None
    return Highlight(
        text=entry.text,
        page=page,
        location_label=label,
        date=entry.added.isoformat() if entry.added else None,
        source="kindle",
    )


def _match_note_index(note: Entry, highlights: list[Entry]) -> int | None:
    """Index of the highlight this note overlaps (nearest by start), else None."""
    candidates = [(i, h) for i, h in enumerate(highlights) if _overlap(note, h)]
    if not candidates:
        return None
    return min(candidates, key=lambda ih: abs(ih[1].loc_start - note.loc_start))[0]


def to_highlights(entries: list[Entry]) -> list[Highlight]:
    """Dedup a book's entries and return its final list of ``Highlight``s."""
    highlights = _dedup([e for e in entries if e.kind == "highlight"])
    notes = _dedup([e for e in entries if e.kind == "note"])

    built = [_to_highlight(h) for h in highlights]
    for note in notes:
        idx = _match_note_index(note, highlights)
        if idx is None:
            orphan = _to_highlight(note)
            orphan.text = ""
            orphan.note = note.text
            built.append(orphan)
        else:
            existing = built[idx].note
            built[idx].note = f"{existing}\n{note.text}" if existing else note.text
    return built
