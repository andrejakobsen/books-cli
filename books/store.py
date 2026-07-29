"""Canonical CSV store for book metadata and highlights.

On-disk source of truth under ``<vault>/Data/``:

- ``Data/sources/<source>.csv``  -- raw per-source metadata layers.
- ``Data/books.csv``             -- derived merged catalog (one row per book).
- ``Data/Highlights/<book-id>.csv`` -- per-book union of highlights (``source`` column).

Metadata layers are merged by fixed source precedence into ``books.csv``; each
book is assigned a stable ``book_id`` (the note stem ``<Title> - <Author>``).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

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
