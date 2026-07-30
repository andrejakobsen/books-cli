# Consolidate importers into `books import`; rename `render` → `export` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the eight individual importer/merge commands and `sync` with a single `books import` command (flags select a subset; no flag runs the sync-set), rename `render` to `export`, and move per-importer settings into `~/.config/books/config.toml`.

**Architecture:** `sync.py`'s `Step`/detect/run/summarize orchestration machinery is evolved into `import_cmd.py`, which builds its step list from selection flags and injects `merge` automatically. Per-importer settings become typed config sections read by the runners. `render.py` is renamed to `export.py`. The individual importer modules stay as internal code (their `convert`/`run` cores are reused); only their Typer command wrappers and registrations are removed.

**Tech Stack:** Python 3.11+, Typer (CLI), Rich via `books.core.ui`, pydantic store models, pytest + `typer.testing.CliRunner`.

**Reference spec:** `docs/superpowers/specs/2026-07-30-consolidate-import-export-design.md`

---

## File Structure

- **Modify** `books/core/config.py` — add `CalibreConfig`/`KoboConfig`/`AudibleConfig`/`CoversConfig` dataclasses, extend `Config`, extend `load_config` parsing, extend `_DEFAULT_FILE`.
- **Rename** `books/commands/render.py` → `books/commands/export.py` — rename command (`render`→`export`) + internal function; no behavior change.
- **Modify** `books/commands/audible/command.py` — add config-driven `run_import(vault, cfg, *, dry_run)`, remove `audible_command` + `register`.
- **Modify** `books/commands/covers/command.py` — add config-driven `run_import(vault, cfg, *, dry_run)`, remove `covers_command` + `register`.
- **Create** `books/commands/import_cmd.py` — the `import` command (evolved `sync.py`): selection flags, automatic merge injection, config-driven runners.
- **Delete** `books/commands/sync.py` — absorbed into `import_cmd.py`.
- **Modify** `books/commands/reset.py` — help/success text references `import` instead of `sync`.
- **Modify** `books/cli.py` — `CAPABILITIES = (export, import_cmd, reset)`; drop the rest.
- **Rename** `tests/commands/test_render.py` → `tests/commands/test_export.py` — update command name in invocations.
- **Rename** `tests/commands/test_sync.py` → `tests/commands/test_import.py` — adapt to `import_cmd` + selection/merge tests.
- **Modify** `tests/commands/test_cli.py` — new command surface.
- **Modify** `tests/core/test_config.py` — new config-section tests (create if absent).
- **Modify** `tests/commands/test_audible_*.py` / `test_covers.py` — replace any CLI-wrapper assertions with `run_import` calls.
- **Modify** `CLAUDE.md` — rewrite capability list + pipeline description.

---

## Task 1: Per-importer config sections

**Files:**
- Modify: `books/core/config.py`
- Test: `tests/core/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/core/test_config.py` (create the file with this content if it does not exist; if it exists, append the functions and reuse its existing imports):

```python
from books.core import config


def _write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text)
    return p


def test_config_defaults_when_sections_absent(tmp_path):
    cfg = config.load_config(_write(tmp_path, 'vault = "V"\n'))
    assert cfg.calibre.library == config.DEFAULT_CALIBRE_LIBRARY
    assert cfg.kobo.db == ""
    assert cfg.audible.transcriber == "local"
    assert cfg.audible.select == "interactive"
    assert cfg.covers.interactive is False
    assert cfg.covers.limit == 0


def test_config_reads_importer_sections(tmp_path):
    text = (
        'vault = "V"\n'
        '[calibre]\nlibrary = "~/Books"\n'
        '[kobo]\ndb = "/tmp/K.sqlite"\n'
        '[audible]\ntranscriber = "openai"\nselect = "all"\n'
        '[covers]\ninteractive = true\nlimit = 5\n'
    )
    cfg = config.load_config(_write(tmp_path, text))
    assert cfg.calibre.library == "~/Books"
    assert cfg.kobo.db == "/tmp/K.sqlite"
    assert cfg.audible.transcriber == "openai"
    assert cfg.audible.select == "all"
    assert cfg.covers.interactive is True
    assert cfg.covers.limit == 5


def test_config_rejects_bad_values_per_key(tmp_path):
    text = (
        'vault = "V"\n'
        '[audible]\ntranscriber = "bogus"\nselect = 3\n'
        '[covers]\ninteractive = "yes"\nlimit = "lots"\n'
    )
    cfg = config.load_config(_write(tmp_path, text))
    assert cfg.audible.transcriber == "local"   # invalid choice → default
    assert cfg.audible.select == "interactive"  # wrong type → default
    assert cfg.covers.interactive is False      # wrong type → default
    assert cfg.covers.limit == 0                # wrong type → default


def test_config_malformed_toml_falls_back(tmp_path):
    cfg = config.load_config(_write(tmp_path, "this = = not toml"))
    assert cfg.calibre.library == config.DEFAULT_CALIBRE_LIBRARY
    assert cfg.audible.transcriber == "local"


def test_default_file_parses_and_has_sections():
    import tomllib

    data = tomllib.loads(config._DEFAULT_FILE_PARSEABLE)
    assert "calibre" in data and "audible" in data and "covers" in data
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_config.py -k "importer_sections or defaults_when_sections or bad_values or malformed_toml or default_file_parses" -v`
Expected: FAIL with `AttributeError: ... has no attribute 'calibre'` / `DEFAULT_CALIBRE_LIBRARY` / `_DEFAULT_FILE_PARSEABLE`.

- [ ] **Step 3: Add the dataclasses and defaults**

In `books/core/config.py`, after the existing `DEFAULT_IMPORTS = "Data/Imports"` line, add:

```python
DEFAULT_CALIBRE_LIBRARY = "~/Calibre Library"
_TRANSCRIBERS = ("local", "openai", "google")
_SELECT_MODES = ("interactive", "all")
```

Add these dataclasses immediately before the existing `@dataclass class Config:` block:

```python
@dataclass
class CalibreConfig:
    library: str = DEFAULT_CALIBRE_LIBRARY


@dataclass
class KoboConfig:
    db: str = ""  # empty = auto-detect (mounted device / canonical folder)


@dataclass
class AudibleConfig:
    transcriber: str = "local"  # local | openai | google
    select: str = "interactive"  # interactive | all


@dataclass
class CoversConfig:
    interactive: bool = False
    limit: int = 0  # 0 = no limit
```

