# Highlight Tags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Associate tags with individual highlights (from the Highlighted CSV `Tags` column and from inline Kobo `#hashtags`) and render them inside each quote callout so they share the quote's Obsidian block anchor.

**Architecture:** Extend the shared `Highlight` model with a `tags` list and a `sanitize_tag` helper; render tags inside the quote callout. Each importer maps its own source format into `tags`: Highlighted splits its comma-separated `Tags` column; Kobo extracts `#hashtags` from note text and strips them out.

**Tech Stack:** Python 3, stdlib only (`re`, `dataclasses`), Typer CLI, pytest. Run tests with `uv run pytest`.

---

### Task 1: Add `tags` field and `sanitize_tag` to the shared model

**Files:**
- Modify: `booktools/highlights.py`
- Test: `tests/test_highlights.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_highlights.py`:

```python
def test_sanitize_tag_whitespace_to_hyphen():
    assert hl.sanitize_tag("Cold War") == "Cold-War"


def test_sanitize_tag_strips_leading_hash():
    assert hl.sanitize_tag("#Stalin") == "Stalin"


def test_sanitize_tag_trims_surrounding_whitespace():
    assert hl.sanitize_tag("  spaced  ") == "spaced"


def test_sanitize_tag_empty_returns_none():
    assert hl.sanitize_tag("") is None
    assert hl.sanitize_tag("   ") is None
    assert hl.sanitize_tag("#") is None


def test_highlight_tags_defaults_to_empty_list():
    h = hl.Highlight(text="x")
    assert h.tags == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_highlights.py -k "sanitize_tag or tags_defaults" -v`
Expected: FAIL — `AttributeError: module 'booktools.highlights' has no attribute 'sanitize_tag'` and `TypeError`/missing `tags`.

- [ ] **Step 3: Implement the field and helper**

In `booktools/highlights.py`, change the import line:

```python
from dataclasses import dataclass, field
```

Add `tags` to the `Highlight` dataclass (after the `date` field):

```python
    date: str | None = None
    tags: list[str] = field(default_factory=list)
```

Add the helper after the `Highlight` dataclass (before `build_anchors`):

```python
def sanitize_tag(raw: str) -> str | None:
    """Normalize a raw tag into a valid Obsidian inline tag, or None if empty.

    Strips surrounding whitespace and a single leading '#', then collapses
    internal whitespace runs to a single '-' (Obsidian inline tags cannot
    contain spaces). Returns None when nothing is left.
    """
    if raw is None:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("#"):
        cleaned = cleaned[1:].strip()
    cleaned = re.sub(r"\s+", "-", cleaned)
    return cleaned or None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_highlights.py -k "sanitize_tag or tags_defaults" -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add booktools/highlights.py tests/test_highlights.py
git commit -m "Add tags field + sanitize_tag helper to Highlight model"
```

---

### Task 2: Render tags inside the quote callout

**Files:**
- Modify: `booktools/highlights.py` (the `render_highlights` function)
- Test: `tests/test_highlights.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_highlights.py`:

```python
def test_render_tags_inside_quote_callout_above_anchor():
    hs = [hl.Highlight(text="A line", chapter_index=2, block="17", segment="5",
                       tags=["Stalin", "USSR"])]
    out = hl.render_highlights(hs)
    # tag line lives inside the callout (prefixed with "> ")
    assert "> #Stalin #USSR" in out
    # ...above the block anchor, below the quoted text
    quote_block = out.split("^ch2-b17-5")[0]
    assert quote_block.index("> A line") < quote_block.index("> #Stalin #USSR")


def test_render_no_tags_callout_unchanged():
    hs = [hl.Highlight(text="A line", chapter_index=2, block="17", segment="5")]
    out = hl.render_highlights(hs)
    assert "#" not in out.split("^ch2-b17-5")[0]  # no tag line in the quote block


def test_render_tags_and_note_both_present():
    hs = [hl.Highlight(text="A line", note="my thought", chapter_index=2,
                       block="1", segment="0", tags=["Stalin"])]
    out = hl.render_highlights(hs)
    assert "> #Stalin" in out          # tag inside quote callout
    assert "> [!note]-" in out         # note callout still rendered
    assert out.index("> #Stalin") < out.index("> [!note]-")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_highlights.py -k "render_tags or render_no_tags" -v`
Expected: FAIL — tag line not present in output.

- [ ] **Step 3: Implement tag rendering**

In `booktools/highlights.py`, replace the body of `render_highlights` so the quote text and tags are composed before wrapping in the callout. Change this block:

```python
    for h, anchor in zip(highlights, anchors):
        block = f"{_callout('quote', _label(h), h.text, expanded=True)}\n^{anchor}"
        if h.note and h.note.strip():
```

to:

```python
    for h, anchor in zip(highlights, anchors):
        body = h.text
        if h.tags:
            tag_line = " ".join(f"#{t}" for t in h.tags)
            body = f"{body}\n\n{tag_line}"
        block = f"{_callout('quote', _label(h), body, expanded=True)}\n^{anchor}"
        if h.note and h.note.strip():
```

(The existing `_callout` helper already prefixes every line with `> ` and turns the
blank line into `>`, so the tags land inside the callout with a blank separator line.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_highlights.py -v`
Expected: PASS (all highlights tests, including the pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add booktools/highlights.py tests/test_highlights.py
git commit -m "Render highlight tags inside the quote callout"
```

---

### Task 3: Extract Kobo hashtags from note text

**Files:**
- Modify: `booktools/kobo_export.py` (the `row_to_highlight` function; add a module-level regex + helper)
- Test: `tests/test_kobo_export.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_kobo_export.py`:

```python
import pytest


class _R(dict):
    """Row stub matching kobo_export's row access (missing keys -> None)."""
    def __getitem__(self, k):
        return dict.get(self, k)


def _hl(note):
    row = _R(chapter_index=1, chapter="Ch", chapter_progress=0.1,
             container_path=r"span#kobo\.1\.0", highlight="Hi", note=note,
             date_created="2026-07-01")
    return ke.row_to_highlight(row)


@pytest.mark.parametrize("note", [
    "Note. #tag1 #tag2",
    "Note.#tag1 #tag2",
    "Note. #tag1#tag2",
])
def test_kobo_extracts_tags_and_strips_note(note):
    h = _hl(note)
    assert h.note == "Note."
    assert h.tags == ["tag1", "tag2"]


def test_kobo_note_only_tags_becomes_none():
    h = _hl("#tag1 #tag2")
    assert h.note is None
    assert h.tags == ["tag1", "tag2"]


def test_kobo_no_tags_note_verbatim():
    h = _hl("Just a plain note.")
    assert h.note == "Just a plain note."
    assert h.tags == []


def test_kobo_dedupes_tags_preserving_order():
    h = _hl("#tag1 middle #tag1")
    assert h.note == "middle"
    assert h.tags == ["tag1"]


def test_kobo_preserves_nested_and_hyphen_tags():
    h = _hl("#history/ussr #cold-war")
    assert h.tags == ["history/ussr", "cold-war"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_kobo_export.py -k "kobo_extracts or kobo_note_only or kobo_no_tags or kobo_dedupes or kobo_preserves" -v`
Expected: FAIL — tags empty and note still contains hashtags.

- [ ] **Step 3: Implement hashtag extraction**

In `booktools/kobo_export.py`, add the import for the sanitize helper. Change:

```python
from booktools.highlights import Highlight, render_highlights
```

to:

```python
from booktools.highlights import Highlight, render_highlights, sanitize_tag
```

Add a module-level regex and helper near the top (after the imports, before `QUERY`):

```python
_HASHTAG_RE = re.compile(r"#(\w[\w/-]*)")


def extract_tags(note: str | None) -> tuple[str | None, list[str]]:
    """Split inline #hashtags out of a note.

    Returns (clean_note, tags): tags are the hashtag names in first-seen order,
    de-duplicated and sanitized; clean_note is the note with all hashtag spans
    removed and whitespace collapsed (None if nothing readable remains).
    """
    if not note:
        return None, []
    tags: list[str] = []
    for name in _HASHTAG_RE.findall(note):
        tag = sanitize_tag(name)
        if tag and tag not in tags:
            tags.append(tag)
    clean = _HASHTAG_RE.sub("", note)
    clean = re.sub(r"\s+", " ", clean).strip()
    return (clean or None), tags
```

Then update `row_to_highlight` to use it. Replace:

```python
def row_to_highlight(row: sqlite3.Row) -> Highlight:
    """Map a Kobo query row to a source-agnostic Highlight."""
    block, segment = parse_container(row["container_path"])
    idx = row["chapter_index"]
    return Highlight(
        text=(row["highlight"] or "").strip(),
        note=(row["note"] or "").strip() or None,
        chapter_index=None if idx is None else int(idx),
        chapter_title=(row["chapter"] or "").strip() or None,
        progress=None if row["chapter_progress"] is None else float(row["chapter_progress"]),
        block=block or None,
        segment=segment or None,
        date=(row["date_created"] or "").strip() or None,
    )
```

with:

```python
def row_to_highlight(row: sqlite3.Row) -> Highlight:
    """Map a Kobo query row to a source-agnostic Highlight."""
    block, segment = parse_container(row["container_path"])
    idx = row["chapter_index"]
    note, tags = extract_tags((row["note"] or "").strip() or None)
    return Highlight(
        text=(row["highlight"] or "").strip(),
        note=note,
        chapter_index=None if idx is None else int(idx),
        chapter_title=(row["chapter"] or "").strip() or None,
        progress=None if row["chapter_progress"] is None else float(row["chapter_progress"]),
        block=block or None,
        segment=segment or None,
        date=(row["date_created"] or "").strip() or None,
        tags=tags,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_kobo_export.py -v`
Expected: PASS (new tests + pre-existing `test_row_to_highlight_maps_fields`, which uses a note without hashtags so `note == "note"` still holds).

- [ ] **Step 5: Commit**

```bash
git add booktools/kobo_export.py tests/test_kobo_export.py
git commit -m "Extract inline #hashtags from Kobo notes as tags"
```

---

### Task 4: Split the Highlighted CSV `Tags` column

**Files:**
- Modify: `booktools/highlighted_obsidian.py` (the `row_to_highlight` function)
- Test: `tests/test_highlighted_obsidian.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_highlighted_obsidian.py`:

```python
def test_row_to_highlight_splits_tags_on_comma():
    h = hi.row_to_highlight({"Highlight": "x", "Tags": "Stalin, USSR"})
    assert h.tags == ["Stalin", "USSR"]


def test_row_to_highlight_single_tag():
    h = hi.row_to_highlight({"Highlight": "x", "Tags": "Stalin"})
    assert h.tags == ["Stalin"]


def test_row_to_highlight_no_tags():
    assert hi.row_to_highlight({"Highlight": "x", "Tags": ""}).tags == []
    assert hi.row_to_highlight({"Highlight": "x"}).tags == []


def test_row_to_highlight_sanitizes_tag_whitespace():
    h = hi.row_to_highlight({"Highlight": "x", "Tags": "Cold War, USSR"})
    assert h.tags == ["Cold-War", "USSR"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_highlighted_obsidian.py -k "splits_tags or single_tag or no_tags or sanitizes_tag" -v`
Expected: FAIL — `h.tags` is `[]` (field exists but importer never populates it).

- [ ] **Step 3: Implement tag splitting**

In `booktools/highlighted_obsidian.py`, add `sanitize_tag` to the import:

```python
from booktools.highlights import Highlight, render_highlights, sanitize_tag
```

Replace `row_to_highlight`:

```python
def row_to_highlight(row: dict) -> Highlight:
    """Map a Highlighted CSV row to a source-agnostic Highlight."""
    return Highlight(
        text=(row.get("Highlight") or "").strip(),
        note=(row.get("Note") or "").strip() or None,
        page=(row.get("Location") or "").strip() or None,
        date=(row.get("Date") or "").strip() or None,
    )
```

with:

```python
def row_to_highlight(row: dict) -> Highlight:
    """Map a Highlighted CSV row to a source-agnostic Highlight."""
    raw_tags = (row.get("Tags") or "").split(",")
    tags = [t for t in (sanitize_tag(part) for part in raw_tags) if t]
    return Highlight(
        text=(row.get("Highlight") or "").strip(),
        note=(row.get("Note") or "").strip() or None,
        page=(row.get("Location") or "").strip() or None,
        date=(row.get("Date") or "").strip() or None,
        tags=tags,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_highlighted_obsidian.py -v`
Expected: PASS (new tests + pre-existing `test_parse_and_map`).

- [ ] **Step 5: Commit**

```bash
git add booktools/highlighted_obsidian.py tests/test_highlighted_obsidian.py
git commit -m "Split Highlighted CSV Tags column into per-highlight tags"
```

---

### Task 5: Full-suite regression check

**Files:** none (verification only)

- [ ] **Step 1: Run the entire suite**

Run: `uv run pytest -q`
Expected: PASS — all tests green, no regressions in `test_highlights.py`,
`test_kobo_export.py`, `test_highlighted_obsidian.py`, or the CLI/importer tests.

- [ ] **Step 2: Commit (only if any incidental fixes were needed)**

```bash
git add -A
git commit -m "Fix regressions surfaced by full test run"
```

If the suite was already green, skip this commit.
