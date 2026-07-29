# covers & audible → CSV writers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `covers` and `audible` from direct-markdown writers (via `VaultIndex`) into pure CSV-store writers, then delete `VaultIndex` so `render` is the sole producer of Obsidian notes.

**Architecture:** `covers` scans `Data/books.csv` for cover-less books, fetches an image (unchanged network code), stages it under `Data/Sources/_covers/covers/<book_id>.jpg`, and writes a `covers` metadata layer (identity + learned isbn + staged path) that `merge` folds in and `render` materializes. `audible` resolves each book to a `book_id` via `store.Catalog.find`, writes per-book highlights via `store.write_highlights` and a small `audible` metadata layer (`format: audiobook`). Both run post-merge; a subsequent `merge` + `render` surfaces their metadata. `VaultIndex` and its tests are then deleted.

**Tech Stack:** Python 3.11, Typer, pydantic (`store.BookRow`/`HighlightRow`), pytest. Design reference: `docs/superpowers/specs/2026-07-29-covers-audible-to-csv-design.md`.

**Read before starting:**
- `books/core/store.py` — `BookRow`, `HighlightRow`, `write_layer`, `read_layer`, `read_books_csv`, `write_highlights`, `read_highlights`, `highlight_to_row`, `Catalog.find`, `PRECEDENCE` (already lists `covers` and `audible`), `sources_dir`, `books_csv_path`.
- `books/commands/calibre.py` — the stage→materialize pattern this plan mirrors for covers (`convert`, the staging dir, `cover` = vault-relative staged path).
- `books/commands/render.py` — `_materialize_cover` (copies a row's staged `cover` to `Data/Covers/<book_id>.jpg`) and `_cover_value` (derives `cover:` from the on-disk file).
- `books/commands/highlighted.py` — the highlight-importer store-writer pattern (`store.Catalog(output)`, `catalog.find(BookRef(...))`, `store.write_highlights`).

**Conventions:** Commit directly to `main` (per CLAUDE.md — no branches/PRs). Run `uv run pytest -q` before each commit. Run single tests with `uv run pytest <path>::<name> -v`.

---

## Task 1: `covers` — repoint `MissingBook` identity from note path to `book_id`

`MissingBook` currently carries `note_path`; the candidate lookups (`sources.py`) only read `title`/`authors`/`isbn`/`amazon`. Replace `note_path` with `book_id` so a `MissingBook` describes a catalog row instead of a note file.

**Files:**
- Modify: `books/commands/covers/sources.py:11-19` (the `MissingBook` dataclass)
- Test: `tests/commands/test_covers.py`

- [ ] **Step 1: Update the `MissingBook` dataclass**

In `books/commands/covers/sources.py`, replace:

```python
@dataclass
class MissingBook:
    """A book note whose `cover:` frontmatter is blank/absent."""
    note_path: Path
    title: str
    authors: list[str]
    isbn: str | None
    amazon: str | None
```

with:

```python
@dataclass
class MissingBook:
    """A catalog book (row in books.csv) that has no cover yet."""
    book_id: str
    title: str
    authors: list[str]
    isbn: str | None
    amazon: str | None
```

The `from pathlib import Path` import in `sources.py` may now be unused — remove it only if `grep -n "Path" books/commands/covers/sources.py` shows no other use.

- [ ] **Step 2: Update every `MissingBook(...)` call in the candidate tests**

The candidate-lookup tests in `tests/commands/test_covers.py` construct `MissingBook(note_path=None, title=..., ...)`. Replace each `note_path=None,` with `book_id="x",`. Do it mechanically:

Run: `grep -n "note_path=None" tests/commands/test_covers.py`
For each hit, change `note_path=None,` → `book_id="x",`. (Tests that construct a note-backed book — `test_apply_cover_*`, `test_find_missing_*`, `test_note_to_missing_*`, `test_run_*` — are rewritten wholesale in later tasks; leave them for now, they will be deleted/replaced.)

- [ ] **Step 3: Run the candidate-lookup tests**

Run: `uv run pytest tests/commands/test_covers.py -k "google or openlibrary or apple or amazon or normalize or itunes or pick_cover or image or fetch_with_retry or gather" -q`
Expected: PASS (these don't touch the store; they only build `MissingBook`s and call the lookups).

- [ ] **Step 4: Commit**

```bash
git add books/commands/covers/sources.py tests/commands/test_covers.py
git commit -m "refactor(covers): MissingBook carries book_id, not note_path

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `covers` — scan the store for cover-less books

Add a store scan that replaces `find_missing`/`note_to_missing` (which scanned `Books/*.md`). A book needs a cover when its `books.csv` `cover` field is blank **and** no `Data/Covers/<book_id>.jpg` exists on disk (the disk check keeps re-runs idempotent before a re-merge folds the cover back into `books.csv`).

**Files:**
- Modify: `books/commands/covers/command.py` (imports + new scan function; remove `find_missing`/`note_to_missing`/`_cover_is_blank`)
- Test: `tests/commands/test_covers.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/commands/test_covers.py` (near the top, after the imports):

```python
from books.core import store


def _seed_catalog(vault, rows):
    """Write books.csv with the given BookRows (each needs a book_id)."""
    store.write_books_csv(vault, rows)


def test_books_missing_cover_selects_blank_and_no_disk_file(tmp_path):
    _seed_catalog(tmp_path, [
        store.BookRow(book_id="A - Ann", title="A", authors=["Ann"],
                      isbn="111", amazon="B001", cover=""),          # blank -> included
        store.BookRow(book_id="B - Bee", title="B", authors=["Bee"],
                      cover="Data/Sources/_covers/x.jpg"),            # has cover -> excluded
        store.BookRow(book_id="C - Cee", title="C", authors=["Cee"]),# blank -> included
    ])
    # C already has a materialized on-disk cover -> excluded despite blank field
    disk = tmp_path / "Data" / "Covers"
    disk.mkdir(parents=True)
    (disk / "C - Cee.jpg").write_bytes(b"img")

    missing = covers.books_missing_cover(tmp_path)
    ids = sorted(m.book_id for m in missing)
    assert ids == ["A - Ann"]
    a = next(m for m in missing if m.book_id == "A - Ann")
    assert a.title == "A" and a.authors == ["Ann"]
    assert a.isbn == "111" and a.amazon == "B001"


def test_books_missing_cover_no_catalog_returns_empty(tmp_path):
    assert covers.books_missing_cover(tmp_path) == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/commands/test_covers.py::test_books_missing_cover_selects_blank_and_no_disk_file -v`
Expected: FAIL with `AttributeError: module 'books.commands.covers' has no attribute 'books_missing_cover'`

- [ ] **Step 3: Implement the scan**

In `books/commands/covers/command.py`, replace the obsidian import block and the `_cover_is_blank`/`note_to_missing`/`find_missing` functions.

Change the imports at the top from:

```python
from books.commands.covers.images import (
    default_fetch_bytes,
    default_fetch_json,
    is_valid_image,
)
from books.commands.covers.sources import (
    Candidate,
    MissingBook,
    iter_candidates,
)
from books.core import config
from books.core.paths import resolve_path
from books.renderers.obsidian import (
    BOOKS_DIRNAME,
    VaultIndex,
    cover_path,
    cover_refs,
    ensure_top_embed,
    extract_wikilinks,
    frontmatter_values,
    unquote,
    update_frontmatter,
    yaml_quote,
)
```

to:

```python
from books.commands.covers.images import (
    default_fetch_bytes,
    default_fetch_json,
    is_valid_image,
)
from books.commands.covers.sources import (
    Candidate,
    MissingBook,
    iter_candidates,
)
from books.core import config, store
```

Then delete `_cover_is_blank`, `note_to_missing`, and `find_missing`, and add:

```python
def books_missing_cover(vault: Path) -> list[MissingBook]:
    """Catalog rows (books.csv) that still need a cover.

    A book needs a cover when its stored ``cover`` is blank *and* no materialized
    ``Data/Covers/<book_id>.jpg`` exists on disk. The on-disk check keeps re-runs
    idempotent even before a re-merge folds a freshly-fetched cover back into
    books.csv.
    """
    out: list[MissingBook] = []
    covers_dir = store.data_dir(vault) / "Covers"
    for row in store.read_books_csv(vault):
        if not row.book_id:
            continue
        if (row.cover or "").strip():
            continue
        if (covers_dir / f"{row.book_id}.jpg").is_file():
            continue
        out.append(MissingBook(
            book_id=row.book_id,
            title=row.title,
            authors=list(row.authors),
            isbn=(row.isbn or "").strip() or None,
            amazon=(row.amazon or "").strip() or None,
        ))
    return out
```

- [ ] **Step 4: Run the new tests**

Run: `uv run pytest tests/commands/test_covers.py -k "books_missing_cover" -v`
Expected: PASS. (Other tests in the file are still broken — they reference the removed functions; the next task fixes them.)

- [ ] **Step 5: Commit**

```bash
git add books/commands/covers/command.py tests/commands/test_covers.py
git commit -m "feat(covers): scan books.csv for cover-less books

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: `covers` — write a staged `covers` layer instead of note frontmatter

Rewrite `run` and replace `apply_cover` with a store sink: stage the winning image to `Data/Sources/_covers/covers/<book_id>.jpg`, accumulate a `store.BookRow` (identity + learned isbn + staged path), and write the `covers` layer — merging with any existing layer so partial (`--limit`/`--book`) runs never drop previously-fetched covers.

**Files:**
- Modify: `books/commands/covers/command.py` (remove `apply_cover`; rewrite `run`; `pick_cover`/`QuitRequested`/`_terminal_prompt` unchanged)
- Test: `tests/commands/test_covers.py`

- [ ] **Step 1: Write the failing tests**

Replace the whole block of note-based `run`/`apply_cover` tests in `tests/commands/test_covers.py` — delete these tests: `test_apply_cover_backfills_isbn_when_learned`, `test_apply_cover_does_not_overwrite_existing_isbn`, `test_apply_cover_writes_file_and_frontmatter`, `test_apply_cover_idempotent`, `test_find_missing_selects_blank_cover_book_notes`, `test_find_missing_no_books_dir_returns_empty`, `test_note_to_missing_eligible_and_ineligible`, `test_run_fetches_and_applies`, `test_run_backfills_isbn_from_chosen_candidate`, `test_run_dry_run_writes_nothing`, `test_run_limit_caps_processing`, `test_run_quit_stops_early`, `test_run_single_book_only_processes_that_note`, `test_run_single_book_ineligible_is_no_op`, `test_run_single_book_ignores_limit`, `test_run_counts_errored_sources`, `test_run_does_not_count_later_source_errors_when_earlier_succeeds`.

Add these store-based replacements:

```python
def _google_volume_with_isbn(isbn):
    return {"items": [{"volumeInfo": {
        "title": "T", "authors": ["Ann"],
        "industryIdentifiers": [{"type": "ISBN_13", "identifier": isbn}],
        "imageLinks": {"thumbnail": "http://x/y?zoom=1"}}}]}


def test_run_stages_image_and_writes_covers_layer(tmp_path):
    _seed_catalog(tmp_path, [
        store.BookRow(book_id="A - Ann", title="A", authors=["Ann"]),
    ])

    def fetch_json(url):
        return GOOGLE_VOLUME if "googleapis" in url else {"docs": []}

    stats = covers.run(
        tmp_path, interactive=False, dry_run=False, limit=None,
        fetch_json=fetch_json,
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"), prompt=None)

    assert stats["missing"] == 1 and stats["fetched"] == 1
    assert stats["by_source"]["google"] == 1
    # image staged under Data/Sources/_covers/covers/<book_id>.jpg
    staged = tmp_path / "Data" / "Sources" / "_covers" / "covers" / "A - Ann.jpg"
    assert staged.is_file()
    # covers layer row points at the staged path
    rows = store.read_layer(tmp_path, "covers")
    assert len(rows) == 1
    assert rows[0].cover == "Data/Sources/_covers/covers/A - Ann.jpg"
    assert rows[0].title == "A" and rows[0].authors == ["Ann"]


def test_run_records_learned_isbn_in_layer(tmp_path):
    _seed_catalog(tmp_path, [
        store.BookRow(book_id="A - Ann", title="A", authors=["Ann"], isbn=""),
    ])
    volume = _google_volume_with_isbn("9780141032184")
    covers.run(
        tmp_path, interactive=False, dry_run=False, limit=None,
        fetch_json=lambda url: volume if "googleapis" in url else {"docs": []},
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"), prompt=None)
    rows = store.read_layer(tmp_path, "covers")
    assert rows[0].isbn == "9780141032184"


def test_run_dry_run_writes_nothing(tmp_path):
    _seed_catalog(tmp_path, [store.BookRow(book_id="A - Ann", title="A", authors=["Ann"])])
    stats = covers.run(
        tmp_path, interactive=False, dry_run=True, limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"), prompt=None)
    assert stats["fetched"] == 1                       # would-fetch still counted
    assert not (tmp_path / "Data" / "Sources" / "_covers").exists()
    assert store.read_layer(tmp_path, "covers") == []


def test_run_limit_preserves_existing_layer_rows(tmp_path):
    _seed_catalog(tmp_path, [
        store.BookRow(book_id="A - Ann", title="A", authors=["Ann"]),
        store.BookRow(book_id="B - Bee", title="B", authors=["Bee"]),
    ])
    # pre-existing covers layer for a previously-fetched book
    store.write_layer(tmp_path, "covers", [
        store.BookRow(title="Z", authors=["Zed"],
                      cover="Data/Sources/_covers/covers/Z - Zed.jpg")])

    covers.run(
        tmp_path, interactive=False, dry_run=False, limit=1,
        fetch_json=lambda url: GOOGLE_VOLUME if "googleapis" in url else {"docs": []},
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"), prompt=None)

    stems = sorted(Path(r.cover).stem for r in store.read_layer(tmp_path, "covers"))
    assert "Z - Zed" in stems           # prior row preserved
    assert "A - Ann" in stems           # newly staged
    assert len(stems) == 2              # limit=1 processed one new book


def test_run_counts_errored_sources(tmp_path):
    _seed_catalog(tmp_path, [
        store.BookRow(book_id="X - Y", title="X", authors=["Y"], amazon="B00ABCDEFG"),
    ])

    def fetch_json(url):
        if "googleapis" in url:
            raise _http_error(429)
        return {"docs": []}

    stats = covers.run(
        tmp_path, interactive=False, dry_run=True, limit=None,
        fetch_json=fetch_json,
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"), prompt=None)
    assert stats["errored"]["google"] == 1
    assert stats["fetched"] == 1        # amazon still succeeded


def test_run_single_book_only_processes_that_book(tmp_path):
    _seed_catalog(tmp_path, [
        store.BookRow(book_id="A - Ann", title="A", authors=["Ann"]),
        store.BookRow(book_id="B - Bee", title="B", authors=["Bee"]),
    ])
    covers.run(
        tmp_path, interactive=False, dry_run=False, limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME if "googleapis" in url else {"docs": []},
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"),
        prompt=None, book_id="A - Ann")
    stems = [Path(r.cover).stem for r in store.read_layer(tmp_path, "covers")]
    assert stems == ["A - Ann"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/commands/test_covers.py -k "run_stages or learned_isbn or dry_run_writes or limit_preserves or counts_errored or single_book_only" -v`
Expected: FAIL (`run` still has the old signature / writes notes).

- [ ] **Step 3: Rewrite `run` and delete `apply_cover`**

In `books/commands/covers/command.py`, delete `apply_cover` entirely, and replace `run` with:

```python
def _covers_staging(vault: Path) -> Path:
    return store.sources_dir(vault) / "_covers" / "covers"


def _stage_image(vault: Path, book_id: str, image: bytes) -> str:
    """Write *image* to the covers staging dir; return its vault-relative path."""
    staging = _covers_staging(vault)
    staging.mkdir(parents=True, exist_ok=True)
    dest = staging / f"{book_id}.jpg"
    dest.write_bytes(image)
    return dest.relative_to(vault).as_posix()


def _existing_covers_layer(vault: Path) -> dict[str, "store.BookRow"]:
    """Prior covers-layer rows keyed by the book_id embedded in their staged path.

    Lets a partial run (``--limit``/``--book``) preserve covers fetched earlier
    instead of overwriting the layer with only this run's rows.
    """
    from pathlib import Path as _P
    out: dict[str, store.BookRow] = {}
    for row in store.read_layer(vault, "covers"):
        if row.cover:
            out[_P(row.cover).stem] = row
    return out


def run(vault, *, interactive, dry_run, limit,
        fetch_json, fetch_bytes, prompt, book_id=None):
    """Fetch covers for catalog books missing one, into the ``covers`` layer.

    Reads books.csv for cover-less books (:func:`books_missing_cover`), fetches an
    image per book (network unchanged), stages it under
    ``Data/Sources/_covers/covers/<book_id>.jpg`` and records a ``covers`` layer
    row (identity + learned isbn + staged path). ``merge`` folds it in and
    ``render`` materializes it. When *book_id* is given, only that catalog book is
    processed. Returns a stats dict.
    """
    all_missing = books_missing_cover(vault)
    if book_id is not None:
        missing = [m for m in all_missing if m.book_id == book_id]
        scanned = 1
    else:
        missing = all_missing
        scanned = len(store.read_books_csv(vault))

    stats = {
        "scanned": scanned,
        "missing": len(missing),
        "processed": 0,
        "fetched": 0,
        "not_found": 0,
        "by_source": {"apple": 0, "google": 0, "openlibrary": 0, "amazon": 0},
        "errored": {"apple": 0, "google": 0, "openlibrary": 0, "amazon": 0},
    }

    layer = _existing_covers_layer(vault) if not dry_run else {}
    todo = missing if (book_id is not None or limit is None) else missing[:limit]
    for book in todo:
        stats["processed"] += 1
        if interactive:
            print(f"\n{book.title} — {', '.join(book.authors) or 'Unknown'}")
        errored: list[str] = []
        candidates = iter_candidates(book, fetch_json, errored)
        try:
            picked = pick_cover(
                candidates, fetch_bytes, interactive=interactive, prompt=prompt)
        except QuitRequested:
            print("Quit.")
            break
        finally:
            for src in errored:
                stats["errored"][src] = stats["errored"].get(src, 0) + 1
        if picked is None:
            stats["not_found"] += 1
            print(f"  no cover: {book.title}")
            continue
        cand, data = picked
        stats["fetched"] += 1
        stats["by_source"][cand.source] = stats["by_source"].get(cand.source, 0) + 1
        if dry_run:
            print(f"  [dry-run] {cand.source}: {cand.image_url}")
            continue
        cover_rel = _stage_image(vault, book.book_id, data)
        layer[book.book_id] = store.BookRow(
            title=book.title,
            authors=list(book.authors),
            isbn=(cand.isbn or book.isbn or ""),
            amazon=(book.amazon or ""),
            cover=cover_rel,
        )
        print(f"  ✓ {cand.source}: {book.title}")

    if not dry_run:
        store.write_layer(vault, "covers", list(layer.values()))
    return stats
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/commands/test_covers.py -k "run_stages or learned_isbn or dry_run_writes or limit_preserves or counts_errored or single_book_only" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add books/commands/covers/command.py tests/commands/test_covers.py
git commit -m "feat(covers): write a staged covers layer instead of note frontmatter

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `covers` — rewire the CLI to the store and drop obsidian imports

`covers_command` scanned `Books/`; point it at `books.csv`, make `--book` a `book_id`, and drop the `VaultIndex`/`BOOKS_DIRNAME` path. Update the package `__init__` exports.

**Files:**
- Modify: `books/commands/covers/command.py` (`covers_command`)
- Modify: `books/commands/covers/__init__.py` (drop `find_missing`/`note_to_missing`/`apply_cover`; add `books_missing_cover`)
- Test: `tests/commands/test_covers.py`

- [ ] **Step 1: Write the failing tests**

Replace `test_cli_covers_dry_run`, `test_cli_covers_reports_errored_sources`, `test_cli_covers_single_book_interactive_by_default`, and `test_cli_covers_single_book_rejects_note_outside_books` in `tests/commands/test_covers.py` with:

```python
def test_cli_covers_dry_run(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from books.cli import app

    _seed_catalog(tmp_path, [store.BookRow(book_id="A - Ann", title="A", authors=["Ann"])])
    monkeypatch.setattr(covers.command, "default_fetch_json", lambda url: GOOGLE_VOLUME)
    monkeypatch.setattr(
        covers.command, "default_fetch_bytes", lambda url: (b"x" * 3000, "image/jpeg"))

    result = CliRunner().invoke(app, ["covers", "-o", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "missing" in result.output.lower()
    assert store.read_layer(tmp_path, "covers") == []


def test_cli_covers_errors_without_catalog(tmp_path):
    from typer.testing import CliRunner
    from books.cli import app
    result = CliRunner().invoke(app, ["covers", "-o", str(tmp_path)])
    assert result.exit_code != 0
    assert "books.csv" in result.output.lower()


def test_cli_covers_single_book_by_id(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from books.cli import app

    _seed_catalog(tmp_path, [
        store.BookRow(book_id="A - Ann", title="A", authors=["Ann"]),
        store.BookRow(book_id="B - Bee", title="B", authors=["Bee"]),
    ])
    monkeypatch.setattr(covers.command, "default_fetch_json",
                        lambda url: GOOGLE_VOLUME if "googleapis" in url else {"docs": []})
    monkeypatch.setattr(
        covers.command, "default_fetch_bytes", lambda url: (b"x" * 3000, "image/jpeg"))
    monkeypatch.setattr(covers.command, "_terminal_prompt", lambda c: "accept")

    result = CliRunner().invoke(app, ["covers", "-o", str(tmp_path), "-b", "A - Ann"])
    assert result.exit_code == 0, result.output
    stems = [Path(r.cover).stem for r in store.read_layer(tmp_path, "covers")]
    assert stems == ["A - Ann"]


def test_cli_covers_registered():
    from books.cli import app
    names = {c.name for c in app.registered_commands}
    assert "covers" in names
```

Also delete `test_dataclasses_exist`'s `note_path=` usage: change its `MissingBook(note_path=Path("/x/Books/A.md"), ...)` to `MissingBook(book_id="A - Ann", ...)`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/commands/test_covers.py -k "cli_covers or dataclasses_exist" -v`
Expected: FAIL

- [ ] **Step 3: Rewrite `covers_command`**

In `books/commands/covers/command.py`, replace `covers_command` with:

```python
def covers_command(
    output: Path | None = typer.Option(
        None, "--output", "-o",
        help="Obsidian vault. Defaults to the vault from your config file "
             "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
    book: str | None = typer.Option(
        None, "--book", "-b",
        help="Fetch a cover for a single catalog book by its book_id (the "
             "'<Title> - <Author>' stem in Data/books.csv). Interactive by default."),
    interactive: bool | None = typer.Option(
        None, "--interactive/--no-interactive",
        help="Confirm each candidate: accept / next / skip book / quit. "
             "Defaults on for a single --book, off for a full scan.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Report the chosen cover per book without writing anything.",
    ),
    limit: int | None = typer.Option(
        None, "--limit",
        help="Process at most this many books missing a cover (ignored with --book).",
    ),
) -> None:
    """Fetch covers for catalog books missing one, into the ``covers`` layer.

    Reads Data/books.csv for 'type: book' rows whose 'cover' is blank (and which
    have no Data/Covers/<book_id>.jpg yet) and fetches a cover from Apple Books,
    then Google Books, then Open Library, then Amazon (only when the row has an
    'amazon' ASIN). The image is staged under Data/Sources/_covers/covers/ and a
    'covers' layer row is written (with any learned ISBN); run 'merge' then
    'render' to fold it in and materialize Data/Covers/<book_id>.jpg. By default
    the best match is written automatically; use --interactive to approve each,
    or --dry-run to preview. Pass --book <book_id> for a single book.
    """
    vault = config.resolve_vault(output)
    if not store.books_csv_path(vault).is_file():
        raise typer.BadParameter(
            f"no books.csv under {store.data_dir(vault)} — run the importers + merge first",
            param_hint="--output",
        )

    if interactive is None:
        interactive = book is not None

    stats = run(
        vault, interactive=interactive, dry_run=dry_run, limit=limit,
        fetch_json=default_fetch_json, fetch_bytes=default_fetch_bytes,
        prompt=_terminal_prompt, book_id=book,
    )
    bs = stats["by_source"]
    typer.echo(
        f"Scanned {stats['scanned']} books, {stats['missing']} missing covers → "
        f"{stats['fetched']} fetched "
        f"(apple {bs['apple']}, google {bs['google']}, "
        f"openlibrary {bs['openlibrary']}, amazon {bs['amazon']}), "
        f"{stats['not_found']} not found."
    )
    errored = {src: n for src, n in stats.get("errored", {}).items() if n}
    if errored:
        detail = ", ".join(f"{src} {n}" for src, n in errored.items())
        typer.secho(
            f"⚠ source errors (rate-limited / unreachable, not 'no match'): {detail}",
            fg=typer.colors.YELLOW,
        )
```

Confirm `resolve_path` is no longer imported (it was only used for `--book` path resolution). Run `grep -n "resolve_path" books/commands/covers/command.py` and remove the import if unused.

- [ ] **Step 4: Update the package exports**

In `books/commands/covers/__init__.py`, in the import from `books.commands.covers.command`, remove `apply_cover`, `find_missing`, `note_to_missing` and add `books_missing_cover`. Update `__all__` the same way (remove those three, add `"books_missing_cover"`).

- [ ] **Step 5: Run the full covers test file**

Run: `uv run pytest tests/commands/test_covers.py -q`
Expected: PASS (all remaining tests).

- [ ] **Step 6: Commit**

```bash
git add books/commands/covers/command.py books/commands/covers/__init__.py tests/commands/test_covers.py
git commit -m "feat(covers): CLI reads books.csv, --book takes a book_id, drop VaultIndex

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `covers` → `merge` → `render` end-to-end integration test

Prove the full covers path: a cover-less book → `covers` layer → `merge` folds cover+isbn → `render` materializes `Data/Covers/<book_id>.jpg` + emits the embed, byte-identical on a second render.

**Files:**
- Test: `tests/commands/test_covers.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/commands/test_covers.py`:

```python
def test_covers_merge_render_materializes_cover(tmp_path):
    from books.commands import render
    # a goodreads-style source layer with one cover-less book
    store.write_layer(tmp_path, "goodreads", [
        store.BookRow(title="A", authors=["Ann"], isbn="")])
    store.merge(tmp_path)                       # -> books.csv with a book_id

    covers.run(
        tmp_path, interactive=False, dry_run=False, limit=None,
        fetch_json=lambda url: _google_volume_with_isbn("9780141032184")
        if "googleapis" in url else {"docs": []},
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"), prompt=None)

    store.merge(tmp_path)                       # fold covers layer into books.csv
    row = next(r for r in store.read_books_csv(tmp_path) if r.title == "A")
    assert row.isbn == "9780141032184"          # learned isbn folded in
    assert row.cover.endswith(".jpg")           # staged path folded in

    render.render(tmp_path)
    cover_file = tmp_path / "Data" / "Covers" / f"{row.book_id}.jpg"
    assert cover_file.is_file()                  # materialized
    note = (tmp_path / "Books" / f"{row.book_id}.md").read_text()
    assert f"![[Data/Covers/{row.book_id}.jpg|150]]" in note

    first = (tmp_path / "Books" / f"{row.book_id}.md").read_bytes()
    render.render(tmp_path)
    assert (tmp_path / "Books" / f"{row.book_id}.md").read_bytes() == first
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/commands/test_covers.py::test_covers_merge_render_materializes_cover -v`
Expected: PASS (all pieces exist; this is a wiring test). If it fails, fix the wiring in `run`/scan, not the test.

- [ ] **Step 3: Commit**

```bash
git add tests/commands/test_covers.py
git commit -m "test(covers): end-to-end covers → merge → render materialization

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `audible` — resolve via `Catalog.find` and write the store

Replace `VaultIndex.find` + `render_note` with `store.Catalog.find` + `store.write_highlights` + an `audible` metadata layer. Keep the entire download/cut/transcribe/cache pipeline.

**Files:**
- Modify: `books/commands/audible/command.py` (imports, `run`, new `book_highlight_rows`; delete `render_note`)
- Test: `tests/commands/test_audible_obsidian.py`

- [ ] **Step 1: Write the failing tests**

In `tests/commands/test_audible_obsidian.py`, add the store import and a catalog-seed helper near the top (after `from books.commands.audible import models`):

```python
from books.core import store


def _seed_catalog(vault, rows):
    store.write_books_csv(vault, rows)
```

Delete these note-based tests: `test_render_note_writes_frontmatter_and_marked_section`, `test_render_note_skips_empty_text_highlights`. Rewrite the `run` tests below (delete the old versions, add these). Replace `_seed_note`/`_library_and_notes` usage with catalog seeding:

```python
def test_book_highlight_rows_maps_clips_with_annotation_ids():
    clips = {
        "a1": {"text": "First clip.", "start_ms": 120_000, "end_ms": 150_000,
               "note": None, "date": None, "chapter": "The Rise", "chapter_index": 2},
        "a2": {"text": "", "start_ms": 0, "end_ms": None, "note": None,
               "date": None, "chapter": None, "chapter_index": None},  # empty -> dropped
    }
    rows = ao.book_highlight_rows(clips)
    assert [r.annotation_id for r in rows] == ["a1"]
    assert rows[0].source == "audible"
    assert rows[0].text == "First clip."
    assert rows[0].chapter_title == "The Rise"


def _catalog_and_library(tmp_path):
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(out, [store.BookRow(
        book_id="Stalin - Stephen Kotkin", title="Stalin",
        authors=["Stephen Kotkin"], amazon="B0STALIN")])
    book = ao.LibraryBook(asin="B0STALIN", title="Stalin",
                          authors=["Stephen Kotkin"])
    anns = {"B0STALIN": [ao.Annotation(id="a1", start_ms=120_000,
                                       end_ms=150_000, note="Nice")]}
    return out, book, anns


def test_run_writes_highlights_and_audible_layer(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    client = FakeClient([book], anns)
    cache_path = out / "Data" / "Imports" / "audible" / "cache.json"
    down, cut = FakeDownloader(), FakeCutter()
    stats = ao.run(out, client=client, downloader=down, cutter=cut,
                   transcriber=_fake_transcriber, cache_path=cache_path,
                   clip_window=30)
    assert stats["books"] == 1 and stats["entries"] == 1
    assert stats["downloaded"] == 1 and stats["transcribed"] == 1
    hl = store.read_highlights(out, "Stalin - Stephen Kotkin")
    assert [r.source for r in hl] == ["audible"]
    assert hl[0].text == "transcribed text"
    assert hl[0].annotation_id == "a1"
    layer = store.read_layer(out, "audible")
    assert len(layer) == 1
    assert layer[0].amazon == "B0STALIN"
    assert layer[0].format == "audiobook"


def test_run_skips_unmatched_without_download(tmp_path):
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(out, [])                     # empty catalog -> no match
    book = ao.LibraryBook(asin="B0X", title="Unknown", authors=["Nobody"])
    client = FakeClient([book], {"B0X": [ao.Annotation(id="a1", start_ms=0, end_ms=10)]})
    down = FakeDownloader()
    stats = ao.run(out, client=client, downloader=down, cutter=FakeCutter(),
                   transcriber=_fake_transcriber,
                   cache_path=out / "c.json", clip_window=30)
    assert stats["skipped"] == 1 and stats["books"] == 0
    assert down.calls == []
    assert store.read_layer(out, "audible") == []


def test_run_no_highlights_writes_nothing(tmp_path):
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(out, [store.BookRow(
        book_id="Stalin - Stephen Kotkin", title="Stalin",
        authors=["Stephen Kotkin"], amazon="B0STALIN")])
    book = ao.LibraryBook(asin="B0STALIN", title="Stalin", authors=["Stephen Kotkin"])
    anns = {"B0STALIN": [ao.Annotation(id="a1", start_ms=0, end_ms=10, note=None)]}
    stats = ao.run(out, client=FakeClient([book], anns),
                   downloader=FakeDownloader(), cutter=FakeCutter(),
                   transcriber=lambda path: "", cache_path=out / "c.json",
                   clip_window=30)
    assert stats["books"] == 0 and stats["entries"] == 0
    assert store.read_highlights(out, "Stalin - Stephen Kotkin") == []
    assert store.read_layer(out, "audible") == []


def test_run_replaces_only_audible_highlights(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    # a pre-existing highlight from another source must survive an audible run
    store.write_highlights(out, "Stalin - Stephen Kotkin", "kobo",
                           [store.HighlightRow(source="kobo", text="kept")])
    ao.run(out, client=FakeClient([book], anns), downloader=FakeDownloader(),
           cutter=FakeCutter(), transcriber=_fake_transcriber,
           cache_path=out / "c.json", clip_window=30)
    hl = store.read_highlights(out, "Stalin - Stephen Kotkin")
    sources = sorted(r.source for r in hl)
    assert sources == ["audible", "kobo"]


def test_run_idempotent_uses_cache_no_redownload(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    cache_path = out / "Data" / "Imports" / "audible" / "cache.json"
    down1 = FakeDownloader()
    ao.run(out, client=FakeClient([book], anns), downloader=down1,
           cutter=FakeCutter(), transcriber=_fake_transcriber,
           cache_path=cache_path, clip_window=30)
    before = store.read_highlights(out, "Stalin - Stephen Kotkin")
    down2 = FakeDownloader()
    ao.run(out, client=FakeClient([book], anns), downloader=down2,
           cutter=FakeCutter(), transcriber=_fake_transcriber,
           cache_path=cache_path, clip_window=30)
    after = store.read_highlights(out, "Stalin - Stephen Kotkin")
    assert down2.calls == []
    assert [r.to_csv_dict() for r in before] == [r.to_csv_dict() for r in after]


def test_run_continues_when_one_book_fails(tmp_path):
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(out, [
        store.BookRow(book_id="Stalin - Stephen Kotkin", title="Stalin",
                      authors=["Stephen Kotkin"], amazon="B0BAD"),
        store.BookRow(book_id="Peace - Leo Tolstoy", title="Peace",
                      authors=["Leo Tolstoy"], amazon="B0GOOD"),
    ])
    bad = ao.LibraryBook(asin="B0BAD", title="Stalin", authors=["Stephen Kotkin"])
    good = ao.LibraryBook(asin="B0GOOD", title="Peace", authors=["Leo Tolstoy"])
    anns = {
        "B0BAD": [ao.Annotation(id="a1", start_ms=1000, end_ms=2000)],
        "B0GOOD": [ao.Annotation(id="a2", start_ms=1000, end_ms=2000)],
    }

    class BoomDownloader(FakeDownloader):
        def download(self, asin, dest_dir):
            if asin == "B0BAD":
                raise RuntimeError("boom")
            return super().download(asin, dest_dir)

    stats = ao.run(out, client=FakeClient([bad, good], anns),
                   downloader=BoomDownloader(), cutter=FakeCutter(),
                   transcriber=_fake_transcriber, cache_path=out / "c.json",
                   clip_window=30)
    assert stats["failed"] == 1
    assert stats["books"] == 1 and stats["entries"] == 1
    assert store.read_highlights(out, "Peace - Leo Tolstoy")[0].text == "transcribed text"


def test_run_dry_run_writes_nothing(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    down = FakeDownloader()
    stats = ao.run(out, client=FakeClient([book], anns), downloader=down,
                   cutter=FakeCutter(), transcriber=_fake_transcriber,
                   cache_path=out / "c.json", clip_window=30, dry_run=True)
    assert down.calls == []
    assert store.read_highlights(out, "Stalin - Stephen Kotkin") == []
    assert store.read_layer(out, "audible") == []
    assert not (out / "c.json").exists()
    assert stats["books"] == 0
```

Leave `test_run_point_bookmark_uses_window_before_mark` but migrate its note-seeding to catalog-seeding (replace `_seed_note(...)` with `_seed_catalog(out, [store.BookRow(book_id="Stalin - Stephen Kotkin", title="Stalin", authors=["Stephen Kotkin"], amazon="B0STALIN")])` and set the annotation's asin book to `amazon="B0STALIN"`).

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/commands/test_audible_obsidian.py -k "book_highlight_rows or run_writes_highlights or run_no_highlights or run_replaces or run_skips_unmatched" -v`
Expected: FAIL (`book_highlight_rows` missing; `run` still uses `VaultIndex`).

- [ ] **Step 3: Rewrite `run` + add `book_highlight_rows`; delete `render_note`**

In `books/commands/audible/command.py`, change the imports from:

```python
from books.commands.audible.models import Annotation, Chapter, LibraryBook
from books.core import config
from books.core.highlights import Highlight, parse_markers
from books.renderers.obsidian import (
    AUTHORS_DIRNAME,
    BookRef,
    VaultIndex,
    link_list,
    render_highlights,
    render_marked_section,
    update_frontmatter,
    write_stub,
    yaml_quote,
)
```

to:

```python
from books.commands.audible.models import Annotation, Chapter, LibraryBook
from books.core import config, store
from books.core.highlights import Highlight, parse_markers
from books.core.matching import BookRef
```

Delete `render_note` and add:

```python
def book_highlight_rows(clips: dict) -> list["store.HighlightRow"]:
    """Map a book's cached clips into audible-source HighlightRows.

    Each clip record becomes a Highlight (:func:`record_to_highlight`); empty-text
    records are dropped. The cache key (the Audible annotation id) is the stable
    ``annotation_id`` so re-runs replace cleanly.
    """
    rows: list[store.HighlightRow] = []
    for ann_id, rec in clips.items():
        h = record_to_highlight(rec)
        if h.text:
            rows.append(store.highlight_to_row(h, "audible", ann_id))
    return rows
```

Then replace `run` with (only the sink + resolution differ from the current body — keep the download/transcribe block verbatim):

```python
def run(vault, *, client, downloader, cutter, transcriber, cache_path,
        clip_window, limit=None, asin=None, dry_run=False,
        echo=lambda *_: None) -> dict:
    """Import Audible clips into the CSV store. All heavy I/O is injected.

    Resolves each library book to a book_id via the merged catalog
    (Data/books.csv); an unmatched book is skipped and counted. For a matched book
    with transcribed clips, writes per-book highlights (source ``audible``) and an
    ``audible`` metadata layer row (``format: audiobook``). ``merge`` + ``render``
    later surface them. In *dry_run* mode nothing is written.
    """
    vault.mkdir(parents=True, exist_ok=True)
    catalog = store.Catalog(vault)
    cache = load_cache(cache_path)
    stats = {"books": 0, "entries": 0, "skipped": 0,
             "downloaded": 0, "transcribed": 0, "failed": 0,
             "est_seconds": 0.0}

    # Preserve other audiobooks' layer rows across partial (--asin/--limit) runs.
    layer = {r.amazon: r for r in store.read_layer(vault, "audible") if r.amazon}

    library = client.library()
    if asin:
        library = [b for b in library if b.asin == asin]

    matched = 0
    for book in library:
        try:
            ref = BookRef(title=book.title, authors=book.authors, amazon=book.asin)
            book_id = catalog.find(ref)
            if book_id is None:
                stats["skipped"] += 1
                if dry_run:
                    authors = ", ".join(book.authors) or "?"
                    anns = client.annotations(book.asin)
                    secs = _clip_seconds(anns, clip_window)
                    stats["est_seconds"] += secs
                    echo(f"[dry-run] SKIP (no book): {book.title} — {authors} "
                         f"[asin {book.asin}] — {len(anns)} clip(s), "
                         f"~{secs/60:.1f} min, ~${secs * COST_PER_SECOND:.2f}")
                continue
            if limit is not None and matched >= limit:
                break
            matched += 1

            annotations = client.annotations(book.asin)
            if not annotations:
                continue

            book_cache = cache.setdefault(book.asin,
                                          {"title": book.title, "clips": {}})
            clips = book_cache.setdefault("clips", {})
            new = uncached(annotations, clips)

            if dry_run:
                secs = _clip_seconds(new, clip_window)
                stats["est_seconds"] += secs
                echo(f"[dry-run] {book.title}: {len(annotations)} annotations, "
                     f"{len(new)} new to transcribe — ~{secs/60:.1f} min, "
                     f"~${secs * COST_PER_SECOND:.2f}")
                continue

            if new:
                chapters = client.chapters(book.asin)
                with tempfile.TemporaryDirectory() as td:
                    tmp = Path(td)
                    audio = downloader.download(book.asin, tmp)
                    stats["downloaded"] += 1
                    for ann in new:
                        start, end = _clip_bounds(ann, clip_window)
                        clip_path = cutter.cut(audio, start, end,
                                               tmp / f"{ann.id}.wav")
                        text = transcriber(clip_path)
                        clips[ann.id] = annotation_to_record(ann, text, chapters)
                        stats["transcribed"] += 1
                save_cache(cache_path, cache)

            rows = book_highlight_rows(clips)
            if not rows:
                continue
            store.write_highlights(vault, book_id, "audible", rows)
            layer[book.asin] = store.BookRow(
                title=book.title, authors=list(book.authors),
                amazon=book.asin, format="audiobook")
            stats["books"] += 1
            stats["entries"] += len(rows)
        except Exception as exc:  # noqa: BLE001 — continue-on-error per book
            stats["failed"] += 1
            echo(f"[skip] {book.title} [asin {book.asin}]: {exc}")
            continue

    if not dry_run:
        store.write_layer(vault, "audible", list(layer.values()))
    return stats
```

Note: `record_to_highlight`, `annotation_to_record`, `_merge_markers`, `_clip_bounds`, `_clip_seconds`, `load_cache`, `save_cache`, `uncached`, `format_timestamp`, `chapter_for` are all unchanged and stay. `Chapter` is still imported (used by `chapter_for`/`annotation_to_record`).

- [ ] **Step 4: Run the audible tests**

Run: `uv run pytest tests/commands/test_audible_obsidian.py -q`
Expected: PASS (the two CLI tests `test_cli_enriches_note_end_to_end` / `test_cli_dry_run_builds_no_heavy_adapters` are handled in Task 7; if they fail here on the note assertion, that is expected and fixed next).

- [ ] **Step 5: Commit**

```bash
git add books/commands/audible/command.py tests/commands/test_audible_obsidian.py
git commit -m "feat(audible): write highlights + audible layer to the store, drop VaultIndex

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: `audible` — update the CLI end-to-end test and message

The CLI test asserted note content; assert store content. The success message says "Output: <vault>" — keep it but it now reflects store writes.

**Files:**
- Modify: `tests/commands/test_audible_obsidian.py` (`test_cli_enriches_note_end_to_end`)
- Test: same file

- [ ] **Step 1: Rewrite the CLI end-to-end test**

Replace `test_cli_enriches_note_end_to_end` with:

```python
def test_cli_enriches_book_end_to_end(monkeypatch, tmp_path):
    from books.core import config, store
    out, book, anns = _catalog_and_library(tmp_path)
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: out)
    monkeypatch.setattr(
        config, "resolve_imports",
        lambda name, output=None: out / "Data" / "Imports" / name)
    monkeypatch.setattr(ao, "_build_client",
                        lambda quality="normal": FakeClient([book], anns))
    monkeypatch.setattr(ao, "_build_transcriber",
                        lambda kind, model: _fake_transcriber)
    monkeypatch.setattr(ao, "_build_cutter", lambda: FakeCutter())
    monkeypatch.setattr(ao, "_build_downloader", lambda client: FakeDownloader())

    result = runner.invoke(app, ["audible"])
    assert result.exit_code == 0, result.output
    hl = store.read_highlights(out, "Stalin - Stephen Kotkin")
    assert hl and hl[0].text == "transcribed text"
    assert "1 book" in result.output
```

`test_cli_dry_run_builds_no_heavy_adapters` needs no change beyond its existing `resolve_imports` monkeypatch (already points into a temp path); confirm it still passes.

- [ ] **Step 2: Run the audible tests**

Run: `uv run pytest tests/commands/test_audible_obsidian.py -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/commands/test_audible_obsidian.py
git commit -m "test(audible): CLI end-to-end asserts store writes

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Delete `VaultIndex` and its tests

With no remaining callers, remove `vault_index.py`, its re-exports, and its dedicated tests. The note-naming collision ladder lives in `books/core/naming.py` (`next_free_stem`/`strip_subtitle`/`safe_filename`) and is exercised by `store.assign_book_id`/`store.merge` tests, so no coverage is lost.

**Files:**
- Delete: `books/renderers/obsidian/vault_index.py`
- Modify: `books/renderers/obsidian/__init__.py` (drop `BookNote`/`VaultIndex`/`build_index`)
- Modify: `tests/renderers/obsidian/test_obsidian.py` (delete VaultIndex tests)

- [ ] **Step 1: Confirm there are no remaining runtime callers**

Run: `grep -rn "VaultIndex\|build_index\|BookNote\|find_or_create" books/`
Expected: matches only inside `books/renderers/obsidian/vault_index.py` and `books/renderers/obsidian/__init__.py`. If any other file matches, stop and convert it first.

- [ ] **Step 2: Delete the VaultIndex tests**

In `tests/renderers/obsidian/test_obsidian.py`, delete these test functions entirely: `test_vaultindex_creates_new_note_with_stub`, `test_vaultindex_matches_existing_by_title_author`, `test_vaultindex_disambiguates_same_title_different_book`, `test_new_note_filename_strips_subtitle_and_appends_author`, `test_new_note_filename_without_author_uses_title_only`, `test_new_note_filename_collision_keeps_subtitle_colon_as_comma`, `test_new_note_filename_counter_when_full_title_also_collides`, `test_vaultindex_find_returns_none_when_no_match`, `test_vaultindex_find_returns_existing_note`, `test_vaultindex_matches_existing_note_by_amazon`, `test_new_stub_carries_flag_defaults`.

Then run `grep -n "VaultIndex\|build_index\|BookNote\|find_or_create\|ob.BookNote" tests/renderers/obsidian/test_obsidian.py` — expected: no matches. (If `test_new_stub_carries_flag_defaults` used `write_stub` rather than `VaultIndex`, keep it; per the current file it uses `find_or_create`, so delete it.)

- [ ] **Step 3: Remove the re-exports**

In `books/renderers/obsidian/__init__.py`, delete the import block:

```python
from books.renderers.obsidian.vault_index import (
    BookNote,
    VaultIndex,
    build_index,
)
```

and remove `"BookNote"`, `"VaultIndex"`, and `"build_index"` from `__all__`.

- [ ] **Step 4: Delete the module**

Run: `git rm books/renderers/obsidian/vault_index.py`

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS. If an import of `VaultIndex`/`BookNote`/`build_index` breaks a test elsewhere, delete or migrate that usage (search with the Step 1 grep across `tests/`).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(obsidian): delete VaultIndex — render is the sole note producer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Document the post-merge ordering

Record that `covers`/`audible` are post-merge, metadata-then-remerge steps, and that they are not part of `sync`.

**Files:**
- Modify: `CLAUDE.md` (the `covers` and `audible` capability bullets, and the two-phase pipeline paragraph)

- [ ] **Step 1: Update the `audible` bullet**

In `CLAUDE.md`, in the `books/commands/audible/` bullet, replace the description of the sink (currently "imports ... into existing Obsidian book notes (enrich-only via `VaultIndex.find` ...)" and the `## Highlights` rendering) with the store-writer behavior:

> `books/commands/audible/` → `audible` — imports **Audible bookmarks & clips** into the CSV store (enrich-only: matched via `store.Catalog.find` by ASIN as `amazon` then title/author; unmatched books skipped and counted). For a matched book it writes per-book highlights (`store.write_highlights`, source `audible`) and a small `audible` metadata layer (`Data/Sources/audible.csv`, carrying `format: audiobook` + the ASIN) via `store.write_layer`; run `merge` + `render` afterward to fold the layer in and render the `## Highlights` section. Authenticates to the Audible cloud, downloads + ffmpeg-decrypts + cuts each clip, transcribes it (pluggable `--transcriber`, default `local` faster-whisper), and caches transcriptions in `<vault>/Data/Imports/audible/cache.json` (keyed by ASIN + annotation id). Runs after `merge`; **not** part of `sync`. Lives as a package (`command.py` + `models.py` + `client.py` + `transcribe.py`).

- [ ] **Step 2: Update the `covers` bullet**

Replace the opening of the `books/commands/covers/` bullet (currently "scans an existing vault for `type: book` notes with a blank `cover:` field ... fills the note's `cover:` frontmatter + top embed ... via the shared `books/renderers/obsidian/` helpers") with:

> `books/commands/covers/` → `covers` — scans the merged catalog (`Data/books.csv`) for books with a blank `cover` (and no materialized `Data/Covers/<book_id>.jpg`) and fetches a cover image. Sources are tried in order (Apple Books → Google Books → Open Library → Amazon, unchanged). The fetched image is staged under `Data/Sources/_covers/covers/<book_id>.jpg` and a `covers` metadata layer (`Data/Sources/covers.csv`) records the staged path + any learned ISBN; run `merge` + `render` afterward to fold it in and materialize `Data/Covers/<book_id>.jpg` + the note embed. Runs after `merge`; **not** part of `sync`. `--book <book_id>` targets a single catalog book (interactive by default), `--dry-run` previews, `--limit N` caps the run. Split into `command.py` (scan/select + CLI + store sink), `sources.py` (per-provider lookups + `Candidate`/`MissingBook`), and `images.py` (HTTP retry/backoff + image validation).

- [ ] **Step 3: Update the shared-layer / VaultIndex references**

In `CLAUDE.md`, in the "Two ways to resolve a book to a note (`VaultIndex`)" bullet and the "Flat note filenames (`VaultIndex._new_note_path` ...)" bullet, remove the `VaultIndex` references: state that book identity is resolved by `store.Catalog.find` (ISBN → Amazon → title/author) and that flat note filenames come from `books/core/naming.py` (`next_free_stem`/`strip_subtitle`/`safe_filename`) via `store.assign_book_id`. Delete any sentence claiming `VaultIndex.find` is still used by `audible` (it no longer exists). Also update the intro paragraph that says `covers` and `audible` "work directly against rendered notes" to say they now write the store (post-merge) like the other importers.

- [ ] **Step 4: Verify no stale VaultIndex mentions remain in guidance**

Run: `grep -n "VaultIndex\|find_or_create" CLAUDE.md`
Expected: no matches (or only historical mentions clearly marked as removed). Fix any that describe current behavior.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: covers/audible are post-merge CSV writers; VaultIndex retired

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Final verification

- [ ] **Step 1: Full suite**

Run: `uv run pytest -q`
Expected: PASS, no skips introduced by this work.

- [ ] **Step 2: No obsidian imports remain in the two converted commands**

Run: `grep -rn "renderers.obsidian" books/commands/covers/ books/commands/audible/`
Expected: no matches.

- [ ] **Step 3: CLI smoke check**

Run: `uv run books covers --help` and `uv run books audible --help`
Expected: both render help text; `covers --book` documents a `book_id`; no tracebacks.

- [ ] **Step 4: Confirm clean tree**

Run: `git status`
Expected: clean (all work committed).
