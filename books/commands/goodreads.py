#!/usr/bin/env python3
"""Write a Goodreads library CSV export into the CSV metadata store.

Reads the CSV Goodreads produces from "My Books -> Import and export" and dumps
every row (all shelves) into the ``goodreads`` metadata layer
(``Data/Sources/goodreads.csv``). The ``render`` command later turns each merged
row into a note; this importer owns no notes, reviews, or stubs.

Standard library only.
"""

from __future__ import annotations

import csv as _csv
from dataclasses import dataclass, field
from pathlib import Path

import typer

from books.core import config, store

GOODREADS_BOOK_URL = "https://www.goodreads.com/book/show/"


@dataclass
class GoodreadsBook:
    title: str
    book_id: str | None = None
    authors: list[str] = field(default_factory=list)
    isbn: str | None = None
    isbn13: str | None = None
    rating: int | None = None
    publisher: str | None = None
    pages: str | None = None
    published: str | None = None  # year only
    binding: str | None = None  # Goodreads "Binding" (Hardcover, Kindle Edition, ...)
    date_read: str | None = None
    date_added: str | None = None
    status: str | None = None  # reading status (Exclusive Shelf)
    shelves: list[str] = field(default_factory=list)
    review: str | None = None
    private_notes: str | None = None


def _strip_isbn(raw: str) -> str | None:
    """Unwrap Goodreads' ="..." Excel escaping; '=""' -> None."""
    raw = (raw or "").strip()
    if raw.startswith('="') and raw.endswith('"'):
        raw = raw[2:-1]
    return raw.strip('"').strip() or None


def _norm_date(raw: str) -> str | None:
    raw = (raw or "").strip()
    return raw.replace("/", "-") or None


def _split_authors(author: str, additional: str) -> list[str]:
    authors = [author.strip()] if (author or "").strip() else []
    for extra in (additional or "").split(","):
        if extra.strip():
            authors.append(extra.strip())
    return authors


def _norm_status(shelf: str) -> str | None:
    shelf = (shelf or "").strip()
    if not shelf:
        return None
    return "reading" if shelf == "currently-reading" else shelf


# Goodreads "Binding" values grouped into our canonical `format` property.
_EBOOK_BINDINGS = {"kindle edition", "ebook", "nook", "e-book"}
_AUDIO_BINDINGS = {"audiobook", "audio cd", "audible audio"}


def _norm_format(binding: str | None) -> str:
    """Map a Goodreads binding to a canonical format; default to physical.

    Goodreads exports are predominantly physical editions, so an unknown or
    missing binding falls back to "physical".
    """
    b = (binding or "").strip().lower()
    if b in _EBOOK_BINDINGS:
        return "ebook"
    if b in _AUDIO_BINDINGS:
        return "audiobook"
    return "physical"


def parse_csv(path: Path) -> list[GoodreadsBook]:
    books: list[GoodreadsBook] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in _csv.DictReader(fh):
            rating_raw = (row.get("My Rating") or "").strip()
            try:
                rating = int(float(rating_raw))
            except ValueError:
                rating = 0
            shelves = [s.strip() for s in (row.get("Bookshelves") or "").split(",") if s.strip()]
            books.append(
                GoodreadsBook(
                    title=(row.get("Title") or "").strip(),
                    book_id=(row.get("Book Id") or "").strip() or None,
                    authors=_split_authors(
                        row.get("Author", ""), row.get("Additional Authors", "")
                    ),
                    isbn=_strip_isbn(row.get("ISBN", "")),
                    isbn13=_strip_isbn(row.get("ISBN13", "")),
                    rating=rating if rating > 0 else None,
                    publisher=(row.get("Publisher") or "").strip() or None,
                    pages=(row.get("Number of Pages") or "").strip() or None,
                    published=(row.get("Year Published") or "").strip() or None,
                    binding=(row.get("Binding") or "").strip() or None,
                    date_read=_norm_date(row.get("Date Read", "")),
                    date_added=_norm_date(row.get("Date Added", "")),
                    status=_norm_status(row.get("Exclusive Shelf", "")),
                    shelves=shelves,
                    review=(row.get("My Review") or "").strip() or None,
                    private_notes=(row.get("Private Notes") or "").strip() or None,
                )
            )
    return books


# --- Store row construction -------------------------------------------------


def _row_from_book(book: GoodreadsBook) -> store.BookRow:
    """Map a parsed Goodreads row to a store ``BookRow`` (all fields verbatim)."""
    isbn = book.isbn13 or book.isbn or ""
    goodreads_url = f"{GOODREADS_BOOK_URL}{book.book_id}" if book.book_id else ""
    review_parts: list[str] = []
    if book.review:
        review_parts.append(book.review)
    if book.private_notes:
        review_parts.append(f"### Private Notes\n\n{book.private_notes}")
    return store.BookRow(
        title=book.title,
        authors=list(book.authors),
        publisher=book.publisher or "",
        published=book.published or "",
        format=_norm_format(book.binding),
        pages=book.pages or "",
        status=book.status or "",
        shelves=list(book.shelves),
        rating=str(book.rating) if book.rating is not None else "",
        isbn=isbn,
        goodreads=goodreads_url,
        date_added=book.date_added or "",
        date_read=book.date_read or "",
        review="\n\n".join(review_parts),
    )


def convert(csv_path: Path, output: Path) -> dict:
    """Write every Goodreads row into the ``goodreads`` metadata layer CSV.

    Every shelf is emitted (books.csv becomes the whole library); the renderer
    turns each row into a note.
    """
    stats = {"books": 0, "reviews": 0, "skipped": 0}
    output.mkdir(parents=True, exist_ok=True)
    rows: list[store.BookRow] = []
    for book in parse_csv(csv_path):
        if not book.title or not book.authors:
            stats["skipped"] += 1
            continue
        row = _row_from_book(book)
        rows.append(row)
        stats["books"] += 1
        if row.review:
            stats["reviews"] += 1
    store.write_layer(output, "goodreads", rows)
    return stats


def goodreads_to_obsidian(
    csv: Path | None = typer.Option(
        None,
        "--csv",
        "-c",
        help="Path to a Goodreads CSV export, or a folder of exports (the newest "
        "*.csv is used). Defaults to <vault>/Data/Imports/goodreads. Relative "
        "paths resolve against the current directory.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
) -> None:
    """Write a Goodreads CSV export into the CSV metadata store.

    Every row (all shelves) is dumped into ``Data/Sources/goodreads.csv``; the
    ``render`` command later turns each merged row into a note. No notes, reviews,
    or stubs are written here.
    """
    try:
        csv = config.resolve_csv_arg(csv, "goodreads", output)
    except FileNotFoundError as exc:
        raise typer.BadParameter(str(exc), param_hint="--csv") from exc
    output = config.resolve_vault(output)

    if not csv.is_file():
        raise typer.BadParameter(f"CSV not found: {csv}", param_hint="--csv")

    output.mkdir(parents=True, exist_ok=True)
    stats = convert(csv, output)
    typer.echo(
        f"Done. {stats['books']} books, {stats['reviews']} reviews, "
        f"{stats['skipped']} skipped.\nOutput: {output}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("goodreads")(goodreads_to_obsidian)
