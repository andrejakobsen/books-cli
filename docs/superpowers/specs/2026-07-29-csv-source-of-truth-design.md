# CSV as the source of truth

**Date:** 2026-07-29
**Status:** Design approved, pending spec review

## Motivation

Today every importer writes **directly** into Obsidian markdown — book identity,
metadata, and highlights all live only in the note (frontmatter + a marker-wrapped
`## Highlights` section). The markdown *is* the store. That couples the durable data to
one tool's formatting and makes re-rendering, exporting, or migrating to another format
a markdown-parsing exercise.

This design introduces a **canonical CSV layer** as the durable, tool-agnostic source of
truth for book **metadata** and **highlights**. Obsidian becomes *one renderer among
potentially many* (a future JSON/HTML/Anki renderer is purely additive). CSV is chosen
deliberately over a database file: plain text is hand-editable, git-diffable, and
portable — a binary `.db` would work against the durability goal.

## Scope

**In scope:** book metadata + highlights move to CSV; a new merge step; a new Obsidian
renderer; importers become CSV writers; `sync` becomes a two-phase pipeline.

**Out of scope (unchanged behavior):** personal `Notes/` remain fully manual;
the `covers` image-fetching logic itself; the `#tag`/`@link` convention and highlight
rendering in `highlights.py` (reused as-is).

## Key decisions

1. **On-disk truth = plain CSV** (not SQLite/DuckDB). DuckDB may be added *later* purely
   as an ad-hoc query surface over the CSVs; it never becomes the store.
2. **Merge engine = custom Python** (the fuzzy clustering is custom regardless; data is
   small — hundreds to low-thousands of books).
3. **Precedence merge replaces "first-writer-wins."** Each field is filled from the
   highest-precedence source that has a non-blank value. Order-independent and
   re-run-safe.
4. **No manual-edit capture / no read-back.** The only hand-edited field is `topics`,
   which is **100% user-owned**: no importer and no render ever writes it.
5. **`review` is stored in CSV** (sourced by Goodreads) and rendered **write-once** into
   `## Review`.

## Storage layout

Everything lives under `<vault>/Data/` (a visible folder):

```
Data/
  sources/                 # raw per-source metadata layers (internal storage)
    calibre.csv
    goodreads.csv
    covers.csv
    audible.csv
  books.csv                # DERIVED: one merged row per book (the catalog)
  Highlights/
    <book-id>.csv          # per book; union of all highlight sources
```

- **`book-id` = the existing note stem `<Title> - <Author>`** (with the same
  subtitle-drop and collision handling as `VaultIndex._new_note_path`/`strip_subtitle`),
  keeping `books.csv` ↔ `Books/` ↔ `Covers/` ↔ `Highlights/` in lockstep.
- **Metadata** uses per-source layers merged into the single `books.csv`.
- **Highlights** are a *union* across sources (no precedence — every highlight is kept),
  so the per-book `Data/Highlights/<book-id>.csv` is itself the storage. Each importer
  **replaces only its own `source=` rows** on re-run. There is no per-source highlight
  layer file.

## CSV schemas

Modeled with **pydantic** so the column set is enforced in one place and rows validate on
read/write.

### Metadata — shared by layers and `books.csv`

A source leaves unknown fields blank so the merge is uniform. `book_id` appears only in
the derived `books.csv`; layers omit it (re-running an importer rewrites its whole layer
file, so no cross-run id is needed there). List fields (`authors`, `shelves`) are
`;`-joined.

```
book_id*,          # derived books.csv only
title, authors, series, series_index, publisher, published, language,
format, pages, status, shelves, rating, isbn, amazon, google, goodreads,
uuid, calibre_id, date_added, date_read, review, cover
```

Changes vs today's `BOOK_PROPERTY_ORDER`:

- **`topics` is removed** — it is never sourced, merged, or rendered from data
  (100% user-owned in the note). Calibre stops mapping subjects → topics.
- **`highlighted` / `reviewed` are removed** — the renderer *derives* them from whether
  highlights / a review exist (retires the `OVERWRITE_KEYS` special case).
- **`review` is added** — durable review prose (from Goodreads).
- `type` is always `book`; the renderer sets it (not a CSV column).

### Highlights — per-book (`Data/Highlights/<book-id>.csv`)

Standardized and source-agnostic, mirroring the `Highlight` model. `tags`/`links` are
`;`-joined.

```
source,            # calibre? no — kobo | highlighted | readwise | audible
annotation_id,     # lets a source replace just its own rows on re-run
chapter_index, chapter_title,
location,          # the value, e.g. 42, 45-49, 3:24:15
location_kind,     # percent | page | kindle_loc | timestamp
block, segment,    # Kobo precision (sort + anchors)
date, text, note, tags, links
```

`location`/`location_kind` unify today's `progress`/`page`/timestamp handling;
`block`/`segment` are retained for Kobo's KoboSpan precision used by `sort_key` and
`build_anchors`.

## Merge & precedence

- **Importers just dump their rows** into their own layer CSV — they no longer match
  existing data or worry about overwriting. All cross-source matching is deferred to the
  merge.
- **`merge()`** (in `books/store.py`):
  1. **Cluster** rows across all layers into books, matching by **canonical ISBN**
     (`isbnlib`, ISBN-10↔13 normalized) → **`amazon`** id → **`author_key` + `norm_title`**
     with a **conservative `rapidfuzz` threshold** to tolerate minor title variation
     *without* wrongly merging distinct books. Matching normalization reuses
     `obsidian.py` (`author_key`, `norm_title`, `fold`).
  2. **Assign `book-id`** per cluster (note-stem scheme).
  3. **Coalesce** each field from the highest-precedence layer that has a non-blank
     value.
