# Kobo → Obsidian Highlights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Obsidian output mode to `books kobo` that writes highlights as a per-book `Highlights.md` (Obsidian callouts) embedded into the canonical book note, built on a new source-agnostic highlights layer reusable by future apps.

**Architecture:** A new `booktools/highlights.py` owns a source-neutral `Highlight` model plus anchor/rendering logic. Note-orchestration (matching, find-or-create, leaf+embed writing) is promoted into `booktools/obsidian.py` so both Goodreads reviews and Kobo highlights use it. `kobo_export.py` only reads SQLite and maps rows into the shared model.

**Tech Stack:** Python 3, stdlib only (sqlite3, dataclasses, re), Typer for the CLI, pytest for tests.

---

## File Structure

- **Create** `booktools/highlights.py` — `Highlight` dataclass, `build_anchors`, `render_highlights`.
- **Modify** `booktools/obsidian.py` — add `ensure_embed_section`, `BookRef`, `VaultIndex` (moves `build_index` here), `write_leaf_with_embed`.
- **Modify** `booktools/goodreads_obsidian.py` — refactor `convert` onto `VaultIndex`/`write_leaf_with_embed`; write `Review.md` (generic) with a `## Review` embed.
- **Modify** `booktools/kobo_export.py` — add `--obsidian` mode, row→`Highlight`/`BookRef` mapping, `export_obsidian`.
- **Modify** `README.md` — document the Kobo Obsidian mode + the optional seamless-embed CSS snippet.
- **Create** `tests/test_highlights.py` — unit tests for the shared highlights layer.
- **Modify** `tests/test_obsidian.py` — tests for `ensure_embed_section`, `VaultIndex`, `write_leaf_with_embed`.
- **Modify** `tests/test_goodreads_obsidian.py` — update review-file naming assertions.
- **Create** `tests/test_kobo_export.py` — Kobo row mapping + `export_obsidian` end-to-end against a fake sqlite DB.
- **Modify** `tests/test_cli.py` — `kobo --obsidian` end-to-end.

---

## Task 1: `Highlight` model + anchor building

**Files:**
- Create: `booktools/highlights.py`
- Test: `tests/test_highlights.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_highlights.py`:

```python
"""Unit tests for the source-agnostic highlights layer."""

from booktools import highlights as hl


def test_build_anchors_chapter_and_location():
    hs = [hl.Highlight(text="a", chapter_index=2, block="17", segment="5")]
    assert hl.build_anchors(hs) == ["ch2-b17-5"]


def test_build_anchors_missing_chapter_drops_prefix():
    hs = [hl.Highlight(text="a", block="17", segment="5")]
    assert hl.build_anchors(hs) == ["b17-5"]


def test_build_anchors_missing_location_uses_counter():
    hs = [
        hl.Highlight(text="a", chapter_index=2),
        hl.Highlight(text="b", chapter_index=2),
    ]
    assert hl.build_anchors(hs) == ["ch2-hl1", "ch2-hl2"]


def test_build_anchors_dedupes_collisions():
    hs = [
        hl.Highlight(text="a", chapter_index=2, block="17", segment="5"),
        hl.Highlight(text="b", chapter_index=2, block="17", segment="5"),
    ]
    assert hl.build_anchors(hs) == ["ch2-b17-5", "ch2-b17-5-2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_highlights.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'booktools.highlights'`.

- [ ] **Step 3: Write minimal implementation**

Create `booktools/highlights.py`:

```python
"""Source-agnostic highlight model + Obsidian rendering.

A *Highlight* is a reading annotation independent of the app it came from (Kobo,
Kindle, Apple Books, ...). Each source maps its own storage into this model; all
Obsidian formatting (callouts, stable block anchors) lives here so every source
shares one output format.

Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Highlight:
    text: str
    note: str | None = None
    chapter_index: int | None = None
    chapter_title: str | None = None
    progress: float | None = None      # 0.0-1.0 within the chapter
    block: str | None = None           # stable location component (e.g. KoboSpan block)
    segment: str | None = None         # secondary location component
    date: str | None = None


def build_anchors(highlights: list[Highlight]) -> list[str]:
    """Compute a unique Obsidian block-id per highlight.

    Base is ``ch<index>`` (when known) joined with the location ``b<block>-<seg>``.
    When no location is available a per-list counter ``hl<n>`` is used instead.
    Collisions get a ``-2``, ``-3`` suffix so ids are always unique in the file.
    """
    seen: set[str] = set()
    anchors: list[str] = []
    for i, h in enumerate(highlights, start=1):
        chapter = f"ch{h.chapter_index}" if h.chapter_index is not None else ""
        if h.block:
            loc = f"b{h.block}" + (f"-{h.segment}" if h.segment else "")
        else:
            loc = f"hl{i}"
        base = "-".join(p for p in (chapter, loc) if p)
        anchor = base
        n = 2
        while anchor in seen:
            anchor = f"{base}-{n}"
            n += 1
        seen.add(anchor)
        anchors.append(anchor)
    return anchors
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_highlights.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add booktools/highlights.py tests/test_highlights.py
git commit -m "Add source-agnostic Highlight model + anchor builder"
```

---

## Task 2: `render_highlights` (callout rendering)

**Files:**
- Modify: `booktools/highlights.py`
- Test: `tests/test_highlights.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_highlights.py`:

```python
def test_render_single_highlight_no_note():
    hs = [hl.Highlight(text="A line", chapter_index=2, progress=0.42,
                       block="17", segment="5")]
    out = hl.render_highlights(hs)
    assert "> [!quote]+ ch. 2 · 42%" in out
    assert "> A line" in out
    assert "^ch2-b17-5" in out
    assert "[!note]" not in out  # no annotation -> no note callout


def test_render_highlight_with_note():
    hs = [hl.Highlight(text="A line", note="my thought", chapter_index=2,
                       progress=0.5, block="1", segment="0")]
    out = hl.render_highlights(hs)
    assert "> [!note]-" in out
    assert "> my thought" in out
    assert "^ch2-b1-0-note" in out


def test_render_multiline_text_prefixes_each_line():
    hs = [hl.Highlight(text="line one\nline two", chapter_index=1, block="3")]
    out = hl.render_highlights(hs)
    assert "> line one" in out
    assert "> line two" in out


def test_render_label_falls_back_to_chapter_title_then_percent():
    hs = [hl.Highlight(text="x", chapter_title="Intro", progress=0.1, block="2")]
    out = hl.render_highlights(hs)
    assert "> [!quote]+ Intro · 10%" in out
    hs2 = [hl.Highlight(text="y", progress=0.9, block="2")]
    assert "> [!quote]+ 90%" in hl.render_highlights(hs2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_highlights.py -v`
Expected: FAIL with `AttributeError: module 'booktools.highlights' has no attribute 'render_highlights'`.

- [ ] **Step 3: Write minimal implementation**

Append to `booktools/highlights.py`:

```python
def _label(h: Highlight) -> str:
    parts: list[str] = []
    if h.chapter_index is not None:
        parts.append(f"ch. {h.chapter_index}")
    elif h.chapter_title:
        parts.append(h.chapter_title)
    if h.progress is not None:
        parts.append(f"{round(h.progress * 100)}%")
    return " · ".join(parts)


def _callout(kind: str, title: str, body: str, expanded: bool) -> str:
    marker = "+" if expanded else "-"
    head = f"> [!{kind}]{marker}"
    if title:
        head += f" {title}"
    body_lines = "\n".join(f"> {ln}" if ln.strip() else ">"
                           for ln in body.split("\n"))
    return f"{head}\n{body_lines}"


def render_highlights(highlights: list[Highlight]) -> str:
    """Render an ordered list of highlights as an Obsidian ``Highlights.md`` body."""
    anchors = build_anchors(highlights)
    blocks: list[str] = []
    for h, anchor in zip(highlights, anchors):
        block = f"{_callout('quote', _label(h), h.text, expanded=True)}\n^{anchor}"
        if h.note and h.note.strip():
            note = _callout("note", "", h.note, expanded=False)
            block += f"\n\n{note}\n^{anchor}-note"
        blocks.append(block)
    return "\n\n".join(blocks) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_highlights.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add booktools/highlights.py tests/test_highlights.py
git commit -m "Render highlights as Obsidian quote/note callouts with anchors"
```

---

## Task 3: `ensure_embed_section` in the shared layer

