# Follow-up: covers & audible → CSV writers

**Date:** 2026-07-29
**Status:** SUPERSEDED by `docs/superpowers/specs/2026-07-29-covers-audible-to-csv-design.md`
(kept as the original scoping note; the linked design is the implementation-ready spec)
**Reference:** `docs/superpowers/specs/2026-07-29-importers-to-csv-writers-design.md`

The core-five pass converts calibre/goodreads/kobo/highlighted/readwise into CSV
writers. `covers` and `audible` still write markdown directly via `VaultIndex`.
This note lists what remains to bring them onto the store, so `render` becomes the
sole owner of Obsidian output and `VaultIndex` can retire.

## covers

Today: scans `type: book` notes with a blank `cover:`, fetches an image, writes
`Data/Covers/<stem>.jpg` + fills the note's `cover:` frontmatter/embed; also
backfills a learned `isbn`.

To convert:
- **Read from the store, not the vault.** Iterate `books.csv` rows (via
  `store.read_books_csv`) that have no `cover`, instead of scanning notes.
- **Write a `covers` layer, not notes.** Emit `Data/Sources/covers.csv` rows keyed
  to the book (carry `cover` = the saved image path + any learned `isbn`); let
  `merge` + `render` fold them in. `covers` sits in `PRECEDENCE` already.
- **Image file naming.** Cover images are named `<book_id>.jpg`, and `book_id`
  only exists post-merge — so covers must run *after* merge (like the highlight
  importers). Save the fetched image to a staging path and let `render`
  materialize it (reuse the calibre stage→materialize flow), OR run covers
  strictly after merge and write straight to `Data/Covers/<book_id>.jpg`.
- **Resolve books via `store.Catalog.find`** (ISBN → Amazon → title/author),
  matching the other post-merge importers; unmatched books skipped + counted.
- Drop all `books.renderers.obsidian` imports; keep `sources.py`/`images.py`
  (network + validation) untouched.

## audible

Today: enrich-only via `VaultIndex.find` (by ASIN then title/author), fills
`format: audiobook`, downloads + decrypts + transcribes clips, renders them into a
marker-wrapped `## Highlights` section. Cache in `Data/Imports/audible/cache.json`.

To convert:
- **Write two things to the store:** a small `audible` metadata layer
  (`format: audiobook`, `amazon`=ASIN) so books.csv can carry it, and per-book
  highlights via `store.write_highlights(vault, book_id, "audible", rows)`.
- **Resolve via `store.Catalog.find`** by ASIN-as-`amazon` then title/author;
  unmatched books skipped + counted. Runs after merge.
- **Transcription cache is unchanged** (keyed by ASIN + annotation id) — it already
  makes re-runs cheap; `write_highlights` replace-by-source keeps re-runs clean.
- `annotation_id` = the Audible annotation id (stable) → good dedupe key.
- Keep the ffmpeg/download/transcribe pipeline and the `[audible]` optional extra
  exactly as-is; only the sink changes. Drop `books.renderers.obsidian` imports.

## sync + cleanup

- Add `covers` and `audible` as post-merge steps in `sync` (they need `books.csv`),
  after the other highlight importers, before `render`. Note: `covers` is
  currently excluded from `sync` — decide whether to include it once converted.
- Once both are converted, **`VaultIndex` has no callers** → delete
  `books/renderers/obsidian/vault_index.py` and its re-exports; `render` is then
  the only producer of Obsidian notes.

## Testing

- covers: assert the written `covers` layer / staged image + materialized
  `Data/Covers/<book_id>.jpg`; unmatched book skipped + counted; learned ISBN lands
  in the merged row.
- audible: assert the metadata layer (`format: audiobook`) + highlight rows in the
  store; cache still short-circuits re-download; re-run replaces only audible rows.
