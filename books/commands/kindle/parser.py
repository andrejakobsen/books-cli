#!/usr/bin/env python3
"""Parse Kindle's ``My Clippings.txt`` log into raw ``Entry`` records.

The log appends one record per event, records separated by a line of
``==========``. Each record is: a title line ``Title (Author)`` (often preceded
by a per-record UTF-8 BOM), a metadata line (``- Your <Kind> <locator> | Added
on <date>``), a blank line, then the text (empty for Bookmarks). Standard
library only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

SEPARATOR = "=========="

_MONTHS = {
    name: num
    for num, name in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}

_KIND_RE = re.compile(r"-\s*Your\s+(\w+)", re.IGNORECASE)
_PAGE_RE = re.compile(r"on page\s+([0-9ivxlcdm]+(?:-[0-9ivxlcdm]+)?)", re.IGNORECASE)
_LOC_RE = re.compile(r"location\s+(\d+(?:-\d+)?)", re.IGNORECASE)
_ADDED_RE = re.compile(r"Added on\s+(.+?)\s*$", re.IGNORECASE)
# e.g. "Friday, 31 July 2015 00:17:35"
_DATE_RE = re.compile(r"\w+,\s*(\d{1,2})\s+(\w+)\s+(\d{4})\s+(\d{2}):(\d{2}):(\d{2})")
_AUTHOR_RE = re.compile(r"\(([^()]*)\)\s*$")


@dataclass
class Entry:
    """One raw clipping event."""

    kind: str  # "highlight" | "note" | "bookmark" | ...
    title: str
    author: str
    page: str | None
    location: str | None
    loc_start: int | None
    loc_end: int | None
    added: datetime | None
    text: str


def _range_ints(value: str | None) -> tuple[int | None, int | None]:
    """Numeric (start, end) from a range like ``472-473`` or a single ``364``.

    Returns ``(None, None)`` when the leading component is not an integer (e.g. a
    roman-numeral page ``xvii``). A single value yields ``(n, n)``.
    """
    if not value:
        return None, None
    parts = value.split("-")
    try:
        start = int(parts[0])
    except ValueError:
        return None, None
    try:
        end = int(parts[1]) if len(parts) > 1 else start
    except ValueError:
        end = start
    return start, end


def _parse_date(meta_line: str) -> datetime | None:
    """Parse the ``Added on <weekday>, <D Month YYYY> <HH:MM:SS>`` suffix.

    Uses a fixed English month-name map (locale-independent). Returns ``None``
    when the date is missing or unrecognizable.
    """
    added = _ADDED_RE.search(meta_line)
    if not added:
        return None
    m = _DATE_RE.search(added.group(1))
    if not m:
        return None
    day, month_name, year, hh, mm, ss = m.groups()
    month = _MONTHS.get(month_name.capitalize())
    if not month:
        return None
    try:
        return datetime(int(year), month, int(day), int(hh), int(mm), int(ss))
    except ValueError:
        return None


def _parse_record(block: str) -> Entry | None:
    """Parse one record block into an ``Entry`` (``None`` when malformed)."""
    lines = block.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if len(lines) < 2:
        return None
    title_line = lines[0].lstrip("﻿").strip()
    meta_line = lines[1].strip()

    kind_m = _KIND_RE.search(meta_line)
    if not kind_m:
        return None
    kind = kind_m.group(1).lower()

    author_m = _AUTHOR_RE.search(title_line)
    if author_m:
        author = author_m.group(1).strip()
        title = title_line[: author_m.start()].strip()
    else:
        author = ""
        title = title_line

    page_m = _PAGE_RE.search(meta_line)
    loc_m = _LOC_RE.search(meta_line)
    page = page_m.group(1) if page_m else None
    location = loc_m.group(1) if loc_m else None
    loc_start, loc_end = _range_ints(location if location is not None else page)

    added = _parse_date(meta_line)
    text = "\n".join(lines[2:]).strip()
    return Entry(kind, title, author, page, location, loc_start, loc_end, added, text)


def parse_clippings(text: str) -> list[Entry]:
    """Parse the whole ``My Clippings.txt`` into a list of ``Entry`` records."""
    entries: list[Entry] = []
    for block in text.split(SEPARATOR):
        if not block.strip():
            continue
        entry = _parse_record(block)
        if entry is not None:
            entries.append(entry)
    return entries