**Files:**
- Modify: `booktools/obsidian.py` (add near the "Filesystem helpers" section)
- Test: `tests/test_obsidian.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_obsidian.py`:

```python
def test_ensure_embed_section_adds_when_absent():
    note = '---\ntype: book\n---\n\nBody.\n'
    out = ob.ensure_embed_section(note, "Highlights", "Highlights.md")
    assert "## Highlights" in out
    assert "![](Highlights.md)" in out
    assert "Body." in out


def test_ensure_embed_section_noop_when_present():
    note = '---\ntype: book\n---\n\n## Highlights\n![](Highlights.md)\n'
    assert ob.ensure_embed_section(note, "Highlights", "Highlights.md") == note
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_obsidian.py -k ensure_embed -v`
Expected: FAIL with `AttributeError: module 'booktools.obsidian' has no attribute 'ensure_embed_section'`.

- [ ] **Step 3: Write minimal implementation**

Add to `booktools/obsidian.py` after `write_stub` (in the Filesystem helpers section):

```python
def ensure_embed_section(note_text: str, heading: str, target: str) -> str:
    """Append a '## <heading>' section embedding *target* iff not already present.

    Uses a relative Markdown embed (``![](target)``) so generic leaf filenames
    (Highlights.md/Review.md) resolve against the note's own folder. The existing
    body is otherwise untouched.
    """
    if re.search(rf"(?m)^##\s+{re.escape(heading)}\s*$", note_text):
        return note_text
    sep = "" if note_text.endswith("\n") else "\n"
    return f"{note_text}{sep}\n## {heading}\n![]({target})\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_obsidian.py -k ensure_embed -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add booktools/obsidian.py tests/test_obsidian.py
git commit -m "Add ensure_embed_section shared helper"
```

---

## Task 4: `BookRef`, `VaultIndex`, `write_leaf_with_embed` (promote note orchestration)

**Files:**
- Modify: `booktools/obsidian.py` (move `build_index` here from goodreads; add `BookRef`, `VaultIndex`, `write_leaf_with_embed`)
- Test: `tests/test_obsidian.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_obsidian.py`:

```python
def test_vaultindex_creates_new_note_with_stub(tmp_path):
    idx = ob.VaultIndex(tmp_path)
    ref = ob.BookRef(title="Napoleon: A Life", authors=["Andrew Roberts"], isbn=None)
    note, created = idx.find_or_create(ref)
    assert created is True
    assert note == tmp_path / "Andrew Roberts" / "Napoleon_ A Life" / "Napoleon_ A Life.md"
    text = note.read_text()
    assert "type: book" in text
    assert 'title: "Napoleon: A Life"' in text
    assert "[[Andrew Roberts]]" in text


def test_vaultindex_matches_existing_by_title_author(tmp_path):
    book_dir = tmp_path / "Andrew Roberts" / "Napoleon A Life"
    book_dir.mkdir(parents=True)
    note = book_dir / "Napoleon A Life.md"
    note.write_text(
        '---\ntype: book\ntitle: "Napoleon - A Life"\n'
        'authors: ["[[Andrew Roberts]]"]\n---\nBody.\n', encoding="utf-8")
    idx = ob.VaultIndex(tmp_path)
    found, created = idx.find_or_create(
        ob.BookRef(title="Napoleon: A Life", authors=["Andrew Roberts"], isbn=None))
    assert created is False
    assert found == note


def test_write_leaf_with_embed_overwrites_and_embeds(tmp_path):
    note = tmp_path / "Book" / "Book.md"
    note.parent.mkdir(parents=True)
    note.write_text('---\ntype: book\n---\n\nBody.\n', encoding="utf-8")
    wrote = ob.write_leaf_with_embed(note, "Highlights.md", "content v1\n", "Highlights")
    assert wrote is True
    assert (note.parent / "Highlights.md").read_text() == "content v1\n"
    assert "![](Highlights.md)" in note.read_text()
    # Second call overwrites the leaf but does not duplicate the embed.
    ob.write_leaf_with_embed(note, "Highlights.md", "content v2\n", "Highlights")
    assert (note.parent / "Highlights.md").read_text() == "content v2\n"
    assert note.read_text().count("## Highlights") == 1


def test_write_leaf_with_embed_no_overwrite_keeps_existing(tmp_path):
    note = tmp_path / "Book" / "Book.md"
    note.parent.mkdir(parents=True)
    note.write_text('---\ntype: book\n---\n', encoding="utf-8")
    (note.parent / "Review.md").write_text("original\n", encoding="utf-8")
    wrote = ob.write_leaf_with_embed(note, "Review.md", "new\n", "Review", overwrite=False)
    assert wrote is False
    assert (note.parent / "Review.md").read_text() == "original\n"  # not clobbered
    assert "![](Review.md)" in note.read_text()  # embed still ensured
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_obsidian.py -k "vaultindex or write_leaf" -v`
Expected: FAIL with `AttributeError: module 'booktools.obsidian' has no attribute 'VaultIndex'`.

