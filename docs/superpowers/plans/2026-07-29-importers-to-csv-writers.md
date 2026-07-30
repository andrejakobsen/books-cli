# Importers → CSV Writers (Plan C, core five) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewire the five core importers (`calibre`, `goodreads`, `kobo`, `highlighted`, `readwise`) to write the CSV store instead of Obsidian markdown, add a `books merge` command, teach `render` to materialize calibre covers + create Author stubs, and make `sync` a two-phase pipeline (import → merge → highlight import → render).

**Architecture:** Metadata importers (`calibre`, `goodreads`) dump `store.BookRow`s into `Data/Sources/<source>.csv` via `store.write_layer`. `store.merge` clusters them into `Data/books.csv` with a stable `book_id`. Highlight importers (`kobo`, `highlighted`, `readwise`) resolve each book to a `book_id` via `store.Catalog(vault).find(ref)` and write `Data/Highlights/<book_id>.csv` via `store.write_highlights`. `render` (already built) turns the store into notes; this plan adds staged-cover materialization + Author stubs. `covers` + `audible` are untouched (deferred).

**Tech Stack:** Python 3.11, Typer, pydantic row models (`books/core/store.py`), `python-frontmatter` + `ruamel.yaml` (render, already wired). The five importers become store-only and drop all `books.renderers.obsidian` imports except—for cover staging—none (calibre uses `shutil` + `store` path helpers).

**Design reference:** `docs/superpowers/specs/2026-07-29-importers-to-csv-writers-design.md`

**Decisions locked in:**
- Vault is disposable — **no migration/backfill**.
- Convert **core five only**; `covers` + `audible` keep their markdown path (safe: render only rewrites `## Highlights` when the store has rows, and derives the cover from the on-disk image).
- **Goodreads emits every shelf**; every book becomes a note (no shelf gating).
- **Calibre covers**: stage to `Data/Sources/_covers/calibre/<n>.jpg`, record the vault-relative path in the layer row's `cover`; `render` materializes it to `Data/Covers/<book_id>.jpg`.
- **Author stubs** created by `render`; **Topics stubs dropped**.
- `rating` is stored **numeric** (e.g. `4` / `3.5`) in the store — `render.render_rating` converts to stars.
- `VaultIndex` stays (still used by covers/audible); full retirement is a later follow-up.

**Rating contract note:** `store.BookRow.rating` holds the numeric value as a string. Calibre's `meta.rating` is a float 0–5 (or None); Goodreads' `rating` is an int 1–5 (or None). Store `str(value)` when present, else `""`.

---

## File structure

- **Modify** `books/commands/calibre.py` — `convert` builds `BookRow`s → `store.write_layer("calibre", …)`; stages covers; drops `VaultIndex`, topics, stubs, description.
- **Modify** `books/commands/goodreads.py` — `convert` builds `BookRow`s for every row → `store.write_layer("goodreads", …)`; drops `VaultIndex`, shelf gating, `## Review` handling, stubs.
- **Modify** `books/commands/kobo.py` — `export_obsidian` resolves via `store.Catalog` and writes `store.write_highlights`; CSV/zip mode (`export`) unchanged.
- **Modify** `books/commands/highlighted.py` — `convert` resolves via `store.Catalog` + `store.write_highlights`.
- **Modify** `books/commands/readwise.py` — `convert` resolves via `store.Catalog` + `store.write_highlights`.
- **Modify** `books/commands/render.py` — add `_materialize_cover` (called in `render_note`) + Author-stub creation in `render`.
- **Create** `books/commands/merge.py` — the `books merge` command.
- **Modify** `books/cli.py` — register `merge`.
- **Modify** `books/commands/sync.py` — two-phase pipeline with `merge` + `render` steps.
- **Modify** tests: `tests/commands/test_calibre.py`, `test_goodreads.py`, `test_kobo.py`, `test_highlighted.py`, `test_readwise.py`, `test_render.py`, `test_sync.py`; **create** `tests/commands/test_merge.py`.
- **Modify** docs: `CLAUDE.md`, `README.md`.

---

## Task 1: Calibre → CSV writer (with cover staging)

**Files:**
- Modify: `books/commands/calibre.py`
- Test: `tests/commands/test_calibre.py`

- [ ] **Step 1: Write the failing tests**

Replace the body of `tests/commands/test_calibre.py` with store-based tests (keep any `parse_opf` unit tests already present — only replace the ones that assert markdown/notes). Add:

```python
from pathlib import Path

from books.commands import calibre
from books.core import store


def _make_calibre_book(root: Path, folder: str, opf: str, cover: bytes | None = None) -> None:
    book_dir = root / folder
    book_dir.mkdir(parents=True)
    (book_dir / "metadata.opf").write_text(opf, encoding="utf-8")
    if cover is not None:
        (book_dir / "cover.jpg").write_bytes(cover)


_OPF = """<?xml version='1.0'?>
<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>The Deluge</dc:title>
    <dc:creator opf:role="aut">Adam Tooze</dc:creator>
    <dc:identifier opf:scheme="ISBN">9780141032184</dc:identifier>
    <dc:subject>History</dc:subject>
    <meta name="calibre:rating" content="8"/>
  </metadata>
</package>
"""


def test_calibre_writes_layer_csv(tmp_path):
    lib = tmp_path / "lib"
    _make_calibre_book(lib, "Adam Tooze/The Deluge (1)", _OPF)
    vault = tmp_path / "vault"

    stats = calibre.convert(lib, vault)

    rows = store.read_layer(vault, "calibre")
    assert len(rows) == 1
    row = rows[0]
    assert row.title == "The Deluge"
    assert row.authors == ["Adam Tooze"]
    assert row.isbn == "9780141032184"
    assert row.format == "ebook"
    assert row.rating == "4"  # calibre 8/2 = 4.0 -> "4"
    assert stats["books"] == 1


def test_calibre_does_not_map_topics_or_write_notes(tmp_path):
    lib = tmp_path / "lib"
    _make_calibre_book(lib, "Adam Tooze/The Deluge (1)", _OPF)
    vault = tmp_path / "vault"

    calibre.convert(lib, vault)

    # No book notes are created by calibre anymore.
    assert not (vault / "Books").exists()
    # No topics column exists in the store schema, so subjects are dropped.
    assert "topics" not in store.BookRow.model_fields


def test_calibre_stages_cover_and_records_path(tmp_path):
    lib = tmp_path / "lib"
    _make_calibre_book(lib, "Adam Tooze/The Deluge (1)", _OPF, cover=b"\xff\xd8\xff\xe0JPEGDATA")
    vault = tmp_path / "vault"

    stats = calibre.convert(lib, vault)

    row = store.read_layer(vault, "calibre")[0]
    staged = vault / row.cover
    assert staged.is_file()
    assert staged.read_bytes() == b"\xff\xd8\xff\xe0JPEGDATA"
    assert row.cover.startswith("Data/Sources/_covers/calibre/")
    assert stats["covers"] == 1


def test_calibre_rerun_replaces_layer(tmp_path):
    lib = tmp_path / "lib"
    _make_calibre_book(lib, "Adam Tooze/The Deluge (1)", _OPF)
    vault = tmp_path / "vault"
    calibre.convert(lib, vault)
    calibre.convert(lib, vault)  # re-run
    assert len(store.read_layer(vault, "calibre")) == 1  # not duplicated
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/commands/test_calibre.py -q`
Expected: FAIL — `convert` still returns markdown/note-based results and `row.cover` is unset / no layer file.

