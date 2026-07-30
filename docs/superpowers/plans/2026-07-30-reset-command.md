# `books reset` Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated `books reset` command that deletes the purely-derived CSV store (`Data/books.csv` + `Data/Highlights/`) so a subsequent `sync` rebuilds it from raw sources, clearing orphaned per-`book_id` highlight files.

**Architecture:** A pure `store.reset_store(vault, *, dry_run)` helper in `books/core/store.py` owns the filesystem deletion and returns counts; a thin `books/commands/reset.py` command (mirroring `merge.py`) resolves the vault, prints a plan, guards deletion behind `--dry-run`/`--yes`/a confirm prompt, and calls the helper. Registered via `CAPABILITIES` in `books/cli.py`.

**Tech Stack:** Python 3.11+, Typer (CLI), Rich via `books.core.ui`, pytest + `typer.testing.CliRunner`.

**Reference spec:** `docs/superpowers/specs/2026-07-30-reset-command-design.md`

---

## File Structure

- **Create** `books/commands/reset.py` — the `reset` CLI command + `register(app)`.
- **Modify** `books/core/store.py` — add `reset_store(vault, *, dry_run=False)`.
- **Modify** `books/cli.py` — import `reset`, add to `CAPABILITIES`.
- **Create** `tests/commands/test_reset.py` — CLI tests.
- **Modify** `tests/core/test_store.py` — `reset_store` unit tests.
- **Modify** `CLAUDE.md` — capability list + recovery-flow note.

`store.py` already imports `shutil` (used by `stage_cover`), and already defines
`books_csv_path`, `highlights_dir`, and `data_dir` — no new imports/helpers needed there.

---

## Task 1: `store.reset_store` helper

**Files:**
- Modify: `books/core/store.py` (add function after `write_highlights`, near the other path/IO helpers)
- Test: `tests/core/test_store.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/core/test_store.py`:

```python
def test_reset_store_deletes_books_csv_and_highlights(tmp_path):
    vault = tmp_path / "vault"
    store.write_books_csv(vault, [store.BookRow(title="X", authors=["A"])])
    store.write_highlights(vault, "X - A", "kobo", [store.HighlightRow(text="hi", source="kobo")])
    # An orphaned highlight file from a since-changed book_id.
    store.write_highlights(
        vault, "Old Id - A", "kobo", [store.HighlightRow(text="stale", source="kobo")]
    )

    result = store.reset_store(vault)

    assert result == {"books_csv": True, "highlight_files": 2}
    assert not store.books_csv_path(vault).exists()
    assert not store.highlights_dir(vault).exists()


def test_reset_store_dry_run_deletes_nothing(tmp_path):
    vault = tmp_path / "vault"
    store.write_books_csv(vault, [store.BookRow(title="X", authors=["A"])])
    store.write_highlights(vault, "X - A", "kobo", [store.HighlightRow(text="hi", source="kobo")])

    result = store.reset_store(vault, dry_run=True)

    assert result == {"books_csv": True, "highlight_files": 1}
    assert store.books_csv_path(vault).exists()
    assert store.highlights_dir(vault).exists()


def test_reset_store_keeps_source_layers(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "calibre", [store.BookRow(title="X", authors=["A"])])
    store.write_books_csv(vault, [store.BookRow(title="X", authors=["A"])])

    store.reset_store(vault)

    assert store.layer_path(vault, "calibre").exists()


def test_reset_store_noop_when_absent(tmp_path):
    vault = tmp_path / "vault"

    result = store.reset_store(vault)

    assert result == {"books_csv": False, "highlight_files": 0}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/core/test_store.py -k reset_store -v`
Expected: FAIL with `AttributeError: module 'books.core.store' has no attribute 'reset_store'`

- [ ] **Step 3: Implement `reset_store`**

In `books/core/store.py`, add immediately after the `write_highlights` function (around line 604):

