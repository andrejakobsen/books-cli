# Obsidian Renderer (Plan B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `books/render_obsidian.py` — the Obsidian renderer that reads the CSV store (`Data/books.csv` + `Data/Highlights/<book-id>.csv`) built in Plan A and writes/updates the flat book notes under `Books/`, plus a `render` CLI command.

**Architecture:** The renderer is a *pure consumer* of `books/store.py`. Per book it writes frontmatter **authoritatively** from the merged `BookRow` (every schema key), with three exceptions: `topics` is 100%-user-owned (preserved verbatim; empty on a new note), and `highlighted`/`reviewed` are **derived** (true iff highlights / a review exist). The cover embed, a write-once `## Review`, and a marker-wrapped `## Highlights` section (via `highlights.render_highlights`) make up the body; content outside those managed regions is left untouched. Frontmatter I/O uses `python-frontmatter` (robust read) + `ruamel.yaml` (authoritative write), per the design spec.

**Tech Stack:** Python 3.11, `python-frontmatter` (frontmatter read/split), `ruamel.yaml` (frontmatter write), `pydantic` v2 row models from `books/store.py`, Typer for the command. Reuses `books/obsidian.py` (`wikilink`, `ensure_section`, `render_marked_section`, `ensure_top_embed`, `format_rating`, `BOOK_PROPERTY_ORDER`, `BOOKS_DIRNAME`, `COVERS_DIRNAME`, `COVER_WIDTH`) and `books/highlights.py` (`render_highlights`).

**Design reference:** `docs/superpowers/specs/2026-07-29-csv-source-of-truth-design.md`

**Decisions locked in (deviations from / clarifications of the spec):**
- **`source`/`sources` frontmatter key: dropped.** A merged book has many contributing sources; the old single `source:` key is meaningless and is removed from the note frontmatter. (Highlight provenance still lives per-row in the Highlights CSV and is surfaced by the mixed-source `### <Source>` grouping.) `NOTE_PROPERTY_ORDER` = `BOOK_PROPERTY_ORDER` minus `source`.
- **Frontmatter I/O = `python-frontmatter` + `ruamel.yaml`** (spec-literal). **Accepted consequence:** the first render re-serializes every existing note's frontmatter into ruamel's block style (quoted wikilinks, block-style lists), a one-time vault-wide diff. The plan therefore does **not** rely on a byte-for-byte "render output matches the old markdown path" migration check — idempotency (render twice ⇒ identical bytes) is the invariant we test instead.
- **`rating` contract:** `books.csv` stores the *numeric* rating (e.g. `4`); the renderer converts numeric ratings to stars via `format_rating` (`render_rating`). Non-numeric values pass through unchanged. (Plan C importers must store the numeric value.)

**Out of scope (later plans):** importers becoming CSV writers (Plan C), the `sync` two-phase pipeline (Plan C), a standalone `books merge` command (Plan C), the one-time markdown→CSV highlight backfill (migration). This plan renders from an already-merged store.

---

## File structure

- Modify: `books/highlights.py` — add an optional `source` field to `Highlight`; make `render_highlights` group by source (with a `### <Source>` header) when the input mixes ≥2 distinct sources. Single-source output is byte-identical to today.
- Modify: `books/store.py` — `row_to_highlight` populates the new `Highlight.source` from the row.
- Create: `books/render_obsidian.py` — the renderer: frontmatter serialization helpers, `book_frontmatter`, `render_body`, `render_note`, `render`, and the `render` Typer command.
- Modify: `books/cli.py` — register the new capability.
- Modify: `pyproject.toml` — add runtime deps `python-frontmatter`, `ruamel.yaml`.
- Test: `tests/test_highlights.py` (append), `tests/test_store.py` (append), `tests/test_render_obsidian.py` (create).

`books/render_obsidian.py` public surface:

```
NOTE_PROPERTY_ORDER
render_rating(raw) -> str
dump_frontmatter(meta) -> str
load_note(path) -> (dict, str)
book_frontmatter(row, note_path, existing, has_highlights) -> dict
render_body(existing_body, row, note_path, highlights) -> str
render_note(vault, row, highlights) -> Path
render(vault) -> dict            # stats
render_command(...)              # Typer command "render"
register(app) / main()
```

---

## Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add runtime deps**

Edit the `[project].dependencies` array to add the two frontmatter libraries. It becomes:

