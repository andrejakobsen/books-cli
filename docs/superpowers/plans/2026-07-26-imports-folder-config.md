# `.imports` Folder Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let every importer default its input to a canonical subfolder under a hidden `.imports/` folder inside the Obsidian vault, configured by a single `imports` key.

**Architecture:** Extend `booktools/config.py` with an `imports` config key, a `resolve_imports(name, output)` helper (`<vault>/<imports>/<name>`), and a `newest_csv(folder)` helper. Each importer's input option becomes optional and, when omitted, resolves to its `.imports/<name>` subfolder. Explicit flags still override with today's resolution.

**Tech Stack:** Python 3.11+ stdlib (`tomllib`, `pathlib`, `dataclasses`), Typer, pytest.

**Reference spec:** `docs/superpowers/specs/2026-07-26-imports-folder-config-design.md`

**Conventions:** Commit after each task. Run `uv run pytest -q` before committing. Commit directly to `main` (per CLAUDE.md — no branches/PRs). End commit messages with the `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` trailer.

---

## Task 1: Add `imports` key to config

**Files:**
- Modify: `booktools/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
def test_load_config_reads_imports_key(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        'obsidian_path = "~/Obs"\nvault = "History"\nimports = "Sources"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.imports == "Sources"


def test_load_config_defaults_imports_when_absent(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('vault = "History"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.imports == config.DEFAULT_IMPORTS


def test_load_config_defaults_imports_on_non_string(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('imports = 5\nvault = "History"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.imports == config.DEFAULT_IMPORTS


def test_default_file_includes_imports(tmp_path):
    cfg_file = tmp_path / "booktools" / "config.toml"
    config.load_config(cfg_file)
    assert 'imports = ".imports"' in cfg_file.read_text()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -k imports -q`
Expected: FAIL (`AttributeError: ... 'DEFAULT_IMPORTS'` / `Config` has no field `imports`).

- [ ] **Step 3: Implement the config changes**

In `booktools/config.py`, add the constant next to the others:

```python
DEFAULT_OBSIDIAN_PATH = "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian"
DEFAULT_VAULT = "History"
DEFAULT_IMPORTS = ".imports"
```

Update `_DEFAULT_FILE`:

```python
_DEFAULT_FILE = (
    "# booktools configuration\n"
    f'obsidian_path = "{DEFAULT_OBSIDIAN_PATH}"\n'
    f'vault = "{DEFAULT_VAULT}"\n'
    "# Folder (inside the vault) holding raw import sources, hidden from Obsidian.\n"
    f'imports = "{DEFAULT_IMPORTS}"\n'
)
```

Add the field to `Config`:

```python
@dataclass
class Config:
    """Resolved config values (built-in defaults when unset)."""

    obsidian_path: str = DEFAULT_OBSIDIAN_PATH
    vault: str = DEFAULT_VAULT
    imports: str = DEFAULT_IMPORTS
```

In `load_config`, after the existing `vault` fallback block and before `return`:

```python
    imports = data.get("imports")
    if not isinstance(imports, str) or not imports:
        imports = DEFAULT_IMPORTS
    return Config(obsidian_path=obsidian_path, vault=vault, imports=imports)
```

(Replace the existing `return Config(obsidian_path=..., vault=...)` line.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS (all config tests, including the four new ones).

- [ ] **Step 5: Commit**

```bash
git add booktools/config.py tests/test_config.py
git commit -m "feat(config): add imports key for the .imports source folder

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Add `resolve_imports` helper

**Files:**
- Modify: `booktools/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
def test_resolve_imports_joins_onto_vault(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        'obsidian_path = "/data/Obs"\nvault = "History"\nimports = ".imports"\n')
    monkeypatch.setattr(config, "config_path", lambda: cfg_file)
    assert config.resolve_imports("goodreads", None) == Path(
        "/data/Obs/History/.imports/goodreads")


def test_resolve_imports_respects_output_override(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('imports = ".imports"\n')
    monkeypatch.setattr(config, "config_path", lambda: cfg_file)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: Path("/work")))
    assert config.resolve_imports("kobo", Path("MyVault")) == Path(
        "/work/MyVault/.imports/kobo")


