# Highlighted Folder-of-CSVs Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the `highlighted` command accept a folder for `--csv` and import every top-level CSV file in it in one run.

**Architecture:** Add a pure helper `resolve_csv_paths(csv)` that maps a file to `[file]` and a folder to its sorted top-level `*.csv` list (raising `BadParameter` on an empty folder). Keep `convert()` per-file and unchanged; the CLI loops over the resolved paths, calls `convert` per file inside a try/except (skip-and-continue on error), and sums the stats. Cross-file book merging is already handled by the existing shared Obsidian layer (`VaultIndex` re-reads the vault per `convert`, and `update_frontmatter` never overwrites).

**Tech Stack:** Python 3.11+ stdlib, Typer, pytest.

---

### Task 1: `resolve_csv_paths` helper

**Files:**
- Modify: `books/highlighted_obsidian.py` (add helper after `parse_csv`, ~line 44)
- Test: `tests/test_highlighted_obsidian.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_highlighted_obsidian.py`:

```python
import pytest
import typer


def test_resolve_csv_paths_single_file(tmp_path):
    p = write_csv(tmp_path)
    assert hi.resolve_csv_paths(p) == [p]


def test_resolve_csv_paths_folder_sorted(tmp_path):
    (tmp_path / "b.csv").write_text(HEADER + ROWS, encoding="utf-8")
    (tmp_path / "a.csv").write_text(HEADER + ROWS, encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    result = hi.resolve_csv_paths(tmp_path)
    assert [p.name for p in result] == ["a.csv", "b.csv"]


def test_resolve_csv_paths_empty_folder_raises(tmp_path):
    with pytest.raises(typer.BadParameter):
        hi.resolve_csv_paths(tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_highlighted_obsidian.py -k resolve_csv_paths -v`
Expected: FAIL with `AttributeError: module 'books.highlighted_obsidian' has no attribute 'resolve_csv_paths'`

- [ ] **Step 3: Write minimal implementation**

Add after `parse_csv` in `books/highlighted_obsidian.py`:

```python
def resolve_csv_paths(csv_path: Path) -> list[Path]:
    """Resolve --csv into a list of CSV files.

    A file yields ``[csv_path]``; a directory yields its sorted top-level
    ``*.csv`` files (non-recursive). An empty directory raises BadParameter.
    """
    if csv_path.is_dir():
        paths = sorted(csv_path.glob("*.csv"))
        if not paths:
            raise typer.BadParameter(
                f"no CSV files found in {csv_path}", param_hint="--csv")
        return paths
    return [csv_path]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_highlighted_obsidian.py -k resolve_csv_paths -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add books/highlighted_obsidian.py tests/test_highlighted_obsidian.py
git commit -m "feat(highlighted): resolve --csv folder to a sorted list of CSVs"
```

---

### Task 2: CLI loops over CSVs, sums stats, skips bad files

**Files:**
- Modify: `books/highlighted_obsidian.py` — `highlighted_to_obsidian` (~lines 105-137)
- Test: `tests/test_highlighted_obsidian.py`

This task changes the CLI command. The CLI is exercised via Typer's `CliRunner`. Tests assert on the printed summary and on the vault contents.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_highlighted_obsidian.py`:

```python
from typer.testing import CliRunner
from books.cli import app

runner = CliRunner()

# A second book, distinct ISBN, for the multi-file folder test.
ROWS_TROTSKY = (
    '"Ideas are more powerful than guns.",The Prophet Armed,Isaac Deutscher,'
    '9781781683118,,Read,2026-07-25,88,Trotsky,,2026-07-25 09:00:00,N\n'
)


def test_cli_folder_imports_all_and_sums(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "stalin.csv").write_text(HEADER + ROWS, encoding="utf-8")
    (src / "trotsky.csv").write_text(HEADER + ROWS_TROTSKY, encoding="utf-8")
    out = tmp_path / "Obsidian"
    result = runner.invoke(app, ["highlighted", "-c", str(src), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "2 files" in result.output
    assert (out / "Books" / "Stalin - Stephen Kotkin.md").exists()
    assert (out / "Books" / "The Prophet Armed - Isaac Deutscher.md").exists()
    # books/entries summed across both files
    assert "3 books" in result.output
    assert "3 highlights" in result.output


def test_cli_folder_merges_same_book_across_files(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.csv").write_text(HEADER + ROWS, encoding="utf-8")
    # same ISBN -> same book, one more highlight
    (src / "b.csv").write_text(
        HEADER + '"Another line.",Stalin,Stephen Kotkin,9781594203794,,Reading,'
        '2026-07-24,60,Stalin,,2026-07-24 12:00:00,N\n', encoding="utf-8")
    out = tmp_path / "Obsidian"
    result = runner.invoke(app, ["highlighted", "-c", str(src), "-o", str(out)])
    assert result.exit_code == 0, result.output
    # exactly one Stalin note (no duplicate)
    stalin_notes = list((out / "Books").glob("Stalin*"))
    assert len(stalin_notes) == 1
    hl = (out / "Exports" / "Stephen Kotkin" / "Stalin" / "Highlights.md").read_text()
    assert "Fear is the mind-killer" in hl
    assert "Another line." in hl


def test_cli_folder_skips_bad_csv(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "good.csv").write_text(HEADER + ROWS, encoding="utf-8")
    # a .csv with no usable columns still parses to rows with empty Title and is
    # skipped at the row level; force a hard failure instead: a directory named
    # like a csv is not possible, so simulate a parse error via unreadable bytes.
    (src / "bad.csv").write_bytes(b"\xff\xfe\x00not a valid utf-8 csv\x00")
    out = tmp_path / "Obsidian"
    result = runner.invoke(app, ["highlighted", "-c", str(src), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "1 skipped" in result.output
    assert (out / "Books" / "Stalin - Stephen Kotkin.md").exists()


def test_cli_single_file_shows_one_file(tmp_path):
    csv = write_csv(tmp_path)
    out = tmp_path / "Obsidian"
    result = runner.invoke(app, ["highlighted", "-c", str(csv), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "1 file" in result.output
    assert (out / "Books" / "Stalin - Stephen Kotkin.md").exists()


def test_cli_empty_folder_errors(tmp_path):
    src = tmp_path / "empty"
    src.mkdir()
    out = tmp_path / "Obsidian"
    result = runner.invoke(app, ["highlighted", "-c", str(src), "-o", str(out)])
    assert result.exit_code != 0
```