- [ ] **Step 3: Rewrite `convert` (and helpers) in `books/commands/calibre.py`**

Replace the imports from `books.renderers.obsidian` and the `write_note` / `_calibre_updates` / `convert` functions. New top imports:

```python
from __future__ import annotations

import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

import typer

from books.core import config, store
from books.core.paths import resolve_path
```

Delete `_calibre_updates`, `write_note`, and the `books.renderers.obsidian` import block entirely. Add a `BookMetadata → BookRow` mapper and rewrite `convert`:

```python
def _rating_str(rating: float | None) -> str:
    """Numeric rating as a compact string ('4', '3.5'), '' when absent."""
    if rating is None:
        return ""
    return str(int(rating)) if float(rating).is_integer() else str(rating)


def _to_row(meta: BookMetadata, cover_rel: str) -> store.BookRow:
    """Map parsed Calibre metadata to a store BookRow (cover = staged rel path)."""
    return store.BookRow(
        title=meta.title or "",
        authors=list(meta.authors),
        series=meta.series or "",
        series_index=meta.series_index or "",
        publisher=meta.publisher or "",
        published=meta.published or "",
        language=meta.language or "",
        format="ebook",  # everything in a Calibre library is an ebook
        rating=_rating_str(meta.rating),
        isbn=meta.isbn or "",
        amazon=meta.amazon or "",
        google=meta.google or "",
        uuid=meta.uuid or "",
        calibre_id=meta.calibre_id or "",
        date_added=meta.date_added or "",
        cover=cover_rel,
    )


def convert(library: Path, output: Path) -> dict:
    """Parse a Calibre library into the ``calibre`` metadata layer CSV.

    Covers are staged under ``Data/Sources/_covers/calibre/<n>.jpg`` and their
    vault-relative path recorded in the row's ``cover`` field; ``render``
    materializes them to ``Data/Covers/<book_id>.jpg`` after merge. No notes,
    stubs, or topics are written (topics are user-owned; the renderer owns notes).
    """
    stats = {"books": 0, "covers": 0, "skipped": 0, "authors": set()}
    output.mkdir(parents=True, exist_ok=True)

    staging = store.sources_dir(output) / "_covers" / "calibre"
    if staging.exists():
        shutil.rmtree(staging)  # fresh each run so re-runs don't accumulate

    rows: list[store.BookRow] = []
    for opf_path in sorted(library.rglob("metadata.opf")):
        rel_parts = opf_path.relative_to(library).parts
        if any(part in IGNORED_NAMES for part in rel_parts):
            continue
        try:
            meta = parse_opf(opf_path)
        except ET.ParseError as exc:
            print(f"WARN: could not parse {opf_path}: {exc}")
            stats["skipped"] += 1
            continue
        if not meta.title:
            stats["skipped"] += 1
            continue

        cover_rel = ""
        cover_src = opf_path.parent / "cover.jpg"
        if cover_src.is_file():
            staging.mkdir(parents=True, exist_ok=True)
            staged = staging / f"{len(rows)}.jpg"
            shutil.copy2(cover_src, staged)
            cover_rel = staged.relative_to(output).as_posix()
            stats["covers"] += 1

        rows.append(_to_row(meta, cover_rel))
        stats["books"] += 1
        stats["authors"].update(meta.authors)

    store.write_layer(output, "calibre", rows)
    return stats
```

Keep `parse_opf`, `BookMetadata`, `_date_only`, `NS`, `IGNORED_NAMES`, `IGNORED_EBOOK_SUFFIXES` unchanged. In the CLI wrapper `calibre_to_obsidian`, the echo line still uses `stats['books']`, `stats['covers']`, `len(stats['authors'])`, `stats['skipped']` — those keys still exist, so **leave the CLI function as-is** (it already reads only those keys). Remove the now-unused `topics` reference from its echo string if present (it referenced `stats['topics']` — change that line to drop topics):

```python
    typer.echo(
        f"Done. {stats['books']} books, {stats['covers']} covers, "
        f"{len(stats['authors'])} authors, {stats['skipped']} skipped.\n"
        f"Output: {output}"
    )
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/commands/test_calibre.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add books/commands/calibre.py tests/commands/test_calibre.py
git commit -m "$(printf 'feat(calibre): write the CSV store layer instead of markdown\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 2: Goodreads → CSV writer

**Files:**
- Modify: `books/commands/goodreads.py`
- Test: `tests/commands/test_goodreads.py`

- [ ] **Step 1: Write the failing tests**

Replace the note/`VaultIndex`-based tests in `tests/commands/test_goodreads.py` with layer-based ones (keep pure `parse_csv` / `_norm_format` / `split`-helper unit tests). Add:

```python
from pathlib import Path

from books.commands import goodreads
from books.core import store

_CSV = (
    "Title,Author,Additional Authors,ISBN,ISBN13,My Rating,Publisher,"
    "Number of Pages,Year Published,Binding,Date Read,Date Added,Exclusive Shelf,"
    "Bookshelves,My Review,Private Notes,Book Id\n"
    'The Deluge,Adam Tooze,,="",="9780141032184",4,Penguin,720,2014,Paperback,'
    "2020/01/02,2019/12/01,read,history,Great book,,12345\n"
    'Wanted,Some Author,,="",="",0,,,,,,,to-read,wishlist,,,999\n"'
)


def _write_csv(tmp_path: Path) -> Path:
    p = tmp_path / "goodreads.csv"
    p.write_text(_CSV, encoding="utf-8")
    return p


def test_goodreads_writes_layer_for_every_shelf(tmp_path):
    vault = tmp_path / "vault"
    stats = goodreads.convert(_write_csv(tmp_path), vault)

    rows = {r.title: r for r in store.read_layer(vault, "goodreads")}
    assert set(rows) == {"The Deluge", "Wanted"}  # to-read included
    assert stats["books"] == 2


def test_goodreads_row_fields_and_review(tmp_path):
    vault = tmp_path / "vault"
    goodreads.convert(_write_csv(tmp_path), vault)

    row = next(r for r in store.read_layer(vault, "goodreads") if r.title == "The Deluge")
    assert row.authors == ["Adam Tooze"]
    assert row.isbn == "9780141032184"
    assert row.rating == "4"
    assert row.format == "physical"
    assert row.shelves == ["history"]
    assert row.review == "Great book"
    assert row.goodreads == "https://www.goodreads.com/book/show/12345"
    assert row.date_read == "2020-01-02"