- [ ] **Step 4: Extend `Config` with the sub-sections**

Replace the existing `Config` dataclass body with:

```python
@dataclass
class Config:
    """Resolved config values (built-in defaults when unset)."""

    obsidian_path: str = DEFAULT_OBSIDIAN_PATH
    vault: str = DEFAULT_VAULT
    imports: str = DEFAULT_IMPORTS
    calibre: CalibreConfig = field(default_factory=CalibreConfig)
    kobo: KoboConfig = field(default_factory=KoboConfig)
    audible: AudibleConfig = field(default_factory=AudibleConfig)
    covers: CoversConfig = field(default_factory=CoversConfig)
```

Update the import at the top of the file from `from dataclasses import dataclass` to:

```python
from dataclasses import dataclass, field
```

- [ ] **Step 5: Add the section parsers and wire them into `load_config`**

Add these module-level helpers (place them just above `load_config`):

```python
def _table(data: dict, name: str) -> dict:
    """Return the ``[name]`` sub-table, or ``{}`` when absent/not a table."""
    t = data.get(name)
    return t if isinstance(t, dict) else {}


def _str_or(t: dict, key: str, default: str) -> str:
    v = t.get(key)
    return v if isinstance(v, str) else default


def _nonempty_str_or(t: dict, key: str, default: str) -> str:
    v = t.get(key)
    return v if isinstance(v, str) and v else default


def _bool_or(t: dict, key: str, default: bool) -> bool:
    v = t.get(key)
    return v if isinstance(v, bool) else default


def _int_or(t: dict, key: str, default: int) -> int:
    v = t.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else default


def _choice_or(t: dict, key: str, choices: tuple[str, ...], default: str) -> str:
    v = t.get(key)
    return v if isinstance(v, str) and v in choices else default


def _parse_sections(data: dict) -> dict:
    """Build the four importer sub-configs from parsed TOML *data*."""
    cal = _table(data, "calibre")
    kob = _table(data, "kobo")
    aud = _table(data, "audible")
    cov = _table(data, "covers")
    return {
        "calibre": CalibreConfig(
            library=_nonempty_str_or(cal, "library", DEFAULT_CALIBRE_LIBRARY)
        ),
        "kobo": KoboConfig(db=_str_or(kob, "db", "")),
        "audible": AudibleConfig(
            transcriber=_choice_or(aud, "transcriber", _TRANSCRIBERS, "local"),
            select=_choice_or(aud, "select", _SELECT_MODES, "interactive"),
        ),
        "covers": CoversConfig(
            interactive=_bool_or(cov, "interactive", False),
            limit=_int_or(cov, "limit", 0),
        ),
    }
```

In `load_config`, the early-return paths (file absent, malformed TOML) must return a `Config()` with default sections — `Config()` already supplies them via `default_factory`, so those two `return Config()` lines are unchanged. Replace the **final** return line:

```python
    return Config(obsidian_path=obsidian_path, vault=vault, imports=imports)
```

with:

```python
    return Config(
        obsidian_path=obsidian_path,
        vault=vault,
        imports=imports,
        **_parse_sections(data),
    )
```

- [ ] **Step 6: Extend `_DEFAULT_FILE` with commented sections**

Replace the existing `_DEFAULT_FILE = (...)` assignment with:

```python
_DEFAULT_FILE = (
    "# books configuration\n"
    f'obsidian_path = "{DEFAULT_OBSIDIAN_PATH}"\n'
    f'vault = "{DEFAULT_VAULT}"\n'
    "# Folder (inside the vault) holding raw import sources.\n"
    f'imports = "{DEFAULT_IMPORTS}"\n'
    "\n"
    "# Per-importer settings (uncomment to override the defaults shown).\n"
    "# [calibre]\n"
    f'# library = "{DEFAULT_CALIBRE_LIBRARY}"\n'
    "# [kobo]\n"
    '# db = "/path/to/KoboReader.sqlite"  # default: mounted device / imports folder\n'
    "# [audible]\n"
    '# transcriber = "local"   # local | openai | google\n'
    '# select = "interactive"  # interactive | all\n'
    "# [covers]\n"
    "# interactive = false\n"
    "# limit = 0                # 0 = no limit\n"
)

# A fully-uncommented copy used only by tests to assert the sections parse.
_DEFAULT_FILE_PARSEABLE = (
    f'obsidian_path = "{DEFAULT_OBSIDIAN_PATH}"\n'
    f'vault = "{DEFAULT_VAULT}"\n'
    f'imports = "{DEFAULT_IMPORTS}"\n'
    "[calibre]\n"
    f'library = "{DEFAULT_CALIBRE_LIBRARY}"\n'
    "[kobo]\n"
    'db = ""\n'
    "[audible]\n"
    'transcriber = "local"\n'
    'select = "interactive"\n'
    "[covers]\n"
    "interactive = false\n"
    "limit = 0\n"
)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_config.py -v`
Expected: PASS (all config tests, including the new ones).

- [ ] **Step 8: Commit**