- [ ] **Step 3: Write minimal implementation**

Add to `booktools/obsidian.py`. First, near the top add a dataclass import:

```python
from dataclasses import dataclass, field
```

Add this new section after the "Frontmatter merge" section:

```python
# --- Book-note orchestration (shared by importers) --------------------------

@dataclass
class BookRef:
    """Source-neutral book identity used for matching and note creation."""
    title: str
    authors: list[str] = field(default_factory=list)
    isbn: str | None = None


def build_index(vault: Path) -> tuple[dict[str, Path], dict[tuple, Path]]:
    """Index existing book notes by normalized ISBN and (title, author)."""
    by_isbn: dict[str, Path] = {}
    by_title_author: dict[tuple, Path] = {}
    for md in vault.rglob("*.md"):
        if md.parent.name in ("Authors", "Genres"):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = frontmatter_values(text)
        if unquote(fm.get("type", "")) != "book":
            continue
        isbn = norm_isbn(unquote(fm.get("isbn", "")))
        if isbn:
            by_isbn.setdefault(isbn, md)
        title = unquote(fm.get("title", ""))
        authors = extract_wikilinks(fm.get("authors", ""))
        if title and authors:
            by_title_author.setdefault((norm_title(title), author_key(authors[0])), md)
    return by_isbn, by_title_author


class VaultIndex:
    """Match books to existing notes, creating stub notes when absent."""

    def __init__(self, vault: Path) -> None:
        self.vault = vault
        self.by_isbn, self.by_ta = build_index(vault)

    def _match(self, ref: BookRef) -> Path | None:
        isbn = norm_isbn(ref.isbn)
        if isbn and isbn in self.by_isbn:
            return self.by_isbn[isbn]
        if ref.title and ref.authors:
            key = (norm_title(ref.title), author_key(ref.authors[0]))
            if key in self.by_ta:
                return self.by_ta[key]
        return None

    def _register(self, ref: BookRef, note: Path) -> None:
        isbn = norm_isbn(ref.isbn)
        if isbn:
            self.by_isbn.setdefault(isbn, note)
        if ref.title and ref.authors:
            self.by_ta.setdefault(
                (norm_title(ref.title), author_key(ref.authors[0])), note)

    def find_or_create(self, ref: BookRef) -> tuple[Path, bool]:
        """Return (note_path, created). Creates a stub note+folder when absent."""
        note = self._match(ref)
        created = note is None
        if created:
            author = ref.authors[0] if ref.authors else "Unknown Author"
            folder = self.vault / safe_filename(author) / safe_filename(ref.title)
            folder.mkdir(parents=True, exist_ok=True)
            note = folder / f"{safe_filename(ref.title)}.md"
            stub = update_frontmatter("---\ntype: book\n---\n", {
                "title": yaml_quote(ref.title) if ref.title else "",
                "authors": link_list(ref.authors) if ref.authors else "",
            })
            note.write_text(stub, encoding="utf-8")
        self._register(ref, note)
        return note, created


def write_leaf_with_embed(
    note_path: Path, leaf_name: str, content: str, heading: str,
    overwrite: bool = True,
) -> bool:
    """Write ``<folder>/<leaf_name>`` and ensure a '## heading' embed in the note.

    With ``overwrite=False`` an existing leaf is left untouched (used for reviews);
    the embed section is still ensured either way. Returns True if the leaf was
    written.
    """
    leaf = note_path.parent / leaf_name
    wrote = False
    if overwrite or not leaf.exists():
        leaf.parent.mkdir(parents=True, exist_ok=True)
        leaf.write_text(content, encoding="utf-8")
        wrote = True
    text = note_path.read_text(encoding="utf-8")
    updated = ensure_embed_section(text, heading, leaf_name)
    if updated != text:
        note_path.write_text(updated, encoding="utf-8")
    return wrote
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_obsidian.py -v`
Expected: PASS (all, including the 4 new tests).

