# Highlighted: folder-of-CSVs import

**Date:** 2026-07-26
**Capability:** `booktools/highlighted_obsidian.py` → `highlighted`

## Goal

Let the `highlighted` command accept a folder for `--csv` and process every CSV
file inside it in one run, in addition to the existing single-file behavior.

## Interface

`--csv` accepts either:
- a **file** — current behavior, unchanged; or
- a **folder** — every top-level `*.csv` in the folder is processed.

Folder scan is **non-recursive** (top-level `*.csv` only), and files are processed
in **sorted (alphabetical) order** for deterministic runs. No new CLI options.

## Behavior

### Resolving inputs

A new helper resolves the `--csv` argument into a list of CSV paths:

- file → `[path]`
- directory → `sorted(path.glob("*.csv"))`
  - if the folder contains no CSVs → raise `typer.BadParameter`
    ("no CSV files found in …", `param_hint="--csv"`)
- neither file nor directory → `typer.BadParameter` ("CSV not found: …") as today

### Processing

`convert(csv_path, output)` stays per-file and unchanged. A new loop calls
`convert` once per resolved CSV path, accumulating stats across files.

Merging across files is already handled by the existing shared layer:
- Each `convert` builds its own `VaultIndex(output)`, which re-reads the vault, so
  a book created while processing file 1 is *found* (not duplicated) when file 2
  references the same book (matched by ISBN, then Author/Title).
- `update_frontmatter` / `write_leaf_with_embed` never overwrite, so highlights
  accumulate across files just like Calibre→Goodreads today.

### Error handling

Each file's `convert` call is wrapped in try/except. On failure:
- echo a warning to **stderr** naming the file and the error,
- increment a `skipped` counter,
- continue with the remaining files.

A single bad/empty/unexpected CSV never aborts the whole run.

### Reporting

The summary always shows the file count (uniform for single file and folder):

```
Done. 3 files (1 skipped), 12 books, 340 highlights, 5 authors.
Output: <vault>
```

The `(N skipped)` clause is omitted when nothing was skipped. Stats (`books`,
`entries`, `authors`) are summed across all successfully-processed files; authors
are de-duplicated across files (a set, as today).

## Out of scope / unchanged

- `scripts/highlighted_obsidian.py` shim (calls `main()`), unchanged.
- `booktools/highlights.py`, `booktools/obsidian.py`, and other capabilities.
- Recursion into subfolders.
- Any change to how a single CSV is parsed or rendered.

## Testing (TDD)

New tests in `tests/test_highlighted_obsidian.py`:

1. Folder with two CSVs → both imported; stats summed; file count = 2.
2. Same book across two CSVs → highlights merged into one note (no duplicate note).
3. Folder with one bad CSV + one good CSV → good imported, bad skipped, `skipped` = 1.
4. Folder with no CSVs → `typer.BadParameter`.
5. Single-file path still works (regression), summary shows `1 file`.
