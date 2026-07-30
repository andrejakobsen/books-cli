"""Canonical CSV store for book metadata and highlights.

On-disk source of truth under ``<vault>/Data/``:

- ``Data/Sources/<source>.csv``  -- raw per-source metadata layers.
- ``Data/books.csv``             -- derived merged catalog (one row per book).
- ``Data/Highlights/<book-id>.csv`` -- per-book union of highlights (``source`` column).

Metadata layers are merged by fixed source precedence into ``books.csv``; each
book is assigned a stable ``book_id`` (the note stem ``<Title> - <Author>``).
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from books.core.highlights import Highlight
from books.core.matching import (
    BookRef,
    author_key,
    canonical_isbn,
    norm_amazon,
    norm_title,
    title_similar,
)
from books.core.naming import next_free_stem, safe_filename, strip_subtitle

LIST_SEP = ";"

# Shared metadata columns (layers + books.csv). ``book_id`` is catalog-only.
METADATA_COLUMNS = (
    "title",
    "authors",
    "series",
    "series_index",
    "publisher",
    "published",
    "language",
    "format",
    "pages",
    "status",
    "shelves",
    "rating",
    "isbn",
    "amazon",
    "google",
    "goodreads",
    "uuid",
    "calibre_id",
    "date_added",
    "date_read",
    "review",
    "cover",
)
CATALOG_COLUMNS = ("book_id", *METADATA_COLUMNS)
LIST_FIELDS = ("authors", "shelves")

HIGHLIGHT_COLUMNS = (
    "source",
    "annotation_id",
    "chapter_index",
    "chapter_title",
    "location",
    "location_kind",
    "block",
    "segment",
    "date",
    "text",
    "note",
    "tags",
    "links",
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
    def from_csv_dict(cls, row: dict[str, str]) -> BookRow:
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
    def from_csv_dict(cls, row: dict[str, str]) -> HighlightRow:
        data: dict[str, object] = {}
        for col in HIGHLIGHT_COLUMNS:
            raw = (row.get(col) or "").strip()
            if col in HL_LIST_FIELDS:
                data[col] = [p.strip() for p in raw.split(LIST_SEP) if p.strip()]
            else:
                data[col] = raw
        return cls(**data)


DATA_DIRNAME = "Data"
SOURCES_DIRNAME = "Sources"
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


COVERS_STAGING_DIRNAME = "_covers"


def cover_staging_dir(vault: Path, source: str) -> Path:
    """Where *source* stages fetched/copied covers before merge assigns a book_id.

    ``Data/Sources/_covers/<source>/`` — a per-source scratch area whose images
    are recorded (vault-relative) on each ``BookRow.cover`` and materialized into
    ``Data/Covers/<book_id>.jpg`` by ``render`` after merge.
    """
    return sources_dir(vault) / COVERS_STAGING_DIRNAME / source


def stage_cover(
    vault: Path,
    source: str,
    name: str,
    *,
    data: bytes | None = None,
    src: Path | None = None,
) -> str:
    """Stage one cover image and return its vault-relative posix path.

    Writes ``Data/Sources/_covers/<source>/<name>.jpg`` from either raw *data*
    bytes or by copying an existing *src* file. The returned path is what callers
    record on ``BookRow.cover``.
    """
    staging = cover_staging_dir(vault, source)
    staging.mkdir(parents=True, exist_ok=True)
    dest = staging / f"{name}.jpg"
    if data is not None:
        dest.write_bytes(data)
    elif src is not None:
        shutil.copy2(src, dest)
    else:
        raise ValueError("stage_cover requires either data or src")
    return dest.relative_to(vault).as_posix()


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
    _write_csv(layer_path(vault, source), METADATA_COLUMNS, (r.to_csv_dict() for r in rows))


def read_layer(vault: Path, source: str) -> list[BookRow]:
    return [BookRow.from_csv_dict(r) for r in _read_csv(layer_path(vault, source))]


def read_all_layers(vault: Path) -> dict[str, list[BookRow]]:
    """All present source layers, keyed in ascending precedence order."""
    out: dict[str, list[BookRow]] = {}
    for source in PRECEDENCE:
        if layer_path(vault, source).is_file():
            out[source] = read_layer(vault, source)
    return out


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
    return title_similar(a.title, b.title)


def assign_book_id(title: str, author: str, used_lower: set[str]) -> str:
    """Stable, collision-free book id = the note stem ``<Title> - <Author>``.

    Uses the shared ``next_free_stem`` collision ladder (subtitle dropped ->
    subtitle restored -> numeric suffix), with case-insensitive tracking to
    match case-insensitive filesystems. ``used_lower`` holds lowercased stems.
    """
    stem = next_free_stem(title, author, used_lower)
    used_lower.add(stem.lower())
    return stem


def _rank(source: str) -> int:
    return PRECEDENCE.index(source) if source in PRECEDENCE else -1


def coalesce(members: list[tuple[str, BookRow]]) -> BookRow:
    """Merge ``(source, row)`` members into one row.

    Each field takes the value from the highest-precedence source that has a
    non-blank value. Pure and order-independent (rank depends only on source).
    """
    ordered = sorted(members, key=lambda sr: _rank(sr[0]))
    merged = BookRow()
    for _source, row in ordered:
        for col in METADATA_COLUMNS:
            val = getattr(row, col)
            if col in LIST_FIELDS:
                if val:
                    setattr(merged, col, list(val))
            elif val not in (None, ""):
                setattr(merged, col, val)
    return merged


def _cluster(tagged: list[tuple[str, BookRow]]) -> list[list[tuple[str, BookRow]]]:
    clusters: list[list[tuple[str, BookRow]]] = []
    for item in tagged:
        _src, row = item
        for c in clusters:
            if any(same_book(row, member) for _s, member in c):
                c.append(item)
                break
        else:
            clusters.append([item])
    return clusters


def write_books_csv(vault: Path, rows: list[BookRow]) -> None:
    _write_csv(books_csv_path(vault), CATALOG_COLUMNS, (r.to_csv_dict() for r in rows))


def read_books_csv(vault: Path) -> list[BookRow]:
    return [BookRow.from_csv_dict(r) for r in _read_csv(books_csv_path(vault))]


def merge(vault: Path) -> list[BookRow]:
    """Cluster all layers, coalesce by precedence, assign book_id, write books.csv.

    book_id assignment is deterministic: clusters are sorted by coalesced content
    before id assignment, ensuring the same book gets the same id regardless of
    layer row order (preventing highlight-file orphaning on re-export).
    """
    layers = read_all_layers(vault)
    tagged = [(source, row) for source, rows in layers.items() for row in rows]

    # First coalesce all clusters to get stable content for sorting
    clusters = _cluster(tagged)
    coalesced_clusters = [(coalesce(cluster), cluster) for cluster in clusters]

    # Sort by stable content key: clean_stem, full_title, isbn, amazon, series_index
    # Ensures two same-clean-stem books always sort the same way regardless of row order
    def sort_key(merged_and_cluster: tuple[BookRow, list]) -> tuple:
        merged, _raw_cluster = merged_and_cluster
        author = merged.authors[0] if merged.authors else ""
        clean = strip_subtitle(merged.title).strip()
        clean_stem = safe_filename(f"{clean} - {author}" if author else clean).lower()
        return (
            clean_stem,
            merged.title.casefold(),
            canonical_isbn(merged.isbn) or "",
            norm_amazon(merged.amazon) or "",
            merged.series_index or "",
        )

    sorted_clusters = sorted(coalesced_clusters, key=sort_key)

    # Now assign book_ids in deterministic order
    used: set[str] = set()
    catalog: list[BookRow] = []
    for merged, _raw_cluster in sorted_clusters:
        author = merged.authors[0] if merged.authors else ""
        merged.book_id = assign_book_id(merged.title, author, used)
        catalog.append(merged)
    write_books_csv(vault, catalog)
    return catalog


class Catalog:
    """Identity lookup over ``books.csv`` for the highlight importers.

    ``find(ref)`` returns the ``book_id`` of the matching book or None; it never
    creates anything. Matches by canonical ISBN, then Amazon id, then exact
    normalized (title, author), then a conservative fuzzy title fallback.
    """

    def __init__(self, vault: Path) -> None:
        self.rows = read_books_csv(vault)
        self._by_isbn: dict[str, str] = {}
        self._by_amazon: dict[str, str] = {}
        self._by_ta: dict[tuple[str, tuple[str, str]], str] = {}
        for r in self.rows:
            ci = canonical_isbn(r.isbn)
            if ci:
                self._by_isbn.setdefault(ci, r.book_id)
            na = norm_amazon(r.amazon)
            if na:
                self._by_amazon.setdefault(na, r.book_id)
            if r.authors:
                key = (norm_title(r.title), author_key(r.authors[0]))
                self._by_ta.setdefault(key, r.book_id)

    def find(self, ref: BookRef) -> str | None:
        ci = canonical_isbn(ref.isbn)
        if ci and ci in self._by_isbn:
            return self._by_isbn[ci]
        na = norm_amazon(ref.amazon)
        if na and na in self._by_amazon:
            return self._by_amazon[na]
        if ref.authors:
            key = (norm_title(ref.title), author_key(ref.authors[0]))
            if key in self._by_ta:
                return self._by_ta[key]
            akey = author_key(ref.authors[0])
            for r in self.rows:
                if not r.authors or author_key(r.authors[0]) != akey:
                    continue
                if title_similar(ref.title, r.title):
                    return r.book_id
        return None


def highlight_to_row(h: Highlight, source: str, annotation_id: str) -> HighlightRow:
    """Map a source-agnostic Highlight to a CSV HighlightRow.

    location/location_kind unify progress/page/timestamp:
      progress            -> ("percent", "<pct>")
      page + label "loc." -> ("kindle_loc", page)
      page + label ""     -> ("timestamp", page)   (audio; suppressed prefix)
      page (default)      -> ("page", page)
    """
    location = ""
    kind = ""
    if h.progress is not None:
        location, kind = str(round(h.progress * 100)), "percent"
    elif h.page:
        location = h.page
        if h.location_label == "loc.":
            kind = "kindle_loc"
        elif h.location_label == "":
            kind = "timestamp"
        else:
            kind = "page"
    return HighlightRow(
        source=source,
        annotation_id=annotation_id,
        chapter_index=str(h.chapter_index) if h.chapter_index is not None else "",
        chapter_title=h.chapter_title or "",
        location=location,
        location_kind=kind,
        block=h.block or "",
        segment=h.segment or "",
        date=h.date or "",
        text=h.text,
        note=h.note or "",
        tags=list(h.tags),
        links=list(h.links),
    )


def row_to_highlight(row: HighlightRow) -> Highlight:
    """Reverse of :func:`highlight_to_row`."""
    progress = None
    page = None
    label = None
    if row.location_kind == "percent" and row.location:
        try:
            progress = int(row.location) / 100
        except ValueError:
            progress = None
    elif row.location_kind == "kindle_loc":
        page, label = row.location or None, "loc."
    elif row.location_kind == "timestamp":
        page, label = row.location or None, ""
    elif row.location_kind == "page":
        page = row.location or None

    try:
        chapter_index = int(row.chapter_index) if row.chapter_index else None
    except ValueError:
        chapter_index = None

    return Highlight(
        text=row.text,
        source=row.source or None,
        note=row.note or None,
        chapter_index=chapter_index,
        chapter_title=row.chapter_title or None,
        progress=progress,
        block=row.block or None,
        segment=row.segment or None,
        page=page,
        location_label=label,
        date=row.date or None,
        tags=list(row.tags),
        links=list(row.links),
    )


def import_highlights(
    vault: Path,
    source: str,
    groups: list[tuple[BookRef, list[Highlight]]],
) -> dict:
    """Resolve each ``(BookRef, highlights)`` group to a book and write the store.

    Shared tail of every highlight importer. Each group's ref is resolved to a
    ``book_id`` via :class:`Catalog` (match-only); highlights for groups that
    resolve to the *same* book are accumulated before the single per-book write
    (``write_highlights`` replaces a source wholesale, so a second group would
    otherwise wipe the first). A group that resolves to nothing is skipped and
    counted. Returns ``{"books": int, "entries": int, "skipped": int}``.
    """
    vault.mkdir(parents=True, exist_ok=True)
    catalog = Catalog(vault)
    by_book: dict[str, list[Highlight]] = {}
    skipped = 0
    for ref, highlights in groups:
        book_id = catalog.find(ref)
        if book_id is None:
            skipped += 1
            continue
        by_book.setdefault(book_id, []).extend(highlights)

    stats = {"books": 0, "entries": 0, "skipped": skipped}
    for book_id, hls in by_book.items():
        hl_rows = [highlight_to_row(h, source, str(i)) for i, h in enumerate(hls)]
        write_highlights(vault, book_id, source, hl_rows)
        stats["books"] += 1
        stats["entries"] += len(hl_rows)
    return stats


def read_highlights(vault: Path, book_id: str) -> list[HighlightRow]:
    return [HighlightRow.from_csv_dict(r) for r in _read_csv(highlight_path(vault, book_id))]


def write_highlights(vault: Path, book_id: str, source: str, rows: list[HighlightRow]) -> None:
    """Replace this source's rows in the per-book file, preserving other sources."""
    existing = [r for r in read_highlights(vault, book_id) if r.source != source]
    combined = existing + list(rows)
    _write_csv(
        highlight_path(vault, book_id), HIGHLIGHT_COLUMNS, (r.to_csv_dict() for r in combined)
    )