Note on the bad-CSV test: the `\xff\xfe` bytes are not valid UTF-8, so `open(..., encoding="utf-8-sig")` + `DictReader` raises `UnicodeDecodeError` inside `convert`, which the try/except must catch. If in practice the decode does not raise on the test runner, replace the bad file's contents with a byte sequence that reliably fails UTF-8 decoding, or assert the skip path another way — but keep the test asserting `"1 skipped"` and that the good book imported.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_highlighted_obsidian.py -k cli -v`
Expected: FAIL — the current CLI treats `--csv` as a single file (`is_file()` check rejects a folder) and prints no "files" count.

- [ ] **Step 3: Write minimal implementation**

Replace the body of `highlighted_to_obsidian` (the code after the docstring, currently lines 126-137) in `books/highlighted_obsidian.py` with:

```python
    csv = resolve_path(csv, Path.cwd())
    output = config.resolve_vault(output)

    if not csv.is_file() and not csv.is_dir():
        raise typer.BadParameter(f"CSV not found: {csv}", param_hint="--csv")

    csv_paths = resolve_csv_paths(csv)

    output.mkdir(parents=True, exist_ok=True)

    totals = {"books": 0, "entries": 0, "authors": set()}
    skipped = 0
    for path in csv_paths:
        try:
            stats = convert(path, output)
        except Exception as exc:  # noqa: BLE001 - skip and continue on any bad file
            skipped += 1
            typer.echo(f"Skipped {path.name}: {exc}", err=True)
            continue
        totals["books"] += stats["books"]
        totals["entries"] += stats["entries"]
        totals["authors"].update(stats["authors"])

    files = len(csv_paths)
    files_word = "file" if files == 1 else "files"
    skipped_note = f" ({skipped} skipped)" if skipped else ""
    typer.echo(
        f"Done. {files} {files_word}{skipped_note}, {totals['books']} books, "
        f"{totals['entries']} highlights, {len(totals['authors'])} authors.\n"
        f"Output: {output}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_highlighted_obsidian.py -k cli -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add books/highlighted_obsidian.py tests/test_highlighted_obsidian.py
git commit -m "feat(highlighted): import every CSV in a folder, skipping bad files"
```

---

### Task 3: Update `--csv` help text and docstring

**Files:**
- Modify: `books/highlighted_obsidian.py` — `--csv` option help (~line 109) and command docstring (~lines 118-125)

- [ ] **Step 1: Update the `--csv` help text**

Change the `csv` option's `help` string to:

```python
        help="Path to a Highlighted CSV export, or a folder of CSV exports "
             "(every top-level *.csv is imported). Relative paths resolve "
             "against the current directory.",
```

- [ ] **Step 2: Update the command docstring**

Append to the `highlighted_to_obsidian` docstring a sentence noting folder support:

```
    When --csv is a folder, every top-level '*.csv' file in it is imported in
    sorted order; a file that fails to parse is skipped and reported.
```

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (all tests, including the pre-existing ones).

- [ ] **Step 4: Verify the CLI help renders**

Run: `uv run books highlighted --help`
Expected: help text mentions "or a folder of CSV exports".

- [ ] **Step 5: Commit**

```bash
git add books/highlighted_obsidian.py
git commit -m "docs(highlighted): document folder support in --csv help"
```

---

### Task 4: Update CLAUDE.md capability description

**Files:**
- Modify: `CLAUDE.md` — the `books/highlighted_obsidian.py` bullet under Architecture

- [ ] **Step 1: Edit the capability bullet**

In `CLAUDE.md`, extend the `highlighted` capability bullet to note that `--csv`
accepts a folder. Change the sentence that begins "reads a Highlighted app CSV
export" to also state: "`--csv` accepts a single CSV file or a folder of CSV
exports (every top-level `*.csv` is imported in sorted order; a file that fails
to parse is skipped and reported)."

- [ ] **Step 2: Run the full suite (sanity)**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note highlighted --csv folder support in CLAUDE.md"
```

---

## Self-Review Notes

- **Spec coverage:** Interface (file-or-folder reuse of `--csv`) → Task 1 + Task 2; top-level non-recursive sorted scan → Task 1; empty-folder `BadParameter` → Task 1; per-file `convert` loop + cross-file merge → Task 2; skip-and-continue error handling → Task 2; always-show file count summary with `(N skipped)` → Task 2; help/docstring/CLAUDE.md docs → Tasks 3-4. All spec sections covered.
- **Type consistency:** `resolve_csv_paths(csv_path: Path) -> list[Path]` is defined in Task 1 and called in Task 2. `convert` signature unchanged. `totals` dict mirrors `convert`'s returned `stats` keys (`books`, `entries`, `authors`).
- **No placeholders:** all steps contain concrete code/commands. The bad-CSV test carries an explicit fallback note in case UTF-8 decoding behaves differently on the runner.