```bash
git add books/core/config.py tests/core/test_config.py
git commit -m "feat(config): add per-importer config sections

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Rename `render` → `export`

**Files:**
- Rename: `books/commands/render.py` → `books/commands/export.py`
- Rename: `tests/commands/test_render.py` → `tests/commands/test_export.py`
- Modify: `books/cli.py` (import + `CAPABILITIES`)

- [ ] **Step 1: Rename the module with git**

Run:

```bash
git mv books/commands/render.py books/commands/export.py
git mv tests/commands/test_render.py tests/commands/test_export.py
```

- [ ] **Step 2: Rename the function and command inside `books/commands/export.py`**

In `books/commands/export.py`, rename the function `render_command` → `export_command`, and change the registration line:

```python
def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("export")(export_command)
```

Update the module docstring's first line to:

```python
"""The ``export`` command: turn the merged CSV store into notes for one target.
```

(Leave the rest of the docstring and all rendering logic unchanged — behavior is identical.)

- [ ] **Step 3: Point `books/cli.py` at the renamed module**

In `books/cli.py`, in the `from books.commands import (...)` block, replace `render,` with `export,` (keep the block alphabetical; `export` sorts before `goodreads`). In the `CAPABILITIES` tuple, replace `render,` with `export,` in the same position. (The full rewire of `CAPABILITIES` happens in Task 5; this step only keeps the app importable after the rename.)

- [ ] **Step 4: Update the test invocations in `tests/commands/test_export.py`**

In `tests/commands/test_export.py`, replace every CLI invocation string `"render"` with `"export"`. There are four `CliRunner().invoke(app, [...])` calls using `"render"` (in `test_render_command_renders_vault`, `test_render_command_errors_without_books_csv`, `test_render_command_rejects_removed_no_obsidian_flag`, `test_render_command_refresh_deletes_stale_note`). Change only the leading `"render"` list element to `"export"`; leave function names and all other assertions unchanged.

Run:

```bash
uv run ruff check --fix books/commands/export.py
```

- [ ] **Step 5: Run the export tests**

Run: `uv run pytest tests/commands/test_export.py -v`
Expected: PASS (all previously-passing render tests, now under the `export` command).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: rename render command to export

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Config-driven `run_import` for audible & covers

**Files:**
- Modify: `books/commands/audible/command.py`
- Modify: `books/commands/covers/command.py`
- Test: `tests/commands/test_audible_runimport.py` (new), `tests/commands/test_covers.py`

- [ ] **Step 1: Write the failing audible test**

Create `tests/commands/test_audible_runimport.py`:

```python
"""The config-driven audible.run_import entry point used by `books import`."""

from books.commands.audible import command as audible_cmd
from books.core.config import AudibleConfig


def test_run_import_dry_run_uses_config_transcriber(tmp_path, monkeypatch):
    calls = {}

    def fake_run(vault, **kw):
        calls.update(kw)
        return {"matched": 0, "new": 0, "est_seconds": 0}

    monkeypatch.setattr(audible_cmd, "run", fake_run)
    monkeypatch.setattr(audible_cmd, "_build_client", lambda quality: object())

    cfg = AudibleConfig(transcriber="openai", select="all")
    stats = audible_cmd.run_import(tmp_path, cfg, dry_run=True)

    assert stats["matched"] == 0
    assert calls["dry_run"] is True
    assert calls["show_cost"] is True  # openai → cost shown
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/commands/test_audible_runimport.py -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'run_import'`.

- [ ] **Step 3: Add `run_import` to audible and remove the Typer wrapper**

In `books/commands/audible/command.py`, delete the `audible_command(...)` function and the `register(app)` function, and add in their place:

```python
def run_import(vault: Path, cfg, *, dry_run: bool = False) -> dict:
    """Run the audible import using values from the ``[audible]`` config section.

    *cfg* is a :class:`books.core.config.AudibleConfig`. Behavioral defaults not
    exposed in config (model, quality, clip window, per-book limit) keep their
    prior CLI defaults. The interactive picker is used unless ``select == "all"``
    or there is no interactive terminal (off-tty falls back to processing all).
    """
    cache_dir = config.resolve_imports("audible", vault) / "cache"
    show_cost = cfg.transcriber == "openai"
    client = _build_client("normal")

    if dry_run:
        return run(
            vault,
            client=client,
            downloader=None,
            cutter=None,
            transcriber=None,
            cache_dir=cache_dir,
            clip_window=30,
            limit=None,
            asin=None,
            dry_run=True,
            show_cost=show_cost,
            echo=ui.info,
        )

    interactive = cfg.select != "all" and ui.console.is_terminal
    catalog = store.Catalog(vault)
    with ui.progress("Fetching annotations from Audible…") as prog:
        candidates = build_candidates(client, catalog, cache_dir, None, describe=prog.describe)

    selected = select_books(candidates) if interactive else candidates
    if not selected:
        return {
            "books": 0,
            "new": 0,
            "entries": 0,
            "downloaded": 0,
            "transcribed": 0,
            "failed": 0,
        }

    transcribe_fn = _build_transcriber(cfg.transcriber, "small")
    cutter = _build_cutter()
    downloader = _build_downloader(client)

    return run(
        vault,
        selected=selected,
        client=client,
        downloader=downloader,
        cutter=cutter,
        transcriber=transcribe_fn,
        cache_dir=cache_dir,
        clip_window=30,
        limit=None,
        echo=ui.info,
    )
```

If `typer` is now unused in this file, remove `import typer`. Keep the existing `from books.core import config, store, ui` and `Path` imports (still used).

- [ ] **Step 4: Run the audible test**

Run: `uv run pytest tests/commands/test_audible_runimport.py -v`
Expected: PASS.

- [ ] **Step 5: Write the failing covers test**

Add to `tests/commands/test_covers.py`:

```python
def test_covers_run_import_maps_config(tmp_path, monkeypatch):
    from books.commands.covers import command as covers_cmd
    from books.core.config import CoversConfig

    captured = {}

    def fake_run(vault, **kw):
        captured.update(kw)
        return {
            "by_source": {}, "errored": {}, "scanned": 0,
            "missing": 0, "fetched": 0, "not_found": 0,
        }

    monkeypatch.setattr(covers_cmd, "run", fake_run)

    cfg = CoversConfig(interactive=True, limit=0)
    covers_cmd.run_import(tmp_path, cfg, dry_run=True)

    assert captured["interactive"] is True
    assert captured["dry_run"] is True
    assert captured["limit"] is None   # 0 → no limit
    assert captured["book_id"] is None
```

- [ ] **Step 6: Run it to verify it fails**

Run: `uv run pytest tests/commands/test_covers.py -k run_import -v`
Expected: FAIL with `AttributeError: ... has no attribute 'run_import'`.

- [ ] **Step 7: Add `run_import` to covers and remove the Typer wrapper**

In `books/commands/covers/command.py`, delete the `covers_command(...)` function and the `register(app)` function, and add in their place:

```python
def run_import(vault, cfg, *, dry_run: bool = False) -> dict:
    """Run the covers fetch using values from the ``[covers]`` config section.

    *cfg* is a :class:`books.core.config.CoversConfig`. ``limit == 0`` means no
    limit. Always a full scan (no single-book targeting from ``import``).
    """
    limit = None if cfg.limit <= 0 else cfg.limit
    return run(
        vault,
        interactive=cfg.interactive,
        dry_run=dry_run,
        limit=limit,
        fetch_json=default_fetch_json,
        fetch_bytes=default_fetch_bytes,
        prompt=_terminal_prompt,
        book_id=None,
    )
```

If `typer` is now unused in this file, remove `import typer`.

- [ ] **Step 8: Run the covers test**

Run: `uv run pytest tests/commands/test_covers.py -k run_import -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add books/commands/audible/command.py books/commands/covers/command.py \
        tests/commands/test_audible_runimport.py tests/commands/test_covers.py
git commit -m "feat(audible,covers): add config-driven run_import entry points

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: The `import` command (`import_cmd.py`)

**Files:**
- Create: `books/commands/import_cmd.py`
- Delete: `books/commands/sync.py`
- Rename: `tests/commands/test_sync.py` → `tests/commands/test_import.py`

- [ ] **Step 1: Create `books/commands/import_cmd.py`**

Create the file with this full content:

```python
#!/usr/bin/env python3
"""`import` — ingest raw sources into the CSV store.