```toml
dependencies = [
    "typer>=0.12",
    "pydantic>=2.6",
    "isbnlib>=3.10",
    "rapidfuzz>=3.6",
    "python-frontmatter>=1.1",
    "ruamel.yaml>=0.18",
]
```

- [ ] **Step 2: Sync and verify imports resolve**

Run: `uv sync && uv run python -c "import frontmatter; from ruamel.yaml import YAML; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Verify existing suite still passes**

Run: `uv run pytest -q`
Expected: PASS for everything except the pre-existing `tests/test_audible_client.py::test_annotations_returns_empty_on_404` (needs the optional `[audible]` extra's `httpx`; unrelated to this work). No new failures.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add python-frontmatter + ruamel.yaml for the Obsidian renderer"
```

---

## Task 2: Mixed-source grouping in `render_highlights`

**Files:**
- Modify: `books/highlights.py`
- Test: `tests/test_highlights.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_highlights.py`:

```python
def test_render_highlights_single_source_has_no_source_header():
    from books.highlights import Highlight, render_highlights

    out = render_highlights(
        [
            Highlight(text="one", progress=0.10, source="kobo"),
            Highlight(text="two", progress=0.20, source="kobo"),
        ]
    )
    assert "### " not in out  # no source header, no chapter header
    assert "one" in out and "two" in out


def test_render_highlights_mixed_sources_group_under_headers():
    from books.highlights import Highlight, render_highlights

    out = render_highlights(
        [
            Highlight(text="kobo hl", progress=0.10, source="kobo"),
            Highlight(text="rw hl", progress=0.20, source="readwise"),
        ]
    )
    assert "### Kobo" in out
    assert "### Readwise" in out
    assert out.index("### Kobo") < out.index("### Readwise")  # alphabetical
    # each highlight sits under its own source header
    assert out.index("### Kobo") < out.index("kobo hl") < out.index("### Readwise")


def test_render_highlights_mixed_sources_unique_anchors():
    from books.highlights import Highlight, render_highlights

    # both sources would naively produce a "10" anchor; must be de-duplicated
    out = render_highlights(
        [
            Highlight(text="a", progress=0.10, source="kobo"),
            Highlight(text="b", progress=0.10, source="readwise"),
        ]
    )
    assert out.count("^10\n") + out.count("^10 ") == 0 or out.count("^10") >= 1
    anchors = [ln for ln in out.splitlines() if ln.startswith("^")]
    assert len(anchors) == len(set(anchors))  # all anchors unique
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_highlights.py -k "source_header or mixed_sources" -q`
Expected: FAIL — `Highlight.__init__() got an unexpected keyword argument 'source'`.

- [ ] **Step 3: Write minimal implementation**

In `books/highlights.py`, add a `source` field to the `Highlight` dataclass (append after `links`):

```python
links: list[str] = field(default_factory=list)
source: str | None = None  # provenance (kobo | readwise | ...) for grouping
```

Then extract the per-highlight callout into a helper and rewrite `render_highlights` to group by source. Replace the entire existing `render_highlights` function (the last function in the file) with:

```python
def _callout(h: Highlight, anchor: str, chapter_prefix: str) -> str:
    """Render one highlight as a single expanded ``[!quote]+`` callout block."""
    title_parts = [p for p in (_label(h, chapter_prefix),) if p]
    if h.links:
        title_parts.append(", ".join(wikilink(name) for name in h.links))
    title = " · ".join(title_parts)
    lines = ["> [!quote]+" + (f" {title}" if title else "")]
    lines += _quote_lines(h.text, ">")
    if h.note and h.note.strip():
        lines.append(">")
        lines += _quote_lines(h.note, ">>")
    if h.tags:
        lines.append(">")
        lines.append("> " + " ".join(f"#{t}" for t in h.tags))
    lines.append(f"^{anchor}")
    return "\n".join(lines)


def render_highlights(highlights: list[Highlight], chapter_label: str | None = None) -> str:
    """Render a list of highlights as an Obsidian ``## Highlights`` body.

    Highlights are sorted into reading order (see :func:`sort_key`) before
    rendering, so output is always ordered by chapter + ``%`` (or by page for
    physical books) regardless of input order; this also makes chapter grouping
    robust against scattered input.

    **Source grouping:** when the input mixes *two or more* distinct
    ``Highlight.source`` values the output is split into per-source groups, each
    introduced by a small ``### <Source>`` header (sources in alphabetical
    order), with the usual chapter subheaders and reading-order sort applied
    *within* each group. When all highlights share one source (or none carry a
    source) no source header is emitted and single-source output is unchanged.

    When any highlight in a group carries a ``chapter_title`` that group is
    *chapter-grouped*: a ``### {title}`` header is emitted at each chapter change.
    Each callout's locator keeps the chapter, prefixed by ``chapter_label`` when
    given (else ``"ch."``). Block anchors are unique across the whole section.
    """
    chapter_prefix = chapter_label or "ch."
    distinct_sources = sorted({h.source for h in highlights if h.source})
    if len(distinct_sources) > 1:
        ordered_groups = [
            (src, sorted([h for h in highlights if (h.source or "") == src], key=sort_key))
            for src in distinct_sources
        ]
    else:
        ordered_groups = [(None, sorted(highlights, key=sort_key))]

    # Anchors are computed over the full, final-order sequence so block ids are
    # unique across every source group.
    flat = [h for _src, group in ordered_groups for h in group]
    anchors = build_anchors(flat)
    anchor_by_id = {id(h): a for h, a in zip(flat, anchors)}

    blocks: list[str] = []
    for src, group in ordered_groups:
        if src is not None:
            blocks.append(f"### {src.title()}")
        grouped = any(h.chapter_title for h in group)
        prev_key = None
        for h in group:
            if grouped:
                key = _chapter_key(h)
                if key != prev_key:
                    header = _chapter_header(h)
                    if header:
                        blocks.append(header)
                    prev_key = key
            blocks.append(_callout(h, anchor_by_id[id(h)], chapter_prefix))
    return "\n\n".join(blocks) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_highlights.py -q`
