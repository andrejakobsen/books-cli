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
```

There is no separate lint/format step configured.

## Git workflow

Commit work directly to `main` in this repo — do **not** create feature branches or
open PRs for changes. This overrides the default "branch first when on the default
branch" behavior. Run `uv run pytest -q` before committing.

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
  highlights data model), and `highlights.py` (the `Highlight` model, `#tag`/`@link`
  marker parsing, and reading-order `sort_key` — no markdown/Obsidian knowledge).
- **`books/renderers/`** — output targets. `books/renderers/obsidian/` owns 100% of the
  Obsidian/markdown-specific code (a future renderer slots in beside it). Its
  `__init__.py` re-exports the public API so call sites use `from books.renderers.obsidian
  import X`.
- **`books/commands/`** — the CLI capabilities, each exposing `register(app)`.

Nine capabilities exist today. **Two of them create book notes (`calibre`, `goodreads`);
the four highlight importers (`kobo`, `highlighted`, `readwise`, `audible`) only enrich
existing notes and never create them** — a book with no matching note is skipped and counted
(run `calibre`/`goodreads` first to establish book identity). This is enforced in code
via `VaultIndex.find` (match-only) vs `VaultIndex.find_or_create` (creates). An eighth
(`sync`) is an orchestrator that runs the importers in order and creates nothing itself.
A ninth (`render`) belongs to the newer CSV-store architecture (see `books/core/store.py`): it
reads the merged catalog + per-book highlights from `<vault>/Data/` and writes the book notes,
rather than going through the `VaultIndex` importer model.
- `books/commands/calibre.py` → `calibre` — reads a Calibre library's `metadata.opf` (XML) + `cover.jpg` per book and writes Obsidian notes (creates notes via `find_or_create`). `--library` defaults to `~/Calibre Library`.
- `books/commands/goodreads.py` → `goodreads` — reads a Goodreads CSV export and writes/merges Obsidian notes (creates notes via `find_or_create`). A review is written once into a write-once `## Review` section of the book note (never clobbered on re-runs). Fills a `goodreads:` frontmatter property with the book's full Goodreads URL (`https://www.goodreads.com/book/show/<Book Id>`), including on notes originally created by Calibre (matched via `find_or_create`). New notes are only created for books on the `--shelf` shelves (default `read,currently-reading`), but a book on any other shelf (e.g. `to-read`) that already has a matching note is still enriched via `find` (full never-overwrite merge, so it gets its goodreads link and any other blank fields) — it is just never created. `--csv` accepts a single CSV file or a folder (newest `*.csv`), defaulting to `<vault>/.imports/goodreads`.
- `books/commands/kobo.py` → `kobo` — reads `KoboReader.sqlite` (opened **read-only** via `file:...?mode=ro`) and exports per-book highlight CSVs into a zip. Has a `--csv` flag (the default output mode) and an `--obsidian` flag that renders highlights (via the shared `books/core/highlights.py` model + `books/renderers/obsidian/highlights.py` rendering) into a marker-wrapped `## Highlights` section of an **existing** book note (matched via `VaultIndex.find`; unmatched books are skipped and counted). Note markers follow the `#tag` / `@link` convention (parsed via `highlights.parse_markers`). When no DB path is given, a mounted Kobo (`/Volumes/KOBOeReader/.kobo/KoboReader.sqlite`) is safely snapshotted into `<vault>/.imports/kobo/` via SQLite's read-only backup API (the device file is never modified) and read from there; otherwise the existing copy (or newest `*.sqlite`) in that folder is used.
- `books/commands/highlighted.py` → `highlighted` — reads a Highlighted app CSV export (highlights from physical books, page-located) and renders highlights (via the shared highlights layer) into a marker-wrapped `## Highlights` section of an **existing** book note (matched via `VaultIndex.find`; unmatched books are skipped and counted). `--csv` accepts a single CSV file or a folder of CSV exports (every top-level `*.csv` is imported in sorted order; a file that fails to parse is skipped and reported), defaulting to `<vault>/.imports/highlighted`. Its `Tags` column follows the `#tag` / `@link` convention (`highlights.split_tag_column`).
- `books/commands/readwise.py` → `readwise` — reads a Readwise CSV export and renders highlights (via the shared highlights layer) into a marker-wrapped `## Highlights` section of an **existing** book note (matched via `VaultIndex.find` by Amazon id then standardized title/author; unmatched books are skipped and counted). `--csv` accepts a single CSV file or a folder (newest `*.csv`), defaulting to `<vault>/.imports/readwise`. Fills `amazon`/`shelves`/`series`/`series_index` frontmatter, renders type-aware location labels (`p.`/`loc.`). Its `Tags` column follows the `#tag` / `@link` convention (`highlights.split_tag_column`).
- `books/commands/audible/` → `audible` — imports **Audible bookmarks & clips** into
  existing Obsidian book notes (enrich-only via `VaultIndex.find`, matched by ASIN as
  `amazon` then title/author; unmatched books skipped and counted). Fills
  `format: audiobook` (never overwriting an existing value). Authenticates to
  the Audible cloud (auto-prompt on first run, auth cached at
  `~/.config/books/audible-auth.json`), fetches each book's annotations, downloads the
  audiobook, and uses **ffmpeg** to decrypt (AAXC via `-audible_key`/`-audible_iv`) and
  cut each clip, then transcribes it with a pluggable backend (`--transcriber
  local|openai|google`, default `local`). Clips use their own start→end; a point
  bookmark (no end) uses `--clip-window` seconds ending at the mark. Transcriptions are
  cached in `<vault>/.imports/audible/cache.json` (keyed by ASIN + annotation id), so
  re-runs re-render for free and only download books with new clips; downloaded audio
  is written to a temp dir and deleted. Not part of `sync`. Lives as a package
  (`command.py` + `models.py` + `client.py` + `transcribe.py`), with the shared dataclasses
  (`Annotation`, `Chapter`, `DownloadedAudio`, `LibraryBook`) in `models.py`.