```python
def reset_store(vault: Path, *, dry_run: bool = False) -> dict:
    """Delete the purely-derived store: ``books.csv`` + the ``Highlights/`` dir.

    Source layers under ``Data/Sources/`` and the notes are kept. Returns
    ``{"books_csv": bool, "highlight_files": int}`` describing what was (or,
    under *dry_run*, would be) deleted. Idempotent: missing paths yield
    zeros/false and are not an error.
    """
    books_csv = books_csv_path(vault)
    hl_dir = highlights_dir(vault)
    had_books = books_csv.is_file()
    hl_count = len(list(hl_dir.glob("*.csv"))) if hl_dir.is_dir() else 0
    if not dry_run:
        if had_books:
            books_csv.unlink()
        if hl_dir.is_dir():
            shutil.rmtree(hl_dir)
    return {"books_csv": had_books, "highlight_files": hl_count}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/core/test_store.py -k reset_store -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add books/core/store.py tests/core/test_store.py
git commit -m "feat(store): add reset_store to delete the derived store

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `books reset` command

**Files:**
- Create: `books/commands/reset.py`
- Modify: `books/cli.py` (imports + `CAPABILITIES`)
- Test: `tests/commands/test_reset.py`

- [ ] **Step 1: Write the failing CLI tests**

Create `tests/commands/test_reset.py`:

```python
"""Tests for the `reset` derived-store rebuild command."""

from typer.testing import CliRunner

from books.cli import app
from books.commands import reset
from books.core import store


def _seed(vault):
    store.write_books_csv(vault, [store.BookRow(title="X", authors=["A"])])
    store.write_highlights(vault, "X - A", "kobo", [store.HighlightRow(text="hi", source="kobo")])