- [ ] **Step 5: Commit**

```bash
git add booktools/obsidian.py tests/test_obsidian.py
git commit -m "Promote book-note matching + leaf/embed writing to shared layer"
```

---

## Task 5: Refactor Goodreads onto shared helpers + `Review.md` embed

**Files:**
- Modify: `booktools/goodreads_obsidian.py:141-263` (remove local `build_index`/`match_note`, rewrite `convert`)
- Modify: `tests/test_goodreads_obsidian.py:120-126` (review filename)
- Test: `tests/test_goodreads_obsidian.py`

- [ ] **Step 1: Update the failing test**

In `tests/test_goodreads_obsidian.py`, replace `test_convert_writes_review_file` (lines ~120-126) with:

```python
def test_convert_writes_review_file(tmp_path):
    out = tmp_path / "Obsidian"
    gr.convert(write_csv(tmp_path), out)
    reviews = list(out.rglob("Review.md"))
    assert len(reviews) == 1
    text = reviews[0].read_text()
    assert "Great book." in text and "Loved it." in text
    # The book note embeds the review.
    note = out / "Andrew Roberts" / "Napoleon_ A Life" / "Napoleon_ A Life.md"
    assert "![](Review.md)" in note.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_goodreads_obsidian.py::test_convert_writes_review_file -v`
Expected: FAIL (still writes `<Title> - Review.md`, no `Review.md`, no embed).

- [ ] **Step 3: Rewrite the implementation**

In `booktools/goodreads_obsidian.py`, update imports (the `from booktools.obsidian import (...)` block) to add `BookRef`, `VaultIndex`, `write_leaf_with_embed` and remove now-unused `write_if_absent`:

```python
from booktools.obsidian import (
    BOOK_PROPERTY_ORDER,
    BookRef,
    VaultIndex,
    author_key,
    html_to_markdown,
    link_list,
    norm_isbn,
    norm_title,
    plain_list,
    update_frontmatter,
    write_leaf_with_embed,
    write_stub,
    yaml_quote,
)
```

Delete the local `build_index` and `match_note` functions (the whole
`# --- Matching against an existing vault ---` section, lines ~139-173).

Replace `convert` (lines ~223-263) with:

```python
def convert(csv_path: Path, output: Path, shelf: str = "read") -> dict:
    stats = {"created": 0, "merged": 0, "reviews": 0, "skipped": 0, "authors": set()}
    index = VaultIndex(output)
    authors_dir = output / "Authors"

    for book in parse_csv(csv_path):
        if shelf != "all" and (book.exclusive_shelf or "") != shelf:
            stats["skipped"] += 1
            continue
        if not book.title or not book.authors:
            stats["skipped"] += 1
            continue

        ref = BookRef(title=book.title, authors=book.authors,
                      isbn=book.isbn13 or book.isbn)
        note_path, created = index.find_or_create(ref)
        stats["created" if created else "merged"] += 1

        base = note_path.read_text(encoding="utf-8")
        note_path.write_text(
            update_frontmatter(base, _goodreads_updates(book)), encoding="utf-8")

        for author in book.authors:
            write_stub(authors_dir, author, "author")
            stats["authors"].add(author)

        review = _review_markdown(book)
        if review and write_leaf_with_embed(
                note_path, "Review.md", review, "Review", overwrite=False):
            stats["reviews"] += 1

    return stats
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_goodreads_obsidian.py -v`
Expected: PASS (all, including idempotency and merge tests).

- [ ] **Step 5: Commit**

```bash
git add booktools/goodreads_obsidian.py tests/test_goodreads_obsidian.py
git commit -m "Refactor Goodreads onto shared VaultIndex; generic Review.md + embed"
```

---

## Task 6: Kobo Obsidian mode

