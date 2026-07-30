# Config Defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every `books` command a real default Obsidian vault sourced from a user-editable config file, so `--output` becomes an override you rarely need.

**Architecture:** A new `books/config.py` reads `~/.config/books/config.toml` (auto-created with defaults on first run) into a small `Config` dataclass, and exposes `default_vault()` and a `resolve_vault(output)` helper. Each command changes its `--output` default from `Path("Obsidian")` to `None` and resolves the vault via `resolve_vault`, preserving the existing `--output` override and the `resolve_path` convention.

**Tech Stack:** Python (stdlib `tomllib`, `dataclasses`, `os`, `pathlib`), Typer, pytest.

---

## File Structure

- **Create:** `books/config.py` — config loading + vault resolution (single responsibility: where does the vault live).
- **Create:** `tests/test_config.py` — unit tests for the config module.
- **Modify:** `pyproject.toml` — bump `requires-python` to `>=3.11` (stdlib `tomllib`).
- **Modify:** `books/calibre_obsidian.py`, `books/goodreads_obsidian.py`,
  `books/highlighted_obsidian.py`, `books/readwise_obsidian.py`,
  `books/kobo_export.py`, `books/covers.py` — use config-backed default.
- **Modify:** `CLAUDE.md` — document the config file.

`resolve_path` stays in `books/__init__.py`; `config.py` imports it. No circular
import risk because `__init__.py` does not import `config`.

---

## Task 1: Config module

**Files:**
- Create: `books/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_config.py`:

```python
"""Tests for books.config (config file + vault resolution)."""

from pathlib import Path

from books import config


def test_load_config_creates_default_file_when_absent(tmp_path):
    cfg_file = tmp_path / "books" / "config.toml"
    cfg = config.load_config(cfg_file)
    assert cfg.obsidian_path == config.DEFAULT_OBSIDIAN_PATH
    assert cfg.vault == config.DEFAULT_VAULT
    assert cfg_file.is_file()
    text = cfg_file.read_text()
    assert 'obsidian_path = "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian"' in text
    assert 'vault = "History"' in text


def test_load_config_reads_existing_values(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('obsidian_path = "~/Vaults"\nvault = "Reading"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.obsidian_path == "~/Vaults"
    assert cfg.vault == "Reading"


def test_load_config_falls_back_per_key_on_partial_file(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('vault = "Reading"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.obsidian_path == config.DEFAULT_OBSIDIAN_PATH
    assert cfg.vault == "Reading"


def test_load_config_falls_back_on_malformed_toml(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("this is not valid toml = = =\n")
    cfg = config.load_config(cfg_file)
    assert cfg.obsidian_path == config.DEFAULT_OBSIDIAN_PATH
    assert cfg.vault == config.DEFAULT_VAULT


def test_config_path_respects_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config.config_path() == tmp_path / "xdg" / "books" / "config.toml"


def test_config_path_defaults_to_dot_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert config.config_path() == tmp_path / ".config" / "books" / "config.toml"


def test_default_vault_joins_and_expands(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('obsidian_path = "~/Obs"\nvault = "History"\n')
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/me")))
    assert config.default_vault(cfg_file) == Path("/home/me/Obs/History")


def test_resolve_vault_prefers_explicit_output(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
    assert config.resolve_vault(Path("SomeVault")) == tmp_path / "SomeVault"


def test_resolve_vault_uses_config_when_output_none(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('obsidian_path = "/data/Obs"\nvault = "History"\n')
    monkeypatch.setattr(config, "config_path", lambda: cfg_file)
    assert config.resolve_vault(None) == Path("/data/Obs/History")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'books.config'` (or `AttributeError`).

- [ ] **Step 3: Write the config module**

Create `books/config.py`:

```python
"""User configuration for the ``books`` CLI.

Reads ``~/.config/books/config.toml`` (respecting ``$XDG_CONFIG_HOME``),
auto-creating it with commented defaults on first run. Supplies the default
Obsidian vault directory so most commands need no ``--output``.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from books import resolve_path

DEFAULT_OBSIDIAN_PATH = "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian"
DEFAULT_VAULT = "History"

_DEFAULT_FILE = (
    f'# books configuration\nobsidian_path = "{DEFAULT_OBSIDIAN_PATH}"\nvault = "{DEFAULT_VAULT}"\n'
)


@dataclass
class Config:
    """Resolved config values (built-in defaults when unset)."""

    obsidian_path: str = DEFAULT_OBSIDIAN_PATH
    vault: str = DEFAULT_VAULT


def config_path() -> Path:
    """Location of the config file, honouring ``$XDG_CONFIG_HOME``."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "books" / "config.toml"


def load_config(path: Path | None = None) -> Config:
    """Load config from *path* (default: ``config_path()``).

    Auto-creates the file with defaults when absent. Malformed TOML or missing
    keys fall back to the built-in default per key, so a bad config never crashes.
    """
    path = path or config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_DEFAULT_FILE)
        return Config()
    try:
        data = tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return Config()
    obsidian_path = data.get("obsidian_path")
    vault = data.get("vault")
    if not isinstance(obsidian_path, str) or not obsidian_path:
        obsidian_path = DEFAULT_OBSIDIAN_PATH
    if not isinstance(vault, str) or not vault:
        vault = DEFAULT_VAULT
    return Config(obsidian_path=obsidian_path, vault=vault)


def default_vault(path: Path | None = None) -> Path:
    """The configured vault directory: ``obsidian_path`` (expanded) / ``vault``."""
    cfg = load_config(path)
    return Path(cfg.obsidian_path).expanduser() / cfg.vault


def resolve_vault(output: Path | None) -> Path:
    """Resolve the vault to use for a command.

    Explicit ``--output`` (resolved against the cwd via ``resolve_path``) wins;
    otherwise fall back to the configured default vault.
    """
    if output is not None:
        return resolve_path(output, Path.cwd())
    return default_vault()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Bump the Python floor**

In `pyproject.toml`, change:

```toml
requires-python = ">=3.9"
```

to:

```toml
requires-python = ">=3.11"
```

(Required because `tomllib` is stdlib only from 3.11; the active interpreter is 3.12.)

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (existing tests unaffected).

- [ ] **Step 7: Commit**

```bash
git add books/config.py tests/test_config.py pyproject.toml
git commit -m "feat(config): config file with default Obsidian vault

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Wire the four uniform importers (calibre, goodreads, highlighted, readwise)

These four share the exact pattern: `output: Path = typer.Option(Path("Obsidian"), ...)`
followed by `output = resolve_path(output, Path.cwd())`.

**Files:**
- Modify: `books/calibre_obsidian.py` (option ~line 278, resolve ~line 299)
- Modify: `books/goodreads_obsidian.py` (option ~line 240, resolve ~line 262)
- Modify: `books/highlighted_obsidian.py` (option ~line 111, resolve ~line 126)
- Modify: `books/readwise_obsidian.py` (option ~line 152, resolve ~line 167)
- Test: `tests/test_config.py` (add integration-style assertions is optional; covered below)

- [ ] **Step 1: Write a failing test for the config-backed default**

Add to `tests/test_config.py`:

```python
def test_importers_use_config_default(monkeypatch, tmp_path):
    """resolve_vault(None) is the single source every importer relies on."""
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('obsidian_path = "/vaults"\nvault = "History"\n')
    monkeypatch.setattr(config, "config_path", lambda: cfg_file)
    from books import config as cfg_mod

    assert cfg_mod.resolve_vault(None) == Path("/vaults/History")
```

Run: `uv run pytest tests/test_config.py::test_importers_use_config_default -q`
Expected: PASS already (this pins the contract the importers depend on). If it fails, Task 1 is broken — fix that first.

- [ ] **Step 2: Update `calibre_obsidian.py`**

Add the import near the top (after the existing `from books import resolve_path`):

```python
from books import config
```

Change the `output` option (lines ~278-282) from:

```python
output: Path = (
    typer.Option(
        Path("Obsidian"),
        "--output",
        "-o",
        help="Output Obsidian vault. Relative paths resolve against the current directory.",
    ),
)
```

to:

```python
output: Path | None = (
    typer.Option(
        None,
        "--output",
        "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
)
```

Change the resolution line (~line 299) from:

```python
    output = resolve_path(output, Path.cwd())
```

to:

```python
    output = config.resolve_vault(output)
```

- [ ] **Step 3: Update `goodreads_obsidian.py`**

Add `from books import config` near the top.

Change the `output` option (lines ~240-244) from:

```python
output: Path = (
    typer.Option(
        Path("Obsidian"),
        "--output",
        "-o",
        help="Output Obsidian vault. Relative paths resolve against the current directory.",
    ),
)
```

to:

```python
output: Path | None = (
    typer.Option(
        None,
        "--output",
        "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
)
```

Change the resolution line (~line 262) from:

```python
    output = resolve_path(output, Path.cwd())
```

to:

```python
    output = config.resolve_vault(output)
```

- [ ] **Step 4: Update `highlighted_obsidian.py`**

Add `from books import config` near the top.

Change the `output` option (lines ~111-115) from:

```python
output: Path = (
    typer.Option(
        Path("Obsidian"),
        "--output",
        "-o",
        help="Output Obsidian vault. Relative paths resolve against the current directory.",
    ),
)
```

to:

```python
output: Path | None = (
    typer.Option(
        None,
        "--output",
        "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
)
```

Change the resolution line (~line 126) from:

```python
    output = resolve_path(output, Path.cwd())
```

to:

```python
    output = config.resolve_vault(output)
```

- [ ] **Step 5: Update `readwise_obsidian.py`**

Add `from books import config` near the top.