def test_reset_dry_run_deletes_nothing(tmp_path):
    vault = tmp_path / "vault"
    _seed(vault)

    result = CliRunner().invoke(app, ["reset", "--output", str(vault), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert store.books_csv_path(vault).exists()
    assert store.highlights_dir(vault).exists()


def test_reset_yes_deletes(tmp_path):
    vault = tmp_path / "vault"
    _seed(vault)

    result = CliRunner().invoke(app, ["reset", "--output", str(vault), "--yes"])

    assert result.exit_code == 0, result.output
    assert not store.books_csv_path(vault).exists()
    assert not store.highlights_dir(vault).exists()


def test_reset_non_tty_without_yes_errors(tmp_path):
    vault = tmp_path / "vault"
    _seed(vault)

    # Under CliRunner ui.console.is_terminal is False (not a real terminal).
    result = CliRunner().invoke(app, ["reset", "--output", str(vault)])

    assert result.exit_code != 0
    assert store.books_csv_path(vault).exists()


def test_reset_confirm_yes_deletes(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _seed(vault)
    monkeypatch.setattr(reset, "_is_interactive", lambda: True)
    monkeypatch.setattr(reset.ui, "confirm", lambda *a, **k: True)

    result = CliRunner().invoke(app, ["reset", "--output", str(vault)])

    assert result.exit_code == 0, result.output
    assert not store.books_csv_path(vault).exists()


def test_reset_confirm_no_aborts(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _seed(vault)
    monkeypatch.setattr(reset, "_is_interactive", lambda: True)
    monkeypatch.setattr(reset.ui, "confirm", lambda *a, **k: False)

    result = CliRunner().invoke(app, ["reset", "--output", str(vault)])

    assert result.exit_code == 0, result.output
    assert store.books_csv_path(vault).exists()


def test_reset_noop_when_empty(tmp_path):
    vault = tmp_path / "vault"

    result = CliRunner().invoke(app, ["reset", "--output", str(vault), "--yes"])

    assert result.exit_code == 0, result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/commands/test_reset.py -v`
Expected: FAIL — `ImportError` / `ModuleNotFoundError: No module named 'books.commands.reset'`

- [ ] **Step 3: Create the command module**

Create `books/commands/reset.py`:

```python
#!/usr/bin/env python3
"""`reset` — delete the purely-derived CSV store for a clean rebuild.

Removes ``Data/books.csv`` and the ``Data/Highlights/`` folder (the only store
that accumulates orphaned per-``book_id`` files). Source layers under
``Data/Sources/`` and the notes are kept. Run ``sync`` afterward (plus the manual
``audible``/``covers`` steps) to rebuild.
"""

from __future__ import annotations

from pathlib import Path

import typer

from books.core import config, store, ui


def _is_interactive() -> bool:
    """Whether we can prompt the user (wrapped so tests can override)."""
    return ui.console.is_terminal


def _plan_lines(vault: Path, plan: dict) -> list[str]:
    lines: list[str] = []
    if plan["books_csv"]:
        lines.append(f"  - {store.books_csv_path(vault)}")
    if plan["highlight_files"]:
        lines.append(
            f"  - {store.highlights_dir(vault)} ({plan['highlight_files']} highlight file(s))"
        )
    return lines


def reset_command(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the "
        "current directory.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print what would be deleted without deleting anything.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the confirmation prompt.",
    ),
) -> None:
    """Delete the derived store (Data/books.csv + Data/Highlights/) for a clean rebuild."""
    vault = config.resolve_vault(output)
    plan = store.reset_store(vault, dry_run=True)

    if not plan["books_csv"] and not plan["highlight_files"]:
        ui.info(f"Nothing to reset under {store.data_dir(vault)}.")
        return

    ui.info("The following will be deleted:")
    for line in _plan_lines(vault, plan):
        ui.info(line)

    if dry_run:
        return

    if not yes:
        if not _is_interactive():
            raise typer.BadParameter(
                "No interactive terminal — pass --yes to confirm deletion.",
                param_hint="--yes",
            )
        if not ui.confirm("Delete the derived store?", default=False):
            ui.info("Aborted.")
            return

    result = store.reset_store(vault)
    ui.success(
        f"Reset: removed books.csv={result['books_csv']}, "
        f"{result['highlight_files']} highlight file(s). "
        f"Run `books sync` to rebuild."
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("reset")(reset_command)


def main() -> None:
    typer.run(reset_command)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Register the command in `books/cli.py`**

Add `reset` to the import block (keep alphabetical) so it reads:

```python
from books.commands import (
    audible,
    calibre,
    covers,
    goodreads,
    highlighted,
    kobo,
    merge,
    readwise,
    render,
    reset,
    sync,
)
```

And add `reset` to the `CAPABILITIES` tuple (keep alphabetical):

```python
CAPABILITIES = (
    audible,
    calibre,
    covers,
    goodreads,
    highlighted,
    kobo,
    merge,
    readwise,
    render,
    reset,
    sync,
)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/commands/test_reset.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add books/commands/reset.py books/cli.py tests/commands/test_reset.py
git commit -m "feat(reset): add the reset command to wipe the derived store

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the capability count**

In `CLAUDE.md`, find the sentence beginning "Ten capabilities exist today" and change "Ten" to "Eleven".

- [ ] **Step 2: Add the `reset` bullet**

In `CLAUDE.md`, after the `sync` capability bullet (the `books/commands/sync.py → sync` paragraph), add a new bullet:

```markdown
- `books/commands/reset.py` → `reset` — deletes the **purely-derived** CSV store so a later `sync` rebuilds it from raw sources: removes `Data/books.csv` (regenerated by `merge`) and the whole `Data/Highlights/` folder (the only store that accumulates orphans, since `store.write_highlights` is keyed by `book_id` and never cleans files for ids that no longer exist — e.g. after a matching change reassigns a `book_id`). Keeps the `Data/Sources/*.csv` layers (they self-replace on re-import; the `audible`/`covers` layers carry network/transcription work and aren't part of `sync`), staged covers, raw imports, and all notes (`Books/`/`Authors/` are `render --refresh`'s job). Via `store.reset_store` (the filesystem logic lives in `core`). `--dry-run` previews the deletion; a real run prints the plan and confirms (`--yes`/`-y` skips the prompt; a non-interactive run without `--yes` errors rather than silently deleting). Typical recovery: `reset` → `sync` → (`audible`/`covers` → `merge` → `render` as needed).
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document the reset command

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Final verification

- [ ] **Step 1: Lint and format**

Run: `uv run ruff check --fix && uv run ruff format`
Expected: no remaining lint errors.

- [ ] **Step 2: Full test suite**

Run: `uv run pytest -q`
Expected: all tests pass (previous baseline 464 + the new reset tests).

- [ ] **Step 3: Smoke-test the CLI**

Run: `uv run books reset --help`
Expected: help text shows `--output`, `--dry-run`, and `--yes`.

- [ ] **Step 4: Commit any formatting-only changes (if ruff reformatted)**

```bash
git add -A
git commit -m "style: ruff format for reset command

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```
(Skip if there is nothing to commit.)

---

## Self-Review Notes

- **Spec coverage:** delete-scope table → Task 1 `reset_store` + Task 3 doc; CLI options (`--output`/`--dry-run`/`--yes`) → Task 2; confirm/non-TTY guard → Task 2 (`_is_interactive`, `typer.BadParameter`); no-op safety → Tasks 1 & 2; store helper in `core` → Task 1; tests → Tasks 1 & 2; docs → Task 3.
- **Type consistency:** `reset_store` returns `{"books_csv": bool, "highlight_files": int}` everywhere it's referenced; `_is_interactive` name matches in the command and the monkeypatch test.
- **No placeholders:** every code/test step shows complete code; commands include expected output.