def test_resolve_imports_honors_absolute_imports(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        'obsidian_path = "/data/Obs"\nvault = "History"\nimports = "/srv/raw"\n')
    monkeypatch.setattr(config, "config_path", lambda: cfg_file)
    assert config.resolve_imports("calibre", None) == Path("/srv/raw/calibre")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -k resolve_imports -q`
Expected: FAIL (`AttributeError: module 'booktools.config' has no attribute 'resolve_imports'`).

- [ ] **Step 3: Implement `resolve_imports`**

In `booktools/config.py`, add after `resolve_vault`:

```python
def resolve_imports(name: str, output: Path | None = None) -> Path:
    """Canonical import subfolder for a command: ``<vault>/<imports>/<name>``.

    The imports root resolves inside the vault selected by ``resolve_vault`` (so
    it travels with whichever vault ``--output``/config picks). An absolute
    ``imports`` config value is honored as-is; a relative one joins onto the vault.
    """
    vault = resolve_vault(output)
    cfg = load_config()
    root = resolve_path(Path(cfg.imports), vault)
    return root / name
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -k resolve_imports -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add booktools/config.py tests/test_config.py
git commit -m "feat(config): resolve_imports helper for .imports subfolders

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Add `newest_csv` helper

**Files:**
- Modify: `booktools/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
def test_newest_csv_picks_most_recent(tmp_path):
    old = tmp_path / "old.csv"
    new = tmp_path / "new.csv"
    old.write_text("a")
    new.write_text("b")
    import os
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    assert config.newest_csv(tmp_path) == new


def test_newest_csv_single_file(tmp_path):
    only = tmp_path / "export.csv"
    only.write_text("x")
    assert config.newest_csv(tmp_path) == only


def test_newest_csv_empty_folder_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        config.newest_csv(tmp_path)


def test_newest_csv_missing_folder_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        config.newest_csv(tmp_path / "nope")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -k newest_csv -q`
Expected: FAIL (`AttributeError: ... 'newest_csv'`).

- [ ] **Step 3: Implement `newest_csv`**

In `booktools/config.py`, add after `resolve_imports`:

```python
def newest_csv(folder: Path) -> Path:
    """Return the most-recently-modified top-level ``*.csv`` in *folder*.

    Non-recursive. Raises ``FileNotFoundError`` (with *folder* in the message)
    when the folder is missing or contains no CSV files.
    """
    if not folder.is_dir():
        raise FileNotFoundError(f"no CSV found in {folder}")
    csvs = list(folder.glob("*.csv"))
    if not csvs:
        raise FileNotFoundError(f"no CSV found in {folder}")
    return max(csvs, key=lambda p: p.stat().st_mtime)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -k newest_csv -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add booktools/config.py tests/test_config.py
git commit -m "feat(config): newest_csv helper to pick the latest CSV in a folder

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: calibre default → `.imports/calibre`

**Files:**
- Modify: `booktools/calibre_obsidian.py:272-303`
- Test: `tests/test_calibre_to_obsidian.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_calibre_to_obsidian.py`:

```python
def test_calibre_defaults_library_to_imports(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner
    from booktools import calibre_obsidian as cal, config

    vault = tmp_path / "Vault"
    lib = vault / ".imports" / "calibre"
    lib.mkdir(parents=True)  # empty library -> convert() finds no books
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)
    monkeypatch.setattr(config, "resolve_imports",
                        lambda name, output=None: vault / ".imports" / name)

    app = typer.Typer()
    cal.register(app)
    result = CliRunner().invoke(app, [])

    assert result.exit_code == 0, result.output
    assert "0 books" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_calibre_to_obsidian.py -k defaults_library -q`
Expected: FAIL (calibre resolves the default `Calibre Library` against home, not `.imports`, so the library is "not found").

- [ ] **Step 3: Implement the default**

In `booktools/calibre_obsidian.py`, change the `library` option default to `None`:

```python
    library: Path | None = typer.Option(
        None,
        "--library", "-l",
        help="Path to the Calibre library. Defaults to <vault>/.imports/calibre. "
             "Relative paths resolve against your home directory.",
    ),
