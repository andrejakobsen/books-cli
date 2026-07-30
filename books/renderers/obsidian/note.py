"""Assemble and write the flat Obsidian book notes from the CSV store.

This is the note producer: it turns a merged ``BookRow`` (+ its highlights) into
a self-contained ``Books/<book_id>.md`` note and materializes the cover. It owns
frontmatter assembly, the body layout (cover embed + write-once ``## Review`` +
marker-wrapped ``## Highlights``), and the per-vault render loop. The CLI
``render`` command is a thin dispatcher over :class:`ObsidianRenderer`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import typer

from books.core import store
from books.core.store import BookRow, row_to_highlight
from books.renderers.obsidian.format import format_rating, wikilink
from books.renderers.obsidian.frontmatter import (
    NOTE_PROPERTY_ORDER,
    PRESERVED_EXTRA_KEYS,
    RENDER_KEY_ORDER,
    dump_frontmatter,
    load_note,
)
from books.renderers.obsidian.highlights import render_highlights
from books.renderers.obsidian.layout import (
    AUTHORS_DIRNAME,
    BOOKS_DIRNAME,
    COVERS_DIRNAME,
    cover_embed,
    cover_link,
    write_stub,
)
from books.renderers.obsidian.sections import (
    ensure_section,
    ensure_top_embed,
    render_marked_section,
)


def compose_review(review: str, private_notes: str) -> str:
    """Compose the ``## Review`` section body from the review + private notes.

    The Goodreads importer stores the review and the private notes as separate
    plain-data columns; the markdown layout (private notes under a ``### Private
    Notes`` subheading) is owned here in the renderer. Returns ``""`` when both
    are blank.
    """
    parts: list[str] = []
    review = (review or "").strip()
    private_notes = (private_notes or "").strip()
    if review:
        parts.append(review)
    if private_notes:
        parts.append(f"### Private Notes\n\n{private_notes}")
    return "\n\n".join(parts)


def render_rating(raw: str) -> str:
    """Render a stored rating: numeric -> stars (:func:`format_rating`), else raw."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        return format_rating(float(raw))
    except ValueError:
        return raw


def _scalar(value):
    """Empty/whitespace strings -> None (bare ``key:``); other scalars unchanged."""
    if isinstance(value, str):
        value = value.strip()
    return value or None


def _cover_value(row: BookRow, note_path: Path):
    """The ``cover:`` frontmatter wikilink for a note, or None when no cover.

    Keyed solely off the materialized on-disk ``Data/Covers/<stem>.jpg`` file
    (kept in lockstep with the note stem = book_id). ``render_note`` runs
    :func:`_materialize_cover` first, so by the time this is called the file
    exists iff a staged cover copied successfully (or one already existed on
    disk) -- this avoids emitting a dangling reference for a row whose staged
    source is missing.

    Assumes *note_path* is ``<vault>/Books/<stem>.md`` so ``note_path.parents[1]``
    is the vault root.
    """
    stem = note_path.stem
    cover_file = note_path.parents[1] / COVERS_DIRNAME / f"{stem}.jpg"
    if cover_file.is_file():
        return cover_link(stem)
    return None


def book_frontmatter(row: BookRow, note_path: Path, existing: dict, has_highlights: bool) -> dict:
    """Build the authoritative, canonically-ordered frontmatter dict for a book.

    Every key comes from *row* except: ``type`` (always ``book``), ``topics``
    (preserved from *existing*, ``[]`` when absent), and ``highlighted`` /
    ``reviewed`` (derived booleans).
    """
    meta = {
        "type": "book",
        "title": _scalar(row.title),
        "authors": [wikilink(a) for a in row.authors],
        "topics": existing.get("topics", []) if existing else [],
        "series": _scalar(row.series),
        "series_index": _scalar(row.series_index),
        "publisher": _scalar(row.publisher),
        "published": _scalar(row.published),
        "language": _scalar(row.language),
        "format": _scalar(row.format),
        "pages": _scalar(row.pages),
        "status": _scalar(row.status),
        "highlighted": bool(has_highlights),
        "reviewed": bool(compose_review(row.review, row.private_notes)),
        "shelves": list(row.shelves),
        "rating": _scalar(render_rating(row.rating)),
        "isbn": _scalar(row.isbn),
        "amazon": _scalar(row.amazon),
        "google": _scalar(row.google),
        "goodreads": _scalar(row.goodreads),
        "uuid": _scalar(row.uuid),
        "calibre_id": _scalar(row.calibre_id),
        "date_added": _scalar(row.date_added),
        "date_read": _scalar(row.date_read),
        "cover": _cover_value(row, note_path),
    }
    for key in PRESERVED_EXTRA_KEYS:
        if existing and key in existing:
            meta[key] = existing[key]
    return {k: meta[k] for k in RENDER_KEY_ORDER if k in meta}


