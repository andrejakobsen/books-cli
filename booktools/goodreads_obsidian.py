#!/usr/bin/env python3
"""Convert a Goodreads library CSV export into an Obsidian book vault.

Reads the CSV Goodreads produces from "My Books -> Import and export", and for
each *read* or *currently-reading* book (by default) creates or merges an
Obsidian note in the same
shape as the Calibre importer. Existing information is never overwritten: only
absent/empty properties are filled. A review is written to
"Exports/<Author>/<Title>/Review.md" and embedded into the flat book note under
a "## Review" heading.

Standard library only.
"""

from __future__ import annotations

import csv as _csv
from dataclasses import dataclass, field
from pathlib import Path

import typer

from booktools import resolve_path
from booktools.obsidian import (
    BOOK_PROPERTY_ORDER,
    BookRef,
    VaultIndex,
    html_to_markdown,
    link_list,
    plain_list,
    update_frontmatter,
    with_source,
    write_leaf_with_embed,
    write_stub,
    yaml_quote,
)


@dataclass
class GoodreadsBook:
    title: str
    authors: list[str] = field(default_factory=list)
    isbn: str | None = None
    isbn13: str | None = None
    rating: int | None = None
    publisher: str | None = None
    pages: str | None = None
    published: str | None = None      # year only
    binding: str | None = None        # Goodreads "Binding" (Hardcover, Kindle Edition, ...)
    date_read: str | None = None
    date_added: str | None = None
    status: str | None = None         # reading status (Exclusive Shelf)
    shelves: list[str] = field(default_factory=list)
    review: str | None = None
    private_notes: str | None = None
    exclusive_shelf: str | None = None


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
            books.append(GoodreadsBook(
                title=(row.get("Title") or "").strip(),
                authors=_split_authors(row.get("Author", ""), row.get("Additional Authors", "")),
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
                exclusive_shelf=(row.get("Exclusive Shelf") or "").strip() or None,
            ))
    return books


# --- Note construction ------------------------------------------------------

def _goodreads_updates(book: GoodreadsBook) -> dict[str, str]:
    """Canonical property -> formatted value; empty for fields Goodreads lacks."""
    u = {k: "" for k in BOOK_PROPERTY_ORDER if k != "type"}
    if book.title:
        u["title"] = yaml_quote(book.title)
    if book.authors:
        u["authors"] = link_list(book.authors)
    if book.publisher:
        u["publisher"] = yaml_quote(book.publisher)
    if book.published:
        u["published"] = book.published
    # Derived from Goodreads' Binding; the "never overwrite" merge rule keeps an
    # existing value (e.g. a Calibre-set "ebook") intact when merging.
    u["format"] = _norm_format(book.binding)
    if book.pages:
        u["pages"] = book.pages
    if book.status:
        u["status"] = book.status  # safe plain scalar (read / reading / to-read)
    if book.shelves:
        u["shelves"] = plain_list(book.shelves)
    if book.rating is not None:
        u["rating"] = str(book.rating)
    isbn = book.isbn13 or book.isbn
    if isbn:
        u["isbn"] = yaml_quote(isbn)
    if book.date_added:
        u["date_added"] = book.date_added
    if book.date_read:
        u["date_read"] = book.date_read
    u["source"] = "goodreads"
    return u


def _review_markdown(book: GoodreadsBook) -> str | None:
    if not book.review and not book.private_notes:
        return None
    parts = [f"# {book.title} — Review", ""]
    if book.date_read:
        parts += [f"*Read: {book.date_read}*", ""]
    if book.review:
        parts += [html_to_markdown(book.review), ""]
    if book.private_notes:
        parts += ["## Private Notes", "", html_to_markdown(book.private_notes), ""]
    return "\n".join(parts)


DEFAULT_SHELVES = "read,currently-reading"


def _parse_shelves(shelf: str) -> set[str] | None:
    """Parse the ``--shelf`` value into a set of shelves, or None for "all".

    Accepts a comma-separated list (e.g. ``read,currently-reading``). The special
    value ``all`` (alone or within the list) means "import every book".
    """
    wanted = {s.strip() for s in (shelf or "").split(",") if s.strip()}
    return None if "all" in wanted else wanted


def convert(csv_path: Path, output: Path, shelf: str = DEFAULT_SHELVES) -> dict:
    stats = {"created": 0, "merged": 0, "reviews": 0, "skipped": 0, "authors": set()}
    index = VaultIndex(output)
    authors_dir = output / "Authors"
    wanted = _parse_shelves(shelf)

    for book in parse_csv(csv_path):
        if wanted is not None and (book.exclusive_shelf or "") not in wanted:
            stats["skipped"] += 1
            continue
        if not book.title or not book.authors:
            stats["skipped"] += 1
            continue

        ref = BookRef(title=book.title, authors=book.authors,
                      isbn=book.isbn13 or book.isbn)
        dest = index.find_or_create(ref)
        stats["created" if dest.created else "merged"] += 1

        base = dest.note_path.read_text(encoding="utf-8")
        dest.note_path.write_text(
            update_frontmatter(base, _goodreads_updates(book)), encoding="utf-8")

        for author in book.authors:
            write_stub(authors_dir, author, "author")
            stats["authors"].add(author)

        review = _review_markdown(book)
        if review and write_leaf_with_embed(
                dest.note_path, dest.export_dir, "Review.md",
                with_source("goodreads", review), "Review", overwrite=False):
            stats["reviews"] += 1

    return stats


def goodreads_to_obsidian(
    csv: Path = typer.Option(
        ...,
        "--csv", "-c",
        help="Path to the Goodreads library CSV export. Relative paths resolve against the current directory.",
    ),
    output: Path = typer.Option(
        Path("Obsidian"),
        "--output", "-o",
        help="Output Obsidian vault. Relative paths resolve against the current directory.",
    ),
    shelf: str = typer.Option(
        DEFAULT_SHELVES,
        "--shelf",
        help="Comma-separated Goodreads exclusive shelves to import (read/currently-reading/to-read). Defaults to 'read,currently-reading'. Use 'all' for every book.",
    ),
) -> None:
    """Convert a Goodreads CSV export into Obsidian book notes.

    By default books on the 'read' and 'currently-reading' shelves are imported
    (pass --shelf to narrow, e.g. '--shelf read', or 'all' for everything).
    Existing notes are
    never overwritten: only empty/absent properties are filled, and a review is
    written to 'Exports/<Author>/<Title>/Review.md' and embedded into the flat
    book note under a '## Review' heading. Books are matched to existing notes by
    ISBN, then by a strict Author/Title comparison.
    """
    csv = resolve_path(csv, Path.cwd())
    output = resolve_path(output, Path.cwd())

    if not csv.is_file():
        raise typer.BadParameter(f"CSV not found: {csv}", param_hint="--csv")

    output.mkdir(parents=True, exist_ok=True)
    stats = convert(csv, output, shelf=shelf)
    typer.echo(
        f"Done. {stats['created']} created, {stats['merged']} merged, "
        f"{stats['reviews']} reviews, {len(stats['authors'])} authors, "
        f"{stats['skipped']} skipped.\nOutput: {output}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("goodreads")(goodreads_to_obsidian)


def main() -> None:
    """Standalone entry point so the shim script keeps working on its own."""
    typer.run(goodreads_to_obsidian)


if __name__ == "__main__":
    main()
