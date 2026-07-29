# Importers become CSV writers (Plan C, core five)

**Date:** 2026-07-29
**Status:** Design approved, pending spec review
**Design reference:** `docs/superpowers/specs/2026-07-29-csv-source-of-truth-design.md`
(this realizes that spec's "importers become CSV writers" + "`sync` two-phase" scope,
explicitly deferred in `docs/superpowers/plans/2026-07-29-obsidian-renderer-plan-b.md`).

## Motivation

Plan A built the CSV store (`books/core/store.py`) and Plan B built the `render`
command (`books/commands/render.py`). But the two form a **disconnected pipeline**:
all six importers (`calibre`, `goodreads`, `kobo`, `highlighted`, `readwise`, `audible`)
still write markdown **directly** into the vault via `VaultIndex`, and nothing writes the
store. The store is orphaned — `render` is its only consumer and has no upstream.

This plan connects them for the **core five** importers: they stop knowing about Obsidian
and instead write the CSV store, which `merge` + `render` turn into notes. Obsidian
knowledge collapses into `render` alone.

## Scope

**In scope:** convert `calibre`, `goodreads`, `kobo`, `highlighted`, `readwise` into pure
store writers; add a standalone `books merge` command; rewrite `sync` as a two-phase
pipeline that auto-runs `merge` + `render`; move calibre's local-cover handling to a
stage-then-materialize flow; have `render` create `Authors/` stubs.

**Out of scope (later follow-up):** converting `covers` and `audible` to CSV writers
(they keep their current markdown path this pass); fully retiring `VaultIndex` and its
markdown-write path (still used by covers/audible); any migration/backfill (the target
vault is disposable/regenerable — see Decisions).

## Decisions (locked in with the user)

1. **Vault is disposable — no migration/backfill.** The vault is regenerated from raw
   imports. No code parses existing markdown back into CSV. Clean big-bang cutover.
2. **Core five only.** `covers` + `audible` stay on the markdown path this pass. This is
   safe: `render` only rewrites the `## Highlights` region when the store actually has
   rows, and derives the cover from the image file on disk — so the deferred two are not
   clobbered by a render.
3. **Command surface.** Add a standalone `books merge`; `render` already exists; `sync`
   auto-runs the full two-phase pipeline (importers → merge → highlight importers →
   render).
4. **Goodreads: emit all shelves, note everything.** Goodreads writes a layer row for
   every shelf (recording `shelves`); `books.csv` becomes the whole library and `render`
   writes a note per row. This *changes today's behavior* (to-read books now get notes)
   and removes all shelf-gating / `find_or_create` logic.
5. **Calibre covers: stage + materialize in render.** Calibre copies each local cover to
   a staging dir and records the staged path in its layer row; `render` copies the winning
   row's staged cover to `Data/Covers/<book_id>.jpg` after merge, then the existing cover
   embed logic runs unchanged. Keeps calibre a pure CSV writer and keeps all `book_id`
   knowledge in `render`.
6. **Hub stubs.** `Topics/` stubs are dropped (topics are no longer sourced from data;
   they are 100% user-owned). `Authors/` stubs are created by `render` from `books.csv`
   authors, preserving today's graph hubs.

## Architecture — the two-phase pipeline

```
Phase A (metadata):
    calibre    → Data/Sources/calibre.csv
    goodreads  → Data/Sources/goodreads.csv
    merge      → Data/books.csv           (cluster + assign book_id)

Phase B (highlights):
    kobo / highlighted / readwise
               → Data/Highlights/<book_id>.csv   (resolved via Catalog.find)
    render     → Books/*.md                        (+ Data/Covers/*, Authors/*)
```

The highlight importers require `books.csv` to exist (they resolve a book to a `book_id`
via `store.Catalog.find`), exactly as today's highlight importers require book notes to
exist first — the contract is unchanged, only the backing store differs. Run standalone,
a highlight importer errors/skip-counts cleanly if no `books.csv` is present yet.

## Per-importer conversion

Each importer keeps its parsing logic and its core function name/signature (so `sync` and
existing call sites stay stable); only the **sink** changes and the return-stat dict stays
compatible.

### calibre — `convert(library, output) -> dict`

- Parse `metadata.opf` into the existing `BookMetadata` (unchanged).
- Build a `store.BookRow` per book and accumulate; `store.write_layer(vault, "calibre", rows)`.
- **Drops:** the `source`, `highlighted`, `reviewed` fields (retired from the store
  schema) and the subjects→`topics` mapping (topics are user-owned).
- **Covers:** copy each `cover.jpg` to a staging path
  `Data/Sources/_covers/calibre/<n>.jpg` and set `BookRow.cover` to that path (a marker
  render recognizes). No writing to `Data/Covers/` here.
- **No** `VaultIndex`, no note creation, no `Authors/`/`Topics/` stubs.
- `description` (currently placed in the note body) has no store column; it is dropped
  this pass (calibre descriptions were body prose, not frontmatter — acceptable for the
  disposable-vault cutover; can be revisited if wanted).

