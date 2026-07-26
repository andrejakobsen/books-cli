# Flat Book Notes + Separate Exports Folder — Design

**Date:** 2026-07-25
**Status:** Approved (pending implementation)

## Problem

Today every book lives in its own nested folder that mixes the note with its
heavy artifacts:

```
Obsidian/
  <Author>/<Title>/<Title>.md      # book note (frontmatter + cover + description + ## Highlights / ## Review embeds)
  <Author>/<Title>/cover.jpg
  <Author>/<Title>/Highlights.md
  <Author>/<Title>/Review.md
  Authors/<author>.md
  Genres/<genre>.md
```

The goal is a **flat `Books/` folder** where each note carries all of its
frontmatter properties (from Calibre and/or Goodreads) and inline description,
while the heavy artifacts (cover, highlights, review) move into a separate,
more deeply nested `Exports/` folder that the flat notes reference.

## Target vault layout

```
Obsidian/
  Books/
    <Title>.md                      # flat; all frontmatter, description inline,
                                    # cover embed at top, ## Highlights / ## Review embeds
    <Title> (<Author>).md           # only when a plain <Title>.md is already taken
  Exports/
    <Author>/<Title>/
      cover.jpg
      Highlights.md                 # ---\nsource: kobo\n---      + rendered highlights
      Review.md                     # ---\nsource: goodreads\n--- + review
  Authors/<author>.md               # stub hub notes (unchanged, at root)
  Genres/<genre>.md                 # stub hub notes (unchanged, at root)
```

### How a flat note references its artifacts

References use **vault-relative Obsidian wikilinks**, which handle spaces and
file renames natively and stay unambiguous even though `Highlights.md`,
`Review.md`, and `cover.jpg` names repeat across books:

- Frontmatter: `cover: "[[Exports/<Author>/<Title>/cover.jpg]]"`
- Body, top: `![[Exports/<Author>/<Title>/cover.jpg]]`
- Body section `## Highlights`: `![[Exports/<Author>/<Title>/Highlights.md]]`
- Body section `## Review`: `![[Exports/<Author>/<Title>/Review.md]]`

The exported Highlights and Review live under their own dedicated `##`
subheaders so a user's manual notes elsewhere in the note body stay cleanly
separated from imported content.

## Design decisions (from brainstorming)

- **Moved to `Exports/`:** cover images, highlights, reviews.
- **Kept inline in the flat note:** the Calibre description body.
- **`Exports/` internal layout:** by author, then title
  (`Exports/<Author>/<Title>/`).
- **Flat note naming:** `<Title>.md`; on a real collision with a *different*
  book, disambiguate the later one as `<Title> (<Author>).md`.
- **Reference style:** embed under dedicated `## Highlights` / `## Review`
  subheaders (preserves today's `ensure_embed_section` behavior) via
  vault-relative wikilinks.
- **Cover placement:** both a `cover:` frontmatter property and an embed at the
  top of the body.
- **Migration:** none — regenerate fresh into a new/empty vault.
- **Notes location:** a dedicated `Books/` subfolder (keeps the vault root tidy
  alongside `Exports/`, `Authors/`, `Genres/`).

## Architecture (Approach A)

Route **all three** importers through a single layout authority in
`books/obsidian.py`. Today Goodreads and Kobo already use `VaultIndex` for
matching, but Calibre bypasses it and mirrors the Calibre library's folder tree.
That divergence is removed: `VaultIndex` becomes the single source of truth for
"where does the note live, where do its exports live, what's the embed path."

### `obsidian.py` changes

- **New constants:** `BOOKS_DIRNAME = "Books"`, `EXPORTS_DIRNAME = "Exports"`.
- **`VaultIndex` as layout authority:**
  - `build_index` scans only `vault/Books/*.md` (flat), skipping `Authors`,
    `Genres`, and `Exports`. Matching by normalized ISBN and (title, author) is
    unchanged.
  - Tracks used note stems so it can disambiguate on title collision: the first
    book with a given title gets `<Title>.md`; a later *different* book with the
    same title gets `<Title> (<Author>).md`.
  - `find_or_create(ref)` returns a small `BookNote(note_path, export_dir,
    created)` dataclass, where
    `export_dir = vault/Exports/<safe Author>/<safe Title>`. The stub note is
    created flat in `Books/`.
- **Embedding generalized:** `ensure_embed_section` and `write_leaf_with_embed`
  emit **wikilink embeds** (`![[target]]`) and write the leaf into a
  caller-supplied `export_dir` (no longer `note_path.parent`). The
  "never overwrite body / skip when heading already present" rules are preserved.
- **Cover helper:** a small function to (a) place the cover into `export_dir`
  and (b) produce the `cover:` frontmatter value and the top-of-body embed, both
  as vault-relative wikilinks. `BOOK_PROPERTY_ORDER` is unchanged (`cover`
  stays).

### Importer changes

- **Calibre (`calibre_obsidian.py`):** drop the library-folder-mirroring
  (`sanitize_folder_name` path rebuild). For each `metadata.opf`, build a
  `BookRef`, call `VaultIndex.find_or_create`, write the flat note (frontmatter
  merge + inline description + cover embed at top), copy `cover.jpg` into
  `export_dir`, and set the `cover:` frontmatter. Authors/Genres stubs unchanged.
- **Goodreads (`goodreads_obsidian.py`):** matching unchanged; `Review.md` now
  written into `export_dir` via the generalized `write_leaf_with_embed` (still
  `overwrite=False`), embedded under `## Review` by wikilink.
- **Kobo (`kobo_export.py`):** `Highlights.md` written into `export_dir`,
  embedded under `## Highlights` by wikilink.

## Data flow

1. Importer parses its source into a `BookRef` (+ source-specific fields).
2. `VaultIndex.find_or_create(ref)` → `BookNote(note_path, export_dir, created)`.
3. Importer merges frontmatter into `note_path` (never-overwrite rule).
4. Importer writes any leaf artifact (cover/highlights/review) into `export_dir`
   and ensures a `##` embed section in the flat note pointing at it by
   vault-relative wikilink.
5. Authors/Genres stubs written at vault root.

Running Calibre → Goodreads → Kobo (in any order) composes into one flat note
per book with all three artifacts, because the never-overwrite merge and the
"skip embed if heading present" rules are unchanged.

## Testing

- Update existing `tests/` assertions from the old `<Author>/<Title>/` paths to
  `Books/` + `Exports/<Author>/<Title>/`.
- New tests:
  - Flat-name disambiguation on a title collision between two different books.
  - Export leaves (cover/highlights/review) land under `Exports/<Author>/<Title>/`.
  - Note embeds resolve to the correct vault-relative wikilinks.
  - Cover appears both in the `cover:` frontmatter and as a top-of-body embed.
  - Re-running is idempotent and never overwrites existing values/body.
  - Cross-importer compose (Calibre then Goodreads then Kobo) yields one flat
    note with all three artifacts.
- `scripts/*.py` shims: confirm they still work (they call each module's
  `main()`; no change expected).

## Out of scope

- Migrating an existing old-layout vault in place (we regenerate fresh).
- Any change to Authors/Genres hub-note behavior or their root location.
- Changes to matching normalization (`norm_title`, `author_key`, etc.).
