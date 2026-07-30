# books

Turn your reading data into a clean [Obsidian](https://obsidian.md) vault.

`books` pulls your library and highlights from Calibre, Goodreads, Readwise,
Kobo, the [Highlighted](https://highlighted.app) app, and Audible into one
self-contained Markdown note per book — with covers, reviews, and highlights.

## Install

```bash
uv tool install git+https://github.com/andrejakobsen/books-cli.git
books --help
```

This installs the `books` command to `~/.local/bin`. If your shell can't find
it, run `uv tool update-shell` and restart your terminal.

```bash
uv tool upgrade books        # update
uv tool uninstall books      # remove
books --install-completion   # optional shell tab-completion
```

The `audible` command needs a heavier optional extra plus system `ffmpeg`
(no other command loads it):

```bash
uv tool install 'git+https://github.com/andrejakobsen/books-cli.git[audible]'
brew install ffmpeg
```

<details>
<summary>Install from a local clone</summary>

```bash
git clone https://github.com/andrejakobsen/books-cli.git && cd books-cli
uv tool install .                          # global install
uv tool install . --reinstall --editable   # editable: picks up local edits
uv run books --help                        # or run without installing
```

</details>

## Quickstart

1. Drop your export files into the matching import folders inside your vault:
   `Data/Imports/{goodreads,readwise,highlighted,kobo}`. (Calibre is read from
   `~/Calibre Library`; a mounted Kobo is copied in automatically.)
2. Run everything with one command:

```bash
books sync             # run the full pipeline
books sync --dry-run   # preview which steps would run, and from where
```

`sync` runs two phases: importers write plain CSV data into `Data/` (never
touching your notes), `merge` clusters it into one catalog, and `render` turns
the catalog into Markdown notes. Missing sources are skipped; a failing step
never stops the others.

Covers and Audible are **not** part of `sync` — run them on their own (see below).

## Configuration

On first run `books` creates `~/.config/books/config.toml`:

```toml
obsidian_path = "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian"
vault = "History"
imports = "Data/Imports"
```

Commands write to `obsidian_path/vault`. Pass `--output`/`-o` to override the
vault per run. `imports` is the in-vault folder holding your raw exports — this
is why the zero-config commands just work.

## Commands

With sources in place and a configured vault, none of these need arguments.

| Command | What it does |
| --- | --- |
| **`sync`** | Runs the whole pipeline: `calibre` → `goodreads` → `merge` → `kobo` → `highlighted` → `readwise` → `render`. |
| **`calibre`** | Reads a Calibre library (`--library`, default `~/Calibre Library`) into the `calibre` source layer, staging covers. |
| **`goodreads`** | Reads a Goodreads CSV (all shelves) into the `goodreads` source layer, carrying reviews into the `## Review` section. |
| **`merge`** | Clusters the per-source layers under `Data/Sources/` into the merged catalog `Data/books.csv`. Run after the metadata importers, before `render`. |
| **`kobo`** | Imports Kobo highlights & notes into the highlights store. Reads a mounted device (snapshotted read-only) or a `*.sqlite` in `Data/Imports/kobo`; override with `--db`. |
| **`highlighted`** | Imports highlights from *physical* books via the [Highlighted](https://highlighted.app) app (imports every CSV in the folder). |
| **`readwise`** | Imports Readwise highlights (newest CSV in the folder) into the highlights store. |
| **`render`** | Renders the CSV store (`Data/books.csv` + `Data/Highlights/`) into book notes. See [Rendering](#rendering). |
| **`covers`** | Finds catalog books with no cover and fetches one (Apple Books → Google Books → Open Library → Amazon). Not in `sync`. |
| **`audible`** | Imports Audible bookmarks & clips, transcribed to text. Needs the `[audible]` extra + `ffmpeg`; not in `sync`. See [Audible](#audible). |

The importers are **CSV writers** — they never touch your notes. `calibre` and
`goodreads` write metadata layers under `Data/Sources/`; the highlight importers
(`kobo`, `highlighted`, `readwise`) resolve each book against the merged catalog
and write into `Data/Highlights/`. So run `merge` (or `sync`) before the
highlight importers. Highlights carry their source through the store, so a book
fed by several sources shows them grouped under per-source subheadings.

Override the defaults with explicit paths:

```bash
books goodreads --csv ~/goodreads_library_export.csv
books kobo --db ~/KoboReader.sqlite --output ~/Obsidian
```

`covers` runs after `merge`: it fetches into a `covers` layer, so re-run `merge`
+ `render` afterward to fold covers in.

```bash
books covers                  # auto-pick the best match for each missing cover
books covers --interactive    # approve each candidate
books covers --dry-run        # preview without writing
books covers --book "<id>"    # a single catalog book (interactive by default)
books covers --limit 20       # cap the run
```

## Audible

`books audible` turns your Audible **bookmarks and clips** into highlights: it
authenticates to your account, downloads each audiobook, uses `ffmpeg` to
decrypt and cut the clip's audio, and transcribes it to text — rendered into the
`## Highlights` section of the matching note. Like the other highlight
importers it never creates notes, so run `calibre`/`goodreads`/`merge` first.
Run `merge` + `render` afterward to surface the results.

```bash
books audible                   # import clips into matching notes
books audible --dry-run         # show matches & clip counts; write nothing
books audible --asin B0ABCDEFG  # only this audiobook
books audible --limit 5         # at most 5 matched books
```

On first run you're prompted for your Audible email, password, and marketplace;
the auth is cached at `~/.config/books/audible-auth.json` (mode `600`) so later
runs are non-interactive.

- **Matching** — by ASIN (`amazon` frontmatter id), then standardized title/author.
- **Point bookmarks** — a bookmark with no end transcribes a window *ending* at
  the mark; tune with `--clip-window` (default `30`s). Clips use their own length.
- **Transcriber** — `--transcriber local` (default; `faster-whisper`, offline),
  `openai` (needs `OPENAI_API_KEY`), or `google`. `--model` sets the Whisper size.
- **Caching** — transcriptions cache in `Data/Imports/audible/cache.json`, so
  re-runs re-render for free and only download books with new clips.

Downloading and decrypting audiobooks you own is for personal archival use only.

## Rendering

Book data lives in a plain-CSV store under `Data/` (a merged catalog plus
per-source and per-highlight layers). `render` reads that store and writes the
notes, so the output *format* is just a choice at render time:

```bash
books render                # render every book into Obsidian notes
books render --output ~/Obsidian
```

Today the only format is Obsidian Markdown (`--obsidian`, on by default); the
flag exists so other formats can slot in later. `render` errors cleanly if no
`Data/books.csv` exists yet.

## Vault layout

Notes live in flat, top-level folders; everything the tool manages lives under
`Data/`:

- **`Books/`** — one note per book (`<Title> - <Author>.md`): frontmatter, a
  cover embed, an optional `## Review`, and a `## Highlights` section.
- **`Authors/`** — author stub notes for the graph.
- **`Data/`** — tool-managed data: `Data/Imports/` (raw exports you drop in),
  `Data/Covers/` (cover images), and the CSV store (`Data/Sources/`,
  `Data/Highlights/`, `Data/books.csv`).

Re-running is safe. Highlights sit between `%% books:highlights:start %%` /
`:end %%` markers and are regenerated wholesale; everything else you write —
including a hand-edited `## Review` — is preserved.

## Development

```bash
uv sync            # install deps (incl. dev)
uv run pytest -q   # run the tests
```

Add a capability by creating `books/commands/<feature>.py` with a
`register(app: typer.Typer)` function and adding it to `CAPABILITIES` in
`books/cli.py`. Format-agnostic building blocks live under `books/core/`;
Obsidian/markdown-specific code lives under `books/renderers/obsidian/`.
