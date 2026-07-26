# Kobo → Obsidian highlights export — design

**Date:** 2026-07-24
**Status:** Approved design, pending implementation plan
**Command touched:** `books kobo` (adds an Obsidian output mode); refactor of `books goodreads` onto shared helpers
**New shared module:** `books/highlights.py` (source-agnostic highlight model + renderer, reusable by future apps: Kindle, Apple Books, …)

## Goal

Add an Obsidian output mode to the Kobo capability so highlights and notes are
written into the existing per-book folder layout as an Obsidian-formatted
`Highlights.md`, embedded into the canonical book note. Today `books kobo` only
emits per-book CSVs bundled in a zip.

## Context: the layout already exists

Both existing importers already write a **folder-per-book** vault:

```
<vault>/<Author>/<Title>/
  <Title>.md            # canonical book note (Calibre + Goodreads merge here)
  <Title> - Review.md   # Goodreads review (renamed to Review.md — see below)
  cover.jpg             # Calibre
```

- Goodreads: `output / <author> / <title> / <Title>.md`, review alongside.
- Calibre: mirrors the library's `Author/Title/` tree; note is `<Title>.md`.

So no "folder migration" is needed. The gaps between this and the target design
are only: (1) leaf files should use generic names, (2) the book note has no embed
wiring, (3) the Kobo Obsidian export does not exist.

## Decisions

1. **CLI:** `books kobo` gains `--obsidian`, mutually exclusive with `--csv`
   (still the default). In Obsidian mode, `--output` is the **vault directory**
   (resolved via `resolve_path`). CSV/zip mode is unchanged.
2. **Leaf filenames are generic:** `Highlights.md` and `Review.md` (Goodreads'
   `<Title> - Review.md` is renamed to `Review.md`).
3. **Embeds are relative Markdown embeds:** the book note transcludes leaves with
   `![](Highlights.md)` / `![](Review.md)`. These resolve relative to the note's
   own folder, so generic names never collide across books, the link is short,
   and it survives folder renames. (Wikilinks would resolve vault-globally and so
   could not use generic names without a full path.)
4. **Block anchors use KoboSpan** (`^ch<idx>-b<block>-<seg>`): stable across
   re-exports, so handwritten notes elsewhere that link to an anchor keep
   resolving even after `Highlights.md` is regenerated.
5. **`Highlights.md` is regenerated wholesale** on every export. Its `[!note]`
   blocks reflect Kobo annotations only; personal commentary lives in notes that
   *link to* the stable anchors, never inside `Highlights.md`.
6. **CSS snippet is documented, not shipped:** the README explains the optional
   seamless-embed snippet; the tool never writes into `.obsidian/`.

## Reusable architecture (source-agnostic)

Highlights will later come from other apps (Kindle, Apple Books, …), so the
Obsidian-facing logic is **source-agnostic** and lives in a shared module. Each
app importer only maps its own storage into the shared model; it owns none of the
rendering, anchoring, or note-wiring.

**New module `books/highlights.py`** (stdlib-only) owns:

- **`Highlight` dataclass** — a source-neutral highlight:
  ```
  text: str                 # highlighted passage
  note: str | None          # user annotation, if any
  chapter_index: int | None # reading-order index (for label + anchor)
  chapter_title: str | None
  progress: float | None    # 0.0–1.0 within the chapter (for the % label)
  block: str | None         # location component for a stable anchor (e.g. KoboSpan block)
  segment: str | None       # secondary location component
  date: str | None
  ```
  Apps populate what they have; missing fields degrade gracefully (label/anchor
  fallbacks below). `block`/`segment` are generic "stable location" slots — Kobo
  fills them from KoboSpan; another app might use a CFI or character offset.
- **`build_anchor(highlights) -> list[str]`** (or a stateful builder) — computes a
  unique `^id` per highlight with the fallback + collision rules below.
- **`render_highlights(highlights) -> str`** — renders the whole `Highlights.md`
  body (callouts + anchors) from an ordered `list[Highlight]`. This is the single
  place the callout format lives, shared by every future source.

**`BookRef`** (source-neutral book identity for matching/creation): `title`,
`authors: list[str]`, `isbn: str | None`. Apps build one per book.

**Promote book-note orchestration to shared.** Goodreads already contains
`build_index`/`match_note` and the find-or-create-note-folder logic; move the
generic parts to the shared layer (`books/obsidian.py`, or `highlights.py`)
so any exporter can:

- `find_or_create_book_note(vault, book_ref) -> Path` — match an existing note by
  ISBN then `(norm_title, author_key)`; otherwise create
  `<vault>/<author>/<title>/<Title>.md` (canonical frontmatter + `Authors/` stub).
- `write_leaf_with_embed(note_path, leaf_name, content, heading)` — write
  `<folder>/<leaf_name>` (wholesale) and ensure a `## <heading>` +
  `![](<leaf_name>)` section exists in the book note.

Goodreads is refactored to consume these shared helpers (proving the abstraction
with two callers: Goodreads reviews and Kobo highlights).

**Kobo module becomes thin:** read `KoboReader.sqlite` → per book, build a
`BookRef` and an ordered `list[Highlight]` → call
`render_highlights` + `write_leaf_with_embed`. It owns only Kobo SQL and the
KoboSpan → `block`/`segment` mapping (existing `parse_container`).

## `Highlights.md` format