Expected: PASS — the new tests plus every pre-existing `test_highlights.py` test (single-source output is unchanged by the refactor).

- [ ] **Step 5: Commit**

```bash
git add books/highlights.py tests/test_highlights.py
git commit -m "feat(highlights): group mixed-source highlights under ### Source headers"
```

---

## Task 3: `row_to_highlight` carries source

**Files:**
- Modify: `books/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py`:

```python
def test_row_to_highlight_sets_source():
    row = store.HighlightRow(source="readwise", text="t", location="42", location_kind="percent")
    h = store.row_to_highlight(row)
    assert h.source == "readwise"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -k "row_to_highlight_sets_source" -q`
Expected: FAIL with `AssertionError` (`h.source` is `None`).

- [ ] **Step 3: Write minimal implementation**

In `books/store.py`, in `row_to_highlight`, add `source=row.source or None,` to the `Highlight(...)` constructor call (e.g. right after `text=row.text,`):

```python
    return Highlight(
        text=row.text,
        source=row.source or None,
        note=row.note or None,
        chapter_index=chapter_index,
        chapter_title=row.chapter_title or None,
        progress=progress,
        block=row.block or None,
        segment=row.segment or None,
        page=page,
        location_label=label,
        date=row.date or None,
        tags=list(row.tags),
        links=list(row.links),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py -k "row_to_highlight" -q`
Expected: PASS (the new test plus the existing `row_to_highlight` reversal test).

- [ ] **Step 5: Commit**

```bash
git add books/store.py tests/test_store.py
git commit -m "feat(store): row_to_highlight carries source for renderer grouping"
```

---

## Task 4: Frontmatter serialization helpers

**Files:**
- Create: `books/render_obsidian.py`
- Test: `tests/test_render_obsidian.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_render_obsidian.py`:

```python
import frontmatter

from books import render_obsidian as R


def test_render_rating_numeric_and_passthrough():
    assert R.render_rating("4") == "⭐⭐⭐⭐"
    assert R.render_rating("") == ""
    assert R.render_rating("physical") == "physical"  # non-numeric passes through


def test_dump_frontmatter_roundtrips_wikilinks_and_unicode():
    meta = {
        "type": "book",
        "title": "Café",
        "authors": ["[[Adam Tooze]]"],
        "highlighted": True,
        "rating": "⭐⭐⭐",
        "series": None,
    }
    text = "---\n" + R.dump_frontmatter(meta) + "---\n\nbody\n"
    post = frontmatter.loads(text)
    assert post["title"] == "Café"
    assert post["authors"] == ["[[Adam Tooze]]"]  # wikilink survives quoting
    assert post["highlighted"] is True
    assert post["rating"] == "⭐⭐⭐"  # emoji not escaped
    assert post.content.strip() == "body"


def test_load_note_missing_returns_empty(tmp_path):
    assert R.load_note(tmp_path / "none.md") == ({}, "")


def test_note_property_order_drops_source():
    assert "source" not in R.NOTE_PROPERTY_ORDER
    assert R.NOTE_PROPERTY_ORDER[0] == "type"
    assert "topics" in R.NOTE_PROPERTY_ORDER
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_render_obsidian.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'books.render_obsidian'`.

