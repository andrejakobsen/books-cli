# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                              # create the venv and install deps (incl. dev)
uv run books --help                  # run the CLI without a global install
uv run pytest -q                     # run the full test suite
uv run pytest tests/renderers/obsidian/test_obsidian.py # run one test file
uv run pytest -k "author_key"        # run tests matching an expression
uv tool install . --reinstall        # rebuild & reinstall the global `books` command
uv run ruff check --fix              # lint & auto-fix
uv run ruff format                   # format
```

Linting/formatting is done with **ruff** (config in `pyproject.toml`).

## Git workflow

Commit work directly to `main` in this repo — do **not** create feature branches or
open PRs for changes. This overrides the default "branch first when on the default
branch" behavior. Before committing, always run **both** `uv run ruff check --fix`
+ `uv run ruff format` (fix any remaining lint errors) and `uv run pytest -q`.

## Architecture

Single Typer CLI (`books`) that fans out to independent capability modules. The
entry point is `books/cli.py`, which builds one shared `Typer` app and calls
`register(app)` on every module listed in `CAPABILITIES`. **To add a capability:**
create `books/commands/<feature>.py` (or a `books/commands/<feature>/` package with a
re-exporting `__init__.py`) exposing a `register(app)` function that attaches its
`@app.command(...)`, then add the module to `CAPABILITIES` in `books/cli.py`.

The package is organized in three layers with a one-way dependency direction
(`commands → renderers → core`):
- **`books/core/`** — format-agnostic building blocks: `paths.py` (`resolve_path`),
  `config.py` (vault/imports resolution), `store.py` (the CSV catalog + per-book
  highlights data model), `highlights.py` (the `Highlight` model, `#tag`/`@link`
  marker parsing, and reading-order `sort_key`), `matching.py` (the `BookRef` identity
  dataclass + `norm_title`/`norm_isbn`/`norm_amazon`/`author_key`/`fold` normalization),
  and `naming.py` (the `<Title> - <Author>` note-stem/filename logic: `safe_filename`,
  `strip_subtitle`, `stem_for` (the single `<Title> - <Author>` join point), and
  `next_free_stem`) — none of it carries markdown/Obsidian knowledge.
  The `store` and the Obsidian renderer both consume these identity helpers, importing
  them directly from `core` (the renderer no longer re-exports them).
  `matching.py` also owns the fuzzy match helpers used by `store` (`canonical_isbn`,
  `title_similar`, and the `TITLE_MATCH_THRESHOLD` rapidfuzz cutoff).
- **`books/renderers/`** — output targets. `books/renderers/obsidian/` owns 100% of the
  Obsidian/markdown-specific code (a future renderer slots in beside it). Its
  `__init__.py` re-exports the public API so call sites use `from books.renderers.obsidian
  import X`.
- **`books/commands/`** — the CLI capabilities, each exposing `register(app)`.

Three commands exist today: **`import`** (ingest raw sources into the CSV store),
**`export`** (render the store into notes), and **`reset`** (wipe the derived
store). The former per-source importers (`calibre`, `goodreads`, `kobo`,
`highlighted`, `readwise`, `audible`, `covers`) and `merge` are now internal
modules driven by `import` rather than standalone commands; `render` was renamed
to `export` and `sync` was absorbed into `import`.

Under the hood the store is built by a **two-phase CSV-store pipeline**
(see `books/core/store.py`). The source importers are pure **CSV writers** — none of
them touch the Obsidian notes:

- **Phase A — metadata → catalog.** The `calibre` and `goodreads` importers each write a
  per-source metadata layer (`Data/Sources/<source>.csv`) via `store.write_layer`; `import`
  then clusters the layers into the single merged catalog `Data/books.csv` via `store.merge`
  (the merge step is injected automatically, so callers never sequence it).
- **Phase B — highlights → notes.** The four highlight importers (`kobo`, `highlighted`,
  `readwise`, `kindle`) resolve each book to a `book_id` against the merged catalog
  (`store.Catalog(vault).find(BookRef)` — match-only, never creates) and write its
  highlights into `Data/Highlights/<book_id>.csv` via `store.write_highlights` (a book
  with no catalog match is skipped and counted, so the merge runs first). `export`
  then turns the catalog + highlights into the actual `Books/*.md` notes. Kindle
  clippings are an append-only event log, so the importer deduplicates adjusted
  highlights (keeps the latest by timestamp, matching on location overlap) and attaches
  notes to their highlights.

