# Kobo → Obsidian highlights export — design

**Date:** 2026-07-24
**Status:** Approved design, pending implementation plan
**Command touched:** `books kobo` (adds an Obsidian output mode); minor tweak to `books goodreads`

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

For each book that has highlights:

1. **Locate the book's folder/note** by reusing Goodreads' matching layer
   (`build_index` + `match_note`) against the vault: match by normalized ISBN,
   then by `(norm_title, author_key)`. Kobo provides book title and author
   (`Attribution`); ISBN is used if available from the Kobo `content` row.
2. **If no note exists,** create the folder
   `<vault>/<safe author>/<safe title>/` and a stub `<Title>.md` with the
   canonical frontmatter (`type: book`, `title`, `authors` as wikilinks), plus an
   `Authors/` stub — mirroring how Goodreads creates new notes.
3. **Write `Highlights.md`** into that folder (wholesale overwrite).
4. **Ensure the embed section exists** in `<Title>.md`:

   ```markdown
   ## Highlights
   ![](Highlights.md)
   ```

   Add this section only if a `## Highlights` heading is not already present;
   never otherwise touch the existing body (consistent with the "never overwrite"
   rule, which this extends from frontmatter to a named body section).

## Goodreads tweak (small, for consistency)

- Write the review as `Review.md` (was `<Title> - Review.md`).
- When a review exists, ensure a `## Review` + `![](Review.md)` embed section in
  the book note (same "add only if absent" logic as Highlights).
- Update `tests/test_goodreads_obsidian.py` accordingly.

## Shared layer changes (`booktools/obsidian.py`)

Add reusable, stdlib-only helpers so the embed logic is not duplicated:

- `ensure_embed_section(note_text, heading, target) -> str` — append
  `\n## <heading>\n![](<target>)\n` to the body iff no `## <heading>` heading is
  already present; returns the (possibly unchanged) note text.
- Highlights formatting helpers (callout rendering, anchor building, per-file
  anchor-uniqueness) live in `booktools/kobo_export.py` (Kobo-specific), but any
  genuinely generic piece (e.g. callout line-prefixing) may move to `obsidian.py`.

## Error handling

- Missing database → existing `FileNotFoundError` → `typer.BadParameter`.
- No highlights → print the existing "No highlights or notes found." message.
- `--obsidian` and `--no-csv`/`--csv` interplay: `--obsidian` selects Obsidian
  mode; passing neither keeps CSV as the default. Specifying both `--csv` and
  `--obsidian` is a `typer.BadParameter`.

## Testing (TDD)

- Anchor building: chapter+KoboSpan, missing chapter, missing KoboSpan (counter),
  collision suffixing.
- Callout rendering: single-line, multi-line, annotation present/absent, label
  fallbacks.
- Whole-file `Highlights.md` generation ordering.
- `ensure_embed_section`: adds when absent, no-ops when present, preserves body.
- Matching to an existing Calibre/Goodreads note vs. creating a new stub folder.
- Wholesale regeneration: re-running overwrites `Highlights.md` but leaves the
  book note body (and other files) untouched.
- Goodreads: `Review.md` naming + review embed section.

## Out of scope

- Shipping/enabling the CSS snippet (documented only).
- Any change to CSV/zip mode behavior.
- Deduplicating highlights across Kobo re-reads beyond anchor uniqueness.

## Standalone shim

`scripts/kobo_export.py` remains a thin shim over `booktools.kobo_export.main()`;
no changes beyond staying in sync with the module.
