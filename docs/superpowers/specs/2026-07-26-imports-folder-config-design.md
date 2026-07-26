# Config-driven `.imports` folder for importer inputs

Date: 2026-07-26

## Problem

Every importer takes its input path via a flag with an ad-hoc default:

- `calibre` → `--library` (default `~/Calibre Library`)
- `goodreads` → `--csv` (required)
- `highlighted` → `--csv` (required; accepts a file or folder)
- `readwise` → `--csv` (required)
- `kobo` → `--input`/positional `db` (default `./KoboReader.sqlite`)

There is no way to configure a default input location, so `goodreads`, `readwise`,
and (usually) the others require an explicit path on every run. The user wants the
raw source data to live *with* the Obsidian vault, but hidden from Obsidian, and
wants each importer to find its input automatically.

## Solution overview

Keep the raw data inside the vault in a dot-prefixed folder, `.imports/`. Obsidian
natively ignores any file/folder whose name starts with `.` (no per-vault setting
needed, not indexed, never in the graph). iCloud Drive syncs dot-folders fine.

Each importer gets a canonical subfolder under `.imports/` and uses it as its
default input. Explicit flags continue to override.

```
Obsidian/
  History/               <- vault (obsidian_path/vault)
    .obsidian/
    .imports/            <- raw data, hidden from Obsidian
      calibre/           <- a Calibre library
      goodreads/         <- Goodreads CSV export(s)
      highlighted/       <- Highlighted CSV export(s)
      readwise/          <- Readwise CSV export(s)
      kobo/              <- KoboReader.sqlite
    Books/
    Authors/
    ...
```

## Config schema

Add a single `imports` key to `config.py`, next to `obsidian_path`/`vault`:

```toml
# books configuration
obsidian_path = "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian"
vault = "History"
# Folder (inside the vault) holding raw import sources, hidden from Obsidian.
imports = ".imports"
```

Changes to `books/config.py`:

- `Config` gains an `imports: str = DEFAULT_IMPORTS` field (`DEFAULT_IMPORTS = ".imports"`).
- `_DEFAULT_FILE` gains the commented `imports` line.
- `load_config` reads `imports` with the same defensive per-key fallback used for
  `obsidian_path`/`vault` (non-string or empty → default).
- New helper:

  ```python
  def resolve_imports(name: str, output: Path | None = None) -> Path:
      """Canonical import subfolder for a command: <vault>/<imports>/<name>."""
      vault = resolve_vault(output)
      cfg = load_config()
      root = resolve_path(Path(cfg.imports), vault)  # absolute imports honored; else joined onto vault
      return root / name
  ```

  The imports root resolves **inside the resolved vault**, so it travels with
  whichever vault `--output`/config selects. An absolute `imports` value is used
  as-is (via `resolve_path`).

## Folder → file selection helper

Add a shared helper (in `config.py`) for the single-file CSV importers:

```python
def newest_csv(folder: Path) -> Path:
    """Most-recently-modified top-level *.csv in *folder*.

    Raises FileNotFoundError if the folder is missing or contains no CSV.
    """
```

- Lists top-level `*.csv` only (not recursive), picks max by mtime.
- Missing folder or no CSV → `FileNotFoundError` with the folder path in the message.

## Per-command changes

Each importer's input option becomes optional (`default None`). When omitted it
resolves to its canonical `.imports/<name>` subfolder; an explicit flag overrides
and resolves exactly as it does today.

| Command | Flag | `.imports` subfolder | Folder handling |
|---|---|---|---|
| `calibre` | `--library` / `-l` | `calibre` | used directly as a Calibre library |
| `goodreads` | `--csv` / `-c` | `goodreads` | **newest `*.csv`** |
| `readwise` | `--csv` / `-c` | `readwise` | **newest `*.csv`** |
| `highlighted` | `--csv` / `-c` | `highlighted` | every `*.csv` (unchanged) |
| `kobo` | `db` arg / `--input` | `kobo` | mounted device → safe copy; else `KoboReader.sqlite`, else newest `*.sqlite` |