def test_goodreads_skips_titleless_or_authorless(tmp_path):
    vault = tmp_path / "vault"
    (tmp_path / "g.csv").write_text("Title,Author,Book Id\n,,1\nOnly Title,,2\n", encoding="utf-8")
    stats = goodreads.convert(tmp_path / "g.csv", vault)
    assert stats["skipped"] == 2
    assert store.read_layer(vault, "goodreads") == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/commands/test_goodreads.py -q`
Expected: FAIL — `convert` still uses `VaultIndex` and returns `created/merged` stats.

- [ ] **Step 3: Rewrite `books/commands/goodreads.py`**

Replace the `books.renderers.obsidian` import block with:

```python
from books.core import config, store
```

Delete `_goodreads_updates`, `_review_markdown`, `_parse_shelves`, and the `AUTHORS_DIRNAME`/`VaultIndex`/etc. imports. Add a mapper and rewrite `convert`:

```python
def _row_from_book(book: GoodreadsBook) -> store.BookRow:
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


def convert(csv_path: Path, output: Path, shelf: str = DEFAULT_SHELVES) -> dict:
    """Write every Goodreads row into the ``goodreads`` metadata layer CSV.

    Every shelf is emitted (books.csv becomes the whole library); the renderer
    turns each row into a note. ``shelf`` is accepted for CLI compatibility but no
    longer gates output.
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
```

Update the CLI wrapper `goodreads_to_obsidian` echo (it currently reads `created`/`merged`/`reviews`/`authors`/`skipped`) to the new keys:

```python
    output.mkdir(parents=True, exist_ok=True)
    stats = convert(csv, output, shelf=shelf)
    typer.echo(
        f"Done. {stats['books']} books, {stats['reviews']} reviews, "
        f"{stats['skipped']} skipped.\nOutput: {output}"
    )
```

Keep the `--shelf` option definition (still accepted) but update its help text to note it no longer gates output:

```python
shelf: str = (
    typer.Option(
        DEFAULT_SHELVES,
        "--shelf",
        help="Accepted for compatibility; no longer gates output — every shelf is "
        "written to the store (books.csv is the whole library).",
    ),
)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/commands/test_goodreads.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add books/commands/goodreads.py tests/commands/test_goodreads.py
git commit -m "$(printf 'feat(goodreads): write the CSV store layer for every shelf\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 3: Render — materialize staged calibre covers

**Files:**
- Modify: `books/commands/render.py`
- Test: `tests/commands/test_render.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/commands/test_render.py`:

```python
def test_render_materializes_staged_cover(tmp_path):
    from books.commands import render as R

    vault = tmp_path / "vault"
    staged = store.sources_dir(vault) / "_covers" / "calibre" / "0.jpg"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"\xff\xd8\xff\xe0IMG")
    row = store.BookRow(
        book_id="The Deluge - Adam Tooze",
        title="The Deluge",
        authors=["Adam Tooze"],
        format="ebook",
        cover="Data/Sources/_covers/calibre/0.jpg",
    )
    R.render_note(vault, row, [])
    dest = vault / "Data" / "Covers" / "The Deluge - Adam Tooze.jpg"
    assert dest.is_file()
    assert dest.read_bytes() == b"\xff\xd8\xff\xe0IMG"
    post = frontmatter.loads(
        dest.with_suffix(".md").name
        and (vault / "Books" / "The Deluge - Adam Tooze.md").read_text(encoding="utf-8")
    )
    assert "![[Data/Covers/The Deluge - Adam Tooze.jpg|150]]" in post.content
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/commands/test_render.py -k materializes_staged_cover -q`
Expected: FAIL — the staged file is not copied to `Data/Covers/`.

- [ ] **Step 3: Add `_materialize_cover` and call it in `render_note`**

In `books/commands/render.py`, add `import shutil` near the top imports (after `import io`). Add the helper right above `render_note`:

```python
def _materialize_cover(row: BookRow, note_path: Path) -> None:
    """Copy a staged cover (row.cover = vault-relative path) into Data/Covers/.

    Calibre stages local covers before ``book_id`` exists; here—after merge—we
    copy the winning row's staged image to ``Data/Covers/<book_id>.jpg`` so the
    existing embed/frontmatter logic resolves it. No-op when the row carries no
    cover, the source is missing, or the destination already exists (idempotent).
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
```

Then in `render_note`, add the call immediately after computing `note_path`:

```python
    note_path = vault / BOOKS_DIRNAME / f"{row.book_id}.md"
    _materialize_cover(row, note_path)
    existing_meta, existing_body = load_note(note_path)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/commands/test_render.py -k materializes_staged_cover -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add books/commands/render.py tests/commands/test_render.py
git commit -m "$(printf 'feat(render): materialize staged calibre covers into Data/Covers\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 4: Render — create Author stubs

**Files:**
- Modify: `books/commands/render.py`
- Test: `tests/commands/test_render.py`

- [ ] **Step 1: Write/adjust the tests**

Update the existing stats assertions and add an author-stub test in `tests/commands/test_render.py`.

Change the two stats assertions to include the new `authors` count:

```python
    # was: assert stats == {"notes": 1, "highlights": 1, "reviews": 0, "failed": 0}
    assert stats == {"notes": 1, "highlights": 1, "reviews": 0, "failed": 0, "authors": 1}
```

```python
# the empty-catalog test:
assert R.render(tmp_path / "vault") == {
    "notes": 0,
    "highlights": 0,
    "reviews": 0,
    "failed": 0,
    "authors": 0,
}
```

Add:

```python
def test_render_creates_author_stubs(tmp_path):
    from books.commands import render as R

    vault = tmp_path / "vault"
    store.write_books_csv(
        vault,
        [
            store.BookRow(book_id="X - A", title="X", authors=["Ada Lovelace"]),
        ],
    )
    R.render(vault)
    stub = vault / "Authors" / "Ada Lovelace.md"
    assert stub.is_file()
    assert "type: author" in stub.read_text(encoding="utf-8")
    assert not (vault / "Topics").exists()  # topics stubs are never created
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/commands/test_render.py -k "author_stubs or writes_notes_from_store or empty_catalog" -q`
Expected: FAIL — no `Authors/` stub, and `stats` lacks `authors`.

- [ ] **Step 3: Implement stub creation in `render`**

In `books/commands/render.py`, add `AUTHORS_DIRNAME` and `write_stub` to the `from books.renderers.obsidian import (...)` block. Update `render`:

```python
def render(vault: Path) -> dict:
    """Render every book in ``books.csv`` (+ highlights) into ``Books/``.

    Also creates an ``Authors/<name>.md`` stub for each distinct author (the
    graph hubs calibre/goodreads used to create); topics are never stubbed.
    Continue-on-error per book.
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
        if (row.review or "").strip():
            stats["reviews"] += 1
        for author in row.authors:
            if author and author not in seen_authors:
                write_stub(authors_dir, author, "author")
                seen_authors.add(author)
    stats["authors"] = len(seen_authors)
    return stats
```

Update the `render_command` echo to mention authors:

```python
    typer.echo(
        f"Done. {stats['notes']} notes, {stats['highlights']} highlights, "
        f"{stats['reviews']} reviews, {stats['authors']} authors{suffix}.\n"
        f"Output: {vault}"
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/commands/test_render.py -q`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add books/commands/render.py tests/commands/test_render.py
git commit -m "$(printf 'feat(render): create Author hub stubs from books.csv\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 5: Kobo → highlights store writer