One command replaces the per-source importers. With no flags it runs the
*sync-set* (calibre, goodreads, kobo, highlighted, readwise). Passing importer
flags runs exactly that subset; ``--audible`` and ``--covers`` are opt-in and
run only when named. ``merge`` (clustering the source layers into
``Data/books.csv``) is injected automatically so callers never sequence it.

Each importer detects its own source and is skipped (reported, not an error)
when absent. A step failure is reported but never stops the remaining steps.
Rendering notes is a separate command (`books export`).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.markup import escape

from books.commands import (
    calibre,
    goodreads,
    highlighted,
    kobo,
    readwise,
)
from books.commands.audible import command as audible_cmd
from books.commands.covers import command as covers_cmd
from books.core import config, store, ui

# The importers run with no flags.
SYNC_SET = ("calibre", "goodreads", "kobo", "highlighted", "readwise")
# Importers that resolve against Data/books.csv (need a current catalog first).
_CONSUMERS = ("audible", "covers", "kobo", "highlighted", "readwise")
# Importers that write a Data/Sources/<name>.csv layer after the phase-A merge.
_ENRICHERS = ("audible", "covers")

# --- Detection helpers ------------------------------------------------------


def _imports_folder(name: str, vault: Path) -> Path:
    return config.resolve_imports(name, vault)


def _imports_label(name: str) -> str:
    cfg = config.load_config()
    return f"{cfg.imports}/{name}"


def _has_csv(folder: Path) -> bool:
    return folder.is_dir() and any(folder.glob("*.csv"))


def _calibre_library() -> Path:
    """The configured Calibre library (``[calibre].library``)."""
    return config._expand_user(config.load_config().calibre.library)


def _kobo_db(vault: Path) -> Path:
    """The Kobo DB path: config override, else auto-detected."""
    db = config.load_config().kobo.db
    return config._expand_user(db) if db else kobo.default_kobo_db(vault)


def _detect_calibre(vault: Path) -> str | None:
    library = _calibre_library()
    return str(library) if library.is_dir() else None


def _detect_goodreads(vault: Path) -> str | None:
    return _imports_label("goodreads") if _has_csv(_imports_folder("goodreads", vault)) else None


def _kobo_source(vault: Path) -> str | None:
    override = config.load_config().kobo.db
    if override:
        p = config._expand_user(override)
        return str(p) if p.is_file() else None
    if kobo.KOBO_DEVICE_DB.is_file():
        return "Kobo device"
    folder = _imports_folder("kobo", vault)
    if folder.is_dir() and any(folder.glob("*.sqlite")):
        return _imports_label("kobo")
    return None


def _detect_kobo(vault: Path) -> str | None:
    return _kobo_source(vault)


def _detect_highlighted(vault: Path) -> str | None:
    return (
        _imports_label("highlighted") if _has_csv(_imports_folder("highlighted", vault)) else None
    )


def _detect_readwise(vault: Path) -> str | None:
    return _imports_label("readwise") if _has_csv(_imports_folder("readwise", vault)) else None


def _detect_merge(vault: Path) -> str | None:
    src = store.sources_dir(vault)
    if src.is_dir() and any(src.glob("*.csv")):
        return "Data/Sources"
    if _detect_calibre(vault) or _detect_goodreads(vault):
        return "Data/Sources"
    return None


def _detect_audible(vault: Path) -> str | None:
    return "Audible cloud"


def _detect_covers(vault: Path) -> str | None:
    return "Data/books.csv" if store.books_csv_path(vault).is_file() else None


# --- Step runners -----------------------------------------------------------


def _run_calibre(vault: Path) -> dict:
    return calibre.convert(_calibre_library(), vault)


def _run_goodreads(vault: Path) -> dict:
    csv = config.newest_csv(_imports_folder("goodreads", vault))
    return goodreads.convert(csv, vault)


def _run_kobo(vault: Path) -> dict:
    return kobo.export_obsidian(_kobo_db(vault), vault)


def _run_highlighted(vault: Path) -> dict:
    folder = _imports_folder("highlighted", vault)
    totals = {"books": 0, "entries": 0, "skipped": 0}
    for path in highlighted.resolve_csv_paths(folder):
        stats = highlighted.convert(path, vault)
        totals["books"] += stats["books"]
        totals["entries"] += stats["entries"]
        totals["skipped"] += stats["skipped"]
    return totals


def _run_readwise(vault: Path) -> dict:
    csv = config.newest_csv(_imports_folder("readwise", vault))
    return readwise.convert(csv, vault)


def _run_merge(vault: Path) -> dict:
    return {"books": len(store.merge(vault))}


def _run_audible(vault: Path) -> dict:
    return audible_cmd.run_import(vault, config.load_config().audible)


def _run_covers(vault: Path) -> dict:
    return covers_cmd.run_import(vault, config.load_config().covers)


# --- Summaries --------------------------------------------------------------


def _summ_calibre(s: dict) -> str:
    return (
        f"{s.get('books', 0)} books, {s.get('covers', 0)} covers, "
        f"{len(s.get('authors', ()))} authors, {s.get('skipped', 0)} skipped"
    )


def _summ_goodreads(s: dict) -> str:
    return (
        f"{s.get('books', 0)} books, {s.get('reviews', 0)} reviews, {s.get('skipped', 0)} skipped"
    )


def _summ_highlights(s: dict) -> str:
    skipped = f", {s['skipped']} skipped" if s.get("skipped") else ""
    return f"{s.get('books', 0)} books, {s.get('entries', 0)} highlights{skipped}"