**Files:**
- Modify: `booktools/kobo_export.py` (add ISBN to `QUERY`, add `row_to_highlight`, `export_obsidian`, `--obsidian` option)
- Test: `tests/test_kobo_export.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_kobo_export.py`:

```python
"""Tests for the Kobo exporter (Obsidian mode + row mapping)."""

import sqlite3
from pathlib import Path

from booktools import kobo_export as ke


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE content (
            ContentID TEXT, ContentType INTEGER, Title TEXT, BookTitle TEXT,
            Attribution TEXT, VolumeIndex INTEGER, ISBN TEXT
        );
        CREATE TABLE Bookmark (
            VolumeID TEXT, ContentID TEXT, ChapterProgress REAL, Text TEXT,
            Annotation TEXT, DateCreated TEXT, StartContainerPath TEXT, Hidden TEXT
        );
        """
    )
    # One book, one chapter (ContentType 899), two highlights (one annotated).
    conn.execute("INSERT INTO content VALUES (?,?,?,?,?,?,?)",
                 ("book1", 6, "The Great Gatsby", None, "F. Scott Fitzgerald", None, "9780743273565"))
    conn.execute("INSERT INTO content VALUES (?,?,?,?,?,?,?)",
                 ("book1-ch2", 899, "Chapter 2", None, None, 2, None))
    conn.execute("INSERT INTO Bookmark VALUES (?,?,?,?,?,?,?,?)",
                 ("book1", "book1-ch2", 0.42, "First highlight", "my note",
                  "2026-07-01", r"span#kobo\.17\.5", "false"))
    conn.execute("INSERT INTO Bookmark VALUES (?,?,?,?,?,?,?,?)",
                 ("book1", "book1-ch2", 0.55, "Second highlight", None,
                  "2026-07-02", r"span#kobo\.20\.1", "false"))
    conn.commit()
    conn.close()


def test_row_to_highlight_maps_fields():
    class R(dict):
        def __getitem__(self, k):
            return dict.get(self, k)
    row = R(chapter_index=2, chapter="Chapter 2", chapter_progress=0.42,
            container_path=r"span#kobo\.17\.5", highlight="Hi", note="note",
            date_created="2026-07-01")
    h = ke.row_to_highlight(row)
    assert h.text == "Hi" and h.note == "note"
    assert h.chapter_index == 2 and h.block == "17" and h.segment == "5"
    assert abs(h.progress - 0.42) < 1e-9


def test_export_obsidian_writes_highlights_and_embed(tmp_path):
    db = tmp_path / "KoboReader.sqlite"
    _make_db(db)
    vault = tmp_path / "Obsidian"
    stats = ke.export_obsidian(db, vault)
    assert stats["books"] == 1 and stats["entries"] == 2

    folder = vault / "F. Scott Fitzgerald" / "The Great Gatsby"
    highlights = (folder / "Highlights.md").read_text()
    assert "> [!quote]+ ch. 2 · 42%" in highlights
    assert "^ch2-b17-5" in highlights
    assert "> [!note]-" in highlights          # first highlight has an annotation
    assert highlights.count("[!note]") == 1    # second has none

    note = (folder / "The Great Gatsby.md").read_text()
    assert "![](Highlights.md)" in note


def test_export_obsidian_regenerates_highlights_wholesale(tmp_path):
    db = tmp_path / "KoboReader.sqlite"
    _make_db(db)
    vault = tmp_path / "Obsidian"
    ke.export_obsidian(db, vault)
    note_path = vault / "F. Scott Fitzgerald" / "The Great Gatsby" / "The Great Gatsby.md"
    # Simulate a hand edit to the book note body; it must survive re-export.
    note_path.write_text(note_path.read_text() + "\nMy own paragraph.\n", encoding="utf-8")
    ke.export_obsidian(db, vault)
    assert "My own paragraph." in note_path.read_text()
    assert note_path.read_text().count("## Highlights") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_kobo_export.py -v`
Expected: FAIL with `AttributeError: module 'booktools.kobo_export' has no attribute 'row_to_highlight'`.

- [ ] **Step 3: Write the implementation**

In `booktools/kobo_export.py`:

3a. Add imports near the top (after `from booktools import resolve_path`):

```python
from booktools.highlights import Highlight, render_highlights
from booktools.obsidian import BookRef, VaultIndex, write_leaf_with_embed, write_stub
```