- `books/commands/sync.py` → `sync` — master orchestrator that runs the importers in dependency order using each command's default options: `calibre` → `goodreads` → `kobo` → `highlighted` → `readwise` (covers is **not** included). Each step is skipped when its source is absent (calibre: `~/Calibre Library` exists; goodreads/highlighted/readwise: a `*.csv` in the `.imports/<name>` folder; kobo: a mounted device or a `*.sqlite` in `.imports/kobo`). Each step calls the module's core function directly (`convert`/`export_obsidian`) — no shelling out. Failures are reported but never stop the remaining steps (continue-on-error); a colored per-step + summary report is printed via `typer.secho`. `--output` overrides the vault; `--dry-run` prints the detection plan without writing. Creates no notes itself — it delegates note creation to `calibre`/`goodreads`.
- `books/commands/render.py` → `render` — the CSV-store renderer (Plan B). Reads the merged catalog (`<vault>/Data/books.csv`) + per-book highlights (`<vault>/Data/Highlights/<book-id>.csv`) built by `books/core/store.py` and writes/updates one flat note per book under `Books/`. Frontmatter is written **authoritatively** from the merged row for every canonical key (`NOTE_PROPERTY_ORDER` = `obsidian.BOOK_PROPERTY_ORDER` minus the retired `source` key), EXCEPT: `topics` (100% user-owned — preserved verbatim, `[]` on a new note, never written from data), `aliases`/`cssclasses` (preserved from the existing note when present, positioned after `topics`), and `highlighted`/`reviewed` (derived booleans — true iff the book has highlights / a review). `type` is always `book`. The body carries the cover embed, a write-once `## Review` (via `obsidian.ensure_section`), and a marker-wrapped `## Highlights` (via `highlights.render_highlights` + `obsidian.render_marked_section`); content outside those managed regions is preserved. Highlights from ≥2 distinct sources are grouped under small `### <Source>` headers (single-source output is unchanged); a per-highlight `source` flows from the store's `HighlightRow` via `row_to_highlight`. Frontmatter round-trips via **python-frontmatter** (read) + **ruamel.yaml** (write, `allow_unicode`, no wrapping) — the two non-stdlib runtime deps this capability adds. `render_note` is idempotent (render-twice ⇒ identical bytes); `render(vault)` is continue-on-error per book (a hand-corrupted note is counted and reported, the rest still render). `--output` overrides the vault; the command errors cleanly if no `books.csv` exists yet. Creates no vault-index book notes via the `VaultIndex` path — it writes directly from the store.
- `books/commands/covers/` → `covers` — scans an existing vault for `type: book` notes with a blank `cover:` field and fetches a cover image. Sources are tried in order — Apple Books (iTunes Search API, queried by title+author against the GB store), then Google Books, then Open Library (paperback editions preferred where `physical_format` is known), then Amazon (only when the note already has an `amazon` ASIN, by building the known cover-image URL — no scraping). When a note carries an ISBN it drives the Google/Open Library lookup directly (Google `isbn:` query / Open Library `/b/isbn/` cover) — the most reliable path, unaffected by Google's title-search rate limiting (Apple is always queried by title+author, since its ISBN-term search is unreliable). Stdlib-only (`urllib`); all network I/O is injected for testing. HTTP fetches retry transient failures (429/5xx) with exponential backoff (`fetch_with_retry`), and a source that errors outright (rate-limited/unreachable) is counted and reported separately from one that merely found no match. Author/title queries are normalized before sending (`normalize_author` collapses whitespace and drops translator/co-author tails like "Plato and Benjamin Jowett" → "Plato"). Fetched images are validated by parsing their pixel dimensions (`image_dimensions`, PNG/GIF/JPEG headers, stdlib) and rejecting anything below `MIN_IMAGE_DIM`, falling back to a byte-size check when dimensions are unparseable. An ISBN learned from a source is backfilled into the note's frontmatter (never overwriting an existing one) — an Apple artwork path often embeds the edition ISBN, which is backfilled like any other learned ISBN. Writes `<Title> - <Author>.jpg` into the flat `Covers/` folder and fills the note's `cover:` frontmatter + top embed (at width 150) via the shared `books/renderers/obsidian/` helpers (never overwriting an existing cover). Default mode auto-picks the best match; `--interactive` approves each candidate, `--dry-run` previews, `--limit N` caps the run. `--book PATH` targets a single note under `Books/` (vault inferred from the path) and is interactive by default. Split into a package: `command.py` (scan/select/apply + CLI wiring), `sources.py` (the per-provider lookups + `Candidate`/`MissingBook` models), and `images.py` (HTTP retry/backoff + image-dimension validation).