**Files:**
- Modify: `books/commands/kobo.py`
- Test: `tests/commands/test_kobo.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/commands/test_kobo.py` a test that seeds `books.csv`, then runs `export_obsidian` and asserts highlight rows land in the store. Reuse the file's existing helper for building a Kobo sqlite if present; otherwise add this self-contained one:

```python
import sqlite3
from pathlib import Path

from books.commands import kobo
from books.core import store


def _make_kobo_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE content (ContentID TEXT, ContentType INT, Title TEXT,
            BookTitle TEXT, Attribution TEXT, ISBN TEXT, VolumeIndex INT);
        CREATE TABLE Bookmark (BookmarkID TEXT, VolumeID TEXT, ContentID TEXT,
            ChapterProgress REAL, Text TEXT, Annotation TEXT, DateCreated TEXT,
            StartContainerPath TEXT, Hidden TEXT);
        INSERT INTO content VALUES ('vol1', 6, 'The Deluge', 'The Deluge',
            'Adam Tooze', '9780141032184', NULL);
        INSERT INTO content VALUES ('vol1-1', 899, 'Chapter One', NULL, NULL,
            NULL, 1);
        INSERT INTO Bookmark VALUES ('bm1', 'vol1', 'vol1-1', 0.42,
            'a highlight', NULL, '2020-01-01', 'span#kobo.3.5', 'false');
        """
    )
    conn.commit()
    conn.close()


def test_kobo_writes_highlights_to_store(tmp_path):
    vault = tmp_path / "vault"
    store.write_books_csv(
        vault,
        [
            store.BookRow(
                book_id="The Deluge - Adam Tooze",
                title="The Deluge",
                authors=["Adam Tooze"],
                isbn="9780141032184",
            )
        ],
    )
    db = tmp_path / "KoboReader.sqlite"
    _make_kobo_db(db)

    stats = kobo.export_obsidian(db, vault)

    rows = store.read_highlights(vault, "The Deluge - Adam Tooze")
    assert len(rows) == 1
    assert rows[0].source == "kobo"
    assert rows[0].text == "a highlight"
    assert rows[0].location == "42" and rows[0].location_kind == "percent"
    assert stats == {"books": 1, "entries": 1, "skipped": 0}


def test_kobo_skips_unmatched_book(tmp_path):
    vault = tmp_path / "vault"
    store.write_books_csv(vault, [])  # empty catalog -> nothing matches
    db = tmp_path / "KoboReader.sqlite"
    _make_kobo_db(db)
    stats = kobo.export_obsidian(db, vault)
    assert stats == {"books": 0, "entries": 0, "skipped": 1}


def test_kobo_rerun_replaces_own_rows(tmp_path):
    vault = tmp_path / "vault"
    store.write_books_csv(
        vault,
        [
            store.BookRow(
                book_id="The Deluge - Adam Tooze",
                title="The Deluge",
                authors=["Adam Tooze"],
                isbn="9780141032184",
            )
        ],
    )
    db = tmp_path / "KoboReader.sqlite"
    _make_kobo_db(db)
    kobo.export_obsidian(db, vault)
    kobo.export_obsidian(db, vault)  # re-run
    assert len(store.read_highlights(vault, "The Deluge - Adam Tooze")) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/commands/test_kobo.py -k "writes_highlights_to_store or skips_unmatched or rerun_replaces" -q`
Expected: FAIL — `export_obsidian` still writes markdown via `VaultIndex`.

- [ ] **Step 3: Rewrite `export_obsidian` in `books/commands/kobo.py`**

Replace the `books.renderers.obsidian` import block with:

```python
from books.core import config, store
from books.core.matching import BookRef
```

(Keep `from books.core.highlights import Highlight, parse_markers` and `from books.core.paths import resolve_path`. Keep `safe_filename` import if the zip/CSV path uses it — it does, imported from `books.core.naming`: change `safe_filename` usage in `export()` to `from books.core.naming import safe_filename`.)

Add that import near the top:

```python
from books.core.naming import safe_filename
```

Rewrite `export_obsidian`:

```python
def export_obsidian(db_path: Path, vault: Path) -> dict:
    """Write Kobo highlights into the per-book highlights store.

    Each book is resolved to a ``book_id`` via ``store.Catalog`` (built by the
    metadata importers + merge); a book with no catalog match is skipped and
    counted. Returns {"books": int, "entries": int, "skipped": int}. Raises
    FileNotFoundError if the db is missing.
    """
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(QUERY).fetchall()
    finally:
        conn.close()

    vault.mkdir(parents=True, exist_ok=True)
    catalog = store.Catalog(vault)

    books: dict[str, list] = {}
    for r in rows:
        books.setdefault(r["book_title"] or "Untitled", []).append(r)

    entries = written = skipped = 0
    for title, book_rows in books.items():
        author = (book_rows[0]["author"] or "").strip()
        authors = [author] if author else []
        isbn = (book_rows[0]["isbn"] or "").strip() or None
        book_id = catalog.find(BookRef(title=title, authors=authors, isbn=isbn))
        if book_id is None:
            skipped += 1
            continue
        highlights = [row_to_highlight(r) for r in book_rows]
        hl_rows = [store.highlight_to_row(h, "kobo", str(i)) for i, h in enumerate(highlights)]
        store.write_highlights(vault, book_id, "kobo", hl_rows)
        entries += len(hl_rows)
        written += 1

    return {"books": written, "entries": entries, "skipped": skipped}
```

The `export` (CSV/zip) function and the `kobo_export` CLI are unchanged **except** the `--obsidian` echo already reads only `entries`/`books`/`skipped` (still present).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/commands/test_kobo.py -q`
Expected: PASS (the new tests plus the unchanged CSV/zip-mode tests).

- [ ] **Step 5: Commit**

```bash
git add books/commands/kobo.py tests/commands/test_kobo.py
git commit -m "$(printf 'feat(kobo): write highlights to the CSV store via Catalog.find\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 6: Highlighted → highlights store writer

**Files:**
- Modify: `books/commands/highlighted.py`
- Test: `tests/commands/test_highlighted.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/commands/test_highlighted.py`:

```python
from pathlib import Path

from books.commands import highlighted
from books.core import store

_HL_CSV = (
    "Highlight,Title,Author,ISBN,Location,Tags,Note,Date\n"
    "a quote,The Deluge,Adam Tooze,9780141032184,45,#war @trotsky,my note,2020-01-01\n"
)


def _seed(vault: Path) -> None:
    store.write_books_csv(
        vault,
        [
            store.BookRow(
                book_id="The Deluge - Adam Tooze",
                title="The Deluge",
                authors=["Adam Tooze"],
                isbn="9780141032184",
            )
        ],
    )


def test_highlighted_writes_highlights_to_store(tmp_path):
    vault = tmp_path / "vault"
    _seed(vault)
    csv = tmp_path / "h.csv"
    csv.write_text(_HL_CSV, encoding="utf-8")

    stats = highlighted.convert(csv, vault)

    rows = store.read_highlights(vault, "The Deluge - Adam Tooze")
    assert len(rows) == 1
    assert rows[0].source == "highlighted"
    assert rows[0].text == "a quote"
    assert rows[0].location == "45" and rows[0].location_kind == "page"
    assert rows[0].tags == ["war"] and rows[0].links == ["Trotsky"]
    assert stats["books"] == 1 and stats["entries"] == 1 and stats["skipped"] == 0


def test_highlighted_skips_unmatched(tmp_path):
    vault = tmp_path / "vault"
    store.write_books_csv(vault, [])
    csv = tmp_path / "h.csv"
    csv.write_text(_HL_CSV, encoding="utf-8")
    stats = highlighted.convert(csv, vault)
    assert stats["skipped"] == 1 and stats["books"] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/commands/test_highlighted.py -k "writes_highlights_to_store or skips_unmatched" -q`