```

Replace the resolution line `library = resolve_path(library, Path.home())` with:

```python
    if library is None:
        library = config.resolve_imports("calibre")
    else:
        library = resolve_path(library, Path.home())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_calibre_to_obsidian.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add booktools/calibre_obsidian.py tests/test_calibre_to_obsidian.py
git commit -m "feat(calibre): default --library to <vault>/.imports/calibre

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: goodreads default + folder → newest CSV

**Files:**
- Modify: `booktools/goodreads_obsidian.py:234-266`
- Test: `tests/test_goodreads_obsidian.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_goodreads_obsidian.py`:

```python
def _minimal_goodreads_csv(path):
    path.write_text(
        "Title,Author,ISBN,ISBN13,My Rating,Average Rating,Number of Pages,"
        "Original Publication Year,Date Read,Date Added,Bookshelves,"
        "Exclusive Shelf,My Review\n"
        '"The Deluge","Adam Tooze",,,,,,,,,,read,\n',
        encoding="utf-8")


def test_goodreads_defaults_csv_to_imports_newest(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner
    from booktools import goodreads_obsidian as gr, config

    vault = tmp_path / "Vault"
    folder = vault / ".imports" / "goodreads"
    folder.mkdir(parents=True)
    _minimal_goodreads_csv(folder / "export.csv")
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)
    monkeypatch.setattr(config, "resolve_imports",
                        lambda name, output=None: vault / ".imports" / name)

    app = typer.Typer()
    gr.register(app)
    result = CliRunner().invoke(app, [])

    assert result.exit_code == 0, result.output
    assert (vault / "Books" / "The Deluge - Adam Tooze.md").exists()


def test_goodreads_folder_arg_picks_newest(monkeypatch, tmp_path):
    import os
    import typer
    from typer.testing import CliRunner
    from booktools import goodreads_obsidian as gr, config

    vault = tmp_path / "Vault"
    folder = tmp_path / "exports"
    folder.mkdir()
    old = folder / "old.csv"
    old.write_text("Title,Author,Exclusive Shelf\n", encoding="utf-8")
    _minimal_goodreads_csv(folder / "new.csv")
    os.utime(old, (1000, 1000))
    os.utime(folder / "new.csv", (2000, 2000))
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)

    app = typer.Typer()
    gr.register(app)
    result = CliRunner().invoke(app, ["--csv", str(folder), "--output", str(vault)])

    assert result.exit_code == 0, result.output
    assert (vault / "Books" / "The Deluge - Adam Tooze.md").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_goodreads_obsidian.py -k "imports_newest or folder_arg" -q`
Expected: FAIL (`--csv` is currently required, so running with no `--csv` errors; a folder path fails `csv.is_file()`).

- [ ] **Step 3: Implement default + folder handling**

In `booktools/goodreads_obsidian.py`, change the `csv` option to optional:

```python
    csv: Path | None = typer.Option(
        None,
        "--csv", "-c",
        help="Path to a Goodreads CSV export, or a folder of exports (the newest "
             "*.csv is used). Defaults to <vault>/.imports/goodreads. Relative "
             "paths resolve against the current directory.",
    ),
```

Replace the resolution block (the `csv = resolve_path(...)` line and the following `if not csv.is_file(): raise ...` block) with:

```python
    if csv is None:
        try:
            csv = config.newest_csv(config.resolve_imports("goodreads", output))
        except FileNotFoundError as exc:
            raise typer.BadParameter(str(exc), param_hint="--csv")
    else:
        csv = resolve_path(csv, Path.cwd())
        if csv.is_dir():
            try:
                csv = config.newest_csv(csv)
            except FileNotFoundError as exc:
                raise typer.BadParameter(str(exc), param_hint="--csv")
    output = config.resolve_vault(output)

    if not csv.is_file():
        raise typer.BadParameter(f"CSV not found: {csv}", param_hint="--csv")
```

