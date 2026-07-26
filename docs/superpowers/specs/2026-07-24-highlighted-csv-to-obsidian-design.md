# Highlighted CSV → Obsidian highlights — design

**Date:** 2026-07-24
**Status:** Approved design, pending implementation
**Command added:** `books highlighted` (new capability)
**Shared-layer change:** add a `page` dimension to `booktools/highlights.py`

## Goal

Import highlights captured by the **Highlighted** app (OCR of *physical* books)
from its CSV export into the existing per-book Obsidian vault, reusing the
source-agnostic highlights layer built for Kobo. Each book gets a `Highlights.md`
embedded into its canonical note, matched/merged by ISBN (then title+author) so
Highlighted highlights land alongside any existing Calibre/Goodreads data.

## Input format

`Highlights for Stalin.csv` header:

```
Highlight, Title, Author, ISBN, Collections, Reading Status,
Book Added Date, Location, Tags, Note, Date, Favorite
```

- `Highlight` — the highlighted passage (may span multiple lines).
- `Location` — a **page number or page range** (`4`, `45-49`). This is the stable
  per-highlight location for anchors — the payoff of physical-book capture.
- `Note` — user annotation (may be blank).
- `Title` / `Author` / `ISBN` — book identity for matching.
- `Date` — capture timestamp.
- `Collections`, `Tags`, `Reading Status`, `Book Added Date`, `Favorite` —
  **ignored for now** (YAGNI). ISBN is persisted to frontmatter (see below)
  because it is the primary match key.

Rows are imported **regardless of Reading Status** (highlights exist independent
of whether a book is finished). Highlight text is imported **verbatim**, including
any stray/erroneous captures — the user curates in-app and re-exports.

## Decisions

1. **Command name `highlighted`** (after the app), mirroring `goodreads`/`kobo`.
2. **Page label + anchor:** callout label reads `p. 45` (ranges shown with an
   en dash, `p. 45–49`); the block anchor is `^p45` / `^p45-49` (hyphen kept).
   Stable across re-exports because the page is a stable source field.
3. **Import all rows** (no status filter).
4. **Match/merge by ISBN, then (norm_title, author_key)** via the shared
   `VaultIndex`; a new book creates `<vault>/<Author>/<Title>/<Title>.md`.
5. **`Highlights.md` regenerated wholesale** each run (same rule as Kobo);
   personal commentary lives in notes linking to the stable anchors.

## Shared-layer change (`booktools/highlights.py`)

Add one field and thread it through the two format helpers. Existing sources
(Kobo) leave it `None` and are unaffected.

- `Highlight.page: str | None = None` — a human page/location (e.g. `"45-49"`).
- `_label`: when `page` is set, append a `p. <page>` part (hyphens rendered as
  en dashes for display). Combines cleanly with chapter/progress when a future
  source has both; for Highlighted only `p. <page>` shows.
- `build_anchors`: when `page` is set, the location component is `p<sanitized>`
  where sanitize keeps digits and hyphens (`45-49` → `p45-49`). Falls back to the
  existing `block`/`segment` then `hl<n>` counter when `page` is empty/unusable.
  Collision suffixing (`-2`, `-3`) still guarantees uniqueness — this is what
  handles multiple highlights on the same page.

## New module `booktools/highlighted_obsidian.py`

Mirrors `goodreads_obsidian.py`; owns only CSV parsing + field mapping, delegating
all rendering and note-wiring to the shared layer.

- `parse_csv(path) -> list[dict]` — `csv.DictReader`, `utf-8-sig` (tolerates BOM).
- `row_to_highlight(row) -> Highlight` — maps `Highlight`/`Note`/`Location`/`Date`
  into the model (empty strings → `None`).
- `convert(csv_path, output) -> dict` — group rows by book (key: ISBN else title),
  preserving CSV order; per book:
  1. `BookRef(title, [author], isbn)` → `VaultIndex.find_or_create`.
  2. `update_frontmatter` to persist `title`/`authors`/`isbn` (never-overwrite).
  3. `write_leaf_with_embed(note, "Highlights.md", render_highlights(...),
     "Highlights")` and `write_stub` for the author.
  Returns `{"books", "entries", "authors"}`.
- `highlighted_to_obsidian(...)` Typer command: `--csv/-c` (required),
  `--output/-o` (default `Obsidian`); paths via `resolve_path`; missing CSV →
  `typer.BadParameter`. `register(app)` + `main()` as usual.

Register in `booktools/cli.py` `CAPABILITIES`; add `scripts/highlighted_obsidian.py`
shim over `main()`.

## Co-existence

Because matching is ISBN-first, *Stalin* (`9781594203794`) resolves to the same
note the Calibre/Goodreads importers use, so highlights embed alongside the
review. Re-running any importer stays idempotent for the note body (frontmatter
fill-blanks-only + single embed section + wholesale leaf regeneration).

## Testing (TDD)

- `tests/test_highlights.py`: `page` → label `p. 45` / `p. 45–49`; anchor
  `p45` / `p45-49`; same-page collision suffixing; `page=None` unchanged.
- `tests/test_highlighted_obsidian.py`: parse fields; `row_to_highlight` mapping;
  `convert` creates note + `Highlights.md` + `![](Highlights.md)` embed + persists
  ISBN; merges into an existing note by ISBN; idempotent re-run.
- `tests/test_cli.py`: registration count → 4, `highlighted` in `--help`/subcommand
  help; end-to-end run writing a book's `Highlights.md`.
- README: a "Highlighted → Obsidian" section.

## Out of scope

- Collections/Tags/Favorite/Reading Status frontmatter (YAGNI; revisit on demand).
- A generic multi-format `highlights` importer (revisit when a 2nd CSV source
  appears — at which point promote the group-by-book loop into the shared layer).
- Any change to CSV/zip or existing importer behavior.