Expected: FAIL — still `VaultIndex`-based.

- [ ] **Step 3: Rewrite `convert` in `books/commands/highlighted.py`**

Replace the `books.renderers.obsidian` import block with:

```python
from books.core import config, store
from books.core.matching import BookRef
```

Keep `from books.core.highlights import Highlight, split_tag_column` and `from books.core.paths import resolve_path`. Rewrite `convert`:

```python
def convert(csv_path: Path, output: Path) -> dict:
    """Write every highlight, grouped by book, into the per-book store."""
    stats = {"books": 0, "entries": 0, "skipped": 0}
    output.mkdir(parents=True, exist_ok=True)
    catalog = store.Catalog(output)

    groups: dict[str, dict] = {}
    for row in parse_csv(csv_path):
        title = (row.get("Title") or "").strip()
        if not title:
            continue
        isbn = (row.get("ISBN") or "").strip() or None
        author = (row.get("Author") or "").strip()
        key = isbn or title
        group = groups.setdefault(key, {"title": title, "author": author, "isbn": isbn, "rows": []})
        group["rows"].append(row)

    for group in groups.values():
        authors = [group["author"]] if group["author"] else []
        book_id = catalog.find(BookRef(title=group["title"], authors=authors, isbn=group["isbn"]))
        if book_id is None:
            stats["skipped"] += 1
            continue
        highlights = [row_to_highlight(r) for r in group["rows"]]
        hl_rows = [
            store.highlight_to_row(h, "highlighted", str(i)) for i, h in enumerate(highlights)
        ]
        store.write_highlights(output, book_id, "highlighted", hl_rows)
        stats["books"] += 1
        stats["entries"] += len(hl_rows)

    return stats
```

Update the folder-mode CLI echo (`highlighted_to_obsidian`): it aggregates `totals["authors"]` — drop the authors references. Change the `totals` init and aggregation and final echo:

```python
totals = {"books": 0, "entries": 0, "skipped": 0}
skipped = 0
for path in csv_paths:
    try:
        stats = convert(path, output)
    except Exception as exc:  # noqa: BLE001
        skipped += 1
        typer.echo(f"Skipped {path.name}: {exc}", err=True)
        continue
    totals["books"] += stats["books"]
    totals["entries"] += stats["entries"]
    totals["skipped"] += stats["skipped"]

files = len(csv_paths)
files_word = "file" if files == 1 else "files"
skipped_note = f" ({skipped} skipped)" if skipped else ""
no_note = f" ({totals['skipped']} skipped — no book)" if totals["skipped"] else ""
typer.echo(
    f"Done. {files} {files_word}{skipped_note}, {totals['books']} books{no_note}, "
    f"{totals['entries']} highlights.\nOutput: {output}"
)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/commands/test_highlighted.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add books/commands/highlighted.py tests/commands/test_highlighted.py
git commit -m "$(printf 'feat(highlighted): write highlights to the CSV store via Catalog.find\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 7: Readwise → highlights store writer

**Files:**
- Modify: `books/commands/readwise.py`
- Test: `tests/commands/test_readwise.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/commands/test_readwise.py`:

```python
from pathlib import Path

from books.commands import readwise
from books.core import store

_RW_CSV = (
    "Highlight,Book Title,Book Author,Amazon Book ID,Note,Color,Tags,"
    "Location Type,Location,Highlighted at,Document tags\n"
    "insight,The Deluge (History #1),Adam Tooze,B00XYZ,,,,page,120,2020-01-01,\n"
)


def _seed(vault: Path) -> None:
    store.write_books_csv(
        vault,
        [
            store.BookRow(
                book_id="The Deluge - Adam Tooze",
                title="The Deluge",
                authors=["Adam Tooze"],
                amazon="B00XYZ",
            )
        ],
    )


def test_readwise_writes_highlights_to_store(tmp_path):
    vault = tmp_path / "vault"
    _seed(vault)
    csv = tmp_path / "rw.csv"
    csv.write_text(_RW_CSV, encoding="utf-8")

    stats = readwise.convert(csv, vault)

    rows = store.read_highlights(vault, "The Deluge - Adam Tooze")
    assert len(rows) == 1
    assert rows[0].source == "readwise"
    assert rows[0].text == "insight"
    assert rows[0].location == "120" and rows[0].location_kind == "page"
    assert stats["books"] == 1 and stats["entries"] == 1 and stats["skipped"] == 0


def test_readwise_skips_unmatched(tmp_path):
    vault = tmp_path / "vault"
    store.write_books_csv(vault, [])
    csv = tmp_path / "rw.csv"
    csv.write_text(_RW_CSV, encoding="utf-8")
    stats = readwise.convert(csv, vault)
    assert stats["skipped"] == 1 and stats["books"] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/commands/test_readwise.py -k "writes_highlights_to_store or skips_unmatched" -q`
Expected: FAIL — still `VaultIndex`-based.

- [ ] **Step 3: Rewrite `convert` in `books/commands/readwise.py`**

Replace the `books.renderers.obsidian` import block with:

```python
from books.core import config, store
from books.core.matching import BookRef
```

Keep `from books.core.highlights import Highlight, split_tag_column`. Rewrite `convert`:

```python
def convert(csv_path: Path, output: Path) -> dict:
    """Write every highlight, grouped by book, into the per-book store."""
    stats = {"books": 0, "entries": 0, "skipped": 0}
    output.mkdir(parents=True, exist_ok=True)
    catalog = store.Catalog(output)

    groups: dict[str, dict] = {}
    for row in parse_csv(csv_path):
        raw_title = (row.get("Book Title") or "").strip()
        if not raw_title:
            continue
        title, series, series_index = split_series(raw_title)
        amazon = (row.get("Amazon Book ID") or "").strip() or None
        author = (row.get("Book Author") or "").strip()
        key = amazon or f"{title}\x00{author}"
        group = groups.setdefault(
            key, {"title": title, "author": author, "amazon": amazon, "rows": []}
        )
        group["rows"].append(row)

    for group in groups.values():
        authors = [group["author"]] if group["author"] else []
        book_id = catalog.find(
            BookRef(title=group["title"], authors=authors, amazon=group["amazon"])
        )
        if book_id is None:
            stats["skipped"] += 1
            continue
        highlights = [row_to_highlight(r) for r in group["rows"]]
        hl_rows = [store.highlight_to_row(h, "readwise", str(i)) for i, h in enumerate(highlights)]
        store.write_highlights(output, book_id, "readwise", hl_rows)
        stats["books"] += 1
        stats["entries"] += len(hl_rows)

    return stats
