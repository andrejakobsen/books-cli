"""Canonical CSV store for book metadata and highlights.

On-disk source of truth under ``<vault>/Data/``:

- ``Data/sources/<source>.csv``  -- raw per-source metadata layers.
- ``Data/books.csv``             -- derived merged catalog (one row per book).
- ``Data/Highlights/<book-id>.csv`` -- per-book union of highlights (``source`` column).

Metadata layers are merged by fixed source precedence into ``books.csv``; each
book is assigned a stable ``book_id`` (the note stem ``<Title> - <Author>``).
"""

from __future__ import annotations

import csv
from pathlib import Path

import isbnlib
from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from books.obsidian import author_key, norm_amazon, norm_isbn, norm_title, safe_filename, strip_subtitle

LIST_SEP = ";"

# Shared metadata columns (layers + books.csv). ``book_id`` is catalog-only.
METADATA_COLUMNS = (
    "title", "authors", "series", "series_index", "publisher", "published",
    "language", "format", "pages", "status", "shelves", "rating", "isbn",
    "amazon", "google", "goodreads", "uuid", "calibre_id", "date_added",
    "date_read", "review", "cover",
)
CATALOG_COLUMNS = ("book_id", *METADATA_COLUMNS)
LIST_FIELDS = ("authors", "shelves")

HIGHLIGHT_COLUMNS = (
    "source", "annotation_id", "chapter_index", "chapter_title", "location",
    "location_kind", "block", "segment", "date", "text", "note", "tags", "links",
)
HL_LIST_FIELDS = ("tags", "links")


class BookRow(BaseModel):
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    series: str = ""
    series_index: str = ""
    publisher: str = ""
    published: str = ""
    language: str = ""
    format: str = ""
    pages: str = ""
    status: str = ""
    shelves: list[str] = Field(default_factory=list)
    rating: str = ""
    isbn: str = ""
    amazon: str = ""
    google: str = ""
    goodreads: str = ""
    uuid: str = ""
    calibre_id: str = ""
    date_added: str = ""
    date_read: str = ""
    review: str = ""
    cover: str = ""
    book_id: str = ""  # populated only in the merged catalog

    def to_csv_dict(self) -> dict[str, str]:
        out: dict[str, str] = {"book_id": self.book_id}
        for col in METADATA_COLUMNS:
            val = getattr(self, col)
            out[col] = LIST_SEP.join(val) if col in LIST_FIELDS else str(val or "")
        return out

    @classmethod
    def from_csv_dict(cls, row: dict[str, str]) -> "BookRow":
        data: dict[str, object] = {}
        if row.get("book_id"):
            data["book_id"] = row["book_id"].strip()
        for col in METADATA_COLUMNS:
            raw = (row.get(col) or "").strip()
            if col in LIST_FIELDS:
                data[col] = [p.strip() for p in raw.split(LIST_SEP) if p.strip()]
            else:
                data[col] = raw
        return cls(**data)


