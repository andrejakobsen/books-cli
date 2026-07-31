# Kindle importer — design

**Date:** 2026-07-31
**Status:** Approved (design), pending implementation plan

## Overview

A new **Phase-B highlights importer** named `kindle` that ingests Kindle's
`My Clippings.txt` log. It parses the log, **deduplicates adjusted highlights**
(keeping only the latest version of a highlight that was resized/edited),
**attaches notes to their highlights**, resolves each book against the merged
catalog, and writes the results into the per-book highlights store
(`Data/Highlights/<book_id>.csv`, source `"kindle"`). Like kobo/highlighted/
readwise, it is a pure CSV/store writer — it never creates book notes; `export`
turns the store into notes.

It joins the **default sync-set** (runs with no flags when a `My Clippings.txt`
is present) and is also selectable via `books import --kindle` and the standalone
`books kindle` command.

## The `My Clippings.txt` format

Kindle appends one record per event to `My Clippings.txt`. Records are separated
by a line of exactly `==========`. Each record has four parts:

1. **Title line** — `Title (Author)`. Many titles are preceded by a per-record
   UTF-8 BOM (`﻿`) that must be stripped. The author is the **last**
   parenthesized group and may be in `"Last, First"` form.
2. **Metadata line** — begins with `- Your `, then the kind and locator:
   - `- Your Highlight at location 472-473 | Added on Friday, 31 July 2015 00:17:35`
   - `- Your Highlight on page 94-94 | Added on ...`
   - `- Your Highlight on page 157 | location 3043-3045 | Added on ...`
   - `- Your Note at location 364 | Added on ...`
   - `- Your Bookmark at location 11 | Added on ...`
3. **Blank line.**
4. **Text** — the highlighted/annotated text (empty for Bookmarks).

Entry-kind counts observed in the sample file: Highlight ≈ 4718, Note ≈ 565,
Bookmark ≈ 11.

## Module layout

A new **package** `books/commands/kindle/` (mirroring the `audible`/`covers`
precedent), because the parse + dedup + note-attachment logic is more than one
file should carry:

- `parser.py` — tokenize `My Clippings.txt` into raw `Entry` records (pure).
- `dedup.py` — deduplicate adjusted highlights + attach notes (pure, the novel
  logic; the most heavily tested module).
- `command.py` — `register(app)`, the `kindle` Typer command, `run_import(vault,
  cfg)`, device detection, and book grouping + catalog resolution.
- `__init__.py` — re-export the public API (`register`, `run_import`, `convert`).

*Alternative considered:* a single `kindle.py` file. Rejected — the dedup logic
deserves its own isolated, testable module.

## Parsing (`parser.py`)

Split the file on lines equal to `==========`. For each non-empty record, parse
the four parts into an `Entry`:

```
Entry(
    kind: str,            # "highlight" | "note" | "bookmark"
    title: str,           # BOM stripped
    author: str,          # may be "Last, First"
    page: str | None,     # display page range, e.g. "94-94" (when present)
    location: str | None, # display location range, e.g. "472-473" (when present)
    loc_start: int | None,# numeric range start used for dedup + sorting
    loc_end: int | None,  # numeric range end
    added: datetime | None,
    text: str,
)
```

- **BOM:** strip a leading `﻿` from the title line.
- **Author:** last parenthesized group of the title line.
- **Kind:** parsed from `Your <Kind>` (case-insensitive) → lowercased.
- **Locator:** capture `page` and/or `location` independently. The numeric
  `loc_start`/`loc_end` range is derived from **`location` if present, else
  `page`** (location is the finest-grained, ebook-native position and is what we
  dedup/overlap on). A single value like `location 364` yields
  `loc_start == loc_end == 364`.
- **Date:** parse `Added on <Weekday>, <D Month YYYY> <HH:MM:SS>` using a **fixed
  English weekday/month-name map** (locale-independent — do NOT rely on
  `strptime` `%A`/`%B`, which are locale-dependent). Unparseable → `added = None`.
- **Text:** the remaining lines joined; may be empty (Bookmarks).

Malformed records (missing metadata line, unrecognizable locator) are skipped
defensively rather than crashing the whole import.

## Dedup + note attachment (`dedup.py`) — the core

Operates per book, on that book's `Entry` list:

1. **Split** into highlights / notes / bookmarks. **Drop bookmarks** (no text).
2. **Dedup highlights.** Sort by `(loc_start, loc_end)` (entries missing a
   numeric range sort last and are never merged). Cluster **consecutive** entries
   whose ranges **overlap**, where `overlap(a, b)` is true when:
   - they share a start (`a.loc_start == b.loc_start`), **or**
   - they share an end (`a.loc_end == b.loc_end`), **or**
   - one range's endpoint falls inside the other
     (`a.loc_start <= b.loc_start <= a.loc_end` or the symmetric case).

   Clustering is a single left-to-right walk that extends the running cluster
   while the next entry overlaps the cluster's covered range. From each cluster,
   **keep the entry with the latest `added`** timestamp (tie → the one later in
   file order; `added is None` sorts oldest). This collapses "adjusted highlight"
   event chains to their final version. Non-overlapping highlights are kept
   separately.
3. **Dedup notes** using the same overlap rule (edited notes also re-log
   multiple events; keep the latest).
4. **Attach notes.** Each surviving note attaches to the surviving **highlight**
   whose range overlaps/contains it (nearest by `loc_start` on ties) → sets that
   `Highlight.note`. A note that matches **no** highlight becomes a **standalone
   text-less `Highlight` carrying the note** (per the "attach notes to
   highlights" decision).

Output: a list of source-agnostic `Highlight`s for the book, ready for the store.

## Book resolution & store write (`command.py`)

- **Group** entries by `(norm_title, author_key)` — Kindle provides no
  ISBN/Amazon id, so identity is title+author only (normalization from
  `books/core/matching.py`).
- Build one `BookRef(title=<clean title>, authors=[author])` per group.
- Map each surviving `Entry` → `Highlight`:
  - `text` = entry text (empty for standalone notes),
  - `note` = attached note (if any),
  - `page` = the display range (location range when location-based, else page
    range),
  - `location_label` = `"loc."` for location-based entries, `None` (default
    `"p."`) for page-based entries,
  - `date` = ISO-formatted `added` (or `None`),
  - `source = "kindle"`.
- Resolve + write via `store.import_highlights(vault, "kindle", resolved)`
  (custom cross-row grouping means we bypass `group_and_import`'s per-row path).
  Books with no catalog match are **skipped and counted**, so `merge` must run
  first (guaranteed by the pipeline). Returns `{"books", "entries", "skipped"}`.

Rendering is unaffected: no chapter titles → flat `## Highlights` output, sorted
by the numeric leading value of `page` (via the existing `sort_key`).

## Config & wiring

- Add `"kindle"` to `DEFAULT_IMPORTERS` in `books/core/config.py`.
- Canonical imports subfolder: `Data/Imports/kindle/My Clippings.txt`.
- Optional `[kindle]` config section with a `clippings` path override (empty =
  auto-detect). Add a `KindleConfig` dataclass + parsing alongside the existing
  per-importer config sections.
- **Device detection:** glob `/Volumes/*/documents/My Clippings.txt` (robust to
  whatever the Kindle volume is named) and use the first match; otherwise fall
  back to `Data/Imports/kindle/My Clippings.txt`. An explicit `--clippings` /
  `[kindle].clippings` always wins.
- **`import_cmd.py`:** add `"kindle"` to `_CONSUMERS`; add `_detect_kindle`
  (mounted device or canonical file present) and `_run_kindle`; add a `Step`
  entry; extend the highlights-phase tuple `("kobo", "highlighted", "readwise")`
  to include `"kindle"`; add a `--kindle` selector flag.

## CLI

- `books kindle [--clippings PATH] [--output VAULT]` — standalone importer,
  mirroring `books readwise`.
- `books import --kindle` — select just this importer; runs by default in the
  no-flag sync-set when a source is detected.

## Testing (TDD)

- **`parser`:** multi-record split; BOM strip; all three location formats
  (`location`, `page`, `page + location`); each kind (highlight/note/bookmark);
  date parsing (and unparseable → `None`); empty-text records; malformed record
  skipped.
- **`dedup`:** overlap variants (same start / same end / contained / adjacent
  non-overlapping kept separate); latest-timestamp wins; timestamp tie → file
  order; note dedup; note attached to overlapping highlight; standalone note →
  text-less highlight-with-note; bookmarks dropped.
- **`command` (integration):** end-to-end into the store against a merged
  catalog — book resolution, entry counts, and the skipped-when-unmatched count.

## Out of scope (YAGNI)

- No chapter/section inference (Kindle clippings carry none).
- No Amazon/ISBN enrichment from Kindle (identity is title+author only).
- No cross-device merge beyond reading a single `My Clippings.txt`.