(Note: `config.resolve_imports("goodreads", output)` is called with the original
`output` value **before** `output` is reassigned to the resolved vault, so the
imports folder tracks an explicit `--output` vault too.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_goodreads_obsidian.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add booktools/goodreads_obsidian.py tests/test_goodreads_obsidian.py
git commit -m "feat(goodreads): default --csv to .imports/goodreads, accept a folder (newest CSV)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: readwise default + folder → newest CSV

**Files:**
- Modify: `booktools/readwise_obsidian.py:146-171`
- Test: `tests/test_readwise.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_readwise.py`:

```python
_READWISE_HEADER = (
    "Highlight,Book Title,Book Author,Amazon Book ID,Note,Color,Tags,"
    "Location Type,Location,Highlighted at,Document tags\n")
_READWISE_ROW = (
    '"A passage.","Stalin: Volume I (Stalin #1)",Stephen Kotkin,B00INIXPYE,'
    ',,,page,3,2026-07-17 14:00:25+00:00,\n')


def test_readwise_defaults_csv_to_imports_newest(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner
    from booktools import readwise_obsidian as rw, config

    vault = tmp_path / "Vault"
    folder = vault / ".imports" / "readwise"
    folder.mkdir(parents=True)
    (folder / "export.csv").write_text(_READWISE_HEADER + _READWISE_ROW, encoding="utf-8")
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)
    monkeypatch.setattr(config, "resolve_imports",
                        lambda name, output=None: vault / ".imports" / name)

    app = typer.Typer()
    rw.register(app)
    result = CliRunner().invoke(app, [])

    assert result.exit_code == 0, result.output
    assert (vault / "Books" / "Stalin - Stephen Kotkin.md").exists()


def test_readwise_folder_arg_picks_newest(monkeypatch, tmp_path):
    import os
    import typer
    from typer.testing import CliRunner
    from booktools import readwise_obsidian as rw, config

    vault = tmp_path / "Vault"
    folder = tmp_path / "exports"
    folder.mkdir()
    old = folder / "old.csv"
    old.write_text(_READWISE_HEADER, encoding="utf-8")
    (folder / "new.csv").write_text(_READWISE_HEADER + _READWISE_ROW, encoding="utf-8")
    os.utime(old, (1000, 1000))
    os.utime(folder / "new.csv", (2000, 2000))
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)

    app = typer.Typer()
    rw.register(app)
    result = CliRunner().invoke(app, ["--csv", str(folder), "--output", str(vault)])

    assert result.exit_code == 0, result.output
    assert (vault / "Books" / "Stalin - Stephen Kotkin.md").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_readwise.py -k "imports_newest or folder_arg" -q`
Expected: FAIL (`--csv` currently required; folder path fails `csv.is_file()`).

- [ ] **Step 3: Implement default + folder handling**

In `booktools/readwise_obsidian.py`, change the `csv` option to optional:

```python
    csv: Path | None = typer.Option(
        None,
        "--csv", "-c",
        help="Path to a Readwise CSV export, or a folder of exports (the newest "
             "*.csv is used). Defaults to <vault>/.imports/readwise. Relative "
             "paths resolve against the current directory.",
    ),
```

Replace the resolution block (`csv = resolve_path(...)` and the following
`if not csv.is_file(): raise ...`) with:

```python
    if csv is None:
        try:
            csv = config.newest_csv(config.resolve_imports("readwise", output))
        except FileNotFoundError as exc:
            raise typer.BadParameter(str(exc), param_hint="--csv")
    else:
        csv = resolve_path(csv, Path.cwd())
        if csv.is_dir():
            try:
                csv = config.newest_csv(csv)
            except FileNotFoundError as exc:
                raise typer.BadParameter(str(exc), param_hint="--csv")
    output = config.resolve_vault(output)

    if not csv.is_file():
        raise typer.BadParameter(f"CSV not found: {csv}", param_hint="--csv")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_readwise.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add booktools/readwise_obsidian.py tests/test_readwise.py
git commit -m "feat(readwise): default --csv to .imports/readwise, accept a folder (newest CSV)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: highlighted default → `.imports/highlighted`

**Files:**
- Modify: `booktools/highlighted_obsidian.py:120-150`
- Test: `tests/test_highlighted_obsidian.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_highlighted_obsidian.py`:

```python
def test_highlighted_defaults_csv_to_imports(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner
    from booktools import highlighted_obsidian as hl, config

    vault = tmp_path / "Vault"
    folder = vault / ".imports" / "highlighted"
    folder.mkdir(parents=True)
    (folder / "export.csv").write_text(
        "Highlight,Title,Author,ISBN,Collections,Reading Status,"
        "Book Added Date,Location,Tags,Note,Date,Favorite\n"
        '"A line.","The Deluge","Adam Tooze",,,,,42,,,,\n',
        encoding="utf-8")
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: vault)
    monkeypatch.setattr(config, "resolve_imports",
                        lambda name, output=None: vault / ".imports" / name)

    app = typer.Typer()
    hl.register(app)
    result = CliRunner().invoke(app, [])

    assert result.exit_code == 0, result.output
    assert (vault / "Books" / "The Deluge - Adam Tooze.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_highlighted_obsidian.py -k defaults_csv_to_imports -q`
Expected: FAIL (`--csv` is currently required — missing option error).

- [ ] **Step 3: Implement the default**

In `booktools/highlighted_obsidian.py`, change the `csv` option to optional:

```python
    csv: Path | None = typer.Option(
        None,
        "--csv", "-c",
        help="Path to a Highlighted CSV export, or a folder of CSV exports (every "
             "top-level *.csv is imported). Defaults to <vault>/.imports/highlighted. "
             "Relative paths resolve against the current directory.",
    ),
```

Replace the line `csv = resolve_path(csv, Path.cwd())` with:

```python
    if csv is None:
        csv = config.resolve_imports("highlighted", output)
    else:
        csv = resolve_path(csv, Path.cwd())
```

Leave the existing `output = config.resolve_vault(output)`, the `is_file()/is_dir()`
check, and `resolve_csv_paths(csv)` untouched — a missing default folder is neither
a file nor a dir, so the existing `BadParameter("CSV not found: ...")` fires.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_highlighted_obsidian.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add booktools/highlighted_obsidian.py tests/test_highlighted_obsidian.py
git commit -m "feat(highlighted): default --csv to <vault>/.imports/highlighted

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: kobo default → `.imports/kobo`

**Files:**
- Modify: `booktools/kobo_export.py:249-296`
- Test: `tests/test_kobo_export.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_kobo_export.py`. The module already has a helper
`_make_db(path)` (see `tests/test_kobo_export.py:11`) that builds a minimal
KoboReader.sqlite at *path* — reuse it:

```python
def test_kobo_defaults_db_to_imports(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner
    from booktools import kobo_export as ke, config

    vault = tmp_path / "Vault"
    folder = vault / ".imports" / "kobo"
    folder.mkdir(parents=True)
    _make_db(folder / "KoboReader.sqlite")  # existing test helper
    monkeypatch.setattr(config, "resolve_imports",
                        lambda name, output=None: vault / ".imports" / name)

    out_zip = tmp_path / "out.zip"
    app = typer.Typer()
    ke.register(app)
    result = CliRunner().invoke(app, ["--output", str(out_zip)])

    assert result.exit_code == 0, result.output
    assert out_zip.exists()


def test_kobo_default_missing_folder_errors(monkeypatch, tmp_path):
    import typer
    from typer.testing import CliRunner
    from booktools import kobo_export as ke, config

    vault = tmp_path / "Vault"
    monkeypatch.setattr(config, "resolve_imports",
                        lambda name, output=None: vault / ".imports" / name)

    app = typer.Typer()
    ke.register(app)
    result = CliRunner().invoke(app, [])

    assert result.exit_code != 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_kobo_export.py -k "defaults_db or missing_folder" -q`
Expected: FAIL (default is `./KoboReader.sqlite`, so the `.imports/kobo` DB is not found).

- [ ] **Step 3: Implement the default**

In `booktools/kobo_export.py`, add a module-level helper near the top (after imports):

```python
def _default_kobo_db(output: Path | None) -> Path:
    """Locate the Kobo DB under <vault>/.imports/kobo.

    Prefers KoboReader.sqlite, else the newest *.sqlite. Raises
    typer.BadParameter naming the folder when nothing is found.
    """
    folder = config.resolve_imports("kobo", output)
    named = folder / "KoboReader.sqlite"
    if named.is_file():
        return named
    if folder.is_dir():
        sqlites = list(folder.glob("*.sqlite"))
        if sqlites:
            return max(sqlites, key=lambda p: p.stat().st_mtime)
    raise typer.BadParameter(
        f"no KoboReader.sqlite (or *.sqlite) found in {folder}", param_hint="DB")
```

Replace the resolution line:

```python
    db_path = resolve_path(input_path or db or Path("KoboReader.sqlite"), Path.cwd())
```

with:

```python
    explicit = input_path or db
    if explicit is None:
        db_path = _default_kobo_db(output)
    else:
        db_path = resolve_path(explicit, Path.cwd())
```

Update the `db` argument help text:

```python
    db: Path | None = typer.Argument(
        None,
        help="Path to KoboReader.sqlite. Relative paths resolve against the current "
             "directory. [default: <vault>/.imports/kobo/KoboReader.sqlite]",
    ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_kobo_export.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add booktools/kobo_export.py tests/test_kobo_export.py
git commit -m "feat(kobo): default DB to <vault>/.imports/kobo (KoboReader.sqlite)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the Configuration section**

In `CLAUDE.md`, in the `### Configuration` paragraph, after the sentence describing
`obsidian_path` and `vault`, add a sentence describing the new key:

> A third key, `imports` (default `.imports`), names a folder **inside the vault**
> holding raw source data, hidden from Obsidian because it is dot-prefixed. The
> helper `resolve_imports(name, output)` returns `<vault>/<imports>/<name>`, and
> every importer defaults its input to its canonical subfolder — `.imports/calibre`,
> `.imports/goodreads`, `.imports/highlighted`, `.imports/readwise`, `.imports/kobo`
> — so most commands need no input flag. `newest_csv(folder)` picks the most-recent
> `*.csv` for the single-file CSV importers.

- [ ] **Step 2: Update the per-capability notes**

In the capability bullet list, update the `goodreads`, `readwise`, and `kobo` entries
to note the new defaults/folder support. For `goodreads`:

> …reads a Goodreads CSV export and writes/merges Obsidian notes, plus a separate
> `<Title> - Review.md`. `--csv` accepts a single CSV file or a folder (the newest
> `*.csv` is used); it defaults to `<vault>/.imports/goodreads`.

For `readwise`, append to its bullet:

> `--csv` accepts a single CSV or a folder (newest `*.csv`); it defaults to
> `<vault>/.imports/readwise`.

For `kobo`, append to its bullet:

> The DB input defaults to `<vault>/.imports/kobo/KoboReader.sqlite` (or the newest
> `*.sqlite` in that folder) when no path is given.

For `calibre`, append to its bullet:

> `--library` defaults to `<vault>/.imports/calibre`.

For `highlighted`, adjust its existing folder sentence to note the default:

> …it defaults to `<vault>/.imports/highlighted`.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (all tests).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document the .imports folder convention and per-command defaults

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Run `uv run pytest -q` — all tests pass.
- [ ] Manually confirm the shims still import cleanly: `uv run python -c "import scripts.kobo_export"` is not applicable (shims call `main()`); instead confirm `uv run books --help` lists all commands and e.g. `uv run books goodreads --help` shows the new `--csv` help text.
- [ ] Confirm no shim in `scripts/` needed changes (they only call each module's `main()`; the module remains the single source of truth).

## Notes for the implementer

- **Do not create a feature branch.** Per `CLAUDE.md`, commit directly to `main`.
- The `resolve_imports`/`newest_csv` helpers live in `config.py` (stdlib-only) so
  every importer shares them — do not duplicate the logic per module.
- In goodreads/readwise, call `config.resolve_imports(name, output)` with the raw
  `output` value **before** reassigning `output = config.resolve_vault(output)`, so
  an explicit `--output` vault also relocates the imports folder.
- Task 8 reuses the existing `_make_db` helper in `tests/test_kobo_export.py`; if
  any other fixture helper differs from what a task assumes, read the top of the
  test file and use the module's actual helper.