- [ ] **Step 3: Write minimal implementation**

Create `books/render_obsidian.py`:

```python
#!/usr/bin/env python3
"""Render the CSV store (Plan A) into flat Obsidian book notes under ``Books/``.

Reads ``Data/books.csv`` + per-book ``Data/Highlights/<book-id>.csv`` and
writes/updates one self-contained note per book. Frontmatter is written
*authoritatively* from the merged row for every schema key, except:

- ``topics`` -- 100%-user-owned: preserved verbatim on an existing note, empty
  (``[]``) on a brand-new one. Never written from data.
- ``highlighted`` / ``reviewed`` -- derived: true iff the book has highlights /
  a review.

The body carries the cover embed, a write-once ``## Review`` section, and a
marker-wrapped ``## Highlights`` section; anything outside those managed regions
is left untouched. Frontmatter round-trips via python-frontmatter (read) +
ruamel.yaml (write).
"""

from __future__ import annotations

import io
from pathlib import Path

import frontmatter
from ruamel.yaml import YAML

from books.obsidian import (
    BOOK_PROPERTY_ORDER,
    COVERS_DIRNAME,
    COVER_WIDTH,
    ensure_section,
    ensure_top_embed,
    format_rating,
    render_marked_section,
    wikilink,
)
from books.store import BookRow, row_to_highlight

# The note frontmatter schema: the canonical order minus the retired ``source``
# key (a merged book has many contributing sources; a single value is meaningless).
NOTE_PROPERTY_ORDER = tuple(k for k in BOOK_PROPERTY_ORDER if k != "source")


def _yaml() -> YAML:
    y = YAML()
    y.default_flow_style = False
    y.allow_unicode = True  # keep ⭐ and accented names literal, not \uXXXX
    y.width = 4096  # never line-wrap long titles / values
    return y


def dump_frontmatter(meta: dict) -> str:
    """Serialize an ordered frontmatter dict to a YAML block (trailing newline)."""
    buf = io.StringIO()
    _yaml().dump(meta, buf)
    return buf.getvalue()


def load_note(path: Path) -> tuple[dict, str]:
    """Return (frontmatter dict, body) for an existing note, or ({}, "")."""
    if not path.is_file():
        return {}, ""
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    return dict(post.metadata), post.content


def render_rating(raw: str) -> str:
    """Render a stored rating: numeric -> stars (:func:`format_rating`), else raw."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        return format_rating(float(raw))
    except ValueError:
        return raw
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_render_obsidian.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add books/render_obsidian.py tests/test_render_obsidian.py
git commit -m "feat(render): frontmatter serialization helpers (ruamel + rating)"
```

---

## Task 5: Authoritative frontmatter from a BookRow

**Files:**
- Modify: `books/render_obsidian.py`
- Test: `tests/test_render_obsidian.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render_obsidian.py`:

```python
from books import store


def test_book_frontmatter_authoritative_and_derived(tmp_path):
    note = tmp_path / "Books" / "The Deluge - Adam Tooze.md"
    row = store.BookRow(
        book_id="The Deluge - Adam Tooze",
        title="The Deluge",
        authors=["Adam Tooze"],
        format="ebook",
        shelves=["read"],
        rating="4",
        review="Great book",
    )
    meta = R.book_frontmatter(row, note, existing={}, has_highlights=True)
    assert meta["type"] == "book"
    assert meta["authors"] == ["[[Adam Tooze]]"]
    assert meta["highlighted"] is True  # derived from has_highlights
    assert meta["reviewed"] is True  # derived from row.review
    assert meta["rating"] == "⭐⭐⭐⭐"
    assert meta["shelves"] == ["read"]
    assert list(meta.keys())[0] == "type"  # canonical order
    assert "source" not in meta


def test_book_frontmatter_preserves_existing_topics(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"])
    meta = R.book_frontmatter(row, note, existing={"topics": ["[[History]]"]}, has_highlights=False)
    assert meta["topics"] == ["[[History]]"]
    assert meta["highlighted"] is False
    assert meta["reviewed"] is False


def test_book_frontmatter_new_note_gets_empty_topics(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"])
    meta = R.book_frontmatter(row, note, existing={}, has_highlights=False)
    assert meta["topics"] == []


def test_book_frontmatter_cover_when_row_has_cover(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"], cover="[[Covers/X - A.jpg]]")
    meta = R.book_frontmatter(row, note, existing={}, has_highlights=False)
    assert meta["cover"] == "[[Covers/X - A.jpg]]"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_render_obsidian.py -k "book_frontmatter" -q`
