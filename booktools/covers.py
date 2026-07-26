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
from urllib.parse import quote

from booktools.obsidian import (
    BOOKS_DIRNAME,
    extract_wikilinks,
    frontmatter_values,
    unquote,
)


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


def _cover_is_blank(fm: dict[str, str]) -> bool:
    """True if the note has no usable `cover:` value."""
    return unquote(fm.get("cover", "")).strip() == ""


def find_missing(vault: Path) -> list[MissingBook]:
    """Return `type: book` notes under vault/Books whose cover is blank/absent."""
    out: list[MissingBook] = []
    books_dir = vault / BOOKS_DIRNAME
    if not books_dir.is_dir():
        return out
    for md in sorted(books_dir.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = frontmatter_values(text)
        if unquote(fm.get("type", "")) != "book":
            continue
        if not _cover_is_blank(fm):
            continue
        out.append(MissingBook(
            note_path=md,
            title=unquote(fm.get("title", "")),
            authors=extract_wikilinks(fm.get("authors", "")),
            isbn=(unquote(fm.get("isbn", "")).strip() or None),
            amazon=(unquote(fm.get("amazon", "")).strip() or None),
        ))
    return out


GOOGLE_API = "https://www.googleapis.com/books/v1/volumes"

# imageLinks keys from best to worst.
_GOOGLE_IMAGE_KEYS = (
    "extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail",
)


def _label(title: str, authors: list[str]) -> str:
    return f"{title} — {authors[0]}" if authors else title


def _upgrade_google_url(url: str) -> str:
    """Prefer https and a larger zoom; drop the page-curl overlay."""
    url = url.replace("http://", "https://")
    url = url.replace("&edge=curl", "").replace("edge=curl&", "").replace("edge=curl", "")
    return url


def google_books_candidates(book: MissingBook, fetch_json) -> list[Candidate]:
    """Query Google Books; return one candidate per volume that has an image."""
    if book.isbn:
        q = f"isbn:{book.isbn}"
    else:
        parts = [f'intitle:{book.title}']
        if book.authors:
            parts.append(f"inauthor:{book.authors[0]}")
        q = " ".join(parts)
    url = f"{GOOGLE_API}?q={quote(q, safe=':')}&maxResults=5"
    try:
        data = fetch_json(url)
    except Exception:
        return []
    out: list[Candidate] = []
    for item in data.get("items", []):
        info = item.get("volumeInfo", {})
        links = info.get("imageLinks", {})
        chosen = next((links[k] for k in _GOOGLE_IMAGE_KEYS if links.get(k)), None)
        if not chosen:
            continue
        out.append(Candidate(
            source="google",
            label=_label(info.get("title", book.title), info.get("authors", [])),
            image_url=_upgrade_google_url(chosen),
            fmt=None,
        ))
    return out