### Configuration

`books/core/config.py` supplies the default Obsidian vault. It reads
`~/.config/books/config.toml` (respecting `$XDG_CONFIG_HOME`), auto-creating it
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
`.imports/readwise`, `.imports/kobo`, and `.imports/audible` (which holds the
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
`__init__.py` re-exports the whole public API (so call sites do `from
books.renderers.obsidian import X`), and it is split by responsibility across `layout.py`
(folder constants + cover/filename helpers), `frontmatter.py` (schema + `update_frontmatter`
+ readers), `sections.py` (section helpers), `matching.py` (normalization), `format.py`
(`wikilink`/`link_list`/`html_to_markdown`), `highlights.py` (`render_highlights`), and
`vault_index.py` (`VaultIndex`/`BookNote`). It owns:

- **The flat vault layout.** Everything lives in top-level folders — `Books/` (the
  indexed book notes), `Covers/` (flat cover images named `<Title> - <Author>.jpg`),
  `Notes/` (fully manual personal notes), `Authors/` and `Topics/` (stub/hub notes).
  There is no per-book `Exports/<Author>/<Title>/` folder any more; a book note is a
  single self-contained file. The folder names are constants in `layout.py`
  (`BOOKS_DIRNAME`, `COVERS_DIRNAME`, `NOTES_DIRNAME`, `AUTHORS_DIRNAME`, `TOPICS_DIRNAME`).
- **The book note anatomy.** A book note is frontmatter + a cover embed
  (`![[Covers/<stem>.jpg|150]]`, width from `COVER_WIDTH`) + an optional write-once
  `## Review` section + a marker-wrapped `## Highlights` section. Personal notes are not
  in the book note; the `Notes/` folder holds fully manual notes the user authors by hand.
- **A canonical frontmatter schema** (`BOOK_PROPERTY_ORDER`). Every book note emits
  all keys (empty when unknown) so any importer or a manual edit can fill a field later.
  The key is `topics` (not `genres`), and `cover` is the last key. `highlighted` and
  `reviewed` are booleans (defaulting to `false`) that flip to `true` when highlights or
  a review are imported, used for filtering the vault on reading progress.
- **The "never overwrite" merge rule** (`update_frontmatter`): fills only absent or
  blank keys, leaves non-empty values and the note body untouched, appends new keys in
  canonical order — except keys in `OVERWRITE_KEYS` (`highlighted`, `reviewed`), where a
  `true` update overwrites so the flag can flip on. This is what lets Calibre → Goodreads
  (in either order) plus hand edits accumulate without clobbering. `write_if_absent`
  enforces the same rule at the file level (used for hub/stub notes).
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
new shared logic in `books/renderers/obsidian/` rather than duplicating it per importer.

> **Exception to stdlib-only:** the `audible` capability needs third-party packages
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