Expected: FAIL with `AttributeError: module 'books.render_obsidian' has no attribute 'book_frontmatter'`.

- [ ] **Step 3: Write minimal implementation**

Append to `books/render_obsidian.py`:

```python
def _scalar(value):
    """Empty/whitespace strings -> None (bare ``key:``); other scalars unchanged."""
    if isinstance(value, str):
        value = value.strip()
    return value or None


def _cover_value(row: BookRow, note_path: Path):
    """The ``cover:`` frontmatter wikilink for a note, or None when no cover.

    Present when the row records a cover OR the flat ``Covers/<stem>.jpg`` file
    already exists (kept in lockstep with the note stem = book_id).
    """
    stem = note_path.stem
    cover_file = note_path.parents[1] / COVERS_DIRNAME / f"{stem}.jpg"
    if (row.cover or "").strip() or cover_file.is_file():
        return f"[[{COVERS_DIRNAME}/{stem}.jpg]]"
    return None


def book_frontmatter(row: BookRow, note_path: Path, existing: dict, has_highlights: bool) -> dict:
    """Build the authoritative, canonically-ordered frontmatter dict for a book.

    Every key comes from *row* except: ``type`` (always ``book``), ``topics``
    (preserved from *existing*, ``[]`` when absent), and ``highlighted`` /
    ``reviewed`` (derived booleans).
    """
    meta = {
        "type": "book",
        "title": _scalar(row.title),
        "authors": [wikilink(a) for a in row.authors],
        "topics": existing.get("topics", []) if existing else [],
        "series": _scalar(row.series),
        "series_index": _scalar(row.series_index),
        "publisher": _scalar(row.publisher),
        "published": _scalar(row.published),
        "language": _scalar(row.language),
        "format": _scalar(row.format),
        "pages": _scalar(row.pages),
        "status": _scalar(row.status),
        "highlighted": bool(has_highlights),
        "reviewed": bool((row.review or "").strip()),
        "shelves": list(row.shelves),
        "rating": _scalar(render_rating(row.rating)),
        "isbn": _scalar(row.isbn),
        "amazon": _scalar(row.amazon),
        "google": _scalar(row.google),
        "goodreads": _scalar(row.goodreads),
        "uuid": _scalar(row.uuid),
        "calibre_id": _scalar(row.calibre_id),
        "date_added": _scalar(row.date_added),
        "date_read": _scalar(row.date_read),
        "cover": _cover_value(row, note_path),
    }
    return {k: meta[k] for k in NOTE_PROPERTY_ORDER if k in meta}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_render_obsidian.py -k "book_frontmatter" -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add books/render_obsidian.py tests/test_render_obsidian.py
git commit -m "feat(render): authoritative frontmatter from a BookRow (topics preserved)"
```

---

## Task 6: Body rendering (cover, review, highlights)

**Files:**
- Modify: `books/render_obsidian.py`
- Test: `tests/test_render_obsidian.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render_obsidian.py`:

```python
def test_render_body_cover_review_and_highlights(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(
        book_id="X - A", title="X", authors=["A"], review="My review", cover="[[Covers/X - A.jpg]]"
    )
    hls = [
        store.HighlightRow(
            source="kobo",
            annotation_id="1",
            text="quote one",
            location="42",
            location_kind="percent",
        )
    ]
    body = R.render_body("", row, note, hls)
    assert "![[Covers/X - A.jpg|150]]" in body
    assert "## Review" in body and "My review" in body
    assert "## Highlights" in body and "quote one" in body
    assert "%% books:highlights:start %%" in body


def test_render_body_review_is_write_once(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"], review="My review")
    once = R.render_body("", row, note, [])
    twice = R.render_body(once, row, note, [])
    assert twice.count("## Review") == 1


def test_render_body_mixed_source_groups(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"])
    hls = [
        store.HighlightRow(
            source="kobo", annotation_id="1", text="k", location="10", location_kind="percent"
        ),
        store.HighlightRow(
            source="readwise", annotation_id="2", text="r", location="20", location_kind="percent"
        ),
    ]
    body = R.render_body("", row, note, hls)
    assert "### Kobo" in body
    assert "### Readwise" in body


def test_render_body_preserves_existing_content(tmp_path):
    note = tmp_path / "Books" / "X - A.md"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"])
    body = R.render_body("My own paragraph.", row, note, [])
    assert "My own paragraph." in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_render_obsidian.py -k "render_body" -q`
