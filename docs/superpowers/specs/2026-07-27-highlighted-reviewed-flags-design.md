# Design: `highlighted` / `reviewed` book-note flags

## Goal

Add two boolean frontmatter properties to every book note so the vault can be
filtered on reading progress:

- `highlighted` — the book note has an imported `## Highlights` section.
- `reviewed` — the book note has a `## Review` section.

Primary use case: filter in Obsidian Bases/Dataview for books *with* highlights
(and the inverse — books still missing highlights). Both flags are always
emitted as native YAML booleans (`true`/`false`) so two-way filtering works
symmetrically; an absent value would break `... is false` filters.

## Schema changes (`books/obsidian.py`)

1. Add `highlighted` and `reviewed` to `BOOK_PROPERTY_ORDER`, positioned
   immediately after `status` (the reading-state cluster).
2. Add a module-level exemption set:

   ```python
   OVERWRITE_KEYS = frozenset({"highlighted", "reviewed"})
   ```

   These keys are exempt from the "never overwrite" rule.
3. Add default constants for reuse by writers:

   ```python
   BOOK_FLAG_DEFAULTS = {"highlighted": "false", "reviewed": "false"}
   ```

## `update_frontmatter` behavior change

Current rule: only blank/absent keys are filled. New rule:

- For a key in `OVERWRITE_KEYS`, a **non-empty** update replaces the existing
  value even when it is already set (so `false` → `true`).
- All other keys keep the existing never-overwrite behavior, unchanged.
- Importers only ever pass `true` for these keys, so a flag never regresses
  `true` → `false`. A `false` default only ever lands via the append-absent
  path, which cannot downgrade an already-present `true`.

Implementation: in the "fill blanks in place" loop, treat an `OVERWRITE_KEYS`
key with a non-empty update as always-writable (set it regardless of whether the
existing value is blank).

## Where the flags are written

**Defaults (`false`), added-if-absent:**
- `VaultIndex.find_or_create` stub creation — every new book note carries both
  flags from birth.
- `calibre_obsidian._calibre_updates` and `goodreads_obsidian._goodreads_updates`
  (or their update dicts) include `BOOK_FLAG_DEFAULTS` — these importers re-scan
  the whole library, so pre-existing notes backfill both keys on the next sync.

**Flip to `true`:**
- `kobo_export`, `highlighted_obsidian`, `readwise_obsidian`: add
  `"highlighted": "true"` to the frontmatter update dict written just before
  `render_marked_section(..., "Highlights", ...)`. (These already write
  frontmatter then the highlights section.)
- `goodreads_obsidian.convert`: when a review is actually written
  (`ensure_section` changed the text, i.e. `stats["reviews"]` increments), set
  `reviewed: true`. Because `ensure_section` runs after the first
  `update_frontmatter`, add a second `update_frontmatter(text, {"reviewed":
  "true"})` on the review-written branch (the `OVERWRITE_KEYS` rule flips the
  default `false`).

## Order independence

- Calibre runs before highlights import: sets `highlighted: false`; later the
  highlight importer flips it to `true` via the overwrite rule.
- Highlights import runs before calibre: sets `highlighted: true`; calibre's
  `false` default is append-absent only and cannot downgrade the present `true`.

Both orders converge to the same result. Same for `reviewed` with goodreads.

## Testing

`tests/` (mirroring existing per-module test files):

- `update_frontmatter`:
  - overwrite-key with non-empty update flips an existing `false` → `true`.
  - overwrite-key does **not** downgrade an existing `true` when the update is a
    `false` default arriving via append-absent (i.e. key already present).
  - non-overwrite keys still never overwrite an existing value.
  - absent overwrite-key with a `false` default gets appended as `false`.
- Importers (one assertion each): after import, the book note frontmatter shows
  `highlighted: true` (kobo/highlighted/readwise) and `reviewed: true`
  (goodreads with a review); a new stub shows both defaults `false`.

## Out of scope

- No highlight/review counts (booleans only).
- No migration script; existing notes backfill naturally on next sync.
- No changes to the highlight/review rendering itself.
