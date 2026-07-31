# 📚 books

Turn your reading data into a clean [Obsidian](https://obsidian.md) vault — one
self-contained Markdown note per book, with covers, reviews, and highlights.

Sources: Calibre, Goodreads, Kobo, Readwise, [Highlighted](https://highlighted.app),
Kindle, and Audible.

## 🚀 Install

```bash
uv tool install git+https://github.com/andrejakobsen/books-cli.git
books --help
```

Installs the `books` command to `~/.local/bin` (run `uv tool update-shell` if your
shell can't find it). Audible needs an extra + `ffmpeg`:

```bash
uv tool install 'git+https://github.com/andrejakobsen/books-cli.git[audible]'
brew install ffmpeg
```

<details>
<summary>Other install options</summary>

```bash
uv tool upgrade books        # update
uv tool uninstall books      # remove
books --install-completion   # shell tab-completion

# from a local clone
git clone https://github.com/andrejakobsen/books-cli.git && cd books-cli
uv tool install .            # or: uv run books --help
```

</details>

## ⚡ Quickstart

1. Drop your export files into the matching folders in your vault under
   `Data/Imports/{goodreads,readwise,highlighted,kobo,kindle}`. (Calibre reads
   `~/Calibre Library`; a mounted Kobo/Kindle is auto-detected.)
2. Build the store, then write the notes:

```bash
books import    # ingest every source into the CSV store
books export    # render the store into Obsidian notes
```

## 🛠️ Commands

There are three:

| Command | What it does |
| --- | --- |
| **`import`** | Ingests raw sources into the CSV store under `Data/`. Never touches your notes. |
| **`export`** | Renders the store (`Data/books.csv` + `Data/Highlights/`) into `Books/*.md`. |
| **`reset`** | Deletes the derived store so the next `import` rebuilds it (`--dry-run`, `-y`). |

**`books import`** with no flags runs the default set — `calibre`, `goodreads`,
`kobo`, `highlighted`, `readwise`, `kindle` — clustering everything into one
catalog automatically. Flags pick an exact subset; missing sources are skipped
and a failing step never stops the others.

```bash
books import --dry-run                 # preview which steps run, and from where
books import --goodreads --readwise    # just these two
books import --covers --audible        # opt-in enrichers (network / cloud auth)
books export --refresh                 # clean rebuild of Books/ and Authors/
```

`covers` (cover lookup) and `audible` (bookmarks/clips → transcribed highlights)
are opt-in: pass their flag or add them to `[import].default`. See [Audible](#-audible).

## ⚙️ Configuration

On first run `books` creates `~/.config/books/config.toml`:

```toml
obsidian_path = "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian"
vault = "History"
imports = "Data/Imports"

[export]
timezone = "Europe/Oslo"   # zone for highlight date/time in exported notes
```

Commands write to `obsidian_path/vault`; pass `--output`/`-o` to override per run.
Optional `[import].default`, `[calibre]`, `[kobo]`, `[audible]`, `[covers]`, and
`[kindle]` sections tune individual sources. Any missing/invalid key falls back to
its default.

## 🎧 Audible

`books import --audible` turns your Audible **bookmarks and clips** into
highlights: it authenticates, downloads each audiobook, uses `ffmpeg` to decrypt
and cut the clip, and transcribes it to text.

- **Auth** — prompts once for email/password/marketplace, cached at
  `~/.config/books/audible-auth.json` (mode `600`).
- **Transcriber** — `local` (default, offline `faster-whisper`), `openai`
  (`OPENAI_API_KEY`), or `google` — set via `[audible].transcriber`.
- **Caching** — transcriptions cache under `Data/Imports/audible/`, so re-runs
  only fetch books with new clips.

Downloading and decrypting audiobooks you own is for personal archival use only.

## 🗂️ Vault layout

Notes live in flat, top-level folders; tool-managed data lives under `Data/`:

- **`Books/`** — one note per book (`<Title> - <Author>.md`): frontmatter, cover
  embed, optional `## Review`, and a `## Highlights` section.
- **`Authors/`** — author stub notes for the graph.
- **`Data/`** — `Imports/` (raw exports you drop in), `Covers/` (images), and the
  CSV store (`Sources/`, `Highlights/`, `books.csv`).

Re-running is safe: highlights sit between `%% books:highlights:start %%` / `:end %%`
markers and are regenerated wholesale; everything else you write — including a
hand-edited `## Review` — is preserved.

## 🧑‍💻 Development

```bash
uv sync            # install deps (incl. dev)
uv run pytest -q   # run the tests
uv run ruff check --fix && uv run ruff format
```

Add a capability with `books/commands/<feature>.py` exposing `register(app)` and
listing it in `CAPABILITIES` (`books/cli.py`). Format-agnostic code lives in
`books/core/`; Obsidian-specific code in `books/renderers/obsidian/`.