Expected: FAIL with `AttributeError: ... 'render_body'`.

- [ ] **Step 3: Write minimal implementation**

Append to `books/render_obsidian.py` (add `render_highlights` to the imports from `books.highlights`):

```python
from books.highlights import render_highlights  # add near the top imports
```

then the function:

```python
def render_body(existing_body: str, row: BookRow, note_path: Path, highlights: list) -> str:
    """Return the note body: cover embed, write-once ``## Review``, ``## Highlights``.

    Operates on the body only (no frontmatter). Idempotent: the cover embed is
    inserted once, the review section is write-once (:func:`ensure_section`), and
    the highlights live between replace-on-rerun markers
    (:func:`render_marked_section`). Content outside these regions is preserved.
    """
    body = existing_body
    if _cover_value(row, note_path):
        embed = f"![[{COVERS_DIRNAME}/{note_path.stem}.jpg|{COVER_WIDTH}]]"
        body = ensure_top_embed(body, embed)
    review = (row.review or "").strip()
    if review:
        body = ensure_section(body, "Review", review + "\n")
    if highlights:
        rendered = render_highlights([row_to_highlight(h) for h in highlights])
        body = render_marked_section(body, "Highlights", "highlights", rendered)
    return body
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_render_obsidian.py -k "render_body" -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add books/render_obsidian.py tests/test_render_obsidian.py
git commit -m "feat(render): note body (cover embed, write-once review, highlights)"
```

---

## Task 7: `render_note` — write/update one note

**Files:**
- Modify: `books/render_obsidian.py`
- Test: `tests/test_render_obsidian.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render_obsidian.py`:

```python
def test_render_note_creates_note_at_book_id_path(tmp_path):
    vault = tmp_path / "vault"
    row = store.BookRow(
        book_id="The Deluge - Adam Tooze",
        title="The Deluge",
        authors=["Adam Tooze"],
        format="ebook",
    )
    path = R.render_note(vault, row, [])
    assert path == vault / "Books" / "The Deluge - Adam Tooze.md"
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    assert post["title"] == "The Deluge"
    assert post["format"] == "ebook"
    assert post["highlighted"] is False


def test_render_note_is_idempotent(tmp_path):
    vault = tmp_path / "vault"
    row = store.BookRow(
        book_id="X - A", title="X", authors=["A"], format="ebook", review="A review"
    )
    hls = [
        store.HighlightRow(
            source="kobo", annotation_id="1", text="hi", location="10", location_kind="percent"
        )
    ]
    path = R.render_note(vault, row, hls)
    first = path.read_text(encoding="utf-8")
    R.render_note(vault, row, hls)
    assert path.read_text(encoding="utf-8") == first  # render twice == identical


def test_render_note_preserves_topics_and_manual_body(tmp_path):
    vault = tmp_path / "vault"
    note = vault / "Books" / "X - A.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        '---\ntype: book\ntitle: X\ntopics:\n- "[[History]]"\n---\n\nMy own paragraph.\n',
        encoding="utf-8",
    )
    row = store.BookRow(book_id="X - A", title="X", authors=["A"], format="ebook")
    R.render_note(vault, row, [])
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert post["topics"] == ["[[History]]"]  # user-owned, preserved
    assert post["format"] == "ebook"  # refreshed from the row
    assert "My own paragraph." in post.content  # manual body preserved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_render_obsidian.py -k "render_note" -q`
Expected: FAIL with `AttributeError: ... 'render_note'`.

- [ ] **Step 3: Write minimal implementation**

Append to `books/render_obsidian.py` (add `BOOKS_DIRNAME` to the `books.obsidian` import list):

```python
def render_note(vault: Path, row: BookRow, highlights: list) -> Path:
    """Write/update the flat book note for *row* under ``Books/<book_id>.md``.

    Frontmatter is rebuilt authoritatively (topics preserved from the existing
    note); the body preserves manual content and managed sections. The result is
    idempotent: rendering the same row + highlights twice yields identical bytes.
    """
    note_path = vault / BOOKS_DIRNAME / f"{row.book_id}.md"
    existing_meta, existing_body = load_note(note_path)
    meta = book_frontmatter(row, note_path, existing_meta, bool(highlights))
    body = render_body(existing_body, row, note_path, highlights).strip("\n")
    front = "---\n" + dump_frontmatter(meta) + "---\n"
    content = f"{front}\n{body}\n" if body else f"{front}\n"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_text(content, encoding="utf-8")
    return note_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_render_obsidian.py -k "render_note" -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add books/render_obsidian.py tests/test_render_obsidian.py
git commit -m "feat(render): render_note writes an idempotent, topics-preserving note"
```

