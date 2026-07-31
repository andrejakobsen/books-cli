# Standardize Highlight Dates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize every per-highlight timestamp written to `Data/Highlights/<book_id>.csv` to a single canonical format — ISO 8601 UTC, seconds precision, `Z` suffix (e.g. `2024-03-15T14:30:00Z`).

**Architecture:** Add one pure helper `normalize_date` in `books/core/highlights.py`. Apply it at the single store-write funnel (`store.write_highlights`), which every importer path converges on (CSV importers/kobo/kindle via `import_highlights`; audible calls `write_highlights` directly). Unparseable non-empty dates leave the column empty and emit a warning via `books.core.ui.warn`.

**Tech Stack:** Python 3.11+ (`datetime.fromisoformat` handles all source shapes), pydantic v2 (`HighlightRow`), pytest.

**Spec:** `docs/superpowers/specs/2026-07-31-standardize-highlight-dates-design.md`

---

## File Structure

- `books/core/highlights.py` — add `normalize_date`; add `from datetime import datetime, timezone` import.
- `books/core/store.py` — apply normalization + warning inside `write_highlights`; import the helper and `ui`.
- `tests/core/test_highlights.py` — unit tests for `normalize_date`.
- `tests/core/test_store.py` — store-level test: CSV column normalized; unparseable → empty + warning.

---

## Task 1: `normalize_date` helper

**Files:**
- Modify: `books/core/highlights.py` (add import + function)
- Test: `tests/core/test_highlights.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/core/test_highlights.py`:

```python
import pytest

from books.core.highlights import normalize_date


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2024-03-15T14:30:00.000", "2024-03-15T14:30:00Z"),  # kobo (real, ms)
        ("2026-07-01", "2026-07-01T00:00:00Z"),  # kobo/highlighted date-only
        ("2026-07-24 11:15:47", "2026-07-24T11:15:47Z"),  # highlighted (space, naive)
        ("2026-07-17 14:00:25.470174+00:00", "2026-07-17T14:00:25Z"),  # readwise (offset)
        ("2015-07-31T00:17:35", "2015-07-31T00:17:35Z"),  # kindle (isoformat, naive)
        ("2026-07-28 07:38:09.0", "2026-07-28T07:38:09Z"),  # audible (.0 tenths)
    ],
)
def test_normalize_date_canonicalizes_each_source_shape(raw, expected):
    assert normalize_date(raw) == expected


def test_normalize_date_converts_offset_to_utc():
    # +02:00 wall clock 14:30 -> 12:30 UTC
    assert normalize_date("2024-03-15 14:30:00+02:00") == "2024-03-15T12:30:00Z"


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_normalize_date_empty_returns_none(raw):
    assert normalize_date(raw) is None


def test_normalize_date_unparseable_returns_none():
    assert normalize_date("not a date") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_highlights.py -k normalize_date -q`
Expected: FAIL with `ImportError: cannot import name 'normalize_date'`.

- [ ] **Step 3: Add the import**

In `books/core/highlights.py`, the existing imports are:

```python
import math
import re
from dataclasses import dataclass, field
```

Add a datetime import directly below them:

```python
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
```

- [ ] **Step 4: Write the implementation**

Add this function to `books/core/highlights.py` immediately after the `Highlight`
dataclass definition (before `sanitize_tag`):

```python
def normalize_date(raw: str | None) -> str | None:
    """Normalize a raw source timestamp to ISO 8601 UTC (seconds, 'Z' suffix).

    Every highlight source's timestamp reduces to an ISO-8601-parseable string by
    the time it reaches here (Kobo/Highlighted/Kindle/Audible are naive; Readwise
    carries a numeric offset). Naive timestamps are assumed to be UTC; aware ones
    are converted to UTC. Fractional seconds are dropped; date-only input becomes
    ``...T00:00:00Z``.

    Returns None for empty/None input or a string that cannot be parsed.
    """
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_highlights.py -k normalize_date -q`
Expected: PASS (10 tests).

- [ ] **Step 6: Lint, format, commit**

```bash
uv run ruff check --fix
uv run ruff format
git add books/core/highlights.py tests/core/test_highlights.py
git commit -m "feat(highlights): add normalize_date helper (ISO 8601 UTC)"
```

---

## Task 2: Apply normalization at the store-write funnel

**Files:**
- Modify: `books/core/store.py` (`write_highlights`, imports)
- Test: `tests/core/test_store.py`

**Context:** `write_highlights` (currently at `books/core/store.py:597`) is the single
point every importer path converges on. Existing rows are re-read from CSV (already
normalized by prior runs); only the incoming `rows` for the source being written need
normalization. `HighlightRow` is a pydantic v2 model — use `model_copy(update=...)` to
produce a normalized copy rather than mutating in place.

- [ ] **Step 1: Write the failing tests**

Add to `tests/core/test_store.py` (the file already imports `store`, `Highlight`,
`BookRef`):

