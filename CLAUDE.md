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

## Git workflow

Commit work directly to `main` in this repo — do **not** create feature branches or
open PRs for changes. This overrides the default "branch first when on the default
branch" behavior. Run `uv run pytest -q` before committing.

## Architecture

Single Typer CLI (`books`) that fans out to independent capability modules. The
entry point is `booktools/cli.py`, which builds one shared `Typer` app and calls
`register(app)` on every module listed in `CAPABILITIES`. **To add a capability:**
create `booktools/<feature>.py` with a `register(app)` function that attaches its
`@app.command(...)`, then add the module to `CAPABILITIES`.

Six capabilities exist today:
- `booktools/calibre_obsidian.py` → `calibre` — reads a Calibre library's `metadata.opf` (XML) + `cover.jpg` per book and writes Obsidian notes. `--library` defaults to `<vault>/.imports/calibre`.
- `booktools/goodreads_obsidian.py` → `goodreads` — reads a Goodreads CSV export and writes/merges Obsidian notes, plus a separate `<Title> - Review.md`. `--csv` accepts a single CSV file or a folder (newest `*.csv`), defaulting to `<vault>/.imports/goodreads`.
- `booktools/kobo_export.py` → `kobo` — reads `KoboReader.sqlite` (opened **read-only** via `file:...?mode=ro`) and exports per-book highlight CSVs into a zip. Has a `--csv` flag (the default output mode) and an `--obsidian` flag that writes per-book `Highlights.md` notes (rendered via the shared `booktools/highlights.py`) embedded into the canonical book note. Note markers follow the `#tag` / `@link` convention (parsed via `highlights.parse_markers`). When no DB path is given, a mounted Kobo (`/Volumes/KOBOeReader/.kobo/KoboReader.sqlite`) is safely snapshotted into `<vault>/.imports/kobo/` via SQLite's read-only backup API (the device file is never modified) and read from there; otherwise the existing copy (or newest `*.sqlite`) in that folder is used.
- `booktools/highlighted_obsidian.py` → `highlighted` — reads a Highlighted app CSV export (highlights from physical books, page-located) and writes per-book `Highlights.md` notes (via the shared `booktools/highlights.py`) embedded into the canonical book note. `--csv` accepts a single CSV file or a folder of CSV exports (every top-level `*.csv` is imported in sorted order; a file that fails to parse is skipped and reported), defaulting to `<vault>/.imports/highlighted`. Its `Tags` column follows the `#tag` / `@link` convention (`highlights.split_tag_column`).
- `booktools/readwise_obsidian.py` → `readwise` — reads a Readwise CSV export and writes per-book `Highlights.md` notes (via `booktools/highlights.py`) embedded into the canonical book note. `--csv` accepts a single CSV file or a folder (newest `*.csv`), defaulting to `<vault>/.imports/readwise`. Fills `amazon`/`shelves`/`series`/`series_index` frontmatter, renders type-aware location labels (`p.`/`loc.`), and matches existing notes by Amazon id then standardized title/author. Its `Tags` column follows the `#tag` / `@link` convention (`highlights.split_tag_column`).
- `booktools/covers.py` → `covers` — scans an existing vault for `type: book` notes with a blank `cover:` field and fetches a cover image. Sources are tried in order — Google Books, then Open Library (paperback editions preferred where `physical_format` is known), then Amazon (only when the note already has an `amazon` ASIN, by building the known cover-image URL — no scraping). Stdlib-only (`urllib`); all network I/O is injected for testing. Writes `cover.jpg` into `Exports/<Author>/<Title>/` and fills the note's `cover:` frontmatter + top embed via the shared `obsidian.py` helpers (never overwriting an existing cover). Default mode auto-picks the best match; `--interactive` approves each candidate, `--dry-run` previews, `--limit N` caps the run. `--book PATH` targets a single note under `Books/` (vault inferred from the path) and is interactive by default.

### Configuration

`booktools/config.py` supplies the default Obsidian vault. It reads
`~/.config/booktools/config.toml` (respecting `$XDG_CONFIG_HOME`), auto-creating it
with defaults on first run: `obsidian_path` (the folder holding your vaults, default
`~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian`) and `vault` (the vault
name, default `History`). `default_vault()` joins them; `resolve_vault(output)` is
the single helper every command calls — explicit `--output` wins, otherwise the
configured vault is used. This is why most commands need no `--output`. Reads use
stdlib `tomllib` (Python 3.11+); malformed/partial config falls back per key.

The new `imports` key (default `.imports`) names a hidden folder **inside** the vault
that holds raw import sources; `resolve_imports(name, output)` returns
`<vault>/<imports>/<name>` (an absolute `imports` value is honored as-is, a relative one
joins onto the resolved vault). Every importer defaults its input to its canonical
subfolder — `.imports/calibre`, `.imports/goodreads`, `.imports/highlighted`,
`.imports/readwise`, `.imports/kobo` — so most commands need no input flag. For the
single-file CSV importers (goodreads/readwise), `newest_csv(folder)` picks the
most-recently-modified top-level `*.csv` and `resolve_csv_arg(csv, name, output)` resolves
an unset/folder/file `--csv` to one CSV (unset → newest in the canonical subfolder).

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

**Ordering** (in `booktools/highlights.py`, `render_highlights` via `sort_key`): `render_highlights`
always sorts its input into reading order before rendering, so output is ordered regardless of the
caller's input order — by `chapter_index`, then `progress` (% within chapter), then the leading page
number, then KoboSpan `block`/`segment`. Missing components sort last (located highlights lead), and
equal keys keep their original order (stable sort). This is why chapter grouping stays correct even if
a source hands over scattered rows (Readwise/Highlighted preserve CSV order, which isn't guaranteed to
be reading order); Kobo's SQL `ORDER BY` produces the same order and is merely reinforced.

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
- **Flat note filenames** (`VaultIndex._new_note_path` + `strip_subtitle`): new book notes
  are named `<Title> - <Author>.md` with the subtitle (anything after the first `:`) dropped
  — e.g. `The Deluge - Adam Tooze.md`. Only the filename is decluttered; the frontmatter
  `title` and the `Exports/<Author>/<Title>/` folder keep the full title (matching uses the
  full title, so this is safe). When the clean stem is already taken (e.g. two Kotkin
  "Stalin" volumes), the colliding note restores its subtitle to disambiguate, rendering the
  illegal `:` as `,` (`Stalin, Waiting for Hitler, 1929-1941 - Stephen Kotkin.md`); a numeric
  `(n)` suffix is the last resort. Existing notes are matched by frontmatter and never renamed,
  so only newly-created notes use this scheme.
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