def render_body(existing_body: str, row: BookRow, note_path: Path, highlights: list) -> str:
    """Return the note body: cover embed, write-once ``## Review``, ``## Highlights``.

    Operates on the body only (no frontmatter). Idempotent: the cover embed is
    inserted once, the review section is write-once (:func:`ensure_section`), and
    the highlights live between replace-on-rerun markers
    (:func:`render_marked_section`). Content outside these regions is preserved.
    """
    body = existing_body
    if _cover_value(row, note_path):
        body = ensure_top_embed(body, cover_embed(note_path.stem))
    review = compose_review(row.review, row.private_notes)
    if review:
        body = ensure_section(body, "Review", review + "\n")
    if highlights:
        rendered = render_highlights([row_to_highlight(h) for h in highlights])
        body = render_marked_section(body, "Highlights", "highlights", rendered)
    return body


def _materialize_cover(row: BookRow, note_path: Path) -> None:
    """Copy a staged cover (row.cover = vault-relative path) into Data/Covers/.

    Calibre stages local covers before ``book_id`` exists; here—after merge—we
    copy the winning row's staged image to ``Data/Covers/<book_id>.jpg`` so the
    existing embed/frontmatter logic resolves it. No-op when the row carries no
    cover, the source is missing, or the destination already exists (idempotent).

    Assumes *note_path* is ``<vault>/Books/<stem>.md`` so ``note_path.parents[1]``
    is the vault root.
    """
    src_rel = (row.cover or "").strip()
    if not src_rel:
        return
    vault = note_path.parents[1]
    src = vault / src_rel
    dest = vault / COVERS_DIRNAME / f"{note_path.stem}.jpg"
    if src.is_file() and not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def render_note(vault: Path, row: BookRow, highlights: list) -> Path:
    """Write/update the flat book note for *row* under ``Books/<book_id>.md``.

    Frontmatter is rebuilt authoritatively (topics preserved from the existing
    note); the body preserves manual content and managed sections. The result is
    idempotent: rendering the same row + highlights twice yields identical bytes.
    """
    note_path = vault / BOOKS_DIRNAME / f"{row.book_id}.md"
    _materialize_cover(row, note_path)
    existing_meta, existing_body = load_note(note_path)
    meta = book_frontmatter(row, note_path, existing_meta, bool(highlights))
    body = render_body(existing_body, row, note_path, highlights).strip("\n")
    front = "---\n" + dump_frontmatter(meta) + "---\n"
    content = f"{front}\n{body}\n" if body else f"{front}\n"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(content, encoding="utf-8")
    return note_path


def render(vault: Path) -> dict:
    """Render every book in ``books.csv`` (+ its highlights) into ``Books/``.

    Also creates an ``Authors/<name>.md`` stub for each distinct author (the
    graph hubs calibre/goodreads used to create); topics are never stubbed.
    Continue-on-error: a book whose note cannot be rendered (e.g. an existing
    note with hand-corrupted frontmatter) is counted under ``failed`` and
    reported; the remaining books still render.
    """
    stats = {"notes": 0, "highlights": 0, "reviews": 0, "failed": 0, "authors": 0}
    authors_dir = vault / AUTHORS_DIRNAME
    seen_authors: set[str] = set()
    for row in store.read_books_csv(vault):
        if not row.book_id:
            continue
        highlights = store.read_highlights(vault, row.book_id)
        try:
            render_note(vault, row, highlights)
        except Exception as exc:  # continue-on-error per book
            stats["failed"] += 1
            typer.secho(f"  ! {row.book_id}: {exc}", fg=typer.colors.YELLOW)
            continue
        stats["notes"] += 1
        stats["highlights"] += len(highlights)
        if compose_review(row.review, row.private_notes):
            stats["reviews"] += 1
        for author in row.authors:
            if author and author not in seen_authors:
                write_stub(authors_dir, author, "author")
                seen_authors.add(author)
    stats["authors"] = len(seen_authors)
    return stats


class ObsidianRenderer:
    """The Obsidian output target: CSV store -> flat ``Books/*.md`` notes."""

    name = "obsidian"

    def render(self, vault: Path) -> dict:
        return render(vault)


# Re-export the schema constant expected by callers/tests via this module.
__all__ = [
    "NOTE_PROPERTY_ORDER",
    "ObsidianRenderer",
    "book_frontmatter",
    "dump_frontmatter",
    "load_note",
    "render",
    "render_body",
    "render_note",
    "render_rating",
]
