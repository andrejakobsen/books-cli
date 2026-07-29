# covers & audible become CSV writers (retire VaultIndex)

**Date:** 2026-07-29
**Status:** Design approved, pending spec review
**Supersedes:** `docs/superpowers/specs/2026-07-29-covers-audible-to-csv-followup.md`
(the deferred follow-up note — this is its implementation-ready design)
**Design reference:** `docs/superpowers/specs/2026-07-29-importers-to-csv-writers-design.md`
(the "core five" pass this completes)

## Motivation

The core-five pass turned `calibre`/`goodreads`/`kobo`/`highlighted`/`readwise`
into pure CSV writers; `merge` + `render` own all Obsidian output. Two capabilities
still write markdown directly through `VaultIndex`: `covers` (fills a note's `cover:`
frontmatter/embed) and `audible` (enriches a note with `format: audiobook` + a
`## Highlights` section). This pass converts both onto the store so `render` becomes
the **sole** producer of Obsidian notes and `VaultIndex` can be deleted.

## Key facts that shape the design

1. **`render` already derives the cover from disk.** `render._cover_value` emits the
   `cover:` frontmatter + `![[Data/Covers/<book_id>.jpg|150]]` embed iff the on-disk
   file `Data/Covers/<book_id>.jpg` exists — nothing in `books.csv` is required for the
   *image* itself. Only extra *metadata* (covers' learned `isbn`, audible's `format`)
   must flow through `books.csv`, which means a `merge` must fold it in.
2. **`covers` + `audible` need `books.csv` to operate** (covers scans it for cover-less
   books; audible resolves each book to a `book_id` via `store.Catalog.find`). So both
   run *after* an initial `merge`, write layers/highlights, and a subsequent `merge`
   folds their metadata in before `render`.
3. **`book_id` assignment is deterministic.** `store.merge` sorts clusters by
   `(clean_stem, full_title, isbn, amazon, series_index)` and assigns
   `book_id = <Title> - <Author>` via the `next_free_stem` collision ladder. For a book
   with a **unique** clean stem, `book_id` is invariant under added metadata layers.

## Decisions (locked in with the user)

1. **covers cover-file strategy: stage + materialize, like calibre.** `covers` stages
   the fetched image under `Data/Sources/_covers/covers/<n>.jpg` and writes a `covers`
   layer CSV carrying identity + learned `isbn` + the staged path; `merge` folds it in
   and `render` materializes it to `Data/Covers/<book_id>.jpg`. Consistent with calibre,
   reuses the tested materialize path, and `covers` already sits in `PRECEDENCE`.
2. **Re-merge book_id churn: accept + document.** A second `merge` (after covers/audible)
   re-assigns `book_id`s deterministically. For the narrow case of two books sharing a
   clean stem `<Title> - <Author>` (e.g. same-base-title series volumes), a newly-learned
   `isbn`/`amazon` can flip the sort tiebreak and reassign which collider gets the bare
   stem — orphaning highlights already written under the old id. This is accepted (narrow;
   the vault is disposable/regenerable) and documented. Future option: make `merge` carry
   existing `book_id`s forward for unchanged clusters (out of scope here).
3. **`sync` inclusion: neither, by default.** `covers` (external cover APIs → slow /
   rate-limitable) and `audible` (cloud auth + ffmpeg + full-audiobook downloads) both
   stay **manual**, matching today's covers exclusion and audible's heaviness. `sync`
   is unchanged. Run manually, they write against an existing `books.csv`; the user
   re-runs `merge` + `render` (or `sync`) to fold in their metadata. This ordering is
   documented in each command's help + CLAUDE.md.
4. **Retire `VaultIndex`.** Once both are converted it has no callers → delete
   `books/renderers/obsidian/vault_index.py` and drop its re-exports.

## covers — conversion

Signature-stable where possible: keep `run(...)` returning a compatible stats dict.

- **Read from the store.** Iterate `store.read_books_csv(vault)` and select rows whose
  `cover` is blank **and** which have no on-disk `Data/Covers/<book_id>.jpg` (the disk
  check keeps re-runs idempotent before a re-merge folds the cover back in). Replace
  `find_missing`/`note_to_missing` (which scanned notes) with a store scan; build the
  existing `MissingBook` from each row (title, `authors`, `isbn`, `amazon`) and carry its
  `book_id`.
- **Fetch unchanged.** `sources.py` (`iter_candidates`, per-provider lookups, lazy error
  accounting) and `images.py` (retry/backoff, dimension validation) are **untouched**.
  `pick_cover` is unchanged.
- **Sink = a `covers` layer + staged image.** Replace `apply_cover` (which wrote note
  frontmatter) with: stage the winning image bytes to `Data/Sources/_covers/covers/<n>.jpg`
  (fresh dir each run, like calibre) and accumulate a `store.BookRow` carrying identity
  (title/authors/isbn/amazon from the source row, so `merge` clusters it onto the right
  book), the **learned isbn** (from the candidate), and `cover` = the staged vault-relative
  path. Write all rows via `store.write_layer(vault, "covers", rows)`.