```

Update the CLI echo (`readwise_to_obsidian`) to drop authors:

```python
output.mkdir(parents=True, exist_ok=True)
stats = convert(csv, output)
no_note = f" ({stats['skipped']} skipped — no book)" if stats["skipped"] else ""
typer.echo(
    f"Done. {stats['books']} books{no_note}, {stats['entries']} highlights.\nOutput: {output}"
)
```

Note: readwise no longer writes `series`/`amazon`/`shelves` metadata (it wrote frontmatter before). Metadata enrichment from readwise is out of scope this pass (highlight importers write highlights only); `series`/`series_index` are still parsed for grouping but not persisted.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/commands/test_readwise.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add books/commands/readwise.py tests/commands/test_readwise.py
git commit -m "$(printf 'feat(readwise): write highlights to the CSV store via Catalog.find\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 8: The `books merge` command

**Files:**
- Create: `books/commands/merge.py`
- Modify: `books/cli.py`
- Test: `tests/commands/test_merge.py`

- [ ] **Step 1: Write the failing test**

Create `tests/commands/test_merge.py`:

```python
from typer.testing import CliRunner

from books.cli import app
from books.core import store


def test_merge_command_builds_books_csv(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(
        vault,
        "calibre",
        [
            store.BookRow(
                title="The Deluge", authors=["Adam Tooze"], format="ebook", isbn="9780141032184"
            )
        ],
    )

    result = CliRunner().invoke(app, ["merge", "--output", str(vault)])
    assert result.exit_code == 0, result.output

    rows = store.read_books_csv(vault)
    assert len(rows) == 1
    assert rows[0].book_id == "The Deluge - Adam Tooze"


def test_merge_command_errors_without_layers(tmp_path):
    result = CliRunner().invoke(app, ["merge", "--output", str(tmp_path / "vault")])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/commands/test_merge.py -q`
Expected: FAIL — "No such command 'merge'".

- [ ] **Step 3: Create `books/commands/merge.py`**

```python
#!/usr/bin/env python3
"""`merge` — cluster the source layers into the derived books.csv catalog.

Reads every ``Data/Sources/<source>.csv`` layer, clusters rows into books by
ISBN → Amazon id → author + fuzzy title, coalesces each field by source
precedence, assigns a stable ``book_id``, and writes ``Data/books.csv``. Run it
after the metadata importers and before the highlight importers + ``render``.
"""

from __future__ import annotations

from pathlib import Path

import typer

from books.core import config, store


def merge_command(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the "
        "current directory.",
    ),
) -> None:
    """Merge the source layers into Data/books.csv."""
    vault = config.resolve_vault(output)
    if not store.sources_dir(vault).is_dir() or not any(store.sources_dir(vault).glob("*.csv")):
        raise typer.BadParameter(
            f"no source layers under {store.sources_dir(vault)} — run the "
            f"metadata importers (calibre/goodreads) first",
            param_hint="--output",
        )
    catalog = store.merge(vault)
    typer.echo(f"Merged {len(catalog)} books -> {store.books_csv_path(vault)}")


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("merge")(merge_command)


def main() -> None:
    typer.run(merge_command)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Register in `books/cli.py`**

Add `merge` to the import block and `CAPABILITIES` (keep alphabetical order). Find the existing block that imports capability modules from `books.commands` and add `merge`:

```python
from books.commands import (
    audible,
    calibre,
    covers,
    goodreads,
    highlighted,
    kobo,
    merge,
    readwise,
    render,
    sync,
)

CAPABILITIES = (
    audible,
    calibre,
    covers,
    goodreads,
    highlighted,
    kobo,
    merge,
    readwise,
    render,
    sync,
)
```

(Match the exact names already used in `books/cli.py`; only insert `merge` in both places.)

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/commands/test_merge.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add books/commands/merge.py books/cli.py tests/commands/test_merge.py
git commit -m "$(printf 'feat(merge): add the books merge command\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 9: `sync` two-phase pipeline

**Files:**
- Modify: `books/commands/sync.py`
- Test: `tests/commands/test_sync.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/commands/test_sync.py` an end-to-end test that stubs each step's core function to write the store, then asserts merge + render ran and a note exists. Because the real importers need real sources, monkeypatch the module-level `_run_*` runners and detection.

```python
from pathlib import Path

from books.commands import sync
from books.core import store


def test_run_sync_two_phase_end_to_end(tmp_path, monkeypatch):
    vault = tmp_path / "vault"

    # calibre detected + writes a layer
    monkeypatch.setattr(sync, "_detect_calibre", lambda v: "fake-lib")

    def fake_calibre(v):
        store.write_layer(
            v,
            "calibre",
            [
                store.BookRow(
                    title="The Deluge", authors=["Adam Tooze"], format="ebook", isbn="9780141032184"
                )
            ],
        )
        return {"books": 1, "covers": 0, "skipped": 0, "authors": {"Adam Tooze"}}

    monkeypatch.setattr(sync, "_run_calibre", fake_calibre)

    # goodreads absent
    monkeypatch.setattr(sync, "_detect_goodreads", lambda v: None)

    # kobo detected + writes highlights (after merge, so Catalog can match)
    monkeypatch.setattr(sync, "_detect_kobo", lambda v: "fake-db")

    def fake_kobo(v):
        cat = store.Catalog(v)
        bid = cat.find(
            store.BookRef(title="The Deluge", authors=["Adam Tooze"], isbn="9780141032184")
        )
        assert bid is not None  # merge produced books.csv before this step
        store.write_highlights(
            v,
            bid,
            "kobo",
            [
                store.HighlightRow(
                    source="kobo",
                    annotation_id="0",
                    text="hi",
                    location="42",
                    location_kind="percent",
                )
            ],
        )
        return {"books": 1, "entries": 1, "skipped": 0}

    monkeypatch.setattr(sync, "_run_kobo", fake_kobo)

    monkeypatch.setattr(sync, "_detect_highlighted", lambda v: None)
    monkeypatch.setattr(sync, "_detect_readwise", lambda v: None)

    results = sync.run_sync(vault)

    names = {r.name: r.status for r in results}
    assert names["calibre"] == "ran"
    assert names["merge"] == "ran"
    assert names["kobo"] == "ran"
    assert names["render"] == "ran"
    note = vault / "Books" / "The Deluge - Adam Tooze.md"
    assert note.is_file()
    assert "hi" in note.read_text(encoding="utf-8")


def test_run_sync_skips_merge_and_render_when_no_layers(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    for name in ("calibre", "goodreads", "kobo", "highlighted", "readwise"):
        monkeypatch.setattr(sync, f"_detect_{name}", lambda v: None)
    results = sync.run_sync(vault)
    status = {r.name: r.status for r in results}
    assert status["merge"] == "skipped"
    assert status["render"] == "skipped"
```