class HighlightRow(BaseModel):
    source: str = ""
    annotation_id: str = ""
    chapter_index: str = ""
    chapter_title: str = ""
    location: str = ""
    location_kind: str = ""  # percent | page | kindle_loc | timestamp
    block: str = ""
    segment: str = ""
    date: str = ""
    text: str = ""
    note: str = ""
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)

    def to_csv_dict(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for col in HIGHLIGHT_COLUMNS:
            val = getattr(self, col)
            out[col] = LIST_SEP.join(val) if col in HL_LIST_FIELDS else str(val or "")
        return out

    @classmethod
    def from_csv_dict(cls, row: dict[str, str]) -> "HighlightRow":
        data: dict[str, object] = {}
        for col in HIGHLIGHT_COLUMNS:
            raw = (row.get(col) or "").strip()
            if col in HL_LIST_FIELDS:
                data[col] = [p.strip() for p in raw.split(LIST_SEP) if p.strip()]
            else:
                data[col] = raw
        return cls(**data)


DATA_DIRNAME = "Data"
SOURCES_DIRNAME = "sources"
HIGHLIGHTS_DIRNAME = "Highlights"
BOOKS_CSV = "books.csv"


def data_dir(vault: Path) -> Path:
    return vault / DATA_DIRNAME


def sources_dir(vault: Path) -> Path:
    return data_dir(vault) / SOURCES_DIRNAME


def layer_path(vault: Path, source: str) -> Path:
    return sources_dir(vault) / f"{source}.csv"


def books_csv_path(vault: Path) -> Path:
    return data_dir(vault) / BOOKS_CSV


def highlights_dir(vault: Path) -> Path:
    return data_dir(vault) / HIGHLIGHTS_DIRNAME


def highlight_path(vault: Path, book_id: str) -> Path:
    return highlights_dir(vault) / f"{book_id}.csv"


PRECEDENCE = ("calibre", "goodreads", "covers", "kobo", "highlighted", "readwise", "audible")


def _write_csv(path: Path, fieldnames, dict_rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in dict_rows:
            writer.writerow(row)


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_layer(vault: Path, source: str, rows: list[BookRow]) -> None:
    _write_csv(layer_path(vault, source), METADATA_COLUMNS,
               (r.to_csv_dict() for r in rows))


def read_layer(vault: Path, source: str) -> list[BookRow]:
    return [BookRow.from_csv_dict(r) for r in _read_csv(layer_path(vault, source))]


def read_all_layers(vault: Path) -> dict[str, list[BookRow]]:
    """All present source layers, keyed in ascending precedence order."""
    out: dict[str, list[BookRow]] = {}
    for source in PRECEDENCE:
        if layer_path(vault, source).is_file():
            out[source] = read_layer(vault, source)
    return out


TITLE_MATCH_THRESHOLD = 90  # rapidfuzz ratio 0-100; conservative to avoid false merges


def canonical_isbn(isbn: str | None) -> str | None:
    """Canonical ISBN-13 for matching, or None. Falls back to digit-normalization."""
    if not isbn:
        return None
    c = isbnlib.canonical(str(isbn))
    if c and isbnlib.is_isbn10(c):
        c = isbnlib.to_isbn13(c) or c
    return c or norm_isbn(isbn)


def same_book(a: BookRow, b: BookRow) -> bool:
    """True when two rows denote the same book.

    ISBN and Amazon id are authoritative when both sides have them (a conflict
    means *different* books). Otherwise fall back to same author + fuzzy title.
    """
    ia, ib = canonical_isbn(a.isbn), canonical_isbn(b.isbn)
    if ia and ib:
        return ia == ib
    aa, ab = norm_amazon(a.amazon), norm_amazon(b.amazon)
    if aa and ab:
        return aa == ab
    if not (a.authors and b.authors):
        return False
    if author_key(a.authors[0]) != author_key(b.authors[0]):
        return False
    return fuzz.partial_ratio(norm_title(a.title), norm_title(b.title)) >= TITLE_MATCH_THRESHOLD


def _stem(title: str, author: str) -> str:
    clean = strip_subtitle(title).strip()
    base = f"{clean} - {author}".strip() if author else clean
    return safe_filename(base)


def assign_book_id(title: str, author: str, used: set[str]) -> str:
    """Stable, collision-free book id = the note stem ``<Title> - <Author>``.

    Mirrors ``obsidian.VaultIndex._new_note_path``: subtitle dropped; on collision
    the subtitle is restored (``:`` -> ``,``); a numeric ``(n)`` suffix is last resort.
    """
    clean_stem = _stem(title, author)
    if clean_stem not in used:
        used.add(clean_stem)
        return clean_stem

    full = title.replace(":", ",").strip()
    full_stem = safe_filename(f"{full} - {author}".strip() if author else full)
    if full_stem not in used:
        used.add(full_stem)
        return full_stem

    n = 2
    while f"{clean_stem} ({n})" in used:
        n += 1
    stem = f"{clean_stem} ({n})"
    used.add(stem)
    return stem