### calibre
- `--library` default becomes `None`. When `None`: `library = config.resolve_imports("calibre")`.
- When provided: `resolve_path(library, Path.home())` (unchanged).
- Existing "library not found" `BadParameter` covers the missing-default case.

### goodreads / readwise
- `--csv` default becomes `None` (no longer required).
- Resolution:
  - `None` → `folder = config.resolve_imports("goodreads"|"readwise")`, then `csv = newest_csv(folder)`.
  - explicit **file** → unchanged.
  - explicit **folder** → `newest_csv(folder)` (folder support is new for these two).
- `newest_csv` raising `FileNotFoundError` is converted to `typer.BadParameter`
  naming the expected folder (e.g. *"no CSV found in <vault>/.imports/goodreads"*).

Note: this intentionally differs from `highlighted`. Goodreads/Readwise CSVs are
full-library snapshots (newest = most complete; goodreads is typically a single
overwritten file), whereas Highlighted exports are many independent per-book files.

### highlighted
- `--csv` default becomes `None`. When `None`: `csv = config.resolve_imports("highlighted")`.
- Everything else (`resolve_csv_paths`, import-every-CSV) unchanged.

### kobo
- Default input becomes the `.imports/kobo` folder instead of `./KoboReader.sqlite`.
- **Safe device auto-copy.** To eliminate any risk of corrupting the live device DB,
  the export never opens the device file directly. When no path is given and a Kobo
  is mounted (its DB is always at `/Volumes/KOBOeReader/.kobo/KoboReader.sqlite`),
  the command snapshots it into `<vault>/.imports/kobo/KoboReader.sqlite` using
  SQLite's backup API (`sqlite3.Connection.backup`) with the source opened read-only
  (`file:...?mode=ro`) — a consistent copy even with an active WAL, with the device
  file never modified — then reads the copy.
- Resolution when neither `db` nor `--input` given (`_default_kobo_db`):
  - if `KOBO_DEVICE_DB` (the fixed device path) exists → `_safe_copy_db` it into
    `folder/KoboReader.sqlite` and use the copy.
  - else if `folder/KoboReader.sqlite` exists → use it.
  - else newest `*.sqlite` in the folder.
  - else `BadParameter` naming the expected folder.
- `KOBO_DEVICE_DB` is a module-level constant so tests can monkeypatch it.
- Explicit `db`/`--input` → `resolve_path(..., Path.cwd())`, read directly
  (read-only, unchanged).

## Errors

Any command run with nothing configured yet fails with a `typer.BadParameter`
naming the exact expected path, so the fix (drop a file into
`<vault>/.imports/<name>/`) is self-evident.

## Testing

- `Config.imports` fallback (missing key, empty, non-string → default).
- `resolve_imports`: default `.imports` joined onto vault; absolute `imports` honored;
  respects `--output` override.
- `newest_csv`: picks newest by mtime; missing folder → error; empty folder → error;
  single file → that file.
- Per command: default resolves to `.imports/<name>`; explicit override precedence;
  goodreads/readwise folder → newest CSV.
- kobo: mounted device (`KOBO_DEVICE_DB` monkeypatched in tests) → safe copy into
  `.imports/kobo` and export from the copy, device file untouched; no device → uses
  existing `.imports/kobo/KoboReader.sqlite`; nothing available → error.

## Docs

- `CLAUDE.md`: extend the Configuration section (new `imports` key, `.imports`
  convention, per-command subfolders) and adjust the per-command capability notes
  (goodreads/readwise now accept a folder; default inputs live under `.imports`).
- Update `--library` / `--csv` / kobo `db`/`--input` help strings to mention the
  `.imports/<name>` default.

## Out of scope

- Migrating/moving existing raw data into `.imports` (user does this manually).
- Recursive CSV discovery.
- Per-command config overrides (single `imports` key + fixed subfolder names only).
