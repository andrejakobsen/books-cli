# Calibre → Obsidian Converter — Design

**Date:** 2026-07-24
**Status:** Approved design (pending spec review)

## Goal

A Python script that reads a Calibre library folder and generates an Obsidian-friendly
markdown vault. It copies the folder structure and cover images, extracts metadata from
each book's `metadata.opf` (XML) into YAML frontmatter (Obsidian properties), and creates
a graph-friendly vault where books cluster around shared authors and genres.

The script never touches ebook files (`.epub`, `.mobi`, etc.) or Calibre internals.

## Why a script, not an Obsidian template

Obsidian templates (core Templates / Templater) only insert boilerplate when *you*
manually create a note. Since the script generates the files, it writes the YAML
frontmatter directly — simpler, reproducible, and re-runnable. Obsidian automatically
recognizes the frontmatter as properties. **All template logic lives in the script.**

## CLI

```
python calibre_to_obsidian.py [--library PATH] [--output PATH]
```

- `--library` — path to the Calibre library. Default: `~/Calibre Library`
- `--output` — path to the output vault. Default: `~/Obsidian`

## Output structure

Mirrors Calibre with one folder per book (self-contained, so a highlights note can sit
beside each book), plus dedicated hub folders for authors and genres:

```
<output>/
  Authors/
    Andrew Roberts.md              # type: author (stub, created if missing)
  Genres/
    Biography & Autobiography.md   # type: genre  (stub, created if missing)
  Andrew Roberts/
    Napoleon_ A Life/
      Napoleon_ A Life.md          # the book note
      cover.jpg                    # copied from Calibre
      (Napoleon_ A Life - Highlights.md)   # user-added later; script never touches it
```

- The Calibre `(NN)` id suffix is stripped from book folder names.
- Wikilinks resolve by note name, so `[[Andrew Roberts]]` finds `Authors/Andrew Roberts.md`
  regardless of folder depth.

## Book note format

```markdown
---
type: book
title: "Napoleon: A Life"
authors: ["[[Andrew Roberts]]"]
genres: ["[[Biography & Autobiography]]", "[[Military]]", "[[History]]"]
publisher: Penguin
published: 2014-11-03
language: eng
rating:                     # personal rating (0–5), empty if unrated in Calibre
isbn: "9780698176287"
amazon: "0143127853"
google: rjVBAwAAQBAJ
uuid: b9fa96aa-4dca-4e1e-826a-5cfcdaf99043
calibre_id: 9
date_added: 2026-06-04
cover: "[[cover.jpg]]"
---
![[cover.jpg]]

<description converted from HTML to markdown>
```

### Property mapping (from `metadata.opf`)

| Property      | OPF source                                             | Notes |
|---------------|--------------------------------------------------------|-------|
| `type`        | constant `book`                                        | Lets a Base index only book notes |
| `title`       | `dc:title`                                             | |
| `authors`     | `dc:creator[opf:role=aut]`                             | List of `[[wikilinks]]` |
| `genres`      | `dc:subject`                                           | List of `[[wikilinks]]` |
| `publisher`   | `dc:publisher`                                         | |
| `published`   | `dc:date`                                              | Date only (YYYY-MM-DD) |
| `language`    | `dc:language`                                          | |
| `rating`      | `meta[name=calibre:rating]`                            | Calibre stores 0–10 → convert to 0–5; empty if absent |
| `isbn`        | `dc:identifier[opf:scheme=ISBN]`                       | Quoted string |
| `amazon`      | `dc:identifier[opf:scheme=AMAZON]`                     | |
| `google`      | `dc:identifier[opf:scheme=GOOGLE]`                     | |
| `uuid`        | `dc:identifier[opf:scheme=uuid]`                       | |
| `calibre_id`  | `dc:identifier[opf:scheme=calibre]`                    | |
| `date_added`  | `meta[name=calibre:timestamp]`                         | Date only |
| `cover`       | constant `[[cover.jpg]]` (omitted if no cover)         | Card image in a Base |
| series/index  | `meta[name=calibre:series]` / `calibre:series_index`   | Included only if present |

Any field that is absent in a given opf is omitted (or written empty for `rating`).

### Cover handling

- `cover.jpg` is copied into the book folder (output is self-contained/portable).
- Embedded in the body via `![[cover.jpg]]` (renders inline).
- Referenced in the `cover` property as `[[cover.jpg]]` (usable as a Base card image).
- If a book has no cover (one book in the current library), the embed and property are
  omitted; the note is still written.

### Description

The `dc:description` HTML is converted to markdown and placed in the note body below the
cover embed. Calibre descriptions use simple tags (`div, p, br, i, b, em, strong, ul, li,
a`). Conversion uses a small stdlib-only converter built on `html.parser` — **zero pip
dependencies**.

## Graph design (authors + genres as links)

Obsidian's graph does not connect `#tags` by default, but `[[wikilinks]]` always create
graph nodes with backlinks. To get a meaningful graph where books cluster by shared author
and shared genre, `authors` and `genres` are wikilink lists rather than tags. Link
properties still filter and sort correctly in Obsidian Bases, so nothing is lost on the
filtering side.

Stub hub notes are generated for each author and genre (`type: author` / `type: genre`),
making those nodes solid, giving a place to add notes, and letting a Base list all authors
or genres. Stubs are created only if missing — user edits survive re-runs.

## Key behaviors

- **Idempotent & safe:** re-running regenerates book notes and copies covers, but never
  overwrites or deletes any file the script did not create — specifically `* - Highlights.md`
  notes and existing author/genre stubs are preserved.
- **Ignores:** ebook files (`.epub`, `.mobi`, `.azw3`, `.pdf`, etc.), `.calnotes`,
  `.caltrash`, `metadata.db`, `metadata_db_prefs_backup.json`.
- **Graceful degradation:** missing cover, missing metadata fields, or malformed opf for a
  single book logs a warning and continues.
- **Dependencies:** standard library only (`xml.etree.ElementTree`, `html.parser`,
  `pathlib`, `shutil`, `argparse`).

## Testing

A small fixture Calibre library is created under the test suite with:

- Two fake books, one **without** a cover.
- A stray `.epub` file to confirm it is ignored.
- A pre-existing `* - Highlights.md` to confirm it is preserved on re-run.

Tests assert:

- Correct frontmatter values and types (lists as wikilinks, quoted identifiers).
- Cover embed + `cover` property present when a cover exists, omitted when it doesn't.
- Ebook and Calibre-internal files are not copied.
- Author/genre stubs are created with correct `type`.
- Re-running does not overwrite a highlights note or an edited stub.
- HTML description is converted to reasonable markdown.

## Out of scope (YAGNI)

- Fetching community/Goodreads/Google Books ratings (personal rating only).
- Reading `metadata.db` directly (opf files are the source of truth).
- Converting/copying ebook files.
- Incremental sync / change detection beyond the idempotent safety rules above.