---

## Task 8: `render(vault)` — iterate the whole catalog

**Files:**
- Modify: `books/render_obsidian.py`
- Test: `tests/test_render_obsidian.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render_obsidian.py`:

```python
def test_render_writes_notes_from_store(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(
        vault,
        "calibre",
        [
            store.BookRow(
                title="The Deluge", authors=["Adam Tooze"], format="ebook", isbn="9780141032184"
            ),
        ],
    )
    store.merge(vault)
    bid = "The Deluge - Adam Tooze"
    store.write_highlights(
        vault,
        bid,
        "kobo",
        [
            store.HighlightRow(
                source="kobo",
                annotation_id="1",
                text="an insight",
                location="42",
                location_kind="percent",
            ),
        ],
    )
    stats = R.render(vault)
    note = vault / "Books" / f"{bid}.md"
    assert note.is_file()
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert post["title"] == "The Deluge"
    assert post["highlighted"] is True
    assert "an insight" in post.content
    assert stats == {"notes": 1, "highlights": 1, "reviews": 0}


def test_render_empty_catalog_is_noop(tmp_path):
    assert R.render(tmp_path / "vault") == {"notes": 0, "highlights": 0, "reviews": 0}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_render_obsidian.py -k "render_writes or render_empty" -q`
Expected: FAIL with `AttributeError: ... 'render'`.

- [ ] **Step 3: Write minimal implementation**

Append to `books/render_obsidian.py` (add `from books import store` to the imports at the top):

```python
def render(vault: Path) -> dict:
    """Render every book in ``books.csv`` (+ its highlights) into ``Books/``."""
    stats = {"notes": 0, "highlights": 0, "reviews": 0}
    for row in store.read_books_csv(vault):
        if not row.book_id:
            continue
        highlights = store.read_highlights(vault, row.book_id)
        render_note(vault, row, highlights)
        stats["notes"] += 1
        stats["highlights"] += len(highlights)
        if (row.review or "").strip():
            stats["reviews"] += 1
    return stats
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_render_obsidian.py -k "render_writes or render_empty" -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add books/render_obsidian.py tests/test_render_obsidian.py
git commit -m "feat(render): render(vault) iterates books.csv into Books/ notes"
```

---

## Task 9: The `render` CLI command

**Files:**
- Modify: `books/render_obsidian.py`
- Modify: `books/cli.py`
- Test: `tests/test_render_obsidian.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_render_obsidian.py`:

```python
from typer.testing import CliRunner

from books.cli import app


def test_render_command_renders_vault(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "calibre", [store.BookRow(title="X", authors=["A"], format="ebook")])
    store.merge(vault)
    result = CliRunner().invoke(app, ["render", "--output", str(vault)])
    assert result.exit_code == 0, result.output
    assert (vault / "Books" / "X - A.md").is_file()


def test_render_command_errors_without_books_csv(tmp_path):
    result = CliRunner().invoke(app, ["render", "--output", str(tmp_path / "vault")])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_render_obsidian.py -k "render_command" -q`
Expected: FAIL — `render` is not a registered command, so `exit_code` is non-zero for the first test (`result.output` shows "No such command 'render'").

- [ ] **Step 3: Write minimal implementation**

Append to `books/render_obsidian.py` (add `import typer` and `from books import config, store` — merge with the existing `from books import store` line so it reads `from books import config, store`):

