# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                              # create the venv and install deps (incl. dev)
uv run books --help                  # run the CLI without a global install
uv run pytest -q                     # run the full test suite
uv run pytest tests/test_obsidian.py # run one test file
uv run pytest -k "author_key"        # run tests matching an expression
uv tool install . --reinstall        # rebuild & reinstall the global `books` command
```

There is no separate lint/format step configured.

## Architecture

Single Typer CLI (`books`) that fans out to independent capability modules. The
entry point is `booktools/cli.py`, which builds one shared `Typer` app and calls
`register(app)` on every module listed in `CAPABILITIES`. **To add a capability:**
create `booktools/<feature>.py` with a `register(app)` function that attaches its
`@app.command(...)`, then add the module to `CAPABILITIES`.

Five capabilities exist today:
- `booktools/calibre_obsidian.py` → `calibre` — reads a Calibre library's `metadata.opf` (XML) + `cover.jpg` per book and writes Obsidian notes.
- `booktools/goodreads_obsidian.py` → `goodreads` — reads a Goodreads CSV export and writes/merges Obsidian notes, plus a separate `<Title> - Review.md`.
- `booktools/kobo_export.py` → `kobo` — reads `KoboReader.sqlite` (opened **read-only** via `file:...?mode=ro`) and exports per-book highlight CSVs into a zip. Has a `--csv` flag (the default output mode) and an `--obsidian` flag that writes per-book `Highlights.md` notes (rendered via the shared `booktools/highlights.py`) embedded into the canonical book note. Note markers follow the `#tag` / `@link` convention (parsed via `highlights.parse_markers`).
- `booktools/highlighted_obsidian.py` → `highlighted` — reads a Highlighted app CSV export (highlights from physical books, page-located) and writes per-book `Highlights.md` notes (via the shared `booktools/highlights.py`) embedded into the canonical book note. Its `Tags` column follows the `#tag` / `@link` convention (`highlights.split_tag_column`).
- `booktools/readwise_obsidian.py` → `readwise` — reads a Readwise CSV export and writes per-book `Highlights.md` notes (via `booktools/highlights.py`) embedded into the canonical book note. Fills `amazon`/`shelves`/`series`/`series_index` frontmatter, renders type-aware location labels (`p.`/`loc.`), and matches existing notes by Amazon id then standardized title/author. Its `Tags` column follows the `#tag` / `@link` convention (`highlights.split_tag_column`).

**The `#tag` / `@link` convention** (in `booktools/highlights.py`): highlight annotations
carry two marker kinds — `#tag` renders as an Obsidian inline tag, `@link` renders as a
`[[wikilink]]`. Inline in free-form note text (Kobo), `parse_markers` captures each marker
until the next `@`/`#`/newline. In CSV tag columns (Highlighted, Readwise), `split_tag_column`
comma-splits and routes `@`-prefixed entries to links. Links are title-cased with dashes
turned into spaces (`@battle-of-warsaw` → `[[Battle of Warsaw]]`); tags are lowercased slugs.
Links render on the `[!quote]` callout **title line** (middot-joined after the locator, e.g.
`ch. 2 · 42% · [[Trotsky]]`) so people/events scan from the header; tags render on a trailing
line inside the callout body. The author's note sits between them as a nested blockquote (`>>`).

**Chapter subheaders** (in `booktools/highlights.py`, `render_highlights`): when a source
knows chapter titles, highlights group under `## Chapter Title` markdown headers so all the
highlights for a chapter collect under one heading. Grouping triggers when **any** highlight
carries a `chapter_title`; if none do, the output stays flat (unchanged) so page-based sources
(Highlighted) and chapter-less exports (Readwise) are unaffected. In grouped mode a header is
emitted at each chapter change (consecutive-run grouping in reading order), and each callout's
locator drops the now-redundant `ch. N` (keeps `42%`/`p.`/`loc.`). A source's reading-order
index — which may not be the book's printed chapter number — renders as a hidden Obsidian
comment beneath the header (`%% {chapter_label} {index} %%`); the label is a `chapter_label`
argument to `render_highlights` (Kobo passes `"Kobo ch."`, so `%% Kobo ch. 12 %%`), omitted
when no label is given. A title-less highlight sitting among titled ones falls back to a
`## Chapter {index}` header. Highlights are never separated by `---` dividers (blank line only).

### The shared Obsidian layer

`booktools/obsidian.py` is the heart of the design and the reason the Calibre and
Goodreads importers compose. Read it before changing either importer. It owns:

- **A canonical frontmatter schema** (`BOOK_PROPERTY_ORDER`). Every book note emits
  all keys (empty when unknown) so any importer or a manual edit can fill a field later.
- **The "never overwrite" merge rule** (`update_frontmatter`): fills only absent or
  blank keys, leaves non-empty values and the note body untouched, appends new keys in
  canonical order. This is what lets Calibre → Goodreads (in either order) plus hand
  edits accumulate without clobbering. `write_if_absent` enforces the same rule at the
  file level (used for hub/stub notes and reviews).
- **Matching normalization** used to detect that a Goodreads row and an existing Calibre
  note are the same book: `norm_title`, `norm_isbn`, `author_key` (reduces names to
  (first, last), handling "Last, First"), and `fold` (accent/case folding).
- **Formatting + parsing helpers**: `yaml_quote`, `wikilink`/`link_list` (authors and
  genres become `[[wikilinks]]` for Obsidian's graph), `html_to_markdown` (book
  descriptions/reviews), and frontmatter readers (`frontmatter_values`, `unquote`,
  `extract_wikilinks`).

Both importers are stdlib-only (Typer is the sole runtime dependency); prefer keeping
new shared logic in `obsidian.py` rather than duplicating it per importer.

### Path handling

All CLI path arguments pass through `booktools.resolve_path` (in `__init__.py`): absolute
and `~` paths are used as-is; relative paths resolve against the cwd (or home for some
defaults). Use it for any new path option.

### Standalone shims

`scripts/*.py` are thin shims that import and call each module's `main()` so a single
capability runs without the full `books` install. They must stay in sync with the module
they wrap (the module is the single source of truth).

## Docs

Design specs and implementation plans live under `docs/superpowers/`. Those files
reference the older `*-to-obsidian` / `kobo-export` command names — treat them as
historical records, not current usage.