3b. In `QUERY`, add an ISBN column to the final SELECT so books can match by ISBN. Change the select list to include it (add after the `book_title`/`author` lines):

```sql
    COALESCE(book.ISBN, '')                  AS isbn,
```

(Place it right after `COALESCE(book.Attribution, '') AS author,`. The CSV writer selects columns by name, so this extra column does not affect CSV output.)

3c. Add these functions after `parse_container`:

```python
def row_to_highlight(row) -> Highlight:
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


def export_obsidian(db_path: Path, vault: Path) -> dict:
    """Export Kobo highlights into an Obsidian vault (folder-per-book).

    Writes a per-book Highlights.md and embeds it in the canonical note. Returns
    {"books": int, "entries": int}. Raises FileNotFoundError if the db is missing.
    """
    if not db_path.is_file():
        raise FileNotFoundError(db_path)

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(QUERY).fetchall()
    finally:
        conn.close()

    vault.mkdir(parents=True, exist_ok=True)
    index = VaultIndex(vault)
    authors_dir = vault / "Authors"

    # Group rows by book, preserving the query's reading order.
    books: dict[str, list] = {}
    for r in rows:
        books.setdefault(r["book_title"] or "Untitled", []).append(r)

    entries = 0
    for title, book_rows in books.items():
        author = (book_rows[0]["author"] or "").strip()
        authors = [author] if author else []
        isbn = (book_rows[0]["isbn"] or "").strip() or None
        ref = BookRef(title=title, authors=authors, isbn=isbn)

        note_path, _ = index.find_or_create(ref)
        highlights = [row_to_highlight(r) for r in book_rows]
        write_leaf_with_embed(
            note_path, "Highlights.md", render_highlights(highlights), "Highlights")
        for a in authors:
            write_stub(authors_dir, a, "author")
        entries += len(highlights)

    return {"books": len(books), "entries": entries}
```

3d. Add the `--obsidian` option to `kobo_export` and branch on it. Change the signature to add (after `csv_out`):

```python
    obsidian: bool = typer.Option(
        False, "--obsidian",
        help="Write highlights into an Obsidian vault (folder-per-book) instead "
             "of CSV/zip. In this mode --output is the vault directory "
             "[default: ./Obsidian].",
    ),
```

Change `output` to allow a mode-dependent default:

```python
    output: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Output path. CSV mode: a .zip [default: ./kobo_highlights.zip]. "
             "Obsidian mode: a vault directory [default: ./Obsidian]. "
             "Relative paths resolve against the current directory.",
    ),
```

Replace the body from the `if not csv_out:` block through the final echo with:

```python
    db_path = resolve_path(input_path or db or Path("KoboReader.sqlite"), Path.cwd())

    if obsidian:
        vault = resolve_path(output or Path("Obsidian"), Path.cwd())
        try:
            stats = export_obsidian(db_path, vault)
        except FileNotFoundError:
            raise typer.BadParameter(f"database not found: {db_path}", param_hint="DB")
        if stats["entries"] == 0:
            typer.echo("No highlights or notes found.")
            return
        typer.echo(
            f"Exported {stats['entries']} highlights from {stats['books']} book(s) "
            f"-> {vault}")
        return

    if not csv_out:
        raise typer.BadParameter(
            "CSV is currently the only non-Obsidian output mode; drop --no-csv "
            "or pass --obsidian.",
            param_hint="--csv",
        )

    out_path = resolve_path(output or Path("kobo_highlights.zip"), Path.cwd())
    try:
        stats = export(db_path, out_path)
    except FileNotFoundError:
        raise typer.BadParameter(f"database not found: {db_path}", param_hint="DB")

    if stats["entries"] == 0:
        typer.echo("No highlights or notes found.")
        return

    for fname, count in stats["files"]:
        typer.echo(f"  {fname}: {count} entries")
    typer.echo(
        f"\nExported {stats['entries']} entries from {stats['books']} book(s) "
        f"-> {out_path}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_kobo_export.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add booktools/kobo_export.py tests/test_kobo_export.py
git commit -m "Add Kobo Obsidian highlights export mode"
```

---

## Task 7: CLI end-to-end + README docs

