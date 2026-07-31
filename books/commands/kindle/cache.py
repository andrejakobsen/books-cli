#!/usr/bin/env python3
"""Per-book JSON cache for Kindle highlights.

One file per book at ``<vault>/Data/Imports/kindle/cache/<stem>.json`` holds a
book's deduplicated highlights, keyed by a readable ``<Title> - <Author>`` stem
(Kindle carries no ISBN/ASIN). The cache decouples extraction (needs the device)
from catalog resolution: ``command.convert`` refreshes it from the device when
present and always resolves the whole cache against the catalog. Standard library
only.
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path

from books.core.highlights import Highlight
from books.core.naming import safe_filename

_HIGHLIGHT_FIELDS = {f.name for f in fields(Highlight)}


def cache_dir(vault: Path) -> Path:
    """The Kindle cache folder: ``<vault>/Data/Imports/kindle/cache``."""
    return vault / "Data" / "Imports" / "kindle" / "cache"


def highlight_to_dict(h: Highlight) -> dict:
    """Serialize a ``Highlight`` to a plain dict (all fields)."""
    return asdict(h)


def highlight_from_dict(d: dict) -> Highlight:
    """Rebuild a ``Highlight`` from a dict, ignoring unknown keys."""
    return Highlight(**{k: v for k, v in d.items() if k in _HIGHLIGHT_FIELDS})


def book_stem(title: str, author: str, used: set[str]) -> str:
    """A stable, readable cache stem for a book, disambiguated against *used*.

    ``used`` accumulates the lowercased stems already assigned this run (so a rare
    collision between two distinct books gets a ``(2)``/``(3)`` suffix). Callers
    iterate books in a deterministic (sorted) order so assignment is reproducible.
    """
    base = safe_filename(f"{title} - {author}" if author else title)
    stem = base
    n = 2
    while stem.lower() in used:
        stem = f"{base} ({n})"
        n += 1
    used.add(stem.lower())
    return stem


def save_book(cdir: Path, stem: str, title: str, author: str, highlights: list[Highlight]) -> None:
    """Write one book's cache record (wholesale overwrite; parents created)."""
    cdir.mkdir(parents=True, exist_ok=True)
    record = {
        "title": title,
        "author": author,
        "highlights": [highlight_to_dict(h) for h in highlights],
    }
    (cdir / f"{stem}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_all(cdir: Path) -> list[dict]:
    """Every cache record ``{title, author, highlights}``; skips corrupt files."""
    if not cdir.is_dir():
        return []
    records: list[dict] = []
    for path in sorted(cdir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        records.append(
            {
                "title": data.get("title", ""),
                "author": data.get("author", ""),
                "highlights": [highlight_from_dict(h) for h in data.get("highlights", [])],
            }
        )
    return records