def _summ_merge(s: dict) -> str:
    return f"{s.get('books', 0)} books in catalog"


def _summ_audible(s: dict) -> str:
    fail = f", {s['failed']} failed" if s.get("failed") else ""
    return f"{s.get('books', 0)} books, {s.get('entries', 0)} clips{fail}"


def _summ_covers(s: dict) -> str:
    return f"{s.get('fetched', 0)} fetched, {s.get('not_found', 0)} not found"


# --- Step registry ----------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """One pipeline stage: how to detect its source, run it, summarize it."""

    name: str
    detect: Callable[[Path], str | None]
    run: Callable[[Path], dict]
    summarize: Callable[[dict], str]
    where: str


def _all_steps() -> dict[str, Step]:
    """Every importer step keyed by name (merge handled separately)."""
    return {
        "calibre": Step(
            "calibre", _detect_calibre, _run_calibre, _summ_calibre, "~/Calibre Library"
        ),
        "goodreads": Step(
            "goodreads", _detect_goodreads, _run_goodreads, _summ_goodreads,
            _imports_label("goodreads"),
        ),
        "audible": Step("audible", _detect_audible, _run_audible, _summ_audible, "Audible cloud"),
        "covers": Step("covers", _detect_covers, _run_covers, _summ_covers, "Data/books.csv"),
        "kobo": Step(
            "kobo", _detect_kobo, _run_kobo, _summ_highlights,
            f"{_imports_label('kobo')} or a mounted Kobo",
        ),
        "highlighted": Step(
            "highlighted", _detect_highlighted, _run_highlighted, _summ_highlights,
            _imports_label("highlighted"),
        ),
        "readwise": Step(
            "readwise", _detect_readwise, _run_readwise, _summ_highlights,
            _imports_label("readwise"),
        ),
    }


def _merge_step() -> Step:
    return Step("merge", _detect_merge, _run_merge, _summ_merge, "Data/Sources")


def build_steps(selection: set[str]) -> list[Step]:
    """Order the selected importers and inject ``merge`` where needed.

    Order: calibre, goodreads, [merge], audible, covers, [merge], kobo,
    highlighted, readwise. A pre-merge runs when any consumer is selected or a
    phase-A layer is written; a post-merge runs when an enricher wrote a layer.
    """
    steps = _all_steps()
    out: list[Step] = []
    for name in ("calibre", "goodreads"):
        if name in selection:
            out.append(steps[name])
    need_pre = bool(selection & set(_CONSUMERS)) or bool(selection & {"calibre", "goodreads"})
    if need_pre:
        out.append(_merge_step())
    for name in ("audible", "covers"):
        if name in selection:
            out.append(steps[name])
    if selection & set(_ENRICHERS):
        out.append(_merge_step())
    for name in ("kobo", "highlighted", "readwise"):
        if name in selection:
            out.append(steps[name])
    return out


@dataclass
class StepResult:
    """Outcome of one step: status is ran / skipped / failed / planned."""

    name: str
    status: str
    summary: str
    error: str | None = None


# --- Rich output ------------------------------------------------------------


def _header(name: str, source: str) -> None:
    ui.console.print(f"[cyan]▶[/cyan] [bold]{escape(name)}[/bold] [dim]({escape(source)})[/dim]")


def _plan(name: str, source: str) -> None:
    ui.console.print(
        f"[cyan]•[/cyan] [bold]{escape(name)}[/bold] [dim]would run from {escape(source)}[/dim]"
    )


def _result_row(r: StepResult) -> tuple[str, str]:
    if r.status == "failed":
        return "[red]✗[/red]", f"[red]failed — {escape(r.error or '')}[/red]"
    if r.status == "skipped":
        return "[yellow]⊘[/yellow]", f"[dim]{escape(r.summary)}[/dim]"
    if r.status == "planned":
        return "[cyan]•[/cyan]", f"[dim]{escape(r.summary)}[/dim]"
    return "[green]✓[/green]", escape(r.summary)


def _print_summary(results: list[StepResult], *, dry_run: bool = False) -> None:
    ran = sum(1 for r in results if r.status == "ran")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = sum(1 for r in results if r.status == "failed")

    table = ui.summary_table("Import (dry run)" if dry_run else "Import")
    table.add_column("", width=2)
    table.add_column("Step", style="cyan", no_wrap=True)
    table.add_column("Result")
    for r in results:
        glyph, result = _result_row(r)
        table.add_row(glyph, r.name, result)
    ui.console.print(table)

    tally = f"{ran} ok · {skipped} skipped · {failed} failed"
    (ui.error if failed else ui.success)(tally)


# --- Orchestration ----------------------------------------------------------


def run_import(
    vault: Path, *, selection: set[str], dry_run: bool = False
) -> list[StepResult]:
    """Run the selected importers (with auto-merge) in dependency order.

    Returns a ``StepResult`` per step. Failures are recorded and never stop the
    remaining steps. In *dry_run* mode nothing is executed or written.
    """
    if not dry_run:
        vault.mkdir(parents=True, exist_ok=True)

    results: list[StepResult] = []
    for step in build_steps(selection):
        source = step.detect(vault)
        if source is None:
            results.append(StepResult(step.name, "skipped", f"skipped — no source in {step.where}"))
            continue
        if dry_run:
            _plan(step.name, source)
            results.append(StepResult(step.name, "planned", f"would run from {source}"))
            continue
        _header(step.name, source)
        try:
            stats = step.run(vault)
        except Exception as exc:  # continue-on-error
            message = str(exc) or exc.__class__.__name__
            results.append(StepResult(step.name, "failed", "failed", error=message))
            continue
        results.append(StepResult(step.name, "ran", step.summarize(stats)))

    _print_summary(results, dry_run=dry_run)
    return results


def _selection_from_flags(flags: dict[str, bool]) -> set[str]:
    """Chosen importers, or the sync-set when no flag is set."""
    chosen = {name for name, on in flags.items() if on}
    return chosen or set(SYNC_SET)