Change the `output` option (lines ~152-156) from:

```python
output: Path = (
    typer.Option(
        Path("Obsidian"),
        "--output",
        "-o",
        help="Output Obsidian vault. Relative paths resolve against the current directory.",
    ),
)
```

to:

```python
output: Path | None = (
    typer.Option(
        None,
        "--output",
        "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
)
```

Change the resolution line (~line 167) from:

```python
    output = resolve_path(output, Path.cwd())
```

to:

```python
    output = config.resolve_vault(output)
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS. Existing tests pass `--output` explicitly (via the Typer test runner or direct calls), so they still resolve as before.

- [ ] **Step 7: Commit**

```bash
git add books/calibre_obsidian.py books/goodreads_obsidian.py \
        books/highlighted_obsidian.py books/readwise_obsidian.py tests/test_config.py
git commit -m "feat(config): calibre/goodreads/highlighted/readwise default to configured vault

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Wire the `kobo` command

`kobo` already uses `output: Path | None = None`; only the Obsidian-mode resolution
line needs to use the config helper. CSV mode (`--output` = a zip path) is untouched.

**Files:**
- Modify: `books/kobo_export.py` (resolve ~line 297)

- [ ] **Step 1: Add the import**

Near the top of `books/kobo_export.py`, add:

```python
from books import config
```

- [ ] **Step 2: Update the Obsidian-mode vault resolution**

Change (line ~297) from:

```python
        vault = resolve_path(output or Path("Obsidian"), Path.cwd())
```

to:

```python
        vault = config.resolve_vault(output)
```

- [ ] **Step 3: Update the `--obsidian` help text**

Change the `--obsidian` option help (lines ~270-275) from:

```python
obsidian: bool = (
    typer.Option(
        False,
        "--obsidian",
        help="Write highlights into an Obsidian vault (flat note + Exports/) instead "
        "of CSV/zip. In this mode --output is the vault directory "
        "[default: ./Obsidian].",
    ),
)
```

to:

```python
obsidian: bool = (
    typer.Option(
        False,
        "--obsidian",
        help="Write highlights into an Obsidian vault (flat note + Exports/) instead "
        "of CSV/zip. In this mode --output is the vault directory "
        "[default: the vault from ~/.config/books/config.toml].",
    ),
)
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add books/kobo_export.py
git commit -m "feat(config): kobo --obsidian defaults to configured vault

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Wire the `covers` command

`covers` uses `output` only in full-vault-scan mode (the `else` branch); `--book`
mode infers the vault from the note path and is untouched.

**Files:**
- Modify: `books/covers.py` (option ~line 392, resolve ~line 438)

- [ ] **Step 1: Add the import**

`books/covers.py` already has `from books import resolve_path` (line 24).
Change it to also import config:

```python
from books import config, resolve_path
```

- [ ] **Step 2: Update the `output` option**

Change (lines ~392-396) from:

```python
output: Path = (
    typer.Option(
        Path("Obsidian"),
        "--output",
        "-o",
        help="Obsidian vault to scan. Relative paths resolve against the current directory.",
    ),
)
```

to:

```python
output: Path | None = (
    typer.Option(
        None,
        "--output",
        "-o",
        help="Obsidian vault to scan. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
)
```

- [ ] **Step 3: Update the full-scan resolution**

Change (line ~438) from:

```python
        vault = resolve_path(output, Path.cwd())
```

to:

```python
        vault = config.resolve_vault(output)
```

Leave the surrounding `else` block (the `Books/` existence check and `BadParameter`)
unchanged. `resolve_path` is still imported and used for `--book` on line 428.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add books/covers.py
git commit -m "feat(config): covers full-scan defaults to configured vault

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Document the config in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a config section**

In `CLAUDE.md`, under the `## Architecture` section (after the "Six capabilities"
list, before "The `#tag` / `@link` convention"), add:

```markdown
### Configuration

`books/config.py` supplies the default Obsidian vault. It reads
`~/.config/books/config.toml` (respecting `$XDG_CONFIG_HOME`), auto-creating it
with defaults on first run: `obsidian_path` (the folder holding your vaults, default
`~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian`) and `vault` (the vault
name, default `History`). `default_vault()` joins them; `resolve_vault(output)` is
the single helper every command calls — explicit `--output` wins, otherwise the
configured vault is used. This is why most commands need no `--output`. Reads use
stdlib `tomllib` (Python 3.11+); malformed/partial config falls back per key.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(config): document the config file in CLAUDE.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Manual verification (after all tasks)

- [ ] Run `uv run books covers --help` and confirm the `--output` help mentions the config file.
- [ ] Temporarily rename any existing `~/.config/books/config.toml`, run
      `uv run python -c "from books import config; print(config.default_vault())"`,
      confirm it prints `.../Obsidian/History` and the file was created. Restore the original if present.
- [ ] Run `uv run pytest -q` — full suite green.
```