BookRef is exported from `books.core.matching`; make it reachable as `store.BookRef` OR import it in the test. `store` does `from books.core.matching import BookRef`, so `store.BookRef` works.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/commands/test_sync.py -k "two_phase or skips_merge_and_render" -q`
Expected: FAIL — `merge`/`render` are not steps.

- [ ] **Step 3: Rewrite the step wiring in `books/commands/sync.py`**

Add imports at the top (with the existing `from books.commands import (...)` block — add `render` there; `merge` logic uses `store` directly):

```python
from books.commands import (
    calibre,
    goodreads,
    highlighted,
    kobo,
    readwise,
    render,
)
from books.core import config, store
```

Add detection + runners + summaries for the two new steps:

```python
def _detect_merge(vault: Path) -> str | None:
    src = store.sources_dir(vault)
    return "Data/Sources" if src.is_dir() and any(src.glob("*.csv")) else None


def _detect_render(vault: Path) -> str | None:
    return "Data/books.csv" if store.books_csv_path(vault).is_file() else None


def _run_merge(vault: Path) -> dict:
    return {"books": len(store.merge(vault))}


def _run_render(vault: Path) -> dict:
    return render.render(vault)


def _summ_merge(s: dict) -> str:
    return f"{s.get('books', 0)} books merged"


def _summ_render(s: dict) -> str:
    return (
        f"{s.get('notes', 0)} notes, {s.get('highlights', 0)} highlights, "
        f"{s.get('reviews', 0)} reviews"
    )
```

Update `_summ_goodreads` and `_summ_calibre` to the new stat keys:

```python
def _summ_calibre(s: dict) -> str:
    return (
        f"{s.get('books', 0)} books, {s.get('covers', 0)} covers, "
        f"{len(s.get('authors', ()))} authors, {s.get('skipped', 0)} skipped"
    )


def _summ_goodreads(s: dict) -> str:
    return (
        f"{s.get('books', 0)} books, {s.get('reviews', 0)} reviews, {s.get('skipped', 0)} skipped"
    )
```

Update `_run_goodreads` (unchanged call, still `goodreads.convert(csv, vault)`), `_run_highlighted` (drop the `authors` aggregation — it no longer returns authors):

```python
def _run_highlighted(vault: Path) -> dict:
    folder = _imports_folder("highlighted", vault)
    totals = {"books": 0, "entries": 0, "skipped": 0}
    for path in sorted(folder.glob("*.csv")):
        stats = highlighted.convert(path, vault)
        totals["books"] += stats["books"]
        totals["entries"] += stats["entries"]
        totals["skipped"] += stats["skipped"]
    return totals
```

Update `_steps()` to the two-phase order with merge + render inserted:

```python
def _steps() -> list[Step]:
    return [
        Step("calibre", _detect_calibre, _run_calibre, _summ_calibre),
        Step("goodreads", _detect_goodreads, _run_goodreads, _summ_goodreads),
        Step("merge", _detect_merge, _run_merge, _summ_merge),
        Step("kobo", _detect_kobo, _run_kobo, _summ_highlights),
        Step("highlighted", _detect_highlighted, _run_highlighted, _summ_highlights),
        Step("readwise", _detect_readwise, _run_readwise, _summ_highlights),
        Step("render", _detect_render, _run_render, _summ_render),
    ]
```

Also, in `run_sync`, the skip message uses `_imports_label(step.name)` which assumes an imports folder — `merge`/`render` have none. Guard it so those two report a sensible reason:

```python
source = step.detect(vault)
if source is None:
    reason = (
        f"no source in {_imports_label(step.name)}"
        if step.name not in ("merge", "render")
        else "nothing to do"
    )
    _skip(step.name, reason)
    results.append(StepResult(step.name, "skipped", reason))
    continue
```

Update the `sync` command docstring to describe the two-phase pipeline (calibre → goodreads → merge → kobo/highlighted/readwise → render).

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/commands/test_sync.py -q`
Expected: PASS (new tests plus adapted existing ones — see Step 5).

- [ ] **Step 5: Fix any existing sync tests**

The existing `tests/commands/test_sync.py` likely asserts the old 5-step list or the old summary strings. Update those assertions to include `merge`/`render` in the step order and the new summary text. Run the whole file and adjust literals until green:

Run: `uv run pytest tests/commands/test_sync.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add books/commands/sync.py tests/commands/test_sync.py
git commit -m "$(printf 'feat(sync): two-phase pipeline (import -> merge -> highlights -> render)\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 9.5: End-to-end integration test (synthetic data)

**Files:**
- Create: `tests/integration/test_pipeline_end_to_end.py`
- Create (if missing): `tests/integration/__init__.py`

Goal: prove the whole pipeline runs on synthetic sources — a real Calibre library
folder + a real Goodreads CSV + a real Kobo sqlite → `sync` (or the explicit
`calibre → goodreads → merge → kobo → render` sequence) → rendered notes with
frontmatter, a materialized cover, an Author stub, and highlights. No mocks; write
real files to `tmp_path` and read back the rendered vault.

- [ ] **Step 1: Write the integration test**

```python
"""End-to-end: synthetic sources -> full pipeline -> rendered Obsidian vault."""

import sqlite3
from pathlib import Path

import frontmatter

from books.commands import calibre, goodreads, kobo, render
from books.core import store

_OPF = """<?xml version='1.0'?>
<package xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>The Deluge</dc:title>
    <dc:creator opf:role="aut">Adam Tooze</dc:creator>
    <dc:identifier opf:scheme="ISBN">9780141032184</dc:identifier>
    <meta name="calibre:rating" content="8"/>
  </metadata>
</package>
"""

_GOODREADS = (
    "Title,Author,Additional Authors,ISBN,ISBN13,My Rating,Publisher,"
    "Number of Pages,Year Published,Binding,Date Read,Date Added,Exclusive Shelf,"
    "Bookshelves,My Review,Private Notes,Book Id\n"
    'The Deluge,Adam Tooze,,="",="9780141032184",4,Penguin,720,2014,Paperback,'
    "2020/01/02,2019/12/01,read,history,A masterpiece.,,12345\n"
)


def _make_calibre_library(root: Path) -> Path:
    book = root / "Adam Tooze" / "The Deluge (1)"
    book.mkdir(parents=True)
    (book / "metadata.opf").write_text(_OPF, encoding="utf-8")
    (book / "cover.jpg").write_bytes(b"\xff\xd8\xff\xe0COVER")
    return root


