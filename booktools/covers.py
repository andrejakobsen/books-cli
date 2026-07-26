#!/usr/bin/env python3
"""Fill missing book-note covers from Google Books, Open Library, and Amazon.

Scans an Obsidian vault for `type: book` notes whose `cover:` frontmatter is
blank/absent and fetches a cover image. Sources are tried in order — Google
Books, then Open Library (paperback editions preferred where the format is
known), then Amazon (only when the note already carries an `amazon` ASIN, by
constructing the known cover-image URL — no scraping). All network I/O is
injected so the logic is unit-testable; vault writing reuses booktools.obsidian.

Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class MissingBook:
    """A book note whose `cover:` frontmatter is blank/absent."""
    note_path: Path
    title: str
    authors: list[str]
    isbn: str | None
    amazon: str | None


@dataclass
class Candidate:
    """A candidate cover image found for a book."""
    source: str          # "google" | "openlibrary" | "amazon"
    label: str           # matched title / author, for display
    image_url: str
    fmt: str | None      # "paperback" | "hardcover" | None (unknown)