```python
def render_command(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the "
        "current directory.",
    ),
) -> None:
    """Render the CSV store into Obsidian book notes under Books/.

    Reads <vault>/Data/books.csv and <vault>/Data/Highlights/<book-id>.csv (built
    by the importers + merge) and writes one flat note per book. Frontmatter is
    written authoritatively from the store; your hand-edited `topics` and any
    `## Review` section are preserved, as is note body outside the managed
    Highlights markers.
    """
    vault = config.resolve_vault(output)
    if not store.books_csv_path(vault).is_file():
        raise typer.BadParameter(
            f"no books.csv under {store.data_dir(vault)} — run the importers + merge first",
            param_hint="--output",
        )
    vault.mkdir(parents=True, exist_ok=True)
    stats = render(vault)
    typer.echo(
        f"Done. {stats['notes']} notes, {stats['highlights']} highlights, "
        f"{stats['reviews']} reviews.\nOutput: {vault}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("render")(render_command)


def main() -> None:
    """Standalone entry point so a shim script keeps working on its own."""
    typer.run(render_command)


if __name__ == "__main__":
    main()
```

Then wire it into `books/cli.py`. Add `render_obsidian` to both the import block and `CAPABILITIES` (keep alphabetical order):

```python
from books import (
    audible_obsidian,
    calibre_obsidian,
    covers,
    goodreads_obsidian,
    highlighted_obsidian,
    kobo_export,
    readwise_obsidian,
    render_obsidian,
    sync,
)

# Modules that expose a register(app) function. Add new capabilities here.
CAPABILITIES = (
    audible_obsidian,
    calibre_obsidian,
    covers,
    goodreads_obsidian,
    highlighted_obsidian,
    kobo_export,
    readwise_obsidian,
    render_obsidian,
    sync,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_render_obsidian.py -k "render_command" -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add books/render_obsidian.py books/cli.py tests/test_render_obsidian.py
git commit -m "feat(render): add the render CLI command"
```

---

## Task 10: Full-suite check + lint

**Files:**
- (none — verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `uv run pytest -q`
Expected: PASS for everything except the pre-existing `tests/test_audible_client.py::test_annotations_returns_empty_on_404` (optional `[audible]` extra's `httpx`, unrelated). No new failures.

- [ ] **Step 2: Run ruff over the new/changed modules**

Run: `uv run ruff check books/render_obsidian.py books/highlights.py books/store.py books/cli.py tests/test_render_obsidian.py`
Expected: no errors (fix any import-order/unused-import issues ruff reports, then re-run).

- [ ] **Step 3: Commit any lint fixes**

```bash
git add books/render_obsidian.py books/highlights.py books/store.py books/cli.py tests/test_render_obsidian.py
git commit -m "style(render): ruff clean"
```

(If nothing changed, skip the commit.)

---

## Self-review notes (author)

- **Spec coverage:**
  - *The Obsidian renderer* (`render_obsidian.py`) — Tasks 4–9.
  - *Frontmatter authoritative-except-topics/highlighted/reviewed* — Task 5 (`book_frontmatter`).
  - *Cover embed via existing helpers* — Task 6 (`_cover_value` + `ensure_top_embed`, `COVER_WIDTH`).
  - *`## Review` write-once* — Task 6 (`ensure_section`).
  - *`## Highlights` marker-wrapped + last-render-wins + body preserved* — Tasks 6–7 (`render_marked_section`).
  - *Source attribution when mixed-source / no header when single-source* — Task 2 (`render_highlights` grouping) + Task 3 (source propagation).
  - *python-frontmatter + ruamel.yaml* — Tasks 1, 4.
  - *`type` set by renderer; `topics` never written; `highlighted`/`reviewed` derived* — Task 5.
  - *Renderer testing: idempotent re-render, topics untouched, review write-once, derived flags, body preserved* — Tasks 6–8.
- **Deliberate deviations (approved):** `source`/`sources` key dropped entirely (design's `source:` retired, `sources` idea dropped); the byte-match-old-markdown migration check is replaced by an idempotency invariant because ruamel reformats existing frontmatter on first render.
- **Deferred to later plans (by design):** importers → CSV writers, `sync` two-phase pipeline, standalone `books merge`, and the markdown→CSV highlight backfill (Plan C / migration).
- **Type consistency:** the renderer consumes `store.BookRow` / `store.HighlightRow` / `store.read_books_csv` / `store.read_highlights` / `store.row_to_highlight` exactly as Plan A defines them; `Highlight.source` (added in Task 2) is set by `row_to_highlight` (Task 3) and read by `render_highlights` (Task 2). `NOTE_PROPERTY_ORDER` derives from `obsidian.BOOK_PROPERTY_ORDER`, so it tracks any schema change automatically.
- **Idempotency reasoning:** the only external-derived frontmatter value is `topics` (round-trips through python-frontmatter read → ruamel write unchanged); all other keys are recomputed from the row each run, and the body helpers (`ensure_top_embed`/`ensure_section`/`render_marked_section`) are each idempotent — so render-twice yields identical bytes (Task 7 asserts this).
</content>
</invoke>