def import_command(
    calibre_: bool = typer.Option(False, "--calibre", help="Import the Calibre library."),
    goodreads_: bool = typer.Option(False, "--goodreads", help="Import the Goodreads export."),
    kobo_: bool = typer.Option(False, "--kobo", help="Import Kobo highlights."),
    highlighted_: bool = typer.Option(
        False, "--highlighted", help="Import Highlighted app exports."
    ),
    readwise_: bool = typer.Option(False, "--readwise", help="Import the Readwise export."),
    audible_: bool = typer.Option(
        False, "--audible", help="Import Audible clips (opt-in; needs cloud auth)."
    ),
    covers_: bool = typer.Option(
        False, "--covers", help="Fetch missing covers (opt-in; hits the network)."
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show which steps would run (and from which source) without writing anything.",
    ),
) -> None:
    """Ingest raw sources into the CSV store.

    With no flag the sync-set runs (calibre, goodreads, kobo, highlighted,
    readwise); flags select an exact subset. `--audible`/`--covers` run only when
    named. `merge` runs automatically. Rendering notes is a separate command
    (`books export`).
    """
    selection = _selection_from_flags(
        {
            "calibre": calibre_,
            "goodreads": goodreads_,
            "kobo": kobo_,
            "highlighted": highlighted_,
            "readwise": readwise_,
            "audible": audible_,
            "covers": covers_,
        }
    )
    vault = config.resolve_vault(output)
    run_import(vault, selection=selection, dry_run=dry_run)


def register(app: typer.Typer) -> None:
    app.command("import")(import_command)


def main() -> None:
    typer.run(import_command)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Delete `sync.py`**

Run:

```bash
git rm books/commands/sync.py
```

- [ ] **Step 3: Register `import` in `books/cli.py` (interim)**

In `books/cli.py`, in the import block replace `sync,` with `import_cmd as import_cmd,`? No — use a plain alias. Replace the `sync,` line with nothing and add, at the end of the `from books.commands import (...)` block, a separate import line **below** it:

```python
from books.commands import import_cmd
```

In `CAPABILITIES`, replace `sync,` with `import_cmd,`. (Full rewire happens in Task 5.)

- [ ] **Step 4: Rename and rewrite the sync tests as import tests**

Run:

```bash
git mv tests/commands/test_sync.py tests/commands/test_import.py
```

Replace the entire contents of `tests/commands/test_import.py` with:

```python
"""Tests for the consolidated `import` command.

Step `run` functions are monkeypatched so no real Calibre/Kobo data is needed.
"""

from pathlib import Path

from typer.testing import CliRunner

from books.cli import app
from books.commands import import_cmd as imp
from books.core import store


def test_has_csv_true_when_csv_present(tmp_path):
    (tmp_path / "a.csv").write_text("x")
    assert imp._has_csv(tmp_path)


def test_has_csv_false_when_empty_or_missing(tmp_path):
    assert not imp._has_csv(tmp_path)
    assert not imp._has_csv(tmp_path / "nope")


# --- selection & merge injection -------------------------------------------


def _names(steps):
    return [s.name for s in steps]


def test_no_flags_runs_sync_set_with_one_merge():
    steps = imp.build_steps(set(imp.SYNC_SET))
    assert _names(steps) == [
        "calibre", "goodreads", "merge", "kobo", "highlighted", "readwise",
    ]


def test_single_metadata_flag_gets_trailing_merge():
    assert _names(imp.build_steps({"calibre"})) == ["calibre", "merge"]


def test_single_highlight_flag_gets_leading_merge():
    assert _names(imp.build_steps({"kobo"})) == ["merge", "kobo"]


def test_enricher_gets_merge_before_and_after():
    assert _names(imp.build_steps({"audible"})) == ["merge", "audible", "merge"]
    assert _names(imp.build_steps({"covers"})) == ["merge", "covers", "merge"]


def test_selection_from_flags_defaults_to_sync_set():
    assert imp._selection_from_flags({"calibre": False, "kobo": False}) == set(imp.SYNC_SET)
    assert imp._selection_from_flags({"calibre": True, "kobo": True}) == {"calibre", "kobo"}


# --- orchestration ----------------------------------------------------------


def _stub_runs(monkeypatch, order, *, failing=None):
    def make(name):
        def run(vault):
            order.append(name)
            if failing and name == failing:
                raise RuntimeError(f"{name} boom")
            return {}
        return run

    for name in ("calibre", "goodreads", "kobo", "highlighted", "readwise", "merge"):
        monkeypatch.setattr(imp, f"_run_{name}", make(name))


def _detect_all(monkeypatch):
    for name in (
        "_detect_calibre", "_detect_goodreads", "_detect_kobo",
        "_detect_highlighted", "_detect_readwise", "_detect_merge",
    ):
        monkeypatch.setattr(imp, name, lambda v: "src")


def test_runs_selected_in_dependency_order(tmp_path, monkeypatch):
    _detect_all(monkeypatch)
    order = []
    _stub_runs(monkeypatch, order)
    imp.run_import(tmp_path, selection=set(imp.SYNC_SET))
    assert order == ["calibre", "goodreads", "merge", "kobo", "highlighted", "readwise"]


def test_skips_steps_without_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(imp, "_detect_calibre", lambda v: None)
    monkeypatch.setattr(imp, "_detect_goodreads", lambda v: "src")
    monkeypatch.setattr(imp, "_detect_kobo", lambda v: None)
    monkeypatch.setattr(imp, "_detect_highlighted", lambda v: None)
    monkeypatch.setattr(imp, "_detect_readwise", lambda v: None)
    monkeypatch.setattr(imp, "_detect_merge", lambda v: "src")
    order = []
    _stub_runs(monkeypatch, order)
    results = imp.run_import(tmp_path, selection=set(imp.SYNC_SET))
    ran = [r.name for r in results if r.status == "ran"]
    assert ran == ["goodreads", "merge"]


def test_continue_on_error(tmp_path, monkeypatch):
    _detect_all(monkeypatch)
    order = []
    _stub_runs(monkeypatch, order, failing="goodreads")
    results = imp.run_import(tmp_path, selection=set(imp.SYNC_SET))
    statuses = {r.name: r.status for r in results}
    assert statuses["goodreads"] == "failed"
    assert statuses["kobo"] == "ran"  # later steps still run


def test_dry_run_does_not_execute(tmp_path, monkeypatch):
    _detect_all(monkeypatch)
    order = []
    _stub_runs(monkeypatch, order)
    results = imp.run_import(tmp_path, selection=set(imp.SYNC_SET), dry_run=True)
    assert order == []
    assert all(r.status == "planned" for r in results)


# --- CLI wiring -------------------------------------------------------------


def test_import_registered():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "import" in result.output


def test_import_help():
    result = CliRunner().invoke(app, ["import", "--help"])
    assert result.exit_code == 0
    assert "--calibre" in result.output and "--audible" in result.output
```