**Files:**
- Modify: `tests/test_cli.py` (add kobo obsidian e2e; keep existing no-csv test valid)
- Modify: `README.md`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def _kobo_db(tmp_path: Path) -> Path:
    import sqlite3
    db = tmp_path / "KoboReader.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE content (
            ContentID TEXT, ContentType INTEGER, Title TEXT, BookTitle TEXT,
            Attribution TEXT, VolumeIndex INTEGER, ISBN TEXT);
        CREATE TABLE Bookmark (
            VolumeID TEXT, ContentID TEXT, ChapterProgress REAL, Text TEXT,
            Annotation TEXT, DateCreated TEXT, StartContainerPath TEXT, Hidden TEXT);
        """)
    conn.execute("INSERT INTO content VALUES (?,?,?,?,?,?,?)",
                 ("b1", 6, "Dune", None, "Frank Herbert", None, None))
    conn.execute("INSERT INTO content VALUES (?,?,?,?,?,?,?)",
                 ("b1-c1", 899, "One", None, None, 1, None))
    conn.execute("INSERT INTO Bookmark VALUES (?,?,?,?,?,?,?,?)",
                 ("b1", "b1-c1", 0.1, "Fear is the mind-killer", None,
                  "2026-07-01", r"span#kobo\.3\.0", "false"))
    conn.commit()
    conn.close()
    return db


def test_kobo_obsidian_end_to_end(tmp_path):
    db = _kobo_db(tmp_path)
    out = tmp_path / "Obsidian"
    result = runner.invoke(app, ["kobo", str(db), "--obsidian", "--output", str(out)])
    assert result.exit_code == 0, result.output
    note = out / "Frank Herbert" / "Dune" / "Dune.md"
    assert note.exists()
    assert "![](Highlights.md)" in note.read_text()
    assert "Fear is the mind-killer" in (note.parent / "Highlights.md").read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_kobo_obsidian_end_to_end -v`
Expected: FAIL before Task 6 is wired; after Task 6 it should PASS. If it fails here, confirm the `--obsidian` option is registered.

- [ ] **Step 3: Verify no implementation gaps**

No new production code needed (Task 6 wired the CLI). Run the full suite:

Run: `uv run pytest -q`
Expected: PASS (all tests).

- [ ] **Step 4: Update the README**

In `README.md`, under the Kobo section, add documentation for the Obsidian mode and the optional CSS snippet:

```markdown
### Kobo → Obsidian highlights

Export highlights into an Obsidian vault (folder-per-book) instead of CSV:

```bash
books kobo /path/to/KoboReader.sqlite --obsidian --output ~/Obsidian
```

For each book with highlights this writes `<Author>/<Title>/Highlights.md`
(Obsidian `[!quote]`/`[!note]` callouts with stable block anchors) and embeds it
into the book note via `![](Highlights.md)`.

**Optional: seamless embeds.** By default Obsidian wraps embeds in a bordered
box. To make `Highlights.md`/`Review.md` render as if written inline, add a CSS
snippet at `<vault>/.obsidian/snippets/seamless-embeds.css` and enable it under
**Settings → Appearance → CSS snippets**:

```css
.markdown-embed-title { display: none; }
.markdown-embed { border: none; padding: 0; margin: 0; }
.markdown-embed-link { display: none; }
```
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_cli.py README.md
git commit -m "Add kobo --obsidian CLI e2e test and README docs"
```

---

## Self-Review Notes

- **Spec coverage:** CLI `--obsidian` (T6/T7), folder layout reuse (T4/T6), `Highlights.md` format + anchors (T1/T2), KoboSpan mapping (T6), embed via relative Markdown link (T3), canonical note find-or-create (T4/T6), wholesale regeneration (T6 test), Goodreads `Review.md` + embed refactor (T5), source-agnostic `highlights.py` + `BookRef` (T1/T4), CSS documented (T7). All covered.
- **Type consistency:** `Highlight`, `BookRef`, `VaultIndex.find_or_create -> (Path, bool)`, `write_leaf_with_embed(..., overwrite=True) -> bool`, `render_highlights(list[Highlight]) -> str`, `row_to_highlight(row) -> Highlight`, `export_obsidian(db_path, vault) -> dict` used consistently across tasks.
- **Shim:** `scripts/kobo_export.py` calls `main()` unchanged; no edit needed.
```
