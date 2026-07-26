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


def parse_csv(path: Path) -> list[dict]:
    """Read the Readwise CSV export into a list of row dicts."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(_csv.DictReader(fh))


def convert(csv_path: Path, output: Path) -> dict:
    """Import every highlight, grouped by book, into the Obsidian vault."""
    stats = {"books": 0, "entries": 0, "authors": set()}
    index = VaultIndex(output)
    authors_dir = output / "Authors"

    # Group rows by book (Amazon id when present, else standardized title),
    # preserving CSV order.
    groups: dict[str, dict] = {}
    for row in parse_csv(csv_path):
        raw_title = (row.get("Book Title") or "").strip()
        if not raw_title:
            continue
        title, series, series_index = split_series(raw_title)
        amazon = (row.get("Amazon Book ID") or "").strip() or None
        author = (row.get("Book Author") or "").strip()
        doc_tags = [t.strip() for t in (row.get("Document tags") or "").split(",")
                    if t.strip()]
        key = amazon or title
        group = groups.setdefault(key, {
            "title": title, "author": author, "amazon": amazon,
            "series": series, "series_index": series_index,
            "shelves": doc_tags, "rows": []})
        group["rows"].append(row)

    for group in groups.values():
        authors = [group["author"]] if group["author"] else []
        ref = BookRef(title=group["title"], authors=authors, amazon=group["amazon"])
        dest = index.find_or_create(ref)

        updates = {
            "title": yaml_quote(group["title"]),
            "authors": link_list(authors) if authors else "",
            "amazon": yaml_quote(group["amazon"]) if group["amazon"] else "",
            "shelves": plain_list(group["shelves"]) if group["shelves"] else "",
            "source": "readwise",
        }
        if group["series"]:
            updates["series"] = yaml_quote(group["series"])
        if group["series_index"]:
            updates["series_index"] = group["series_index"]
        base = dest.note_path.read_text(encoding="utf-8")
        dest.note_path.write_text(update_frontmatter(base, updates), encoding="utf-8")

        highlights = [row_to_highlight(r) for r in group["rows"]]
        write_leaf_with_embed(
            dest.note_path, dest.export_dir, "Highlights.md",
            with_source("readwise", render_highlights(highlights)), "Highlights")

        for author in authors:
            write_stub(authors_dir, author, "author")
            stats["authors"].add(author)
        stats["books"] += 1
        stats["entries"] += len(highlights)

    return stats