- **Precedence ladder** (low → high), general → specific:

  ```
  calibre / goodreads  <  covers  <  kobo / highlighted / readwise  <  audible
  ```

  e.g. `format` set by calibre/goodreads is overridden by `audible` (authoritative that
  it is an audiobook); a later re-run of goodreads never clobbers audible's value because
  precedence is a pure function of source, not of run order.
- The merge is **pure, deterministic, and order-independent**: the same layer files
  always produce the same `books.csv` regardless of the order importers ran.

## The Obsidian renderer

`books/render_obsidian.py` reads `books.csv` + per-book highlights and writes/updates
notes under `Books/`. It uses **python-frontmatter** + **ruamel.yaml** for robust
frontmatter read/write.

Per note:

- **Frontmatter** is written **authoritatively from `books.csv`** for every schema key,
  **except**:
  - **`topics`** — never written. On a brand-new note the renderer emits an empty
    `topics:` key (so it is present to hand-edit); on an existing note the current value
    is preserved verbatim. Never overwritten.
  - **`highlighted` / `reviewed`** — derived: `true` when the book has highlights / a
    review, else `false`.
- **Cover embed** — `![[Covers/<stem>.jpg|150]]` via existing `obsidian.py` helpers
  (`cover_refs`, `COVER_WIDTH`).
- **`## Review`** — **write-once** from the CSV `review` field (`ensure_section`); a
  hand-edited review is never clobbered.
- **`## Highlights`** — rendered from the per-book CSV via `highlights.render_highlights`
  into the marker-wrapped section (`render_marked_section`); last render wins, hand edits
  outside the markers survive.
  - **Source attribution when ambiguous:** when the per-book CSV contains highlights from
    **more than one distinct `source`**, the renderer groups the highlights by source and
    separates each group with a **small header** (e.g. `### Audible`, `### Highlighted`) —
    a lightweight divider, not a per-highlight label. Within each source group, the
    existing chapter subheaders and reading-order sort apply as usual. When all
    highlights share a single source (the common case), **no** source header is emitted,
    so single-source output is unchanged. `render_highlights` gains an optional
    per-highlight `source` and only surfaces the grouping when the caller passes a
    mixed-source set.
- Note body outside the managed sections is left untouched.

## Module & command changes

**New:**

- `books/store.py` — the CSV store: pydantic row models, layer read/write, `merge()`,
  `Catalog.find(ref)` over `books.csv` (identity lookup for highlight importers, reusing
  the ISBN/amazon/title-author matching), per-book highlight read/write (replace-by-source).
- `books/render_obsidian.py` — the renderer described above.

**Changed — importers become CSV writers (no markdown):**

- `calibre` → `sources/calibre.csv` (drops topics mapping).
- `goodreads` → `sources/goodreads.csv` (incl. `rating`, `review`, `goodreads` URL).
- `covers` → `sources/covers.csv` (still fetches images into `Covers/`; records `cover`
  path + learned `isbn`). Reads `books.csv` to find books with a blank cover.
- `kobo` / `highlighted` / `readwise` → per-book highlight CSVs via `Catalog.find`
  (unmatched books skipped + counted, as today).
- `audible` → `sources/audible.csv` (`format`, ASIN) **and** per-book highlight CSVs.

**`obsidian.py`** keeps its reusable helpers (frontmatter formatting primitives,
`wikilink`/`link_list`, section helpers, cover refs, matching normalization). `VaultIndex`'s
identity role moves into `store.py`; its create/markdown-write paths are retired.

**`sync` pipeline** (two-phase):

```
calibre + goodreads  →  merge  →  covers  →  audible(meta)  →  merge
                     →  kobo + highlighted + readwise + audible(clips)
                     →  render
```

Standalone `books merge` and `books render` commands also exist.

## Rollout & migration

- **One-time backfill (safety net):** parse each existing note's `## Highlights` markdown
  back into its per-book highlight CSV, so highlights from a no-longer-available export
  (old Readwise/Kobo dump) are not lost. Metadata is simply re-derived by re-running the
  importers.
- **`topics` and `## Review` are preserved for free:** the renderer never touches
  `topics` and treats `## Review` as write-once, so the first render over an existing
  note keeps them and refreshes everything else from the re-run sources.
- **Phased dual-write migration:** build `store.py` → build the renderer and validate
  against a *copy* of the vault → migrate importers one at a time (running alongside the
  old markdown path until render output matches) → flip `sync` to the new pipeline and
  delete the markdown-write paths.

## Dependencies

Runtime: **`pydantic`** (row models/validation), **`python-frontmatter`** +
**`ruamel.yaml`** (frontmatter I/O), **`rapidfuzz`** + **`isbnlib`** (matching). Dev:
**`ruff`** (lint/format — none exists today). The standalone `scripts/*.py` shims that
depend on stdlib-only modules stay working; modules that now require the new deps declare
them accordingly.

## Testing

- **Merge order-independence:** feeding the same layers in different orders yields an
  identical `books.csv`.
- **Fuzzy-clustering safety:** near-duplicate titles merge; genuinely distinct books do
  not (threshold guard).
- **Precedence:** `audible` overrides `format`; re-running a lower-precedence source does
  not clobber a higher one.
- **`book_id` collisions:** two same-stem books disambiguate (subtitle restore, then
  numeric suffix).
- **Highlights replace-by-source:** re-running one source replaces only its rows; other
  sources' highlights persist; union renders in reading order.
- **Source attribution:** a mixed-source book groups highlights by source under a small
  `### <Source>` header; a single-source book emits no source header (output unchanged).
- **Renderer:** idempotent re-render; `topics` never written/overwritten; `## Review`
  write-once; `highlighted`/`reviewed` derived correctly; note body outside managed
  sections preserved.
- Existing importer tests adapt to assert layer-CSV output instead of markdown.
```