```python
def test_write_highlights_normalizes_date_column(tmp_path):
    vault = tmp_path / "vault"
    row = store.highlight_to_row(
        Highlight(text="hi", date="2026-07-24 11:15:47"), "highlighted", "0"
    )
    store.write_highlights(vault, "b1", "highlighted", [row])
    back = store.read_highlights(vault, "b1")
    assert [r.date for r in back] == ["2026-07-24T11:15:47Z"]


def test_write_highlights_blanks_and_warns_on_unparseable_date(tmp_path, capsys):
    vault = tmp_path / "vault"
    row = store.highlight_to_row(Highlight(text="hi", date="garbage"), "kobo", "0")
    store.write_highlights(vault, "b1", "kobo", [row])
    back = store.read_highlights(vault, "b1")
    assert [r.date for r in back] == [""]
    assert "could not parse highlight date" in capsys.readouterr().err


def test_write_highlights_leaves_empty_date_empty_without_warning(tmp_path, capsys):
    vault = tmp_path / "vault"
    row = store.highlight_to_row(Highlight(text="hi", date=None), "kobo", "0")
    store.write_highlights(vault, "b1", "kobo", [row])
    back = store.read_highlights(vault, "b1")
    assert [r.date for r in back] == [""]
    assert "could not parse" not in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_store.py -k write_highlights -q`
Expected: FAIL — `test_write_highlights_normalizes_date_column` fails because the raw
`2026-07-24 11:15:47` is written unchanged, and the warning test fails because no
warning is emitted.

- [ ] **Step 3: Add imports to `store.py`**

The existing imports in `books/core/store.py` include:

```python
from books.core.highlights import Highlight
```

Change it to also import the helper, and add the `ui` import (place `from books.core
import ui` with the other `books.core` imports):

```python
from books.core import ui
from books.core.highlights import Highlight, normalize_date
```

- [ ] **Step 4: Normalize inside `write_highlights`**

Replace the current body of `write_highlights` (at `books/core/store.py:597-603`):

```python
def write_highlights(vault: Path, book_id: str, source: str, rows: list[HighlightRow]) -> None:
    """Replace this source's rows in the per-book file, preserving other sources."""
    existing = [r for r in read_highlights(vault, book_id) if r.source != source]
    combined = existing + list(rows)
    _write_csv(
        highlight_path(vault, book_id), HIGHLIGHT_COLUMNS, (r.to_csv_dict() for r in combined)
    )
```

with this version (normalizes the incoming rows; warns once per unparseable date):

```python
def write_highlights(vault: Path, book_id: str, source: str, rows: list[HighlightRow]) -> None:
    """Replace this source's rows in the per-book file, preserving other sources.

    The incoming rows' ``date`` is normalized to ISO 8601 UTC; a non-empty date that
    cannot be parsed is blanked and reported.
    """
    normalized_rows = []
    for r in rows:
        canonical = normalize_date(r.date)
        if r.date and canonical is None:
            ui.warn(f"could not parse highlight date {r.date!r} for {book_id} ({source})")
        normalized_rows.append(r.model_copy(update={"date": canonical or ""}))
    existing = [r for r in read_highlights(vault, book_id) if r.source != source]
    combined = existing + normalized_rows
    _write_csv(
        highlight_path(vault, book_id), HIGHLIGHT_COLUMNS, (r.to_csv_dict() for r in combined)
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_store.py -k write_highlights -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the full suite (no regressions)**

Run: `uv run pytest -q`
Expected: all pass. Importer tests that assert a raw `Highlight.date` value (e.g.
`tests/commands/test_readwise.py`) are unaffected — they assert the in-memory
`Highlight`, which still carries the raw string; only the CSV output is normalized.

- [ ] **Step 7: Lint, format, commit**

```bash
uv run ruff check --fix
uv run ruff format
git add books/core/store.py tests/core/test_store.py
git commit -m "feat(store): normalize highlight dates to ISO 8601 UTC on write"
```

---

## Task 3: Documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Document the normalization**

In `CLAUDE.md`, find the "Phase B — highlights → notes" paragraph in the pipeline
section. Add one sentence at its end describing the behavior:

> Every highlight's timestamp is normalized to ISO 8601 UTC (seconds precision, `Z`
> suffix) on write to the store (`store.write_highlights` via `normalize_date` in
> `books/core/highlights.py`); naive source times are treated as UTC and unparseable
> dates are blanked with a warning.

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note highlight date normalization"
```

---

## Self-Review Notes

- **Spec coverage:** target format (Task 1 helper + tests), naive=UTC / aware→UTC
  (Task 1 tz branch + `test_normalize_date_converts_offset_to_utc`), fractional-drop &
  date-only (Task 1 parametrized cases), central application at store-write (Task 2),
  parse-failure blank + warning (Task 2 tests), empty-without-warning (Task 2 test), no
  schema change (nothing touches `HIGHLIGHT_COLUMNS`/`HighlightRow`), caches untouched
  (only `write_highlights` changed). All covered.
- **Type consistency:** `normalize_date(str | None) -> str | None` used identically in
  Task 1 and Task 2; `HighlightRow.model_copy` is pydantic v2 (confirmed 2.13.4).
- **No placeholders:** every code/command step is concrete.