def _make_kobo_db(path: Path) -> None:
    # Mirror the schema the real QUERY/row_to_highlight in kobo.py expect.
    # NOTE: confirm column/table names against books/commands/kobo.py QUERY and
    # adapt this fixture so the real query returns the highlight below.
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE content (ContentID TEXT, ContentType INT, Title TEXT,
            BookTitle TEXT, Attribution TEXT, ISBN TEXT, VolumeIndex INT);
        CREATE TABLE Bookmark (BookmarkID TEXT, VolumeID TEXT, ContentID TEXT,
            ChapterProgress REAL, Text TEXT, Annotation TEXT, DateCreated TEXT,
            StartContainerPath TEXT, Hidden TEXT);
        INSERT INTO content VALUES ('vol1', 6, 'The Deluge', 'The Deluge',
            'Adam Tooze', '9780141032184', NULL);
        INSERT INTO content VALUES ('vol1-1', 899, 'Chapter One', NULL, NULL,
            NULL, 1);
        INSERT INTO Bookmark VALUES ('bm1', 'vol1', 'vol1-1', 0.42,
            'a memorable highlight', NULL, '2020-01-01', 'span#kobo.3.5', 'false');
        """
    )
    conn.commit()
    conn.close()


def test_full_pipeline_synthetic(tmp_path):
    vault = tmp_path / "vault"
    library = _make_calibre_library(tmp_path / "Calibre Library")
    gr_csv = tmp_path / "goodreads.csv"
    gr_csv.write_text(_GOODREADS, encoding="utf-8")
    kobo_db = tmp_path / "KoboReader.sqlite"
    _make_kobo_db(kobo_db)

    # Phase A: metadata importers -> layers -> merge
    calibre.convert(library, vault)
    goodreads.convert(gr_csv, vault)
    catalog = store.merge(vault)
    assert any(r.book_id == "The Deluge - Adam Tooze" for r in catalog)

    # Phase B: highlight importer (needs books.csv) -> render
    kobo.export_obsidian(kobo_db, vault)
    stats = render.render(vault)

    assert stats["notes"] == 1
    assert stats["failed"] == 0

    note = vault / "Books" / "The Deluge - Adam Tooze.md"
    assert note.is_file()
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert post["type"] == "book"
    assert post["title"] == "The Deluge"
    assert post["isbn"] == "9780141032184"
    assert post["highlighted"] is True
    assert post["reviewed"] is True

    body = post.content
    assert "![[Data/Covers/The Deluge - Adam Tooze.jpg|150]]" in body
    assert "a memorable highlight" in body
    assert "A masterpiece." in body

    # Materialized cover, Author stub
    assert (vault / "Data" / "Covers" / "The Deluge - Adam Tooze.jpg").is_file()
    assert (vault / "Authors" / "Adam Tooze.md").is_file()

    # Idempotent: a second full render produces identical note bytes
    first = note.read_bytes()
    render.render(vault)
    assert note.read_bytes() == first
```

**Adapt, don't force:** confirm the Kobo fixture columns/tables against the real
`QUERY` + `row_to_highlight` in `books/commands/kobo.py` (as Task 5 did) and adjust
the fixture so the real query returns the highlight. If the merged frontmatter uses
different exact values (e.g. rating rendering), assert what the real pipeline
produces — keep the test truthful. The assertions above (note exists, cover
materialized, author stub, highlight + review text present, idempotent re-render)
are the contract to preserve.

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/integration/test_pipeline_end_to_end.py -q`
Expected: PASS. If it fails, fix the wiring/fixture (not by weakening assertions).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/
git commit -m "$(printf 'test: end-to-end pipeline integration test on synthetic data\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Task 10: Full suite, docs, and cleanup

**Files:**
- Modify: `CLAUDE.md`, `README.md`
- (verification only otherwise)

- [ ] **Step 1: Run the entire suite**

Run: `uv run pytest -q`
Expected: PASS for everything except the pre-existing `tests/commands/test_audible_client.py::test_annotations_returns_empty_on_404` (needs the optional `[audible]` extra's `httpx`; unrelated). No other failures. If a covers/audible test fails because it depended on a converted importer creating notes, seed the vault directly with `store.write_books_csv` / `render` in that test instead.

- [ ] **Step 2: Check for dead imports**

Run: `uv run python -c "import books.commands.calibre, books.commands.goodreads, books.commands.kobo, books.commands.highlighted, books.commands.readwise, books.commands.merge, books.commands.sync, books.commands.render; print('ok')"`
Expected: prints `ok`. If any `ImportError`/unused-import warning appears, remove the now-unused `books.renderers.obsidian` names from that module's imports.

- [ ] **Step 3: Update `CLAUDE.md`**

Update the architecture section to reflect that the five importers are now CSV writers and `sync` is two-phase. Specifically:
- In the capabilities list, change `calibre`, `goodreads`, `kobo`, `highlighted`, `readwise` descriptions to say they write the CSV store (`Data/Sources/<name>.csv` for calibre/goodreads; per-book `Data/Highlights/<book_id>.csv` via `store.Catalog.find` for the highlight three) instead of markdown.
- Add a `merge` capability bullet: reads the layers and writes `Data/books.csv`.
- Update the `sync` bullet to the two-phase pipeline: `calibre` + `goodreads` → `merge` → `kobo` + `highlighted` + `readwise` → `render`.
- Update the `render` bullet to note it materializes staged calibre covers and creates `Authors/` stubs.
- Note that `covers` + `audible` remain markdown-writing (VaultIndex) pending a follow-up.

- [ ] **Step 4: Update `README.md`**

Mirror the same changes in any user-facing command list / workflow description (the typical flow becomes `books sync`, or manually `calibre`/`goodreads` → `merge` → highlight importers → `render`).

- [ ] **Step 5: Final full-suite run + commit**

Run: `uv run pytest -q`
Expected: PASS (same known-exception as Step 1).

```bash
git add CLAUDE.md README.md
git commit -m "$(printf 'docs: importers are CSV writers; sync is two-phase\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Self-review notes (author)

- **Spec coverage:**
  - *calibre → CSV writer + cover staging* — Task 1.
  - *goodreads → CSV writer, all shelves* — Task 2.
  - *calibre cover stage-then-materialize* — Task 1 (stage) + Task 3 (materialize).
  - *render creates Author stubs; no Topics stubs* — Task 4.
  - *kobo/highlighted/readwise → highlights store via Catalog.find, skip+count unmatched, replace-by-source on re-run* — Tasks 5–7.
  - *`books merge` command* — Task 8.
  - *sync two-phase (import → merge → highlights → render)* — Task 9.
  - *covers/audible + VaultIndex untouched* — not modified in any task (explicit).
  - *docs* — Task 10.
- **Type/contract consistency:** all importers call `store.write_layer(vault, source, list[BookRow])`, `store.Catalog(vault).find(BookRef) -> str | None`, `store.highlight_to_row(Highlight, source, annotation_id) -> HighlightRow`, and `store.write_highlights(vault, book_id, source, list[HighlightRow])` — exactly as defined in `books/core/store.py`. `BookRef` comes from `books.core.matching` (re-exported as `store.BookRef`). Rating stored numeric-as-string; `render.render_rating` converts. Stats dicts: calibre `{books,covers,skipped,authors}`, goodreads `{books,reviews,skipped}`, highlight importers `{books,entries,skipped}`, merge `{books}`, render `{notes,highlights,reviews,failed,authors}` — matched by the corresponding `_summ_*` in Task 9.
- **Deliberate behavior changes (approved):** every Goodreads shelf becomes a note; Topics stubs dropped; calibre descriptions no longer written to note bodies; readwise no longer writes series/amazon/shelves frontmatter (highlights only).
- **Deferred (later follow-up):** covers + audible → CSV writers; full `VaultIndex` retirement; metadata enrichment from the highlight sources.
