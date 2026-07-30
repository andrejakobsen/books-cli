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

Ten capabilities exist today, organized as a **two-phase CSV-store pipeline**
(see `books/core/store.py`). The source importers are pure **CSV writers** — none of
them touch the Obsidian notes:

- **Phase A — metadata → catalog.** `calibre` and `goodreads` each write a per-source
  metadata layer (`Data/Sources/<source>.csv`) via `store.write_layer`; `merge` clusters
  the layers into the single merged catalog `Data/books.csv` via `store.merge`.
- **Phase B — highlights → notes.** The three highlight importers (`kobo`, `highlighted`,
  `readwise`) resolve each book to a `book_id` against the merged catalog
  (`store.Catalog(vault).find(BookRef)` — match-only, never creates) and write its
  highlights into `Data/Highlights/<book_id>.csv` via `store.write_highlights` (a book
  with no catalog match is skipped and counted, so run `merge`/`sync` first). `render`
  then turns the catalog + highlights into the actual `Books/*.md` notes.

`sync` orchestrates both phases end to end. `audible` and `covers` are two more CSV writers
that both resolve books via `store.Catalog.find` and enrich the store post-merge (audible
writes highlights + an `audible` metadata layer; covers stages an image + a `covers`
metadata layer) — they are run **manually after `merge`** (then re-`merge` + `render` to
fold them in), and are **not** part of `sync`. `render` is the sole producer of Obsidian
notes; note creation belongs solely to it.
- `books/commands/calibre.py` → `calibre` — reads a Calibre library's `metadata.opf` (XML) + `cover.jpg` per book into `store.BookRow`s and writes them to `Data/Sources/calibre.csv` via `store.write_layer`. Covers are staged under `Data/Sources/_covers/calibre/<n>.jpg` and their vault-relative path recorded on the row (materialized into `Data/Covers/` later by `render`). Creates no notes. `--library` defaults to `~/Calibre Library`. Run `merge` then `render` to produce notes.
- `books/commands/goodreads.py` → `goodreads` — reads a Goodreads CSV export into `store.BookRow`s and writes them to `Data/Sources/goodreads.csv` via `store.write_layer`. Carries the review **and** the private notes through the row as separate plain-data columns (`review`/`private_notes`) so `render` can compose the write-once `## Review` section (private notes under a `### Private Notes` subheading — the markdown layout lives in the renderer, not here), and fills the `goodreads:` field with the book's full Goodreads URL (`https://www.goodreads.com/book/show/<Book Id>`). Rows are written for every book in the export (all shelves); `merge` clusters them with the calibre layer, so a shared book gets both sources' fields. `--csv` accepts a single CSV file or a folder (newest `*.csv`), defaulting to `<vault>/Data/Imports/goodreads`. Creates no notes.
- `books/commands/merge.py` → `merge` — clusters the per-source layers under `Data/Sources/` into the single merged catalog `Data/books.csv` via `store.merge`. Errors cleanly (`typer.BadParameter`) when no source layer exists yet. Run it after the metadata importers and before `render`.
- `books/commands/kobo.py` → `kobo` — reads `KoboReader.sqlite` (opened **read-only** via `file:...?mode=ro`) and maps every book's highlights & notes (via the shared `books/core/highlights.py` model) into the highlights store (`Data/Highlights/<book_id>.csv`, source `kobo`) via `store.write_highlights`, resolving each book to a `book_id` via `store.Catalog.find` (unmatched books are skipped and counted). It is a store-only importer — the sole knobs are `--db`/`-d` (the sqlite path, matching the `--csv` convention of the other importers) and `--output`/`-o`; there is no CSV/zip export mode any more. Note markers follow the `#tag` / `@link` convention (parsed via `highlights.parse_markers`). When no `--db` is given, a mounted Kobo (`/Volumes/KOBOeReader/.kobo/KoboReader.sqlite`) is safely snapshotted into `<vault>/Data/Imports/kobo/` via SQLite's read-only backup API (the device file is never modified) and read from there; otherwise the existing copy (or newest `*.sqlite`) in that folder is used.
- `books/commands/highlighted.py` → `highlighted` — reads a Highlighted app CSV export (highlights from physical books, page-located) and writes them into the highlights store (source `highlighted`) via `store.write_highlights`, resolving each book to a `book_id` via `store.Catalog.find` (unmatched books are skipped and counted). `--csv` accepts a single CSV file or a folder of CSV exports (every top-level `*.csv` is imported in sorted order; a file that fails to parse is skipped and reported), defaulting to `<vault>/Data/Imports/highlighted`. **This folder-imports-all behavior is intentional and differs from goodreads/readwise:** the Highlighted app exports one CSV *per book*, so all files in the folder must be read to see every book, whereas a goodreads/readwise export is a single whole-library snapshot where the newest file supersedes older ones (`newest_csv`). Its `Tags` column follows the `#tag` / `@link` convention (`highlights.split_tag_column`).
- `books/commands/readwise.py` → `readwise` — reads a Readwise CSV export and writes highlights into the highlights store (source `readwise`) via `store.write_highlights`, resolving each book to a `book_id` via `store.Catalog.find` by Amazon id then standardized title/author (unmatched books are skipped and counted). A trailing `(Series #N)` suffix is split off the title for grouping/matching (series/amazon/shelves metadata is no longer persisted — this importer writes highlights only). Renders type-aware location labels (`p.`/`loc.`). `--csv` accepts a single CSV file or a folder (newest `*.csv`), defaulting to `<vault>/Data/Imports/readwise`. Its `Tags` column follows the `#tag` / `@link` convention (`highlights.split_tag_column`).
- `books/commands/audible/` → `audible` — imports **Audible bookmarks & clips** into the
  CSV store (enrich-only: each library book is matched via `store.Catalog.find` by ASIN as
  `amazon` then title/author; unmatched books are skipped and counted). For a matched book
  it writes per-book highlights (`store.write_highlights`, source `audible`) and a small
  `audible` metadata layer (`Data/Sources/audible.csv`, carrying `format: audiobook` + the
  ASIN) via `store.write_layer`; run `merge` + `render` afterward to fold the layer in and
  render the `## Highlights` section. Authenticates to the Audible cloud (auto-prompt on
  first run, auth cached at `~/.config/books/audible-auth.json`), fetches each book's
  annotations, downloads the audiobook, and uses **ffmpeg** to decrypt (AAXC via
  `-audible_key`/`-audible_iv`) and cut each clip, then transcribes it with a pluggable
  backend (`--transcriber local|openai|google`, default `local` faster-whisper). Clips use
  their own start→end. **The sidecar is de-duplicated** (`annotations_from_sidecar`): making
  a clip auto-creates a twin `audible.bookmark` at the same position, and a note is stored
  BOTH on the clip (`metadata.note`) AND as a separate `audible.note` record — so each
  position is collapsed to **one** annotation. Bookmarks are dropped entirely (twins and
  lone marks); a clip keeps its `metadata.title`/`metadata.note` (adopting a same-position
  note record's `text` when it has no `metadata.note`); a standalone note with no clip at
  its position is kept as a *text-only* annotation (`end == start`, so `run` renders it from
  its text without downloading/cutting/transcribing). A clip's own **title and note** are
  merged (title first, then note body) into the highlight's nested blockquote, with their
  `#tag`/`@link` markers parsed out and pooled (same convention as Kobo). Transcriptions
  are cached in `<vault>/Data/Imports/audible/cache.json` (keyed by ASIN + annotation id),
  so re-runs re-render for free and only download books with new clips; downloaded audio is
  written to a temp dir and deleted. `book_highlight_rows` renders only ids present in the
  current run's annotations, so a cache written before this dedup never resurfaces the old
  duplicate rows. Runs after `merge`; **not** part of `sync`. Lives as a
  package (`command.py` + `models.py` + `client.py` + `transcribe.py`), with the shared
  dataclasses (`Annotation`, `Chapter`, `DownloadedAudio`, `LibraryBook`) in `models.py`.
- `books/commands/sync.py` → `sync` — master orchestrator that runs the full two-phase pipeline in dependency order using each command's default options: `calibre` → `goodreads` → `merge` → `kobo` → `highlighted` → `readwise` → `render` (covers and audible are **not** included). The source-detection steps are skipped when their source is absent (calibre: `~/Calibre Library` exists; goodreads/highlighted/readwise: a `*.csv` in the `Data/Imports/<name>` folder; kobo: a mounted device or a `*.sqlite` in `Data/Imports/kobo`); the `merge` step runs when any source layer exists (or calibre/goodreads were detected, so `--dry-run` predicts it), and `render` runs when `Data/books.csv` exists (or `merge` would run). Each step calls the module's core function directly (`convert`/`export_obsidian`/`store.merge`/`render.render`) — no shelling out. Failures are reported but never stop the remaining steps (continue-on-error); a colored per-step + summary report is printed via `typer.secho`. `--output` overrides the vault; `--dry-run` prints the detection plan (with each step's source location) without writing. Creates no notes itself — note creation is delegated to the `render` step.
- `books/commands/render.py` → `render` — the CSV-store renderer (Plan B). Reads the merged catalog (`<vault>/Data/books.csv`) + per-book highlights (`<vault>/Data/Highlights/<book-id>.csv`) built by `books/core/store.py` and writes/updates one flat note per book under `Books/`. Frontmatter is written **authoritatively** from the merged row for every canonical key (`NOTE_PROPERTY_ORDER` = `obsidian.BOOK_PROPERTY_ORDER` minus the retired `source` key), EXCEPT: `topics` (100% user-owned — preserved verbatim, `[]` on a new note, never written from data), `aliases`/`cssclasses` (preserved from the existing note when present, positioned after `topics`), and `highlighted`/`reviewed` (derived booleans — true iff the book has highlights / a review). `type` is always `book`. The body carries the cover embed, a write-once `## Review` (via `obsidian.ensure_section`), and a marker-wrapped `## Highlights` (via `highlights.render_highlights` + `obsidian.render_marked_section`); content outside those managed regions is preserved. The `## Review` body is composed by the renderer (`note.compose_review`) from the store's separate `review` + `private_notes` columns — the review text first, then any private notes under a `### Private Notes` subheading — so the importers stay pure data writers and the markdown layout lives in the renderer; a book with only private notes still counts as `reviewed`. Highlights from ≥2 distinct sources are grouped under small `### <Source>` headers (single-source output is unchanged); a per-highlight `source` flows from the store's `HighlightRow` via `row_to_highlight`. Frontmatter round-trips via **python-frontmatter** (read) + **ruamel.yaml** (write, `allow_unicode`, no wrapping). `render_note` is idempotent (render-twice ⇒ identical bytes); `render(vault)` is continue-on-error per book (a hand-corrupted note is counted and reported, the rest still render). `--output` overrides the vault; the command errors cleanly if no `books.csv` exists yet. The output format is selected by a boolean flag (`--obsidian`, default and only format today; future renderers slot in beside it as `--notion`/`--evernote` behind the `books/renderers/base.py` `Renderer` protocol + `books/renderers/get_renderer` registry). `render` is the sole producer of Obsidian notes — the CLI command is a thin dispatcher that resolves the selected renderer and calls `renderer.render(vault)`; the note assembly + write lives in `books/renderers/obsidian/note.py`.
- `books/commands/covers/` → `covers` — scans the merged catalog (`Data/books.csv`) for books with a blank `cover` (and no materialized `Data/Covers/<book_id>.jpg`) and fetches a cover image. Sources are tried in order — Apple Books (iTunes Search API, queried by title+author against the GB store), then Google Books, then Open Library (paperback editions preferred where `physical_format` is known), then Amazon (only when the book already has an `amazon` ASIN, by building the known cover-image URL — no scraping). When a book carries an ISBN it drives the Google/Open Library lookup directly (Google `isbn:` query / Open Library `/b/isbn/` cover) — the most reliable path, unaffected by Google's title-search rate limiting (Apple is always queried by title+author, since its ISBN-term search is unreliable). Stdlib-only (`urllib`); all network I/O is injected for testing. HTTP fetches retry transient failures (429/5xx) with exponential backoff (`fetch_with_retry`), and a source that errors outright (rate-limited/unreachable) is counted and reported separately from one that merely found no match. Author/title queries are normalized before sending (`normalize_author` collapses whitespace and drops translator/co-author tails like "Plato and Benjamin Jowett" → "Plato"). Fetched images are validated by parsing their pixel dimensions (`image_dimensions`, PNG/GIF/JPEG headers, stdlib) and rejecting anything below `MIN_IMAGE_DIM`, falling back to a byte-size check when dimensions are unparseable. The fetched image is staged under `Data/Sources/_covers/covers/<book_id>.jpg` and a `covers` metadata layer (`Data/Sources/covers.csv`) records the staged path + any learned ISBN (an Apple artwork path often embeds the edition ISBN, backfilled like any other learned ISBN; never overwriting an existing one); run `merge` + `render` afterward to fold it in and materialize `Data/Covers/<book_id>.jpg` + the note embed (at width 150). Runs after `merge`; **not** part of `sync`. Default mode auto-picks the best match; `--interactive` approves each candidate, `--dry-run` previews, `--limit N` caps the run. `--book <book_id>` targets a single catalog book and is interactive by default. Split into a package: `command.py` (scan/select + CLI + store sink), `sources.py` (the per-provider lookups + `Candidate`/`MissingBook` models), and `images.py` (HTTP retry/backoff + image-dimension validation).

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
`Data/Imports/readwise`, `Data/Imports/kobo`, and `Data/Imports/audible` (which holds the
transcription `cache.json`, not raw CSVs) — so most commands need no input flag.
(`calibre` is the exception: `--library` defaults to `~/Calibre Library`.) For the
single-file CSV importers (goodreads/readwise), `newest_csv(folder)` picks the
most-recently-modified top-level `*.csv` and `resolve_csv_arg(csv, name, output)` resolves
an unset/folder/file `--csv` to one CSV (unset → newest in the canonical subfolder).

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
  indexed book notes) and `Authors/` (stub/hub notes `render` creates) — while all
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
- **Authoritative frontmatter, at merge not render.** Accumulation now happens in the
  CSV store: `merge` clusters the per-source layers so Calibre → Goodreads (in either
  order) build up a single row, and `render` writes each note's canonical frontmatter
  authoritatively from that row (see `render.py` for the per-key rules: `topics` is
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
- **Cover materialization**: `render` reads each row's staged cover path and writes the
  flat `Data/Covers/<stem>.jpg` file plus the `![[…|150]]` embed (width from `COVER_WIDTH`).
- **Matching normalization** used to cluster rows for the same book: `norm_title`,
  `norm_isbn`, `author_key` (reduces names to (first, last), handling "Last, First"), and
  `fold` (accent/case folding). These live in `books/core/matching.py` (format-agnostic)
  and are imported directly from `core` by both `store` and the renderer.
- **Book identity resolution** (`store.Catalog.find`): every importer resolves a `BookRef`
  to a `book_id` against the merged catalog by ISBN, then Amazon id, then standardized
  (title, author) — match-only, never creating. (The old `VaultIndex` note-resolution class
  has been deleted; `render` is the sole producer of notes and writes them directly from the
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
  topics become `[[wikilinks]]` for Obsidian's graph). `render` handles its own YAML
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
