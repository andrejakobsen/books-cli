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

Seven capabilities exist today. **Two of them create book notes (`calibre`, `goodreads`);
the three highlight importers (`kobo`, `highlighted`, `readwise`) only enrich existing
notes and never create them** — a book with no matching note is skipped and counted
(run `calibre`/`goodreads` first to establish book identity). This is enforced in code
via `VaultIndex.find` (match-only) vs `VaultIndex.find_or_create` (creates). A seventh
(`sync`) is an orchestrator that runs the importers in order and creates nothing itself.
- `booktools/calibre_obsidian.py` → `calibre` — reads a Calibre library's `metadata.opf` (XML) + `cover.jpg` per book and writes Obsidian notes (creates notes via `find_or_create`). `--library` defaults to `~/Calibre Library`.
- `booktools/goodreads_obsidian.py` → `goodreads` — reads a Goodreads CSV export and writes/merges Obsidian notes (creates notes via `find_or_create`). A review is written once into a write-once `## Review` section of the book note (never clobbered on re-runs). `--csv` accepts a single CSV file or a folder (newest `*.csv`), defaulting to `<vault>/.imports/goodreads`.
- `booktools/kobo_export.py` → `kobo` — reads `KoboReader.sqlite` (opened **read-only** via `file:...?mode=ro`) and exports per-book highlight CSVs into a zip. Has a `--csv` flag (the default output mode) and an `--obsidian` flag that renders highlights (via the shared `booktools/highlights.py`) into a marker-wrapped `## Highlights` section of an **existing** book note (matched via `VaultIndex.find`; unmatched books are skipped and counted). Note markers follow the `#tag` / `@link` convention (parsed via `highlights.parse_markers`). When no DB path is given, a mounted Kobo (`/Volumes/KOBOeReader/.kobo/KoboReader.sqlite`) is safely snapshotted into `<vault>/.imports/kobo/` via SQLite's read-only backup API (the device file is never modified) and read from there; otherwise the existing copy (or newest `*.sqlite`) in that folder is used.
- `booktools/highlighted_obsidian.py` → `highlighted` — reads a Highlighted app CSV export (highlights from physical books, page-located) and renders highlights (via the shared `booktools/highlights.py`) into a marker-wrapped `## Highlights` section of an **existing** book note (matched via `VaultIndex.find`; unmatched books are skipped and counted). `--csv` accepts a single CSV file or a folder of CSV exports (every top-level `*.csv` is imported in sorted order; a file that fails to parse is skipped and reported), defaulting to `<vault>/.imports/highlighted`. Its `Tags` column follows the `#tag` / `@link` convention (`highlights.split_tag_column`).
- `booktools/readwise_obsidian.py` → `readwise` — reads a Readwise CSV export and renders highlights (via `booktools/highlights.py`) into a marker-wrapped `## Highlights` section of an **existing** book note (matched via `VaultIndex.find` by Amazon id then standardized title/author; unmatched books are skipped and counted). `--csv` accepts a single CSV file or a folder (newest `*.csv`), defaulting to `<vault>/.imports/readwise`. Fills `amazon`/`shelves`/`series`/`series_index` frontmatter, renders type-aware location labels (`p.`/`loc.`). Its `Tags` column follows the `#tag` / `@link` convention (`highlights.split_tag_column`).
- `booktools/sync.py` → `sync` — master orchestrator that runs the importers in dependency order using each command's default options: `calibre` → `goodreads` → `kobo` → `highlighted` → `readwise` (covers is **not** included). Each step is skipped when its source is absent (calibre: `~/Calibre Library` exists; goodreads/highlighted/readwise: a `*.csv` in the `.imports/<name>` folder; kobo: a mounted device or a `*.sqlite` in `.imports/kobo`). Each step calls the module's core function directly (`convert`/`export_obsidian`) — no shelling out. Failures are reported but never stop the remaining steps (continue-on-error); a colored per-step + summary report is printed via `typer.secho`. `--output` overrides the vault; `--dry-run` prints the detection plan without writing. Creates no notes itself — it delegates note creation to `calibre`/`goodreads`.
- `booktools/covers.py` → `covers` — scans an existing vault for `type: book` notes with a blank `cover:` field and fetches a cover image. Sources are tried in order — Google Books, then Open Library (paperback editions preferred where `physical_format` is known), then Amazon (only when the note already has an `amazon` ASIN, by building the known cover-image URL — no scraping). When a note carries an ISBN it drives the lookup directly (Google `isbn:` query / Open Library `/b/isbn/` cover) — the most reliable path, unaffected by Google's title-search rate limiting. Stdlib-only (`urllib`); all network I/O is injected for testing. HTTP fetches retry transient failures (429/5xx) with exponential backoff (`fetch_with_retry`), and a source that errors outright (rate-limited/unreachable) is counted and reported separately from one that merely found no match. Author/title queries are normalized before sending (`normalize_author` collapses whitespace and drops translator/co-author tails like "Plato and Benjamin Jowett" → "Plato"). Fetched images are validated by parsing their pixel dimensions (`image_dimensions`, PNG/GIF/JPEG headers, stdlib) and rejecting anything below `MIN_IMAGE_DIM`, falling back to a byte-size check when dimensions are unparseable. An ISBN learned from a source is backfilled into the note's frontmatter (never overwriting an existing one). Writes `<Title> - <Author>.jpg` into the flat `Covers/` folder and fills the note's `cover:` frontmatter + top embed (at width 150) via the shared `obsidian.py` helpers (never overwriting an existing cover). Default mode auto-picks the best match; `--interactive` approves each candidate, `--dry-run` previews, `--limit N` caps the run. `--book PATH` targets a single note under `Books/` (vault inferred from the path) and is interactive by default.

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
joins onto the resolved vault). Most importers default their input to a canonical
subfolder — `.imports/goodreads`, `.imports/highlighted`,
`.imports/readwise`, `.imports/kobo` — so most commands need no input flag.
(`calibre` is the exception: `--library` defaults to `~/Calibre Library`.) For the
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

