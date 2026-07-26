# Goodreads → Obsidian (and unified, merge-based book notes)

**Date:** 2026-07-24
**Status:** Approved design

## Goal

Add a `goodreads-to-obsidian` capability to the `books` CLI that turns a
Goodreads library CSV export into Obsidian notes, in the same shape as the
existing `calibre-to-obsidian` output. The two sources overlap (the same book
may come from both), so the guiding rule is:

> **Never overwrite information that already exists. Only fill properties that
> are absent or empty (`None`).**

As part of this, both importers adopt a **single canonical property schema** and
**merge-based** note writing, so Calibre and Goodreads data (and manual edits)
compose without clobbering each other on re-runs.

## Scope decisions (confirmed)

- **Read-only filter (default):** only rows whose `Exclusive Shelf` is `read`
  are imported. Most of the export is `to-read`; those are skipped. A `--shelf`
  option overrides the filter (e.g. `--shelf currently-reading`, or
  `--shelf all` to import every row).
- **Create + merge:** among the filtered rows, Goodreads creates new notes for
  books not in the vault and merges into existing ones.
- **Match order:** existing note is found by normalized ISBN/ISBN13 first, then
  by a **strict** Author/Title match; otherwise the row is new. The fallback
  tolerates only punctuation and author middle-name/initial differences —
  everything else must match. This keeps genuinely distinct books apart (e.g.
  *The Soviet Century* by Moshe Lewin vs *The Soviet Century: Archaeology of a
  Lost World* by Karl Schlögel remain separate).
- **Status + shelves:** import Goodreads `Exclusive Shelf` as `status` and
  `Bookshelves` as a `shelves` list.
- **Review file:** write `My Review` (and `Private Notes`, if present) to a
  separate `<Title> - Review.md` inside the book folder, alongside any
  `<Title> - Highlights.md`. Never overwritten.
- **Calibre re-runs preserve values:** Calibre book notes switch to the same
  fill-only-if-empty merge, so manual/Goodreads edits survive re-runs.
- **Additional Authors** (translators/editors) are included in `authors`.

## Architecture

### New shared module: `books/obsidian.py`

Holds everything both importers need, so they agree on format:

- Formatting helpers moved from `calibre_obsidian.py`: `yaml_quote`,
  `wikilink`, `link_list`, `write_if_absent`, `write_stub`,
  `sanitize_folder_name`.
- `safe_filename(name)` — make a title safe for a filename/folder:
  replace `/ \ : * ? " < > |` and control chars with `_`, collapse spaces,
  strip trailing dots/spaces.
- **Canonical schema** — an ordered list of property keys that every book note
  emits (empty when the source has no value), so merges are trivial and every
  field is manually editable in Obsidian:

  ```
  type (fixed: book)
  title, authors, genres, series, series_index,
  publisher, published, language, pages,
  status, shelves, rating,
  isbn, amazon, google, uuid, calibre_id,
  date_added, date_read, cover
  ```

