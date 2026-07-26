# Readwise → Obsidian importer — design

**Date:** 2026-07-25
**Status:** Approved (ready for implementation planning)

## Goal

Add a `readwise` capability that reads a Readwise CSV export and writes the
highlights into an Obsidian vault in exactly the same shape as the existing
`highlighted` importer: a per-book `Highlights.md` (rendered by the shared
`booktools/highlights.py`) written under `Exports/<Author>/<Title>/` and embedded
into the flat book note under a `## Highlights` heading, with frontmatter filled
under the "never overwrite" rule.

## Input format

Readwise CSV header:

```
Highlight, Book Title, Book Author, Amazon Book ID, Note, Color, Tags,
Location Type, Location, Highlighted at, Document tags
```

- `Location Type` is one of `page`, `location` (Kindle), or `order`.
- `Tags` is comma-separated, per-highlight.
- `Document tags` is comma-separated, book-level.
- `Book Title` may carry a trailing series suffix, e.g. `... (Stalin #1)`.
- There is no ISBN column.

## Architecture

A new capability module `booktools/readwise_obsidian.py`, following the exact
pattern of `booktools/highlighted_obsidian.py`:

1. `parse_csv(path)` — `csv.DictReader`, `utf-8-sig`.
2. Group rows by book, preserving CSV order. Grouping key: Amazon Book ID when
   present, else the standardized title (see below).
3. For each book: `VaultIndex.find_or_create(BookRef(...))`, then
   `update_frontmatter` to fill only empty/absent keys, then
   `write_leaf_with_embed(..., with_source("readwise", render_highlights(...)),
   "Highlights")`, then `write_stub` for the author.
4. `register(app)` attaches an `@app.command("readwise")`; add the module to
   `CAPABILITIES` in `booktools/cli.py`.
5. `scripts/readwise_obsidian.py` shim that imports and calls `main()`, matching
   the other capabilities.

**CLI:** `books readwise --csv data/readwise-data.csv --output Obsidian` — same
options, defaults, and messages as `highlighted`/`goodreads` (`--csv/-c`
required, `--output/-o` default `Obsidian`).

## Column mapping

| Readwise column   | Destination                                             |
|-------------------|---------------------------------------------------------|
| `Highlight`       | `Highlight.text`                                        |
| `Note`            | `Highlight.note`                                        |
| `Tags`            | per-highlight inline `#tags` (comma-split, `sanitize_tag`, dedup) |
| `Highlighted at`  | `Highlight.date`                                        |
| `Location` + `Location Type` | see "Type-aware location"                    |
| `Book Title`      | note title (standardized — see "Title standardization") |
| `Book Author`     | `authors` frontmatter + author stub                     |
| `Amazon Book ID`  | `amazon:` frontmatter + match key                       |
| `Document tags`   | `shelves:` frontmatter (comma-split → `plain_list`)     |
| `Color`           | ignored                                                 |

Frontmatter written via `update_frontmatter` (never overwrites non-empty values):
`title`, `authors`, `amazon`, `shelves`, `series`, `series_index`, and
`source: readwise`.

## Type-aware location

Extend the shared `Highlight` model (`booktools/highlights.py`) with one new
optional field:

```python
location_label: str | None = None  # display prefix for `page`; defaults to "p." when None
```

`_label()` uses `h.location_label or "p."` as the prefix when `h.page` is set.
This is additive and backward-compatible: Kobo and Highlighted pass no
`location_label`, so they keep rendering `p. N` exactly as before. Anchors are
unaffected (`build_anchors` keeps its internal `p<page>` id).

The Readwise importer infers from `Location Type`:

- `page`     → `page = Location`, `location_label = None`  → renders `p. 3`
- `location` → `page = Location`, `location_label = "loc."` → renders `loc. 123`
- `order`    → no location recorded (`page = None`) → generic `hl<n>` anchor, no label

## Title standardization + cross-source matching

Parse a trailing `(<Series> #<N>)` (N may be `1` or `1.5`) off the `Book Title`:

- note/matching title → the title with the suffix removed and whitespace
  trimmed, e.g. `Stalin: Volume I: Paradoxes of Power, 1878-1928`
- `series:` → `Stalin`
- `series_index:` → `1`

If no suffix is present, the title is used verbatim and series fields stay empty.

Matching to existing notes (there is no ISBN):

1. **Amazon Book ID** — extend `BookRef`, `build_index`, and `VaultIndex._match`
   / `_register` to index and match on a normalized Amazon id (additive; other
   importers pass no amazon id and are unaffected). This lets a Readwise book
   merge into a Calibre/Goodreads note that already carries the same `amazon`
   value.
2. **Standardized title + author** — the existing `norm_title` / `author_key`
   match, now using the series-stripped title so it lines up with the clean
   title a Calibre/Goodreads note already has.

## Testing

`tests/test_readwise.py` (mirroring `test_highlighted_obsidian.py`), covering:

- series suffix parsing (with suffix, without suffix, decimal index)
- the three `Location Type` values → correct label / no label
- `Tags` splitting + dedup into inline `#tags`
- `Document tags` → `shelves` frontmatter
- `amazon` fill and amazon-based matching into an existing note
- title/author matching into an existing note via the stripped title
- a full `convert` round-trip asserting the highlight text reaches the written
  `Highlights.md` and the note embeds it under `## Highlights`

Plus a small addition to `tests/test_highlights.py` asserting `location_label`
renders `loc. N` and that the default still renders `p. N`.

## Out of scope

- Non-book Readwise documents (articles, tweets, podcasts) — the importer treats
  every row as a book, consistent with the other importers.
- Splitting a multi-author `Book Author` string (Readwise supplies a single
  author field; kept as one author).
- `Color` grouping/labels.
