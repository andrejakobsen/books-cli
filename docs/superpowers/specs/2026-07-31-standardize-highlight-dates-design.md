# Standardize highlight dates

## Goal

Every per-highlight timestamp we store in `Data/Highlights/<book_id>.csv` should be a
single canonical format: ISO 8601 in UTC, seconds precision, `Z` suffix
(e.g. `2024-03-15T14:30:00Z`). Today the `date` column is populated but each source
writes its own raw string, so the column is a mix of formats.

## Background

The `date` field already exists end to end and needs **no schema change**:

- `Highlight.date: str | None` — `books/core/highlights.py`
- `"date"` in `HIGHLIGHT_COLUMNS`, `HighlightRow.date` — `books/core/store.py`
- round-trips via `highlight_to_row` / `row_to_highlight`

All five highlight sources already capture and propagate a per-highlight timestamp;
the only problem is the format is inconsistent. The raw shapes that reach
`Highlight.date` are:

| Source | Example literal | Separator | TZ |
|---|---|---|---|
| Kobo | `2024-03-15T14:30:00.000` (real) / `2026-07-01` (date-only) | `T` / bare | none |
| Highlighted | `2026-07-24 11:15:47` / `2020-01-01` | space | none |
| Readwise | `2026-07-17 14:00:25.470174+00:00` | space | `+00:00` |
| Kindle | `2015-07-31T00:17:35` (already `.isoformat()`) | `T` | none |
| Audible | `2026-07-28 07:38:09.0` | space | none |

Key fact: **all of these are parseable by `datetime.fromisoformat` on Python 3.11+**
(the project requires `>=3.11`). Verified against all six literal shapes above.

## Decisions

- **Target format:** ISO 8601 UTC, seconds precision, `Z` suffix. Fractional seconds
  are dropped. Date-only inputs become `…T00:00:00Z`.
- **Naive timestamps** (no offset — Kobo, Highlighted, Kindle, Audible) are treated as
  **already UTC**: attach UTC without shifting the wall-clock value.
- **Aware timestamps** (Readwise's `+00:00`) are converted to UTC via `astimezone`.
- **Parse failures:** leave the `date` column empty **and** emit a warning naming the
  book so unparseable formats surface. Never store a raw/unparsed string.
- **Not in scope (YAGNI):** no config key, no timezone-of-record beyond UTC, no
  sorting or rendering by date. `sort_key` continues to ignore `date`.

## Design

### 1. Pure helper — `normalize_date`

Add to `books/core/highlights.py` (format-agnostic, beside the `Highlight` model):

```python
def normalize_date(raw: str | None) -> str | None:
    """Normalize a raw source timestamp to ISO 8601 UTC (seconds, 'Z').

    Returns None for empty/None input or an unparseable string. Naive
    timestamps are assumed to be UTC; aware ones are converted to UTC.
    """
```

Behavior:
- `None` or blank (after strip) → `None`.
- Parse with `datetime.fromisoformat`.
- On `ValueError` → `None` (caller warns).
- If parsed datetime is naive → `replace(tzinfo=timezone.utc)`; else
  `astimezone(timezone.utc)`.
- Return `dt.strftime("%Y-%m-%dT%H:%M:%SZ")`.

The helper is pure and does no logging, so it stays trivially testable. It signals
failure to the caller purely through its `None` return (distinguishing "empty input"
from "unparseable input" is handled at the call site, which already knows the raw
value was non-empty).

### 2. Single application point — store write path

Normalize centrally in the highlights write path in `books/core/store.py`, so all
five importers funnel through one normalizer regardless of raw format. Concretely,
in `write_highlights` (which has `book_id` in scope), for each highlight:

- Compute `normalized = normalize_date(h.date)`.
- If the raw `h.date` was non-empty but `normalized is None`, emit a warning
  identifying the book, e.g.:
  `warning: could not parse highlight date '<raw>' for <book_id>` (using the same
  console/echo mechanism importers use).
- Write `normalized or ""` into the row.

`highlight_to_row` remains a pure mapping function; the normalization + warning live
in `write_highlights` where the `book_id` context exists. (If cleaner in
implementation, `highlight_to_row` may take an already-normalized value — the
important constraint is that normalization happens once, centrally, on the write
path.)

### Why central, not per-importer

- One implementation and one test surface instead of five call sites.
- The Kindle and Audible JSON **caches keep their raw values** — no cache migration.
  They are re-resolved and re-normalized on every `books import`.
- `book_id` is available for a useful warning.

## Testing

Unit tests for `normalize_date`:
- Each source's literal shape → expected `Z` output:
  - `2024-03-15T14:30:00.000` → `2024-03-15T14:30:00Z`
  - `2026-07-01` → `2026-07-01T00:00:00Z`
  - `2026-07-24 11:15:47` → `2026-07-24T11:15:47Z`
  - `2026-07-17 14:00:25.470174+00:00` → `2026-07-17T14:00:25Z`
  - `2015-07-31T00:17:35` → `2015-07-31T00:17:35Z`
  - `2026-07-28 07:38:09.0` → `2026-07-28T07:38:09Z`
- `None` → `None`; `""` / whitespace → `None`.
- Unparseable string (e.g. `not a date`) → `None`.

Store-level test:
- `write_highlights` writes normalized values into the CSV `date` column.
- An unparseable raw date leaves the column empty and emits a warning.

Existing importer tests that assert a raw `Highlight.date` value (e.g. Readwise's
`tests/commands/test_readwise.py` asserting `2026-07-17 14:00:25.470174+00:00`) are
unaffected, because normalization now happens at store-write, not at import — the
`Highlight` object still carries the raw string. Only CSV-level assertions change.