- [ ] **Step 5: Run the import tests**

Run: `uv run pytest tests/commands/test_import.py -v`
Expected: PASS (all selection/merge/orchestration/CLI tests).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(import): add consolidated import command, remove sync

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Rewire the CLI command surface

**Files:**
- Modify: `books/cli.py`
- Modify: `tests/commands/test_cli.py`

- [ ] **Step 1: Rewrite `books/cli.py` imports and `CAPABILITIES`**

Replace the whole `from books.commands import (...)` block and the `CAPABILITIES` tuple with:

```python
from books.commands import (
    export,
    import_cmd,
    reset,
)

# Modules that expose a register(app) function. Add new capabilities here.
CAPABILITIES = (
    export,
    import_cmd,
    reset,
)
```

(The importer modules — calibre, goodreads, merge, kobo, highlighted, readwise, audible, covers — are intentionally no longer imported here; they remain importable as internal modules from `import_cmd`.)

- [ ] **Step 2: Update the app help text**

In `books/cli.py`, change the `help=` argument on `typer.Typer(...)` to:

```python
    help="Tools for books & reading data: import sources into a store, export notes.",
```

- [ ] **Step 3: Rewrite `tests/commands/test_cli.py` surface assertions**

Open `tests/commands/test_cli.py`. Replace the `test_all_capabilities_registered`, `test_capabilities_count_matches_module_list`, and `test_subcommand_help` functions with:

```python
def test_all_capabilities_registered():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("import", "export", "reset"):
        assert command in result.output


def test_removed_commands_are_gone():
    result = runner.invoke(app, ["--help"])
    for command in ("calibre", "goodreads", "merge", "kobo", "highlighted",
                    "readwise", "audible", "covers", "render", "sync"):
        assert command not in result.output


def test_capabilities_count_matches_module_list():
    from books.cli import CAPABILITIES

    assert len(CAPABILITIES) == 3


def test_subcommand_help():
    for command in ("import", "export", "reset"):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, command
        assert command in result.output or "Usage" in result.output
```

Then **delete** the now-obsolete per-command tests in this file that invoke removed commands: `test_calibre_missing_library_errors`, `test_goodreads_requires_csv_option`, `test_goodreads_missing_csv_errors`, `test_kobo_removed_csv_flag_rejected`, `test_kobo_missing_db_errors`, `test_calibre_end_to_end`, `test_goodreads_end_to_end`, `test_kobo_obsidian_end_to_end`, `test_highlighted_end_to_end`, `test_readwise_end_to_end`. (The underlying importer cores are still covered by `tests/commands/test_calibre.py`, `test_goodreads.py`, `test_kobo.py`, `test_highlighted.py`, `test_readwise.py`, which call the `convert`/`export_obsidian` functions directly, not the removed CLI commands. Leave those files untouched unless a test there invokes a removed command via `CliRunner` — see Step 5.)

- [ ] **Step 4: Run the CLI tests**

Run: `uv run pytest tests/commands/test_cli.py -v`
Expected: PASS. If `test_cli.py` still imports names it no longer uses, remove those imports (run `uv run ruff check --fix tests/commands/test_cli.py`).

- [ ] **Step 5: Find and fix any remaining references to removed commands**

Run:

```bash
grep -rn 'invoke(app, \["\(calibre\|goodreads\|merge\|kobo\|highlighted\|readwise\|audible\|covers\|render\|sync\)"' tests/
grep -rn '"render"\|"sync"' tests/ books/
```

For each match in a test that invokes a **removed** CLI command, rewrite it to call the module's core function directly (e.g. `calibre.convert(lib, vault)` instead of `CliRunner().invoke(app, ["calibre", ...])`) or delete it if it's purely a CLI-surface test already covered by `test_cli.py`/`test_import.py`. There should be no remaining `invoke(app, ["render", ...])` (handled in Task 2) or `["sync", ...]` references.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(cli): collapse command surface to import/export/reset

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Update `reset` help & recovery text

**Files:**
- Modify: `books/commands/reset.py`
- Test: `tests/commands/test_reset.py` (verify still green)

- [ ] **Step 1: Update the success message**

In `books/commands/reset.py`, in `reset_command`, change the success message so the final sentence reads:

```python
    ui.success(
        f"Reset: removed books.csv={result['books_csv']}, "
        f"{result['highlight_files']} highlight file(s). "
        f"Run `books import` then `books export` to rebuild."
    )
```

- [ ] **Step 2: Update the module docstring**

In `books/commands/reset.py`, change the docstring line that mentions `sync` to reference the new flow:

```python
Removes ``Data/books.csv`` and the ``Data/Highlights/`` folder (the only store
that accumulates orphaned per-``book_id`` files). Source layers under
``Data/Sources/`` and the notes are kept. Run ``books import`` then
``books export`` afterward (plus the opt-in ``import --audible``/``--covers``
steps) to rebuild.
```

- [ ] **Step 3: Run the reset tests**

Run: `uv run pytest tests/commands/test_reset.py -v`
Expected: PASS (the tests assert exit codes and file state, not the exact message wording).

- [ ] **Step 4: Commit**

```bash
git add books/commands/reset.py
git commit -m "docs(reset): point recovery flow at import/export

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Documentation (`CLAUDE.md`)

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the architecture overview**

In `CLAUDE.md`, in the "Architecture" section, update the "To add a capability" note and the sentence beginning "Eleven capabilities exist today" so it describes the new surface. Replace that sentence and its list intro with:

```markdown
Three commands exist today: **`import`** (ingest raw sources into the CSV store),
**`export`** (render the store into notes), and **`reset`** (wipe the derived
store). The former per-source importers (`calibre`, `goodreads`, `kobo`,
`highlighted`, `readwise`, `audible`, `covers`) and `merge` are now internal
modules driven by `import` rather than standalone commands; `render` was renamed
to `export` and `sync` was absorbed into `import`.
```

- [ ] **Step 2: Replace the per-command bullet list**

Replace the eleven `- books/commands/<x>.py → <x>` bullets with three bullets describing `import`, `export`, `reset`. Use this content:

```markdown
- `books/commands/import_cmd.py` → `import` — the single ingest command. With no
  flags it runs the sync-set (`calibre`, `goodreads`, `kobo`, `highlighted`,
  `readwise`); importer flags (`--calibre` … `--readwise`, plus opt-in
  `--audible`/`--covers`) select an exact subset. `merge` is injected
  automatically (before catalog consumers, after layer writers). Each importer
  detects its own source and is skipped/reported when absent; a failing step
  never stops the others. Reads per-importer settings from the `[calibre]`,
  `[kobo]`, `[audible]`, `[covers]` config sections. Stops at the store — run
  `export` to write notes. `--output` overrides the vault; `--dry-run` prints the
  plan. The importer cores live in their own modules
  (`books/commands/{calibre,goodreads,kobo,highlighted,readwise}.py` and the
  `audible`/`covers` packages, whose `run_import(vault, cfg)` entry points read
  config); `store.merge` clusters the layers.