- `update_frontmatter(note_text, updates) -> str` — the core of "never
  overwrite":
  - Splits the leading `---` … `---` frontmatter from the body. If there is no
    frontmatter, treats the whole file as body and prepends a fresh block.
  - Parses frontmatter into ordered `key -> raw_value` pairs (tolerant,
    line-based; values are the pre-formatted YAML scalars we emit).
  - A key is **eligible to fill** iff it is absent or its value is blank
    (e.g. Calibre's empty `rating:`). Non-empty values are never touched.
  - New keys are inserted in canonical order.
  - The body is returned unchanged.
  - Used by **both** create and merge paths: a new note is `update_frontmatter`
    applied to a `---\ntype: book\n---\n` skeleton, then a body appended.

### `books/calibre_obsidian.py` changes

- Import helpers from `books.obsidian` (behavior-preserving).
- `build_frontmatter` emits the full canonical schema, with Goodreads-only
  fields (`pages`, `status`, `shelves`, `date_read`) present but empty.
- `convert` becomes merge-based for book notes: if the note exists, read it and
  `update_frontmatter` (fill-only-empty, body preserved); if not, build fresh.
  Cover copy and author/genre stubs are unchanged (stubs already use
  `write_if_absent`).

### New module: `books/goodreads_obsidian.py`

- `register(app)` → `goodreads-to-obsidian`; `main()` for the standalone shim.
- CLI: `--csv/-c` (input export, required), `--output/-o` (vault, default
  `Obsidian`, same resolution rules as Calibre), `--shelf` (default `read`;
  `all` disables the filter).
- `parse_csv(path) -> list[GoodreadsBook]` using the stdlib `csv` module.
  Per-field handling:
  - ISBN/ISBN13: strip Goodreads `="…"` Excel escaping; `=""` → none.
  - `My Rating`: `0` → unrated (empty); else integer.
  - Dates `YYYY/MM/DD` → `YYYY-MM-DD`.
  - `authors` = `Author` + split `Additional Authors`.
  - `status` from `Exclusive Shelf`: `currently-reading` → `reading`, else the
    shelf name (`to-read`, `read`).
  - `shelves` from `Bookshelves` (comma-split, trimmed).
  - `published` = `Year Published` (year only).
- `build_index(output)` — scan the vault for `type: book` notes, mapping
  normalized ISBN and normalized (first author, title) → note path. Skips
  `Authors/` and `Genres/` stubs.
- `convert(csv_path, output, shelf="read")`:
  1. Build the index.
  2. Filter rows by `Exclusive Shelf` (unless `shelf == "all"`).
  3. For each remaining row, resolve the target note (matched existing, else new path
     `output/<Author>/<Title>/<Title>.md`).
  4. `update_frontmatter` with the row's values (fill-only-empty), preserving
     body; create parent dirs as needed.
  5. Create author stubs under `Authors/` (`write_if_absent`).
  6. If a review/notes exists, `write_if_absent(book_folder /
     "<Title> - Review.md", ...)`.
- Matching keys / normalization:
  - **ISBN:** digits-only (also handles the trailing `X` check digit); compare
    ISBN and ISBN13.
  - **Title:** lowercase, fold accents (Unicode NFKD + drop combining marks),
    collapse whitespace, strip punctuation → require **exact** equality. No
    subtitle trimming.
  - **Author (strict fuzzy):** same normalization, then compare only the
    **first + last name tokens**, ignoring middle names/initials. So
    `Terry Martin` ≡ `Terry L. Martin` and `Robert Tucker` ≡ `Robert C. Tucker`,
    but different first/last names never match. Handles both Goodreads `Author`
    and `Author l-f` orderings by reducing each to a `{first, last}` pair.
  - A fallback match requires **title exact AND author first/last** to agree.

### `books/cli.py`

Add `goodreads_obsidian` to `CAPABILITIES`.

### `scripts/goodreads_to_obsidian.py`

Standalone shim mirroring the existing ones (`from books.goodreads_obsidian
import main`).

## Field mapping (Goodreads → property)

| Goodreads column        | Property     | Notes                                   |
|-------------------------|--------------|-----------------------------------------|
| Title                   | `title`      |                                         |
| Author + Additional Authors | `authors` | `[[wikilinks]]`; author stubs created   |
| ISBN13 / ISBN           | `isbn`       | strip `="…"`; prefer ISBN13             |
| My Rating (0–5)         | `rating`     | `0` = unrated → empty                    |
| Publisher               | `publisher`  |                                         |
| Number of Pages         | `pages`      |                                         |
| Year Published          | `published`  | year only                               |
| Date Read               | `date_read`  | normalized to `YYYY-MM-DD`              |
| Date Added              | `date_added` | normalized to `YYYY-MM-DD`              |
| Exclusive Shelf         | `status`     | `currently-reading` → `reading`         |
| Bookshelves             | `shelves`    | plain YAML list                         |
| My Review / Private Notes | (review file) | `<Title> - Review.md`, never overwritten |

Goodreads provides no covers, genres, or descriptions; those stay empty for
Goodreads-only books and are filled by Calibre / manual editing.

## Testing

`tests/test_goodreads_obsidian.py` (synthetic CSV):

- CSV parsing: ISBN unescaping, rating `0`→empty, date normalization,
  additional-authors split.
- Shelf filter: default run imports only `read` rows (skips `to-read` /
  `currently-reading`); `--shelf all` imports everything.
- New note creation with canonical schema and correct folder/filename.
- Merge into an existing Calibre note: fills empty `status`/`pages`/`shelves`/
  `date_read`, preserves existing `title`/`publisher`/`rating`, and leaves the
  body (description + cover embed) untouched.
- Matching by ISBN and by strict Author/Title fallback (no duplicate note
  created), including: punctuation-only title difference merges; author
  middle-name/initial difference merges (`Terry Martin` ≡ `Terry L. Martin`);
  but a different subtitle or different author does **not** merge (the two
  *Soviet Century* books stay separate).
- Review file written to the book folder and **not** overwritten on re-run.
- Idempotent: a second full run changes nothing.

Update `tests/test_calibre_to_obsidian.py` for the new schema + merge behavior:

- Book notes now contain the empty Goodreads-only placeholders.
- Re-running Calibre preserves a manually set property value in a book note.
- Existing assertions (covers, stubs, ignored files, html→md) still hold.

`books/obsidian.py` gets direct unit tests for `update_frontmatter`
(fill-empty, never-overwrite, no-frontmatter case) and `safe_filename`.

## Non-goals

- No network calls or cover fetching for Goodreads books.
- No genre inference from Goodreads shelves.
- No reconciliation of conflicting non-empty values between sources (first
  writer wins; the rule is fill-only-empty).
