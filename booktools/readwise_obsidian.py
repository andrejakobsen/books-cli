#!/usr/bin/env python3
"""Convert a Readwise CSV export into an Obsidian book vault.

Readwise exports one row per highlight with columns: Highlight, Book Title,
Book Author, Amazon Book ID, Note, Color, Tags, Location Type, Location,
Highlighted at, Document tags. Each row maps into the shared source-agnostic
Highlight model; per book a "Highlights.md" is written under
"Exports/<Author>/<Title>/" and embedded into the flat note under a
"## Highlights" heading. Books are matched to existing notes by Amazon id, then
by a strict Author/Title comparison (using a title with any "(Series #N)" suffix
removed), so highlights accumulate alongside Calibre/Goodreads data without
clobbering.

Standard library only.
"""

from __future__ import annotations

import csv as _csv
import re
from pathlib import Path

import typer

from booktools import resolve_path
from booktools.highlights import Highlight, render_highlights, sanitize_tag
from booktools.obsidian import (
    BookRef,
    VaultIndex,
    link_list,
    plain_list,
    update_frontmatter,
    with_source,
    write_leaf_with_embed,
    write_stub,
    yaml_quote,
)

# Trailing "(Series #N)" or "(Series #N.M)" suffix on a Readwise book title.
_SERIES_RE = re.compile(r"\s*\(([^()]+?)\s+#(\d+(?:\.\d+)?)\)\s*$")


def split_series(title: str) -> tuple[str, str | None, str | None]:
    """Split a trailing "(Series #N)" off *title*.

    Returns (clean_title, series_name, series_index). When no suffix is present
    the title is returned verbatim with (None, None) for the series fields.
    """
    m = _SERIES_RE.search(title or "")
    if not m:
        return (title or "").strip(), None, None
    clean = (title[: m.start()]).strip()
    return clean, m.group(1).strip(), m.group(2).strip()


def _split_tags(raw: str | None) -> list[str]:
    """Comma-split a tag string into sanitized, de-duplicated inline tags."""
    tags: list[str] = []
    for part in (raw or "").split(","):
        tag = sanitize_tag(part)
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def row_to_highlight(row: dict) -> Highlight:
    """Map a Readwise CSV row to a source-agnostic Highlight.

    Location Type drives the location label: "page" -> "p." (default), "location"
    -> "loc." (Kindle), anything else (e.g. "order") -> no location recorded.
    """
    loc_type = (row.get("Location Type") or "").strip().lower()
    location = (row.get("Location") or "").strip() or None
    page: str | None = None
    label: str | None = None
    if location and loc_type == "page":
        page = location
    elif location and loc_type == "location":
        page, label = location, "loc."
    return Highlight(
        text=(row.get("Highlight") or "").strip(),
        note=(row.get("Note") or "").strip() or None,
        page=page,
        location_label=label,
        date=(row.get("Highlighted at") or "").strip() or None,
        tags=_split_tags(row.get("Tags")),
    )
