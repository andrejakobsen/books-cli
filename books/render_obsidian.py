#!/usr/bin/env python3
"""Render the CSV store (Plan A) into flat Obsidian book notes under ``Books/``.

Reads ``Data/books.csv`` + per-book ``Data/Highlights/<book-id>.csv`` and
writes/updates one self-contained note per book. Frontmatter is written
*authoritatively* from the merged row for every schema key, except:

- ``topics`` -- 100%-user-owned: preserved verbatim on an existing note, empty
  (``[]``) on a brand-new one. Never written from data.
- ``highlighted`` / ``reviewed`` -- derived: true iff the book has highlights /
  a review.

The body carries the cover embed, a write-once ``## Review`` section, and a
marker-wrapped ``## Highlights`` section; anything outside those managed regions
is left untouched. Frontmatter round-trips via python-frontmatter (read) +
ruamel.yaml (write).
"""

from __future__ import annotations

import io
from pathlib import Path

import frontmatter
import typer
from ruamel.yaml import YAML

from books import store
from books.core import config
from books.highlights import render_highlights
from books.renderers.obsidian import (
    BOOK_PROPERTY_ORDER,
    BOOKS_DIRNAME,
    COVER_WIDTH,
    COVERS_DIRNAME,
    ensure_section,
    ensure_top_embed,
    format_rating,
    render_marked_section,
    wikilink,
)
from books.store import BookRow, row_to_highlight

# The note frontmatter schema: the canonical order minus the retired ``source``
# key (a merged book has many contributing sources; a single value is meaningless).
NOTE_PROPERTY_ORDER = tuple(k for k in BOOK_PROPERTY_ORDER if k != "source")

# Non-schema keys that Obsidian itself writes and the user owns. Preserved
# verbatim from an existing note (like ``topics``) but never fabricated: emitted
# only when the existing note already carries them, positioned after ``topics``.
PRESERVED_EXTRA_KEYS = ("aliases", "cssclasses")


def _insert_after(order: tuple, anchor: str, extra: tuple) -> tuple:
    """Return *order* with *extra* keys inserted right after *anchor*."""
    out: list = []
    for key in order:
        out.append(key)
        if key == anchor:
            out.extend(extra)
    return tuple(out)


# Render-time key order: schema keys plus the preserved extras after ``topics``.
_RENDER_KEY_ORDER = _insert_after(NOTE_PROPERTY_ORDER, "topics", PRESERVED_EXTRA_KEYS)


def _yaml() -> YAML:
    y = YAML()
    y.default_flow_style = False
    y.allow_unicode = True       # keep ⭐ and accented names literal, not \uXXXX
    y.width = 4096               # never line-wrap long titles / values
    return y


def dump_frontmatter(meta: dict) -> str:
    """Serialize an ordered frontmatter dict to a YAML block (trailing newline)."""
    buf = io.StringIO()
    _yaml().dump(meta, buf)
    return buf.getvalue()


def load_note(path: Path) -> tuple[dict, str]:
    """Return (frontmatter dict, body) for an existing note, or ({}, "")."""
    if not path.is_file():
        return {}, ""
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    return dict(post.metadata), post.content


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

    Present when the row records a cover OR the flat ``Covers/<stem>.jpg`` file
    already exists (kept in lockstep with the note stem = book_id).

    Assumes *note_path* is ``<vault>/Books/<stem>.md`` so ``note_path.parents[1]``
    is the vault root.
    """
    stem = note_path.stem
    cover_file = note_path.parents[1] / COVERS_DIRNAME / f"{stem}.jpg"
    if (row.cover or "").strip() or cover_file.is_file():
        return f"[[{COVERS_DIRNAME}/{stem}.jpg]]"
    return None


def book_frontmatter(row: BookRow, note_path: Path, existing: dict,
                     has_highlights: bool) -> dict:
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
        "reviewed": bool((row.review or "").strip()),
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
    return {k: meta[k] for k in _RENDER_KEY_ORDER if k in meta}


def render_body(existing_body: str, row: BookRow, note_path: Path,
                highlights: list) -> str:
    """Return the note body: cover embed, write-once ``## Review``, ``## Highlights``.

    Operates on the body only (no frontmatter). Idempotent: the cover embed is
    inserted once, the review section is write-once (:func:`ensure_section`), and
    the highlights live between replace-on-rerun markers
    (:func:`render_marked_section`). Content outside these regions is preserved.
    """
    body = existing_body
    if _cover_value(row, note_path):
        embed = f"![[{COVERS_DIRNAME}/{note_path.stem}.jpg|{COVER_WIDTH}]]"
        body = ensure_top_embed(body, embed)
    review = (row.review or "").strip()
    if review:
        body = ensure_section(body, "Review", review + "\n")
    if highlights:
        rendered = render_highlights([row_to_highlight(h) for h in highlights])
        body = render_marked_section(body, "Highlights", "highlights", rendered)
    return body


def render_note(vault: Path, row: BookRow, highlights: list) -> Path:
    """Write/update the flat book note for *row* under ``Books/<book_id>.md``.

    Frontmatter is rebuilt authoritatively (topics preserved from the existing
    note); the body preserves manual content and managed sections. The result is
    idempotent: rendering the same row + highlights twice yields identical bytes.
    """
    note_path = vault / BOOKS_DIRNAME / f"{row.book_id}.md"
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

    Continue-on-error: a book whose note cannot be rendered (e.g. an existing
    note with hand-corrupted frontmatter) is counted under ``failed`` and
    reported; the remaining books still render.
    """
    stats = {"notes": 0, "highlights": 0, "reviews": 0, "failed": 0}
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
        if (row.review or "").strip():
            stats["reviews"] += 1
    return stats


def render_command(
    output: Path | None = typer.Option(
        None, "--output", "-o",
        help="Obsidian vault. Defaults to the vault from your config file "
             "(~/.config/books/config.toml). Relative paths resolve against the "
             "current directory.",
    ),
) -> None:
    """Render the CSV store into Obsidian book notes under Books/.

    Reads <vault>/Data/books.csv and <vault>/Data/Highlights/<book-id>.csv (built
    by the importers + merge) and writes one flat note per book. Frontmatter is
    written authoritatively from the store; your hand-edited `topics` and any
    `## Review` section are preserved, as is note body outside the managed
    Highlights markers.
    """
    vault = config.resolve_vault(output)
    if not store.books_csv_path(vault).is_file():
        raise typer.BadParameter(
            f"no books.csv under {store.data_dir(vault)} — run the importers + merge first",
            param_hint="--output",
        )
    vault.mkdir(parents=True, exist_ok=True)
    stats = render(vault)
    suffix = f" ({stats['failed']} failed)" if stats.get("failed") else ""
    typer.echo(
        f"Done. {stats['notes']} notes, {stats['highlights']} highlights, "
        f"{stats['reviews']} reviews{suffix}.\nOutput: {vault}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("render")(render_command)


def main() -> None:
    """Standalone entry point so a shim script keeps working on its own."""
    typer.run(render_command)


if __name__ == "__main__":
    main()
