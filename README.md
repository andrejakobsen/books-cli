# booktools

CLI tools for books & reading data. Ships a single `books` command with
sub-commands, built with [Typer](https://typer.tiangolo.com/) and managed with
[uv](https://docs.astral.sh/uv/).

## Install

This is exactly how the `books` command was installed on this machine.

### 1. Install it as a global tool (recommended)

Run from the project root (the folder with `pyproject.toml`):

```bash
uv tool install .       # builds the package and installs the `books` command globally
```

uv places the executable at `~/.local/bin/books`. Verify:

```bash
which books             # -> /Users/<you>/.local/bin/books
books --help
```

If your shell can't find `books`, `~/.local/bin` isn't on your PATH. Fix it with:

```bash
uv tool update-shell    # adds ~/.local/bin to PATH, then restart your terminal
```

### 2. Enable shell autocomplete (optional)

Run this in your own interactive shell (it auto-detects zsh/bash/fish):

```bash
books --install-completion
exec zsh                # reload the shell (or open a new terminal)
```

Then `books <Tab>` completes commands, and `--<Tab>` completes options/paths.

### Updating and removing

```bash
uv tool install . --reinstall              # rebuild & reinstall after code changes
uv tool install . --reinstall --editable   # editable: picks up edits without reinstalling
uv tool list                               # show installed tools
uv tool uninstall booktools                # remove the `books` command
```

### Alternative: run without installing globally

```bash
uv sync                 # create the project venv and install deps
uv run books --help     # run via uv without a global install
```

## Configuration

`booktools` reads a config file at `~/.config/booktools/config.toml` (honoring
`$XDG_CONFIG_HOME`), auto-created with defaults on first run. It has three keys:

```toml
obsidian_path = "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian"
vault = "History"
imports = ".imports"
```

The vault used by every command is `obsidian_path/vault`; pass `--output` to
override it for a single run. `imports` names a **hidden** (dot-prefixed) folder
*inside* the vault that holds raw import sources — because it starts with a dot,
Obsidian keeps it out of its file explorer, search, and graph. Each importer reads
its own subfolder: `.imports/goodreads`, `.imports/readwise`,
`.imports/highlighted`, `.imports/kobo`. This is why the zero-config
`books <command>` invocations below just work — drop a source in the right
subfolder and the importer finds it. (`calibre` is the exception: it defaults to
`~/Calibre Library`, where Calibre keeps its library.)

## Commands

```bash
# One command to refresh the whole vault — runs every importer in order,
# skipping any whose source is missing:
books sync           # calibre → goodreads → kobo → highlighted → readwise
books sync --dry-run # show which steps would run (and from where) without writing

# With sources dropped into <vault>/.imports/<name>/ and a configured vault,
# every importer runs with no arguments (output defaults to the configured vault):
books calibre        # imports ~/Calibre Library
books goodreads      # newest CSV in <vault>/.imports/goodreads
books readwise       # newest CSV in <vault>/.imports/readwise
books highlighted    # every CSV in <vault>/.imports/highlighted
books kobo           # copies a mounted Kobo's DB into <vault>/.imports/kobo, exports a zip

# ...or point at explicit paths (overrides the defaults):
books calibre --library ~/"Calibre Library" --output ~/Obsidian
books goodreads --csv ~/goodreads_library_export.csv
books kobo ~/KoboReader.sqlite --obsidian
```

Output defaults to the configured vault; in kobo's CSV mode `--output` is a zip
path that defaults to `./kobo_highlights.zip`.

- **`sync`** — Master orchestrator: runs every importer in dependency order
  (`calibre` → `goodreads` → `kobo` → `highlighted` → `readwise`) using each
  command's default options, so one command refreshes the whole vault. The
  note-creating importers run first to establish book identity; the highlight
  enrichers follow and only fill existing notes. Each step is **skipped when its
  source is absent** (calibre: `~/Calibre Library` exists; goodreads/highlighted/
  readwise: a `*.csv` in the matching `.imports/<name>` folder; kobo: a mounted
  device or a `*.sqlite` in `.imports/kobo`), and a step that **fails is reported
  but never stops the others**. Covers are out of scope — run `covers` separately.
  `--output` overrides the vault; `--dry-run` prints the detection plan without
  writing. A colored per-step and summary report is printed at the end.
- **`calibre`** — Convert a Calibre library into an Obsidian markdown
  vault: copies covers into `Covers/`, extracts `.opf` metadata into YAML
  properties, and links authors/topics for a graph-friendly vault. `--library`
  defaults to `~/Calibre Library`.
- **`goodreads`** — Convert a Goodreads CSV export into Obsidian book
  notes (read books by default; `--shelf all` for everything). Merges with
  existing Calibre notes without overwriting, and writes each review once into a
  `## Review` section of the book note (never clobbered on re-runs). `--csv`
  accepts a file or a folder (newest CSV), defaulting to `<vault>/.imports/goodreads`.
- **`readwise`** — Convert a Readwise CSV export into Obsidian book notes,
  rendering highlights into a `## Highlights` section of the book note. `--csv`
  accepts a file or a folder (newest CSV), defaulting to `<vault>/.imports/readwise`.
- **`kobo`** — Export Kobo highlights & notes to per-book CSVs in a zip (`--csv`,
  the default output mode); pass `--obsidian` for the Obsidian vault mode. When no
  DB path is given, a mounted Kobo's database is safely copied into
  `<vault>/.imports/kobo/` and read from there.
- **`highlighted`** — Import highlights captured from *physical* books with the
  [Highlighted](https://highlighted.app) app (CSV export) into Obsidian book
  notes, labelled and anchored by page. `--csv` imports every CSV in a folder,
  defaulting to `<vault>/.imports/highlighted`.

Every importer records provenance: the `source:` property on the book note
(`calibre`/`goodreads`/`kobo`/`highlighted`/`readwise`).

### The vault layout

Everything lives in flat, top-level folders:

- `Books/` — the indexed book notes (`<Title> - <Author>.md`). Each is a single
  self-contained file: frontmatter, a cover embed, an optional `## Review` section,
  and a `## Highlights` section.
- `Covers/` — cover images, named `<Title> - <Author>.jpg` to match their note.
- `Notes/` — your own free-form notes. These are never written by the importers;
  a book note links to its note via a `notes:` frontmatter wikilink.
- `Authors/` and `Topics/` — stub/hub notes for the graph.

Re-running an importer is safe: highlights sit between
`%% books:highlights:start %%` / `%% books:highlights:end %%` markers and are
regenerated wholesale, while anything you write elsewhere in the note (including a
hand-edited `## Review`) is preserved.

### Kobo → Obsidian highlights

Render highlights into your Obsidian vault instead of CSV:

```bash
books kobo /path/to/KoboReader.sqlite --obsidian --output ~/Obsidian
```

For each book with highlights this fills a `## Highlights` section of the book
note (Obsidian `[!quote]`/`[!note]` callouts with stable block anchors).

### Highlighted → Obsidian highlights

Import highlights captured from *physical* books with the
[Highlighted](https://highlighted.app) app (CSV export):

```bash
books highlighted --csv "Highlights for Stalin.csv" --output ~/Obsidian
```

Every highlight is imported and grouped by book. For each book this fills a
`## Highlights` section of the book note — Obsidian `[!quote]`/`[!note]` callouts
labelled by page (`p. 45–49`) with stable `^p45-49` block anchors. Books are
matched to existing notes by ISBN, so highlights land alongside any
Calibre/Goodreads data for the same book.

The standalone scripts in `scripts/` still work too:

```bash
uv run python scripts/calibre_to_obsidian.py --output ~/Obsidian
uv run python scripts/goodreads_to_obsidian.py --csv ~/goodreads_library_export.csv
uv run python scripts/kobo_export.py -o kobo_highlights.zip
```

## Adding a capability

1. Create `booktools/<feature>.py` with a `register(app: typer.Typer)` function
   that attaches your `@app.command()`.
2. Add the module to `CAPABILITIES` in `booktools/cli.py`.

## Development

```bash
uv run pytest -q
```