- **Drop** every `books.renderers.obsidian` import (`VaultIndex`, `cover_path`,
  `cover_refs`, `ensure_top_embed`, `update_frontmatter`, `frontmatter_values`, etc.).
- **CLI:** `--interactive` / `--dry-run` / `--limit` keep their meaning. `--book` targets
  a single book by `book_id` (resolved against `books.csv`) instead of a note path;
  interactive by default as today. The command errors cleanly if no `books.csv` exists.

## audible — conversion

Keep the entire heavy pipeline; change only the sink and the identity lookup.

- **Resolve via the catalog.** Replace `VaultIndex.find(ref)` with
  `store.Catalog(vault).find(BookRef(title=book.title, authors=book.authors, amazon=book.asin))`
  → `book_id` (ISBN → Amazon → title/author). Unmatched books skipped + counted (unchanged
  enrich-only contract). Errors cleanly / skip-counts if no `books.csv` yet.
- **Sink 1 — highlights.** For each matched book, build highlights from cached clips via
  the existing `record_to_highlight`, map with `store.highlight_to_row(h, "audible", ann.id)`
  (the stable Audible annotation id as `annotation_id`), and write via
  `store.write_highlights(vault, book_id, "audible", rows)` (replace-by-source ⇒ clean
  re-runs, other sources preserved). Empty-text records dropped as today.
- **Sink 2 — metadata layer.** Accumulate a `store.BookRow` per matched book carrying
  `format="audiobook"`, `amazon`=ASIN, and `title`/`authors` (for clustering); write via
  `store.write_layer(vault, "audible", rows)`. `audible` is last in `PRECEDENCE`, so it
  only fills a blank `format` — never overriding calibre/goodreads.
- **Unchanged:** auth (`AudibleClient`), library/annotations/chapters fetch, ffmpeg
  cut+decrypt, transcription backends, and the `Data/Imports/audible/cache.json` cache
  (keyed by ASIN + annotation id) — so re-runs still only download books with new clips.
  The `[audible]` optional extra and lazy imports are untouched.
- **Drop** `VaultIndex`, `render_note`, `render_marked_section`, `update_frontmatter`,
  `link_list`, `write_stub`, and author-stub creation — `render` now owns frontmatter,
  the `## Highlights` section, author stubs, and the `highlighted` flag.

## Manual run ordering (documented in help + CLAUDE.md)

Both are post-merge, metadata-then-remerge steps:

```
merge            # build/refresh Data/books.csv
covers           # scan books.csv → Data/Sources/covers.csv (+ staged images)
audible          # Catalog.find → Data/Highlights/<id>.csv (audible) + Data/Sources/audible.csv
merge            # fold covers/audible metadata into books.csv
render           # materialize covers, emit format:audiobook, write notes
```

`render` alone (no re-merge) still surfaces the **cover image** (derived from the
materialized on-disk file) and the **audible highlights** (read per-book by id); the
second `merge` is only needed to surface the learned `isbn` and `format: audiobook`
frontmatter.

## VaultIndex retirement

After both conversions, `grep` confirms `VaultIndex` has no importer. Delete
`books/renderers/obsidian/vault_index.py`; remove `VaultIndex` and `BookNote` from
`books/renderers/obsidian/__init__.py` imports and `__all__`. `write_stub` /
`write_if_absent` (in `layout.py`) stay — `render` uses them. `render` is then the only
producer of Obsidian notes.

## Testing (TDD)

- **covers:** a `books.csv` row with a blank cover and no on-disk file → a staged image
  under `Data/Sources/_covers/covers/` + a `covers.csv` row carrying the staged path and
  learned isbn; a row that already has a cover value **or** an on-disk
  `Data/Covers/<book_id>.jpg` is skipped (idempotent re-run). Then `merge` folds the
  cover/isbn into the merged row and `render` materializes `Data/Covers/<book_id>.jpg` +
  emits the embed; render-twice is byte-identical. `--dry-run` writes nothing.
  `sources.py`/`images.py` tests untouched; existing note-scanning covers tests rewritten
  to store assertions.
- **audible:** a matched book → an `audible.csv` layer row with `format: audiobook` +
  `audible`-source highlight rows in `Data/Highlights/<book_id>.csv`; an unmatched book is
  skipped + counted; the transcription cache still short-circuits re-download; a re-run
  replaces only `audible` rows and leaves other sources' highlights intact. Existing
  `test_audible_obsidian.py` markdown assertions rewritten to store assertions.
- **cleanup:** a test/grep asserting no module imports `VaultIndex`.

## Deliberate behavior changes (vs. today)

1. `covers` and `audible` no longer edit notes directly; their output appears only after
   `merge` + `render`. `render` (not the command) writes the `cover:`/`format:`
   frontmatter and the `## Highlights` section.
2. `covers --book` targets a `book_id` (catalog row) rather than a note path.
3. A second `merge` after covers/audible may (narrowly) reassign a colliding book's id —
   see Decision 2.

Everything else is behavior-preserving.