- `books/commands/export.py` → `export` — the CSV-store renderer (formerly
  `render`). Reads the merged catalog + per-book highlights and writes one flat
  note per book under `Books/`. `--obsidian` selects the (default, only) format;
  `--refresh` does a clean rebuild of `Books/`/`Authors/`; `--output` overrides
  the vault. Note assembly lives in `books/renderers/obsidian/note.py`.
- `books/commands/reset.py` → `reset` — deletes the purely-derived CSV store
  (`Data/books.csv` + `Data/Highlights/`) so a later `import` rebuilds it.
  `--dry-run` previews; `--yes`/`-y` skips the confirm. Recovery flow:
  `reset` → `import` → `export` (plus `import --audible`/`--covers` as needed).
```

- [ ] **Step 3: Update the configuration section**

In the "Configuration" section of `CLAUDE.md`, add a sentence after the `imports` paragraph documenting the new sections:

```markdown
Per-importer settings live in optional `[calibre]`, `[kobo]`, `[audible]`, and
`[covers]` config sections: `[calibre].library` (default `~/Calibre Library`),
`[kobo].db` (default: auto-detect a mounted device / the imports folder),
`[audible].transcriber` (`local`/`openai`/`google`) + `[audible].select`
(`interactive`/`all`), and `[covers].interactive` + `[covers].limit`. Each key
falls back to its built-in default when absent or malformed.
```

- [ ] **Step 4: Fix stale references to the old pipeline**

Search `CLAUDE.md` for `sync`, `merge`, and `render` mentions in the prose (Phase A/B descriptions, the `sync orchestrates` sentence) and update them to describe `import` (auto-merge) + `export`. Run:

```bash
grep -n "sync\|\brender\b\|run \`merge\`" CLAUDE.md
```

Rewrite each prose reference so it names `import`/`export`; leave historical `docs/superpowers/` references alone.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: rewrite capability list for import/export consolidation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Bump the package version to 1.0.0

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Bump the version**

In `pyproject.toml`, under `[project]`, change:

```toml
version = "0.1.0"
```

to:

```toml
version = "1.0.0"
```

- [ ] **Step 2: Verify the version is picked up**

Run: `uv run books --version 2>/dev/null || uv run python -c "import importlib.metadata as m; print(m.version('books'))"`
Expected: prints `1.0.0` (if the CLI has no `--version` flag, the fallback prints the installed metadata version after `uv sync` re-resolves the local package; run `uv sync` first if it still shows `0.1.0`).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: release 1.0.0

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Final verification

- [ ] **Step 1: Lint and format**

Run: `uv run ruff check --fix && uv run ruff format`
Expected: no remaining lint errors.

- [ ] **Step 2: Full test suite**

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 3: Smoke-test the CLI surface**

Run:

```bash
uv run books --help
uv run books import --help
uv run books export --help
```

Expected: top-level help lists exactly `import`, `export`, `reset`; `import --help` shows the seven importer flags + `--output`/`--dry-run`; `export --help` shows `--obsidian`/`--refresh`/`--output`.

- [ ] **Step 4: Smoke-test a dry-run import**

Run: `uv run books import --dry-run --output /tmp/books-smoke-vault`
Expected: a plan table (steps skipped when no source present) and a `0 ok · N skipped · 0 failed` tally; no crash.

- [ ] **Step 5: Commit any formatting-only changes**

```bash
git add -A
git commit -m "style: ruff format for import/export consolidation

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```
(Skip if there is nothing to commit.)

---

## Self-Review Notes

- **Spec coverage:**
  - Command surface (`import`/`export`/`reset`, others removed) → Tasks 2, 4, 5.
  - No-flag = sync-set; flags = exact subset; audible/covers opt-in → Task 4 (`_selection_from_flags`, `build_steps`, tests).
  - Automatic merge injection (before consumers / after writers) → Task 4 (`build_steps` + tests for each selection shape).
  - `render` → `export` rename, behavior unchanged → Task 2.
  - Per-importer settings in `config.toml` → Task 1 (dataclasses + parsing + default file) + Task 3 (audible/covers read cfg) + Task 4 (calibre/kobo runners read cfg).
  - No per-importer CLI flags / no one-off targeting → Task 4 (`import_command` exposes only selection + `--output`/`--dry-run`).
  - Continue-on-error + `--dry-run` planning + rich summary → Task 4 (carried over from sync + tests).
  - Config never crashes on bad input → Task 1 (per-key fallback tests).
  - Docs rewrite + reset recovery flow → Tasks 6, 7.
  - Version bump to 1.0.0 → Task 8.
- **Type consistency:** `run_import(vault, *, selection, dry_run)` (import module) vs `run_import(vault, cfg, *, dry_run)` (audible/covers modules) are deliberately different call sites — the import runners `_run_audible`/`_run_covers` call the latter with `config.load_config().audible`/`.covers`. `Step`/`StepResult` field names match sync's originals. `build_steps` returns `list[Step]`; `_all_steps` returns `dict[str, Step]`; `_merge_step()` returns a fresh `Step` each call (so two merge rows are distinct objects — fine, they render identically).
- **No placeholders:** every code/test step shows complete content; commands include expected output.
- **Known redundancy (intentional):** for `--audible`/`--covers` alone, two `merge` rows appear in the summary (pre + post). This is correct (ensure catalog, then fold the new layer) and merge is idempotent; documented in `build_steps`.
```