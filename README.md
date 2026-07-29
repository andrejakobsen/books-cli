# books

Turn your reading data into a clean [Obsidian](https://obsidian.md) vault.

`books` is a single command that pulls your library and highlights from Calibre,
Goodreads, Readwise, Kobo, the [Highlighted](https://highlighted.app) app, and
Audible (bookmarks & clips, transcribed to text) into tidy, linked Markdown
notes — one self-contained note per book, with covers, reviews, and highlights.
Built with [Typer](https://typer.tiangolo.com/) and
[uv](https://docs.astral.sh/uv/).

## Install

Install straight from GitHub with uv — no clone needed:

```bash
uv tool install git+https://github.com/andrejakobsen/books-cli.git
books --help
```

This puts the `books` command at `~/.local/bin/books`. If your shell can't find
it, run `uv tool update-shell` and restart your terminal.

Later:

```bash
uv tool upgrade books     # update to the latest
uv tool uninstall books   # remove it
books --install-completion  # optional: tab-completion for commands & options
```

The `audible` command needs extra, heavier dependencies (and system `ffmpeg`).
They're an optional extra that no other command loads — install them only if you
want it:

```bash
uv tool install 'git+https://github.com/andrejakobsen/books-cli.git[audible]'
brew install ffmpeg   # ffmpeg is required to decrypt and cut clips
```

<details>
<summary>Install from a local clone instead</summary>

```bash
git clone https://github.com/andrejakobsen/books-cli.git && cd books-cli
uv tool install .            # global install
uv tool install . --reinstall --editable   # editable: picks up local edits
uv run books --help          # or just run it via uv without installing
```
</details>

## Quickstart

1. Drop your export files into hidden subfolders of your vault:
   `.imports/goodreads`, `.imports/readwise`, `.imports/highlighted`,
   `.imports/kobo`. (Calibre is read from `~/Calibre Library`; a mounted Kobo is
   copied in automatically.)
2. Refresh everything with one command:

```bash
books sync             # calibre → goodreads → kobo → highlighted → readwise
books sync --dry-run   # preview which steps would run, and from where
```

Each step is skipped when its source is missing, and a failing step never stops
the others.

## Configuration

On first run `books` creates `~/.config/books/config.toml`:

```toml
obsidian_path = "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian"
vault = "History"
imports = ".imports"
```

Commands write to `obsidian_path/vault`; pass `--output` to override per run.
`imports` is a dot-folder inside the vault holding raw exports — Obsidian keeps
dot-folders out of its explorer, search, and graph. This is why the zero-config
commands above just work: drop a file in the right subfolder and it's found.

## Commands

Run any importer on its own, or `books sync` to run them all. With sources in
`.imports/` and a configured vault, none of these need arguments:

```bash
books calibre        # imports ~/Calibre Library
books goodreads      # newest CSV in .imports/goodreads
books readwise       # newest CSV in .imports/readwise
books highlighted    # every CSV in .imports/highlighted
books kobo           # copies a mounted Kobo's DB in, then exports
books covers         # fetch missing cover images
```

| Command | What it does |
| --- | --- |
| **`sync`** | Runs every importer in order. Note-creating importers (`calibre`, `goodreads`) run first to establish book identity; the highlight importers follow and only enrich existing notes. Covers are out of scope — run `covers` separately. |
| **`calibre`** | Reads a Calibre library — copies covers, extracts `.opf` metadata into YAML, links authors/topics. `--library` defaults to `~/Calibre Library`. |
| **`goodreads`** | Reads a Goodreads CSV (read books by default, `--shelf all` for everything). Writes each review once into a `## Review` section, never clobbered on re-runs. |
| **`readwise`** | Reads a Readwise CSV and renders highlights into a `## Highlights` section. |
| **`kobo`** | Exports Kobo highlights to per-book CSVs in a zip (default), or `--obsidian` to render them into book notes. |
| **`highlighted`** | Imports highlights from *physical* books via the [Highlighted](https://highlighted.app) app, anchored by page. |
| **`audible`** | Imports Audible bookmarks & clips, transcribing each clip to text in a `## Highlights` section. Needs the `[audible]` extra + `ffmpeg`; not part of `sync`. See below. |
| **`covers`** | Finds book notes with a blank cover and fetches one (Apple Books → Google Books → Open Library → Amazon). |

Point at explicit paths to override the defaults:

```bash
books goodreads --csv ~/goodreads_library_export.csv
books kobo ~/KoboReader.sqlite --obsidian --output ~/Obsidian
```

The `--csv` importers accept a single file or a folder. Every book note records
its `source:` (calibre/goodreads/kobo/highlighted/readwise/audible).

## Audible

`books audible` turns your Audible **bookmarks and clips** into highlights. For
each clip it authenticates to your Audible account, downloads the audiobook,
uses `ffmpeg` to decrypt and cut the clip's audio, and transcribes it to text —
rendered into the `## Highlights` section of the *matching* book note. Like the
other highlight importers it never creates notes: a book with no existing note is
skipped and counted, so run `calibre`/`goodreads` first to establish book
identity. It is **not** part of `books sync` — run it on its own.

Prerequisites: install the `[audible]` extra and `ffmpeg` (see
[Install](#install)). Downloading and decrypting audiobooks you own is for
personal archival use only.

```bash
books audible                 # import clips into matching notes
books audible --dry-run       # log in, show which books match & clip counts; write nothing
books audible --asin B0ABCDEFG # only this one audiobook
books audible --limit 5       # process at most 5 matched books
```

On first run you're prompted for your Audible email, password, and marketplace
(`us`, `uk`, `de`, …); the auth is cached at `~/.config/books/audible-auth.json`
(mode `600`) so later runs are non-interactive.

- **Matching** — a library book matches a note by ASIN (the `amazon`
  frontmatter id), then by standardized title/author.
- **Point bookmarks** — a plain bookmark has no end position, so a window of
  audio *ending* at the mark is transcribed. Tune it with `--clip-window`
  (default `30` seconds); clips use their own recorded length.
- **Transcriber** — `--transcriber local` (default; `faster-whisper`, offline,
  no key), `openai` (needs `OPENAI_API_KEY`), or `google` (free, lower quality).
  `--model` picks the Whisper model size (default `small`) for the local/openai
  backends.
- **Caching** — transcriptions are cached in `<vault>/.imports/audible/cache.json`
  (keyed by ASIN + annotation id). Re-runs re-render for free and only download
  books that have new clips; the downloaded audio goes to a temp dir and is
  deleted after cutting.
- **Notes** — any typed note on a clip renders as a nested blockquote, and its
  `#tag` / `@link` markers follow the same convention as the other importers.

## The vault layout

Everything lives in flat, top-level folders:

- **`Books/`** — one note per book (`<Title> - <Author>.md`): frontmatter, a
  cover embed, an optional `## Review`, and a `## Highlights` section.
- **`Covers/`** — cover images named to match their note.
- **`Notes/`** — your own free-form notes; never touched by importers.
- **`Authors/`** and **`Topics/`** — stub notes for the graph.

Re-running is safe. Highlights live between `%% books:highlights:start %%` /
`:end %%` markers and are regenerated wholesale; everything else you write —
including a hand-edited `## Review` — is preserved.

## Development

```bash
uv sync            # install deps (incl. dev)
uv run pytest -q   # run the tests
```

Add a capability by creating `books/commands/<feature>.py` with a
`register(app: typer.Typer)` function, then adding it to `CAPABILITIES` in
`books/cli.py`. Format-agnostic building blocks (config, paths, the CSV store,
the highlight model + parsing) live under `books/core/`; everything
Obsidian/markdown-specific lives under `books/renderers/obsidian/`.