One book per file, highlights in reading order (chapter `VolumeIndex`, then
`chapter_progress`, then `date_created` — the CSV query's existing order):

```markdown
> [!quote]+ ch. 2 · 42%
> Actual highlight text
^ch2-b17-5

> [!note]-
> Kobo annotation text, if any.
^ch2-b17-5-note
```

- **Callout title (label):** `ch. <VolumeIndex> · <pct>%`.
  - `<pct>` reuses the existing `pct()` helper (whole-number percent of
    `chapter_progress`).
  - When `VolumeIndex` is missing: use the chapter title if present
    (`<Chapter> · 42%`), else just `42%`, else empty.
  - The label is display text only and may repeat freely across highlights.
- **Anchor (`^id`, must be unique in the file):**
  `ch<VolumeIndex>-b<block>-<seg>` from `parse_container()` (KoboSpan
  block/segment).
  - Missing chapter index → drop the `ch<idx>` segment (`b17-5`).
  - Missing KoboSpan → fall back to a per-file sequential counter (`hl3`).
  - Collision guard: if a computed anchor is already used in the file, append
    `-2`, `-3`, … so anchors are always unique.
- **`[!quote]+`** is expanded by default; **`[!note]-`** is collapsed by default.
- The `[!note]` block is **omitted entirely** when the Kobo annotation is empty
  (no empty callouts).
- **Multi-line highlight/annotation text:** every line is prefixed with `> ` so
  it stays inside the callout.
- The `^anchor` line immediately follows its callout (no blank line between), then
  a blank line separates blocks — matching the requested format.

## Canonical note integration

For each book that has highlights (all via the shared orchestration helpers, not
Kobo-specific code):

1. **Locate or create the book note** with `find_or_create_book_note(vault,
   book_ref)`: match by normalized ISBN, then `(norm_title, author_key)`;
   otherwise create `<vault>/<author>/<title>/<Title>.md` (canonical frontmatter
   + `Authors/` stub). Kobo builds the `BookRef` from title, `Attribution`
   (author), and ISBN if the `content` row has one.
2. **Write the leaf + embed** with `write_leaf_with_embed(note_path,
   "Highlights.md", body, "Highlights")`: overwrite `Highlights.md` wholesale and
   ensure a `## Highlights` + `![](Highlights.md)` section exists in the book note
   (added only if the `## Highlights` heading is absent; the existing body is
   otherwise never touched — the "never overwrite" rule extended from frontmatter
   to a named body section).

## Goodreads tweak (proves the abstraction with a second caller)

- Write the review as `Review.md` (was `<Title> - Review.md`) via
  `write_leaf_with_embed(note_path, "Review.md", body, "Review")`, producing a
  `## Review` + `![](Review.md)` embed.
- Refactor Goodreads' find-or-create logic to call the shared
  `find_or_create_book_note` (removing the duplicated matching/creation code).
- Update `tests/test_goodreads_obsidian.py` accordingly.

## Shared layer changes

- **`books/highlights.py`** (new): `Highlight`, `render_highlights`, anchor
  building — the source-agnostic highlight model + renderer.
- **`books/obsidian.py`**: `ensure_embed_section(note_text, heading, target)`
  (append `\n## <heading>\n![](<target>)\n` iff the heading is absent);
  `BookRef`, `find_or_create_book_note`, and `write_leaf_with_embed` — the shared
  note orchestration promoted out of Goodreads.
- **`books/kobo_export.py`**: only Kobo SQL + KoboSpan→`block`/`segment`
  mapping; delegates all rendering and note-wiring to the shared helpers.

## Error handling

- Missing database → existing `FileNotFoundError` → `typer.BadParameter`.
- No highlights → print the existing "No highlights or notes found." message.
- `--obsidian` and `--no-csv`/`--csv` interplay: `--obsidian` selects Obsidian
  mode; passing neither keeps CSV as the default. Specifying both `--csv` and
  `--obsidian` is a `typer.BadParameter`.

## Testing (TDD)

Shared layer (`highlights.py` / `obsidian.py`) — tested independently of Kobo,
using `Highlight`/`BookRef` fixtures so future sources inherit the coverage:

- Anchor building: chapter+location, missing chapter, missing location (counter),
  collision suffixing.
- `render_highlights`: single-line, multi-line, annotation present/absent, label
  fallbacks, ordering.
- `ensure_embed_section`: adds when absent, no-ops when present, preserves body.
- `find_or_create_book_note`: match existing note by ISBN / title+author vs.
  create a new stub folder.
- `write_leaf_with_embed`: writes the leaf and the embed section together;
  re-running overwrites the leaf but leaves the book note body untouched.

Kobo (`kobo_export.py`):
- SQLite row → `Highlight`/`BookRef` mapping (incl. KoboSpan → block/segment).
- `--obsidian` end-to-end: highlights written, note embed present, wholesale
  regeneration leaves other files untouched.

Goodreads (`test_goodreads_obsidian.py`):
- `Review.md` naming + review embed section via the shared helper.

## Out of scope

- Shipping/enabling the CSS snippet (documented only).
- Any change to CSV/zip mode behavior.
- Deduplicating highlights across Kobo re-reads beyond anchor uniqueness.

## Standalone shim

`scripts/kobo_export.py` remains a thin shim over `books.kobo_export.main()`;
no changes beyond staying in sync with the module.