- **The flat vault layout.** Everything lives in top-level folders — `Books/` (the
  indexed book notes), `Covers/` (flat cover images named `<Title> - <Author>.jpg`),
  `Notes/` (fully manual personal notes), `Authors/` and `Topics/` (stub/hub notes).
  There is no per-book `Exports/<Author>/<Title>/` folder any more; a book note is a
  single self-contained file. The folder names are constants in `obsidian.py`
  (`BOOKS_DIRNAME`, `COVERS_DIRNAME`, `NOTES_DIRNAME`, `AUTHORS_DIRNAME`, `TOPICS_DIRNAME`).
- **The book note anatomy.** A book note is frontmatter + a cover embed
  (`![[Covers/<stem>.jpg|150]]`, width from `COVER_WIDTH`) + an optional write-once
  `## Review` section + a marker-wrapped `## Highlights` section. Personal notes are not
  in the book note; the `Notes/` folder holds fully manual notes the user authors by hand.
- **A canonical frontmatter schema** (`BOOK_PROPERTY_ORDER`). Every book note emits
  all keys (empty when unknown) so any importer or a manual edit can fill a field later.
  The key is `topics` (not `genres`), and `cover` is the last key.
- **The "never overwrite" merge rule** (`update_frontmatter`): fills only absent or
  blank keys, leaves non-empty values and the note body untouched, appends new keys in
  canonical order. This is what lets Calibre → Goodreads (in either order) plus hand
  edits accumulate without clobbering. `write_if_absent` enforces the same rule at the
  file level (used for hub/stub notes).
- **Section helpers** for idempotent re-imports. `render_marked_section(text, heading,
  marker, content)` wraps `content` between `%% books:<marker>:start %%` / `:end %%`
  comment markers under a `## heading`; on re-runs it replaces everything between the
  markers wholesale (used for `## Highlights`, so the last importer wins and hand edits
  outside the markers survive). `ensure_section(text, heading, content)` is write-once:
  it appends a `## heading` section only if that heading is absent (used for `## Review`,
  so a hand-edited review is never clobbered).
- **Cover reference helpers**: `cover_path(note_path)` maps a book note to its flat
  `Covers/<stem>.jpg` file; `cover_refs(note_path)` returns the `(frontmatter, embed)`
  pair (the embed carrying `|150`).
- **Matching normalization** used to detect that a Goodreads row and an existing Calibre
  note are the same book: `norm_title`, `norm_isbn`, `author_key` (reduces names to
  (first, last), handling "Last, First"), and `fold` (accent/case folding).
- **Two ways to resolve a book to a note** (`VaultIndex`): `find_or_create(ref)` matches an
  existing note or creates a flat stub for a new book — used only by the note-creating
  importers (`calibre`, `goodreads`). `find(ref)` is match-only: it returns the existing
  `BookNote` or `None` and never creates a file — used by the highlight-only importers
  (`kobo`, `highlighted`, `readwise`), which enrich but never author book identity. Both
  match by ISBN, then Amazon id, then standardized (title, author).
- **Flat note filenames** (`VaultIndex._new_note_path` + `strip_subtitle`): new book notes
  are named `<Title> - <Author>.md` with the subtitle (anything after the first `:`) dropped
  — e.g. `The Deluge - Adam Tooze.md`. Only the filename is decluttered; the frontmatter
  `title` keeps the full title (matching uses the full title, so this is safe). When the
  clean stem is already taken (e.g. two Kotkin "Stalin" volumes), the colliding note
  restores its subtitle to disambiguate, rendering the illegal `:` as `,`
  (`Stalin, Waiting for Hitler, 1929-1941 - Stephen Kotkin.md`); a numeric `(n)` suffix is
  the last resort. Existing notes are matched by frontmatter and never renamed, so only
  newly-created notes use this scheme. The note stem also names the book's `Covers/` image
  and `Notes/` note, keeping the three in lockstep.
- **Formatting + parsing helpers**: `yaml_quote`, `wikilink`/`link_list` (authors and
  topics become `[[wikilinks]]` for Obsidian's graph), `html_to_markdown` (book
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
