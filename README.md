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

- **`calibre`** — Convert a Calibre library into an Obsidian markdown
  vault: copies covers, extracts `.opf` metadata into YAML properties, and links
  authors/genres for a graph-friendly vault. `--library` defaults to
  `~/Calibre Library`.
- **`goodreads`** — Convert a Goodreads CSV export into Obsidian book
  notes (read books by default; `--shelf all` for everything). Merges with
  existing Calibre notes without overwriting, and extracts each review into a
  generic `Review.md` embedded in the book note via `![](Review.md)`. `--csv`
  accepts a file or a folder (newest CSV), defaulting to `<vault>/.imports/goodreads`.
- **`readwise`** — Convert a Readwise CSV export into Obsidian book notes,
  writing per-book `Highlights.md` callouts embedded into the book note. `--csv`
  accepts a file or a folder (newest CSV), defaulting to `<vault>/.imports/readwise`.
- **`kobo`** — Export Kobo highlights & notes to per-book CSVs in a zip (`--csv`,
  the default output mode); pass `--obsidian` for the Obsidian vault mode. When no
  DB path is given, a mounted Kobo's database is safely copied into
  `<vault>/.imports/kobo/` and read from there.
- **`highlighted`** — Import highlights captured from *physical* books with the
  [Highlighted](https://highlighted.app) app (CSV export) into Obsidian book
  notes, labelled and anchored by page. `--csv` imports every CSV in a folder,
  defaulting to `<vault>/.imports/highlighted`.

Every export records provenance: content leaves (`Highlights.md`/`Review.md`)
carry a `source:` property (`kobo`/`highlighted`/`goodreads`), and the `calibre`
and `goodreads` importers stamp `source` on the book note itself.

### Kobo → Obsidian highlights

Export highlights into an Obsidian vault (folder-per-book) instead of CSV:

```bash
books kobo /path/to/KoboReader.sqlite --obsidian --output ~/Obsidian
```

For each book with highlights this writes `<Author>/<Title>/Highlights.md`
(Obsidian `[!quote]`/`[!note]` callouts with stable block anchors) and embeds it
into the book note via `![](Highlights.md)`.

**Optional: seamless embeds.** By default Obsidian wraps embeds in a bordered
box. To make `Highlights.md`/`Review.md` render as if written inline, add a CSS
snippet at `<vault>/.obsidian/snippets/seamless-embeds.css` and enable it under
**Settings → Appearance → CSS snippets**:

```css
.markdown-embed-title { display: none; }
.markdown-embed { border: none; padding: 0; margin: 0; }
.markdown-embed-link { display: none; }
```

### Highlighted → Obsidian highlights

Import highlights captured from *physical* books with the
[Highlighted](https://highlighted.app) app (CSV export):

```bash
books highlighted --csv "Highlights for Stalin.csv" --output ~/Obsidian
```

Every highlight is imported and grouped by book. For each book this writes
`<Author>/<Title>/Highlights.md` — Obsidian `[!quote]`/`[!note]` callouts labelled
by page (`p. 45–49`) with stable `^p45-49` block anchors — and embeds it into the
book note via `![](Highlights.md)`. Books are matched to existing notes by ISBN,
so highlights land alongside any Calibre/Goodreads data for the same book.

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
