# Kindle Highlights Cache — Design Spec

**Status:** Approved
**Date:** 2026-07-31
**Depends on:** the existing Kindle importer (`books/commands/kindle/`, spec
`2026-07-31-kindle-importer-design.md`).

## Problem

The Kindle importer is a Phase-B consumer: it resolves each book against the
merged catalog (`Data/books.csv`) and **skips** any book it can't match. Two
consequences hurt a Kindle-primary user:

1. **Import order matters.** If highlights are imported before Calibre/Goodreads
   metadata, every book is skipped and the work is thrown away — the user must
   re-read `My Clippings.txt` after building the catalog.
2. **The source is ephemeral.** `My Clippings.txt` lives only on the device,
   which gets unplugged. Re-resolving later requires re-attaching the Kindle.

## Goal

Decouple **extraction** (needs the device / `My Clippings.txt`) from **catalog
resolution + store write** (needs metadata), mirroring the Audible importer's
per-book transcription cache. After a one-time read, `books import --kindle`
works in **any order** and **without the Kindle attached**: books cached now
attach to the store as soon as their catalog entry exists.

Non-goals: no change to the catalog, `merge`, the match-only resolution
philosophy, or the other highlight importers. Kindle simply stops discarding
unmatched work.

## Design decisions (locked)

- **Refresh semantics:** wholesale per-book overwrite when the device is present
  (each book seen in the current parse replaces its cache file; books only on a
  previous device are left untouched).
- **Resolve scope:** every run re-resolves the **entire** cache against the
  current catalog and writes all matches — even books not in this parse, even
  with no device attached. This is what makes import order irrelevant.
- **Reporting:** cached-but-unmatched books are reported as **pending** (distinct
  from other importers' "skipped"), signalling they are cached and will attach
  once metadata is imported.
- **Cache filename:** readable stem `safe_filename("<Title> - <Author>")`, e.g.
  `The Autobiography of Malcolm X - Malcolm X.json`. Assignment is deterministic
  (books processed in canonical-key order) so the same book always maps to the
  same file and wholesale overwrite is stable; rare collisions between distinct
  books get a stable numeric suffix.

## Architecture

### 1. New module — `books/commands/kindle/cache.py`

Keeps the package's one-purpose-per-file split (parser / dedup / cache /
command). Standard library only (`json`, `dataclasses`, `pathlib`).

Public API:

- `cache_dir(vault: Path) -> Path` — `<vault>/Data/Imports/kindle/cache/`.
- `save_book(cache_dir: Path, title: str, author: str, highlights: list[Highlight]) -> None`
  — write one book's JSON record (wholesale overwrite; parents created).
- `load_all(cache_dir: Path) -> list[dict]` — every cache record `{title,
  author, highlights: [Highlight]}`, skipping missing/corrupt files.
- `Highlight ↔ dict` serialization via `dataclasses.asdict` / `Highlight(**d)`.

**Cache record** (`<stem>.json`):

```json
{"title": "The Autobiography of Malcolm X",
 "author": "Malcolm X",
 "highlights": [{"text": "...", "note": "a thought", "page": "472-473",
                 "location_label": "loc.", "date": "2015-07-31T00:18:38",
                 "source": "kindle", "tags": [], "links": [],
                 "chapter_index": null, "chapter_title": null,
                 "progress": null, "block": null, "segment": null}]}
```

The full `Highlight` dataclass is serialized generically (all fields), so the
cache is future-proof if Kindle later carries more locator data.

### 2. Reworked `convert(clippings_path: Path | None, output: Path) -> dict`

Two decoupled steps:

1. **Extract** (only when `clippings_path` is a real file): parse → group by
   `(norm_title, author_key)` → `to_highlights` per group → `save_book`
   (wholesale overwrite) for each group.
2. **Resolve** (always): `load_all` the cache → build a `(BookRef, highlights)`
   list from every record → `store.import_highlights(output, "kindle", ...)`,
   which resolves each `BookRef` against the catalog (match-only) and writes the
   matches.

Returns `{"books": int, "entries": int, "pending": int}` — `import_highlights`'
existing `skipped` count is surfaced as **pending**.

### 3. Detection & entry points (`command.py` + `import_cmd.py`)

- `_detect_kindle` (pipeline): source present when the clippings file exists
  **or** the cache dir contains any `*.json`. Label = the clippings path when
  present, else the cache dir.
- `run_import(vault, cfg)`: run `convert` when a clippings file **or** a
  non-empty cache exists; return empty stats only when both are absent. Passes
  `clippings_path=None` when the device file is absent (resolve-only run).
- Standalone `kindle_import`: runs from cache alone; errors only when an
  *explicit* `--clippings` path is missing, or when nothing (clippings + cache)
  exists to import.
- New `_summ_kindle(s)` summarizer: `"{books} books, {entries} highlights,
  {pending} pending"` (kindle no longer shares `_summ_highlights`).

### 4. Config, docs

- **Config:** unchanged. The cache dir is the canonical
  `Data/Imports/kindle/cache/` (no new keys), exactly like Audible.
- **Docs:** update the kindle mentions in `CLAUDE.md`; note the Audible-parallel
  cache and the pending/resolve-anytime behavior.

## Data flow

```
My Clippings.txt (device, optional)
      │ parse + dedup (per book)
      ▼
Data/Imports/kindle/cache/<stem>.json   ← wholesale overwrite
      │ load_all (every run)
      ▼
store.import_highlights(vault, "kindle", records)
      │ Catalog.find (match-only)
      ├─ matched  → Data/Highlights/<book_id>.csv   (books/entries)
      └─ no match → stays cached                     (pending)
```

## Testing (TDD)

- **`cache.py`:** JSON round-trip; `Highlight` serialize/deserialize (incl. note,
  tags/links, nulls); wholesale overwrite replaces a book's record; deterministic
  stem assignment; collision → stable numeric suffix.
- **`convert`:** extract-then-cache when clippings present; resolve-from-cache
  when the device is absent but a cache exists; `pending` count for unmatched;
  matched books written to `Data/Highlights/`; wholesale overwrite on re-parse.
- **`import_cmd`:** `_detect_kindle` true with a cache-only vault (no device);
  `_summ_kindle` renders the pending count.

## Out of scope

- Building catalog rows from highlight sources (rejected: pollutes the catalog
  with metadata-poor stubs).
- Note-based catalog construction from `Books/*.md`.
- Any change to kobo/highlighted/readwise or the merge contract.
