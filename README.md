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

## Commands

```bash
books calibre --library ~/"Calibre Library" --output ~/Obsidian
books goodreads --csv ~/goodreads_library_export.csv --output ~/Obsidian
books kobo ~/KoboReader.sqlite --csv -o kobo_highlights.zip
```

- **`calibre`** — Convert a Calibre library into an Obsidian markdown
  vault: copies covers, extracts `.opf` metadata into YAML properties, and links
  authors/genres for a graph-friendly vault.
- **`goodreads`** — Convert a Goodreads CSV export into Obsidian book
  notes (read books by default; `--shelf all` for everything). Merges with
  existing Calibre notes without overwriting, and extracts each review into a
  separate `<Title> - Review.md`.
- **`kobo`** — Export Kobo highlights & notes to per-book CSVs in a zip (`--csv`,
  the default output mode; an Obsidian mode will be added later).

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