`import` orchestrates both phases end to end (running the configured default set of
importers with `merge` injected automatically). `audible` and `covers` are two more CSV
writers that both resolve books via `store.Catalog.find` and enrich the store post-merge
(audible writes highlights + an `audible` metadata layer; covers stages an image + a
`covers` metadata layer) — they are **opt-in** (run only when selected via
`import --audible`/`--covers` or added to `[import].default`), and `import` re-merges after
them automatically. `export` is the sole producer of Obsidian notes; note creation belongs
solely to it.
- `books/commands/import_cmd.py` → `import` — the single ingest command. With no
  flags it runs the configured default set (out of the box the sync-set:
  `calibre`, `goodreads`, `kobo`, `highlighted`, `readwise`, `kindle`; change it via
  `[import].default` in the config, e.g. to add `covers`/`audible`); importer
  flags (`--calibre` … `--readwise`, `--kindle`, plus opt-in `--audible`/`--covers`) select
  an exact subset. `merge` is injected
  automatically (before catalog consumers, after layer writers). Each importer
  detects its own source and is skipped/reported when absent; a failing step
  never stops the others. Kindle reads `Data/Imports/kindle/My Clippings.txt` (or a
  mounted Kindle's `documents/My Clippings.txt`, auto-detected). Reads per-importer
  settings from the `[calibre]`, `[kobo]`, `[audible]`, `[covers]`, `[kindle]` config
  sections. Stops at the store — run
  `export` to write notes. `--output` overrides the vault; `--dry-run` prints the
  plan. The importer cores live in their own modules
  (`books/commands/{calibre,goodreads,kobo,highlighted,readwise}.py` and the
  `audible`/`covers`/`kindle` packages, whose `run_import(vault, cfg)` entry points read
  config); `store.merge` clusters the layers.
- `books/commands/export.py` → `export` — the CSV-store renderer (formerly
  `render`). Reads the merged catalog + per-book highlights and writes one flat
  note per book under `Books/`. `--obsidian` selects the (default, only) format;
  `--refresh` does a clean rebuild of `Books/`/`Authors/`; `--output` overrides
  the vault. Note assembly lives in `books/renderers/obsidian/note.py`.
- `books/commands/reset.py` → `reset` — deletes the purely-derived CSV store
  (`Data/books.csv` + `Data/Highlights/`) so a later `import` rebuilds it.
  `--dry-run` previews; `--yes`/`-y` skips the confirm. Recovery flow:
  `reset` → `import` → `export` (plus `import --audible`/`--covers` as needed).

### Configuration

`books/core/config.py` supplies the default Obsidian vault. It reads
`~/.config/books/config.toml` (respecting `$XDG_CONFIG_HOME`), auto-creating it
with defaults on first run: `obsidian_path` (the folder holding your vaults, default
`~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian`) and `vault` (the vault
name, default `History`). `default_vault()` joins them; `resolve_vault(output)` is
the single helper every command calls — explicit `--output` wins, otherwise the
configured vault is used. This is why most commands need no `--output`. Reads use
stdlib `tomllib` (Python 3.11+); malformed/partial config falls back per key.

The `imports` key (default `Data/Imports`) names a folder **inside** the vault
that holds raw import sources (grouped under `Data/` with the CSV store); `resolve_imports(name, output)` returns
`<vault>/<imports>/<name>` (an absolute `imports` value is honored as-is, a relative one
joins onto the resolved vault). Most importers default their input to a canonical
subfolder — `Data/Imports/goodreads`, `Data/Imports/highlighted`,
`Data/Imports/readwise`, `Data/Imports/kobo`, `Data/Imports/kindle` (which holds
`My Clippings.txt`, not raw CSVs), and `Data/Imports/audible` (which holds the
transcription cache under `cache/`, not raw CSVs) — so most commands need no input flag.
(`calibre` is the exception: `--library` defaults to `~/Calibre Library`.) For the
single-file CSV importers (goodreads/readwise), `newest_csv(folder)` picks the
most-recently-modified top-level `*.csv` and `resolve_csv_arg(csv, name, output)` resolves
an unset/folder/file `--csv` to one CSV (unset → newest in the canonical subfolder).

The `[import].default` list names the importers `books import` runs when given no
flags (default: the sync-set; add `"covers"`/`"audible"` to include them). Unknown
names are dropped and an empty/invalid list falls back to the sync-set.
Per-importer settings live in optional `[calibre]`, `[kobo]`, `[audible]`,
`[covers]`, and `[kindle]` config sections: `[calibre].library` (default `~/Calibre Library`),
`[kobo].db` (default: auto-detect a mounted device / the imports folder),
`[audible].transcriber` (`local`/`openai`/`google`) + `[audible].select`
(`interactive`/`all`), `[covers].interactive` + `[covers].limit`, and
`[kindle].clippings` (default: auto-detect a mounted Kindle / the imports folder). Each key
falls back to its built-in default when absent or malformed. With
`[audible].select = "interactive"` (the default) the arrow-key picker chooses
which audiobooks to transcribe; run off-tty (no terminal) the audible step is
**skipped** with a message rather than transcribing the whole library — set
`select = "all"` to run it unattended.

**The `#tag` / `@link` convention** (parsing in `books/core/highlights.py`, rendering in `books/renderers/obsidian/highlights.py`): highlight annotations
carry two marker kinds — `#tag` renders as an Obsidian inline tag, `@link` renders as a
`[[wikilink]]`. Inline in free-form note text (Kobo), `parse_markers` captures each marker
until the next `@`/`#`/newline. In CSV tag columns (Highlighted, Readwise), `split_tag_column`
comma-splits and routes `@`-prefixed entries to links. Links are title-cased with dashes
turned into spaces (`@battle-of-warsaw` → `[[Battle of Warsaw]]`); tags are lowercased slugs.
Links render on the `[!quote]` callout **title line** (middot-joined after the locator, e.g.
`ch. 2 · 42% · [[Trotsky]]`) so people/events scan from the header; tags render on a trailing
line inside the callout body. The author's note sits between them as a nested blockquote (`>>`).

**Chapter subheaders** (in `books/renderers/obsidian/highlights.py`, `render_highlights`): when a source
knows chapter titles, highlights group under `### Chapter Title` markdown headers (level 3,
because the whole block sits under a `## Highlights` section) so all the highlights for a
chapter collect under one heading. Grouping triggers when **any** highlight carries a
`chapter_title`; if none do, the output stays flat (unchanged) so page-based sources
(Highlighted) and chapter-less exports (Readwise) are unaffected. In grouped mode a header is
emitted at each chapter change (consecutive-run grouping in reading order). Each callout's
locator always keeps the chapter, prefixed by the `chapter_label` argument to
`render_highlights` when given (Kobo passes `"Kobo ch."` → `Kobo ch. 12 · 42%`) or `"ch."`
otherwise. A title-less highlight sitting among titled ones falls back to a `### Chapter {index}`
header. Highlights are never separated by `---` dividers (blank line only).

**Ordering** (`render_highlights` in `books/renderers/obsidian/highlights.py` via `sort_key` from `books/core/highlights.py`): `render_highlights`
always sorts its input into reading order before rendering, so output is ordered regardless of the
caller's input order — by `chapter_index`, then `progress` (% within chapter), then the leading page
number, then KoboSpan `block`/`segment`. Missing components sort last (located highlights lead), and
equal keys keep their original order (stable sort). This is why chapter grouping stays correct even if
a source hands over scattered rows (Readwise/Highlighted preserve CSV order, which isn't guaranteed to
be reading order); Kobo's SQL `ORDER BY` produces the same order and is merely reinforced.

### The shared Obsidian layer

The `books/renderers/obsidian/` package is the heart of the design and the reason the
Calibre and Goodreads importers compose. Read it before changing either importer. Its
`__init__.py` re-exports its own public API (so call sites do `from
books.renderers.obsidian import X`); the format-agnostic identity helpers are imported
directly from `books/core/{matching,naming}.py` (the renderer no longer re-exports them).
It is split by responsibility across `layout.py` (folder constants + hub-stub helpers),
`frontmatter.py` (the `BOOK_PROPERTY_ORDER` schema + a split helper),
`sections.py` (section helpers), `format.py` (`format_rating`/`wikilink`),
and `highlights.py` (`render_highlights`). It owns:

- **The flat vault layout.** The note folders live at the top level — `Books/` (the
  indexed book notes) and `Authors/` (stub/hub notes `export` creates) — while all
  tool-managed data lives under `Data/`: `Data/Covers/` (flat cover images named
  `<Title> - <Author>.jpg`), `Data/Imports/` (raw import sources), and the CSV store
  (`Data/Sources/`, `Data/Highlights/`, `Data/books.csv`). There is no per-book
  `Exports/<Author>/<Title>/` folder any more; a book note is a single self-contained
  file. The tool-managed folder names are constants in `layout.py` (`BOOKS_DIRNAME`,
  `COVERS_DIRNAME` = `Data/Covers`, `AUTHORS_DIRNAME`).
- **The book note anatomy.** A book note is frontmatter + a cover embed
  (`![[Data/Covers/<stem>.jpg|150]]`, width from `COVER_WIDTH`) + an optional write-once
  `## Review` section + a marker-wrapped `## Highlights` section. Personal notes are not
  in the book note; the user can keep fully manual notes anywhere else in the vault.
- **A canonical frontmatter schema** (`BOOK_PROPERTY_ORDER`). Every book note emits
  all keys (empty when unknown) so any importer or a manual edit can fill a field later.
  The key is `topics` (not `genres`), and `cover` is the last key. `highlighted` and
  `reviewed` are booleans (defaulting to `false`) that flip to `true` when highlights or
  a review are imported, used for filtering the vault on reading progress.
- **Authoritative frontmatter, at merge not export.** Accumulation now happens in the
  CSV store: the merge step (`store.merge`, run automatically by `import`) clusters the
  per-source layers so Calibre → Goodreads (in either order) build up a single row, and
  `export` writes each note's canonical frontmatter
  authoritatively from that row (see `export.py` for the per-key rules: `topics` is
  user-owned, `highlighted`/`reviewed` are derived, etc.). The old note-level
  `update_frontmatter` "never overwrite" merge helper has been deleted. `write_if_absent`
  still enforces a write-once rule at the file level (used for hub/stub notes).
- **Section helpers** for idempotent re-imports. `render_marked_section(text, heading,
  marker, content)` wraps `content` between `%% books:<marker>:start %%` / `:end %%`
  comment markers under a `## heading`; on re-runs it replaces everything between the
  markers wholesale (used for `## Highlights`, so the last importer wins and hand edits
  outside the markers survive). `ensure_section(text, heading, content)` is write-once:
  it appends a `## heading` section only if that heading is absent (used for `## Review`,
  so a hand-edited review is never clobbered).
- **Cover materialization**: `export` reads each row's staged cover path and writes the
  flat `Data/Covers/<stem>.jpg` file plus the `![[…|150]]` embed (width from `COVER_WIDTH`).
- **Matching normalization** used to cluster rows for the same book: `norm_title`,
  `norm_isbn`, `author_key` (reduces names to (first, last), handling "Last, First"), and
  `fold` (accent/case folding). These live in `books/core/matching.py` (format-agnostic)
  and are imported directly from `core` by both `store` and the renderer.
- **Book identity resolution** (`store.Catalog.find`): every importer resolves a `BookRef`
  to a `book_id` against the merged catalog by ISBN, then Amazon id, then standardized
  (title, author) — match-only, never creating. (The old `VaultIndex` note-resolution class
  has been deleted; `export` is the sole producer of notes and writes them directly from the
  store.)
- **Flat note filenames** (`books/core/naming.py` — `next_free_stem`/`strip_subtitle`/`stem_for`/`safe_filename`,
  driven via `store.assign_book_id`): new book notes
  are named `<Title> - <Author>.md` with the subtitle (anything after the first `:`) dropped
  — e.g. `The Deluge - Adam Tooze.md`. Only the filename is decluttered; the frontmatter
  `title` keeps the full title (matching uses the full title, so this is safe). When the
  clean stem is already taken (e.g. two Kotkin "Stalin" volumes), the colliding note
  restores its subtitle to disambiguate, rendering the illegal `:` as `,`
  (`Stalin, Waiting for Hitler, 1929-1941 - Stephen Kotkin.md`); a numeric `(n)` suffix is
  the last resort. Existing notes are matched by frontmatter and never renamed, so only
  newly-created notes use this scheme. The note stem also names the book's `Data/Covers/`
  image, keeping the two in lockstep.
- **Formatting helpers**: `format_rating` (0-5 → star emoji) and `wikilink` (authors and
  topics become `[[wikilinks]]` for Obsidian's graph). `export` handles its own YAML
  round-tripping via python-frontmatter + ruamel.yaml, so the old string-level
  `yaml_quote`/`link_list`/`html_to_markdown`/frontmatter-reader helpers are gone.

The core runtime deps are deliberately lean — `typer` (CLI), `pydantic` (the store's
`BookRow`/`HighlightRow` models), `isbnlib` + `rapidfuzz` (ISBN/title matching in
`books/core/matching.py`), and `python-frontmatter` + `ruamel.yaml` (the renderer's YAML
round-trip). Everything else is stdlib; the CSV importers themselves add nothing beyond
these. Prefer keeping new shared logic in `books/renderers/obsidian/` (or `books/core/`
for format-agnostic pieces) rather than duplicating it per importer.

> **Heavier optional deps:** the `audible` capability needs third-party packages
> (`audible`, transcriber backends) and system `ffmpeg`. They are an optional
> `[audible]` extra in `pyproject.toml`, imported lazily inside
> `books/commands/audible/command.py` / `client.py` / `transcribe.py` so no
> other command loads them. `cryptography` is an optional-but-recommended accelerator
> for the `audible` package's decryption. Downloading/decrypting owned audiobooks is
> for personal archival use only.

### Path handling

All CLI path arguments pass through `resolve_path` (in `books/core/paths.py`): absolute
and `~` paths are used as-is; relative paths resolve against the cwd (or home for some
defaults). Use it for any new path option.

## Docs

Design specs and implementation plans live under `docs/superpowers/`. Those files
reference the older `*-to-obsidian` / `kobo-export` command names — treat them as
historical records, not current usage.
