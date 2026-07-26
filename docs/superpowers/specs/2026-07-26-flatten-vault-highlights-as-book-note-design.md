# Flatten the vault — highlights *are* the book note

**Date:** 2026-07-26
**Status:** Approved (implementing)

## Problem

Today a book lives in two places: a flat note at `Books/<Title> - <Author>.md`
carries frontmatter and *embeds* a cover image and a `Highlights.md` (and
`Review.md`) that live nested under `Exports/<Author>/<Title>/`. The nesting is
deep, the highlights are a second-class embedded file, and there is no separation
between auto-generated content and personal writing.

## Goals

- The **highlights file becomes the single indexed book note** — frontmatter +
  cover + highlights (+ an optional review) all in one flat file. No `Exports/`.
- **Personal notes live separately** and are never touched by the tooling; the
  book note only *links* to where a personal note would live.
- **Covers move to a flat `Covers/` folder.**
- **`Genres` → `Topics`** everywhere (folder and frontmatter key).
- A **one-time migration** folds the existing vault into the new layout.

## Vault layout (after)

```
Books/       <Title> - <Author>.md   — the single indexed book note
Notes/       <Title> - <Author>.md   — personal notes (hand-made, never touched)
Authors/     <Author>.md             — stub hubs (unchanged)
Topics/      <Topic>.md              — stub hubs (renamed from Genres/)
Covers/      <Title> - <Author>.jpg  — cover images (visible; hidden in Obsidian by the user)
.imports/    raw import sources       — unchanged
```

`Exports/` is removed. Covers live in a **non-hidden** `Covers/` folder (a
dot-folder would stop Obsidian from rendering the embed); the user hides it via
Obsidian's settings.

## Anatomy of a book note

```markdown
---
type: book
title: The Deluge: The Great War...
authors: ["[[Adam Tooze]]"]
topics: ["[[History]]", "[[Europe]]"]
...
cover: "[[Covers/The Deluge - Adam Tooze.jpg]]"
notes: "[[Notes/The Deluge - Adam Tooze]]"
---
![[Covers/The Deluge - Adam Tooze.jpg|150]]

## Review
(imported Goodreads review — written once, never overwritten)

## Highlights
%% books:highlights:start %%
> [!quote] ch. 2 · 42% · [[Trotsky]]
> ...
%% books:highlights:end %%
```

- **Cover** embeds at a fixed width of **150** (`![[...|150]]`). The `cover:`
  frontmatter holds the plain wikilink (no width) for gallery/Bases views.
- **`## Highlights`** body is wrapped in `%% books:highlights:start/end %%`
  markers. Re-runs replace **only** the text between the markers; the heading and
  everything else are left alone. Multi-source behaviour is unchanged: one
  highlights block, last importer to run wins.
- **`## Review`** is written once if absent and then never touched.
- **`notes:`** is a path-qualified wikilink to `Notes/<stem>` (path-qualified so
  it does not collide with the identically-named `Books/<stem>` note). The
  importer never creates the file — the user makes it by hand when needed.

## Shared-layer changes (`books/obsidian.py`)

- `BOOK_PROPERTY_ORDER`: rename `genres` → `topics`; append `notes`.
- Layout constants: keep `BOOKS_DIRNAME`; add `COVERS_DIRNAME="Covers"`,
  `NOTES_DIRNAME="Notes"`, `AUTHORS_DIRNAME="Authors"`, `TOPICS_DIRNAME="Topics"`,
  `COVER_WIDTH=150`; remove `EXPORTS_DIRNAME`.
- `cover_path(note_path) -> Path` → `<vault>/Covers/<note stem>.jpg` (keyed to the
  actual note filename, so it is unique and matches the note).
- `cover_refs(note_path) -> (fm, embed)` → `("[[Covers/<stem>.jpg]]",
  "![[Covers/<stem>.jpg|150]]")`.
- `notes_ref(note_path) -> str` → yaml-quoted `[[Notes/<stem>]]`.
- `render_marked_section(text, heading, marker, content)` — insert-or-replace a
  `## heading` section whose body is delimited by `%% books:<marker>:start/end %%`.
- `ensure_section(text, heading, content)` — append a `## heading` section iff the
  heading is absent (write-once; for the review).
- Remove `ensure_embed_section`, `write_leaf_with_embed`, `with_source`,
  `VaultIndex.export_dir`, `BookNote.export_dir`. `find_or_create` fills the
  `notes:` link on creation.

## Importer changes (one call site each)

- **kobo / readwise / highlighted**: call `render_marked_section(...)` with inline
  `render_highlights(...)` output instead of `write_leaf_with_embed`. Provenance
  frontmatter (`with_source`) is dropped — the book note already carries `source:`.
- **goodreads**: write the review into a write-once `## Review` section
  (`ensure_section`), not a leaf embed. Drop the `# <Title> — Review` H1 (the
  `## Review` heading replaces it).
- **calibre**: copy the cover to `Covers/<stem>.jpg`; emit `topics` frontmatter and
  write `Topics/` stubs (`type: topic`).
- **covers**: write the fetched image to `Covers/<stem>.jpg`.

## Migration (`books migrate`, one-time, `--dry-run`)

For each `Books/*.md`:
1. Inline the `![[Exports/.../Highlights.md]]` embed into a marker-wrapped
   `## Highlights` section (strip the leaf's `source:` frontmatter).
2. Inline the `![[Exports/.../Review.md]]` embed into a write-once `## Review`
   section (strip frontmatter and the leaf's `# ... — Review` H1).
3. Move `Exports/.../cover.jpg` → `Covers/<stem>.jpg`, rewrite the embed to
   `![[Covers/<stem>.jpg|150]]`, and update the `cover:` frontmatter.
4. Rename the `genres:` frontmatter key to `topics:`.
5. Add the `notes:` link if absent.

Then rename `Genres/` → `Topics/` (and `type: genre` → `type: topic` inside), and
delete `Exports/`. Idempotent; `--dry-run` reports without writing.

## Testing

TDD throughout. New unit tests for `render_marked_section` (insert / replace /
preserve-outside), `ensure_section`, `cover_path`, `cover_refs` (width 150),
`notes_ref`, and the `genres→topics` schema change. Update existing importer and
`obsidian` tests that assert `Exports/` paths. A migration round-trip integration
test over a synthetic old-layout vault.
