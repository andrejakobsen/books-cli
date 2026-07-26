# Config defaults for the `books` CLI

**Date:** 2026-07-26
**Status:** Approved

## Problem

Every `books` capability (`calibre`, `goodreads`, `kobo`, `highlighted`,
`readwise`, `covers`) defaults its `--output` (the Obsidian vault) to
`Path("Obsidian")` resolved against the current working directory. In practice
the user's vault always lives at the same absolute location, so `--output` has to
be passed on nearly every invocation. The goal is a user-editable config file that
supplies a real default vault, so `--output` becomes an override you rarely need.

## Goals

- A default Obsidian location and vault sourced from a config file the user can edit.
- With the config in place, most commands need no `--output` — they infer the
  vault (and therefore the right files/folders) automatically.
- Follow the `~/.config` (XDG) convention.
- No new runtime dependency; stdlib only (matches the existing project constraint).

## Non-goals (YAGNI)

- No `books config` view/get/set command — manual editing of the auto-created file only.
- No environment-variable configuration.
- No TOML *writer*: the auto-created file is emitted as plain text.

## Config file

- **Location:** `~/.config/booktools/config.toml`, respecting `$XDG_CONFIG_HOME`
  when set (i.e. `${XDG_CONFIG_HOME:-~/.config}/booktools/config.toml`).
- **Auto-creation:** if the file (or its parent directory) is missing, it is
  created on first run with commented defaults:

  ```toml
  # booktools configuration
  obsidian_path = "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian"
  vault = "History"
  ```

- **Reading:** stdlib `tomllib` (Python 3.11+). No TOML writer needed.

## Schema

Two keys, matching how the user thinks about the layout:

- `obsidian_path` — the directory that contains Obsidian vaults, e.g.
  `~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian`.
- `vault` — the vault name within it, e.g. `History`.

The resolved default vault directory is `expanduser(obsidian_path) / vault`
(e.g. `.../Obsidian/History`). This is the value each command uses in place of the
old `Path("Obsidian")` default. It is a real Obsidian vault folder — the same thing
the existing `--output` already points at (commands look for `Books/` inside it).

## New module: `booktools/config.py`

- `load_config() -> Config` — reads the TOML, auto-creating it with defaults when
  absent, and returns a small dataclass with `obsidian_path: str` and `vault: str`.
- `default_vault() -> Path` — resolves `obsidian_path` (expanding `~`) joined with
  `vault`, returning the vault directory commands use when `--output` is omitted.
  This is the single helper every command calls.
- **Robustness:** malformed or partial TOML falls back to the built-in default
  per key, so a bad config never crashes a command.

## Wiring into commands

Each command's `output` option changes from a hard default of `Path("Obsidian")`
to `None`. Inside the command, resolution becomes:

```python
vault = resolve_path(output, Path.cwd()) if output else config.default_vault()
```

- Preserves the existing `--output` override and the `resolve_path` convention
  (absolute / `~` used as-is; relative resolved against cwd).
- Makes `--output` optional across `calibre`, `goodreads`, `kobo`, `highlighted`,
  `readwise`, and `covers`.
- Help text updates to note the default comes from the config file.

**Precedence:** explicit `--output` flag > config file > built-in fallback.

`covers` additionally has `--book PATH` (single-note mode, vault inferred from the
path). That path stays unchanged; only the full-vault-scan `--output` default is
sourced from config.

### Standalone shims

`scripts/*.py` shims call each module's `main()`, so they inherit the config-backed
default automatically once the modules change. No shim edits needed beyond staying
in sync if a module's `main()` signature changes (it does not here).

## Testing

Unit tests for `config.py`:

- Default file is created (with expected contents) when absent.
- `$XDG_CONFIG_HOME` is respected; falls back to `~/.config` when unset.
- `~` expansion and `obsidian_path` + `vault` joining produce the expected path.
- Malformed / partial TOML falls back to built-in defaults per key.

Command-level:

- Existing tests keep passing (explicit `--output` still works).
- Add a test that omitting `--output` resolves to the configured vault.