### goodreads — `convert(csv_path, output, shelf=...) -> dict`

- Parse the CSV; build a `store.BookRow` for **every** row/shelf (record `shelves`,
  `rating` numeric, `review`, `goodreads` URL, and the other mapped fields).
- `store.write_layer(vault, "goodreads", rows)`.
- The `--shelf` option is retained but no longer gates note creation (kept for
  compatibility / future filtering); document that all shelves are emitted.
- **No** `find`/`find_or_create`, no write-once `## Review` handling (render owns that).

### kobo / highlighted / readwise — signatures unchanged

- Parse into the existing `Highlight` objects (unchanged parsing + `#tag`/`@link`).
- Resolve each book to a `book_id` via `store.Catalog(vault).find(ref)`; **unmatched
  books skipped + counted**, exactly as today.
- Convert with `store.highlight_to_row(h, source, annotation_id)` and write via
  `store.write_highlights(vault, book_id, source, rows)` — which replaces only that
  source's rows for the book, so re-runs are clean and other sources persist.
- `annotation_id`: use the source's stable id where available (Kobo bookmark id);
  otherwise synthesize a deterministic per-run id (e.g. index). Because
  `write_highlights` replaces by-source wholesale, the id need only be unique within the
  source's rows for a book.
- Any metadata these sources used to fill (e.g. readwise's `amazon`/`series`) is out of
  scope for this pass unless it already flows through the highlight path; highlight
  importers write highlights only. (Metadata enrichment from these sources can be added
  later as their own thin layer CSVs.)

## Cover staging + materialize-in-render

- **Stage (calibre):** `Data/Sources/_covers/calibre/<n>.jpg`; the layer row's `cover`
  column holds this staged path.
- **Materialize (render):** for a merged row whose `cover` points at an existing staged
  file, if `Data/Covers/<book_id>.jpg` does not exist, copy the staged file there. Then
  the existing `_cover_value` / `ensure_top_embed` logic in `render` emits the
  `cover:` frontmatter + `![[Data/Covers/<book_id>.jpg|150]]` embed unchanged.
- Idempotent: the copy is skipped once the destination exists; render-twice is identical.

## Author stubs in render

`render` creates `Authors/<name>.md` stubs (via the existing `write_stub`) for every
distinct author across `books.csv`, preserving the graph hubs calibre/goodreads used to
create. `Topics/` stubs are not created.

## `merge` command + `sync` rewrite

- **`books merge`** — new capability module `books/commands/merge.py` (exposing
  `register(app)`, added to `CAPABILITIES` in `books/cli.py`) that calls
  `store.merge(vault)` and prints cluster/book counts. `--output` overrides the vault.
- **`sync`** — rewritten to the two-phase pipeline: calibre + goodreads → `store.merge` →
  kobo + highlighted + readwise → `render`. Keeps its current continue-on-error behavior,
  colored per-step + summary report, per-source detection/skip, and `--dry-run` (now
  showing the phased plan). Each step calls the module core function directly (no
  shelling out), as today.

## Module changes summary

**Changed → CSV writers (no markdown):**
`books/commands/{calibre,goodreads,kobo,highlighted,readwise}.py`.

**Changed:** `books/commands/render.py` — add staged-cover materialization + `Authors/`
stub creation. `books/commands/sync.py` — two-phase pipeline.

**New:** a `merge` capability registered in `books/cli.py`.

**Unchanged this pass:** `books/commands/covers/`, `books/commands/audible/`,
`books/renderers/obsidian/vault_index.py` (still used by covers/audible), all reusable
obsidian helpers, and `books/core/store.py` (already provides `write_layer`,
`write_highlights`, `highlight_to_row`, `Catalog.find`, `merge`).

## Testing

- **Per importer:** assert the written **layer CSV** (calibre/goodreads) or **highlights
  CSV** (kobo/highlighted/readwise) contents — replacing today's markdown assertions.
- **Highlight importers:** an unmatched book is skipped + counted; re-running one source
  replaces only its own rows and leaves other sources' highlights intact.
- **Cover staging:** calibre stages the image + records the staged path; `render`
  materializes it to `Data/Covers/<book_id>.jpg` and emits the embed; render-twice is
  byte-identical.
- **Author stubs:** `render` creates `Authors/<name>.md` for each author; no `Topics/`
  stubs are created.
- **`sync`:** end-to-end on a temp vault (fixtures for a small calibre library +
  goodreads/kobo/etc. exports) produces rendered notes; a missing source skips its step;
  failures are reported but do not stop later steps.
- **Reuse:** the store's existing merge / precedence / clustering tests are unaffected.
- Existing markdown-path importer tests are rewritten to the store assertions above.

## Deliberate behavior changes (vs. today)

1. **Every Goodreads shelf becomes a note** (to-read books now get notes). Previously
   only read/currently-reading created notes.
2. **`Topics/` hub stubs disappear** (topics no longer sourced from data).
3. **Calibre book descriptions are no longer written to the note body** (no store column
   for body prose this pass).

Everything else is behavior-preserving.
