# Readwise → Obsidian Importer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `readwise` capability that imports a Readwise CSV export into an Obsidian vault, in the same shape as the existing `highlighted` importer.

**Architecture:** A new `books/readwise_obsidian.py` module (mirroring `highlighted_obsidian.py`) maps each CSV row into the shared `Highlight` model and writes a per-book `Highlights.md` embedded in the flat book note. Two small additive extensions to the shared layer support it: a `location_label` field on `Highlight` (for `p.`/`loc.` labels) and Amazon-ID matching in `VaultIndex`/`BookRef`.

**Tech Stack:** Python 3, stdlib `csv`, Typer, pytest. Run everything with `uv run`.

---

## File Structure

- **Modify** `books/highlights.py` — add `Highlight.location_label`; use it in `_label()`.
- **Modify** `books/obsidian.py` — add `norm_amazon()`, `BookRef.amazon`, index+match by amazon in `build_index`/`VaultIndex`.
- **Create** `books/readwise_obsidian.py` — the importer (parse, series parsing, row mapping, convert, CLI).
- **Modify** `books/cli.py` — register the module in `CAPABILITIES`.
- **Create** `scripts/readwise_obsidian.py` — standalone shim.
- **Modify** `tests/test_highlights.py` — cover `location_label` rendering.
- **Modify** `tests/test_obsidian.py` — cover amazon normalization + matching.
- **Create** `tests/test_readwise.py` — importer unit + round-trip tests.
- **Modify** `tests/test_cli.py` — include `readwise` in registration/help checks + end-to-end test.

Run the full suite at any point with: `uv run pytest -q`

---

## Task 1: `location_label` on the shared Highlight model

**Files:**
- Modify: `books/highlights.py`
- Test: `tests/test_highlights.py`

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/test_highlights.py`:

```python
def test_location_label_defaults_to_page_prefix():
    hs = [hl.Highlight(text="x", page="123")]
    assert "> [!quote]+ p. 123" in hl.render_highlights(hs)


def test_location_label_overrides_prefix():
    hs = [hl.Highlight(text="x", page="123", location_label="loc.")]
    out = hl.render_highlights(hs)
    assert "> [!quote]+ loc. 123" in out
    assert "p. 123" not in out


def test_location_label_ignored_without_page():
    hs = [hl.Highlight(text="x", location_label="loc.")]
    out = hl.render_highlights(hs)
    assert "loc." not in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_highlights.py::test_location_label_overrides_prefix -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'location_label'`

- [ ] **Step 3: Add the field**

In `books/highlights.py`, inside the `Highlight` dataclass, add the field
immediately after the `page` field (keep the existing comment style):

```python
page: str | None = None  # human page/location (physical books), e.g. "45-49"
location_label: str | None = None  # display prefix for `page`; defaults to "p." when None
date: str | None = None
```

- [ ] **Step 4: Use the field in `_label()`**

In `books/highlights.py`, in `_label()`, replace the page branch:

```python
    if h.page:
        parts.append(f"p. {h.page.replace('-', '–')}")
```

with:

```python
    if h.page:
        prefix = h.location_label or "p."
        parts.append(f"{prefix} {h.page.replace('-', '–')}")
```

- [ ] **Step 5: Run the highlights tests to verify they pass**

Run: `uv run pytest tests/test_highlights.py -q`
Expected: PASS (all, including the three new tests)

- [ ] **Step 6: Commit**

```bash
git add books/highlights.py tests/test_highlights.py
git commit -m "feat(highlights): add location_label prefix for page/location labels"
```

---

## Task 2: Amazon-ID normalization + matching in the shared layer

**Files:**
- Modify: `books/obsidian.py`
- Test: `tests/test_obsidian.py`

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/test_obsidian.py`:

```python
def test_norm_amazon_uppercases_and_strips():
    assert ob.norm_amazon(" b00inixpye ") == "B00INIXPYE"
    assert ob.norm_amazon("B00-INIX_PYE") == "B00INIXPYE"


def test_norm_amazon_empty_is_none():
    assert ob.norm_amazon("") is None
    assert ob.norm_amazon(None) is None


def test_vaultindex_matches_existing_note_by_amazon(tmp_path):
    vault = tmp_path / "Obsidian"
    books = vault / "Books"
    books.mkdir(parents=True)
    (books / "Stalin.md").write_text(
        '---\ntype: book\ntitle: "Stalin"\namazon: "B00INIXPYE"\n---\n\nBody.\n', encoding="utf-8"
    )
    index = ob.VaultIndex(vault)
    dest = index.find_or_create(
        ob.BookRef(title="Totally Different Title", authors=["Someone Else"], amazon="b00inixpye")
    )
    assert dest.created is False
    assert dest.note_path.name == "Stalin.md"
```

Confirm the test module imports the package as `ob`:

Run: `grep -n "import" tests/test_obsidian.py | head`
If it is imported under a different alias, use that alias in the new tests instead of `ob`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_obsidian.py::test_norm_amazon_uppercases_and_strips -v`
Expected: FAIL — `AttributeError: module 'books.obsidian' has no attribute 'norm_amazon'`

- [ ] **Step 3: Add `norm_amazon()`**

In `books/obsidian.py`, in the "Matching normalization" section, add after
`norm_isbn`:

```python
def norm_amazon(amazon: str | None) -> str | None:
    """Alphanumeric-only, uppercased Amazon id (ASIN); None if empty."""
    if not amazon:
        return None
    return re.sub(r"[^a-z0-9]", "", fold(amazon)).upper() or None
```

- [ ] **Step 4: Add `amazon` to `BookRef`**

In `books/obsidian.py`, extend the `BookRef` dataclass:

```python
@dataclass
class BookRef:
    """Source-neutral book identity used for matching and note creation."""

    title: str
    authors: list[str] = field(default_factory=list)
    isbn: str | None = None
    amazon: str | None = None
```

- [ ] **Step 5: Index existing notes by amazon in `build_index`**

In `books/obsidian.py`, change `build_index` to also return an amazon index.
Replace the function body with:

```python
def build_index(vault: Path) -> tuple[dict[str, Path], dict[tuple, Path], dict[str, Path]]:
    """Index existing flat book notes by normalized ISBN, (title, author), and amazon."""
    by_isbn: dict[str, Path] = {}
    by_title_author: dict[tuple, Path] = {}
    by_amazon: dict[str, Path] = {}
    books_dir = vault / BOOKS_DIRNAME
    if not books_dir.is_dir():
        return by_isbn, by_title_author, by_amazon
    for md in sorted(books_dir.glob("*.md")):
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
        amazon = norm_amazon(unquote(fm.get("amazon", "")))
        if amazon:
            by_amazon.setdefault(amazon, md)
        title = unquote(fm.get("title", ""))
        authors = extract_wikilinks(fm.get("authors", ""))
        if title and authors:
            by_title_author.setdefault((norm_title(title), author_key(authors[0])), md)
    return by_isbn, by_title_author, by_amazon
```

- [ ] **Step 6: Wire the amazon index into `VaultIndex`**

In `books/obsidian.py`, in `VaultIndex.__init__`, unpack the new tuple:

```python
def __init__(self, vault: Path) -> None:
    self.vault = vault
    self.by_isbn, self.by_ta, self.by_amazon = build_index(vault)
    books_dir = vault / BOOKS_DIRNAME
    self.used_stems: set[str] = (
        {p.stem.lower() for p in books_dir.glob("*.md")} if books_dir.is_dir() else set()
    )
```

In `_match`, try amazon right after ISBN:

```python
    def _match(self, ref: BookRef) -> Path | None:
        isbn = norm_isbn(ref.isbn)
        if isbn and isbn in self.by_isbn:
            return self.by_isbn[isbn]
        amazon = norm_amazon(ref.amazon)
        if amazon and amazon in self.by_amazon:
            return self.by_amazon[amazon]
        if ref.title and ref.authors:
            key = (norm_title(ref.title), author_key(ref.authors[0]))
            if key in self.by_ta:
                return self.by_ta[key]
        return None
```

In `_register`, register the amazon id too:

```python
def _register(self, ref: BookRef, note: Path) -> None:
    isbn = norm_isbn(ref.isbn)
    if isbn:
        self.by_isbn.setdefault(isbn, note)
    amazon = norm_amazon(ref.amazon)
    if amazon:
        self.by_amazon.setdefault(amazon, note)
    if ref.title and ref.authors:
        self.by_ta.setdefault((norm_title(ref.title), author_key(ref.authors[0])), note)
```

- [ ] **Step 7: Run the obsidian tests to verify they pass**

Run: `uv run pytest tests/test_obsidian.py -q`
Expected: PASS. If any pre-existing test calls `build_index` and unpacks two
values, update it to unpack three (`by_isbn, by_ta, by_amazon = build_index(...)`).

- [ ] **Step 8: Run the whole suite (guard against other build_index callers)**

Run: `uv run pytest -q`
Expected: PASS. `VaultIndex` is the only in-tree caller of `build_index`, but this
confirms nothing else unpacks the old 2-tuple.

- [ ] **Step 9: Commit**

```bash
git add books/obsidian.py tests/test_obsidian.py
git commit -m "feat(obsidian): match books by Amazon id (BookRef.amazon + VaultIndex)"
```

---

## Task 3: Series-suffix parsing helper

**Files:**
- Create: `books/readwise_obsidian.py`
- Test: `tests/test_readwise.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_readwise.py`:

```python
"""Tests for the Readwise -> Obsidian importer."""

from pathlib import Path

from books import readwise_obsidian as rw


def test_split_series_extracts_name_and_index():
    title, series, index = rw.split_series(
        "Stalin: Volume I: Paradoxes of Power, 1878-1928 (Stalin #1)"
    )
    assert title == "Stalin: Volume I: Paradoxes of Power, 1878-1928"
    assert series == "Stalin"
    assert index == "1"


def test_split_series_decimal_index():
    title, series, index = rw.split_series("Some Book (Saga #2.5)")
    assert title == "Some Book"
    assert series == "Saga"
    assert index == "2.5"


def test_split_series_no_suffix_is_verbatim():
    title, series, index = rw.split_series("The Landscape of History")
    assert title == "The Landscape of History"
    assert series is None
    assert index is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_readwise.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'books.readwise_obsidian'`

- [ ] **Step 3: Create the module skeleton with `split_series`**

Create `books/readwise_obsidian.py`:

```python
#!/usr/bin/env python3
"""Convert a Readwise CSV export into an Obsidian book vault.

Readwise exports one row per highlight with columns: Highlight, Book Title,
Book Author, Amazon Book ID, Note, Color, Tags, Location Type, Location,
Highlighted at, Document tags. Each row maps into the shared source-agnostic
Highlight model; per book a "Highlights.md" is written under
"Exports/<Author>/<Title>/" and embedded into the flat note under a
"## Highlights" heading. Books are matched to existing notes by Amazon id, then
by a strict Author/Title comparison (using a title with any "(Series #N)" suffix
removed), so highlights accumulate alongside Calibre/Goodreads data without
clobbering.

Standard library only.
"""

from __future__ import annotations

import csv as _csv
import re
from pathlib import Path

import typer

from books import resolve_path
from books.highlights import Highlight, render_highlights, sanitize_tag
from books.obsidian import (
    BookRef,
    VaultIndex,
    link_list,
    plain_list,
    update_frontmatter,
    with_source,
    write_leaf_with_embed,
    write_stub,
    yaml_quote,
)

# Trailing "(Series #N)" or "(Series #N.M)" suffix on a Readwise book title.
_SERIES_RE = re.compile(r"\s*\(([^()]+?)\s+#(\d+(?:\.\d+)?)\)\s*$")


def split_series(title: str) -> tuple[str, str | None, str | None]:
    """Split a trailing "(Series #N)" off *title*.

    Returns (clean_title, series_name, series_index). When no suffix is present
    the title is returned verbatim with (None, None) for the series fields.
    """
    m = _SERIES_RE.search(title or "")
    if not m:
        return (title or "").strip(), None, None
    clean = (title[: m.start()]).strip()
    return clean, m.group(1).strip(), m.group(2).strip()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_readwise.py -q`
Expected: PASS (three tests)

- [ ] **Step 5: Commit**

```bash
git add books/readwise_obsidian.py tests/test_readwise.py
git commit -m "feat(readwise): add split_series title/series parser"
```

---

## Task 4: Row → Highlight mapping (tags + type-aware location)

**Files:**
- Modify: `books/readwise_obsidian.py`
- Test: `tests/test_readwise.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_readwise.py`:

```python
def test_row_to_highlight_page_location():
    h = rw.row_to_highlight(
        {
            "Highlight": "A passage",
            "Note": "my note",
            "Location Type": "page",
            "Location": "3",
            "Highlighted at": "2026-07-17 14:00:25.470174+00:00",
            "Tags": "",
        }
    )
    assert h.text == "A passage"
    assert h.note == "my note"
    assert h.page == "3"
    assert h.location_label is None
    assert h.date == "2026-07-17 14:00:25.470174+00:00"


def test_row_to_highlight_kindle_location():
    h = rw.row_to_highlight({"Highlight": "x", "Location Type": "location", "Location": "1234"})
    assert h.page == "1234"
    assert h.location_label == "loc."


def test_row_to_highlight_order_has_no_page():
    h = rw.row_to_highlight({"Highlight": "x", "Location Type": "order", "Location": "7"})
    assert h.page is None
    assert h.location_label is None


def test_row_to_highlight_blank_note_is_none():
    h = rw.row_to_highlight(
        {"Highlight": "x", "Note": "", "Location Type": "page", "Location": "1"}
    )
    assert h.note is None


def test_row_to_highlight_splits_and_dedupes_tags():
    h = rw.row_to_highlight({"Highlight": "x", "Tags": "Stalin, USSR, stalin"})
    assert h.tags == ["stalin", "ussr"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_readwise.py::test_row_to_highlight_page_location -v`
Expected: FAIL — `AttributeError: module 'books.readwise_obsidian' has no attribute 'row_to_highlight'`

- [ ] **Step 3: Implement `row_to_highlight`**

Append to `books/readwise_obsidian.py`:

```python
def _split_tags(raw: str | None) -> list[str]:
    """Comma-split a tag string into sanitized, de-duplicated inline tags."""
    tags: list[str] = []
    for part in (raw or "").split(","):
        tag = sanitize_tag(part)
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def row_to_highlight(row: dict) -> Highlight:
    """Map a Readwise CSV row to a source-agnostic Highlight.

    Location Type drives the location label: "page" -> "p." (default), "location"
    -> "loc." (Kindle), anything else (e.g. "order") -> no location recorded.
    """
    loc_type = (row.get("Location Type") or "").strip().lower()
    location = (row.get("Location") or "").strip() or None
    page: str | None = None
    label: str | None = None
    if location and loc_type == "page":
        page = location
    elif location and loc_type == "location":
        page, label = location, "loc."
    return Highlight(
        text=(row.get("Highlight") or "").strip(),
        note=(row.get("Note") or "").strip() or None,
        page=page,
        location_label=label,
        date=(row.get("Highlighted at") or "").strip() or None,
        tags=_split_tags(row.get("Tags")),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_readwise.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add books/readwise_obsidian.py tests/test_readwise.py
git commit -m "feat(readwise): map CSV rows to Highlights with type-aware location"
```

---

## Task 5: `parse_csv` + `convert` (grouping, frontmatter, embed)

**Files:**
- Modify: `books/readwise_obsidian.py`
- Test: `tests/test_readwise.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_readwise.py` (top-level, after the imports add the fixtures):

```python
HEADER = (
    "Highlight,Book Title,Book Author,Amazon Book ID,Note,Color,Tags,"
    "Location Type,Location,Highlighted at,Document tags\n"
)
ROWS = (
    '"First passage.","Stalin: Volume I (Stalin #1)",Stephen Kotkin,B00INIXPYE,'
    "my note,,history,page,3,2026-07-17 14:00:25+00:00,favorites\n"
    '"Second passage.","Stalin: Volume I (Stalin #1)",Stephen Kotkin,B00INIXPYE,'
    ",,,,page,10,2026-07-19 17:36:30+00:00,favorites\n"
)


def write_csv(tmp_path: Path) -> Path:
    p = tmp_path / "readwise-data.csv"
    p.write_text(HEADER + ROWS, encoding="utf-8")
    return p


def test_parse_csv_reads_rows(tmp_path):
    rows = rw.parse_csv(write_csv(tmp_path))
    assert len(rows) == 2
    assert rows[0]["Book Title"] == "Stalin: Volume I (Stalin #1)"


def test_convert_writes_highlights_and_frontmatter(tmp_path):
    out = tmp_path / "Obsidian"
    stats = rw.convert(write_csv(tmp_path), out)
    assert stats["books"] == 1 and stats["entries"] == 2
    note = out / "Books" / "Stalin_ Volume I.md"
    assert note.exists()
    note_text = note.read_text()
    assert "![[Exports/Stephen Kotkin/Stalin_ Volume I/Highlights.md]]" in note_text
    assert 'amazon: "B00INIXPYE"' in note_text
    assert 'series: "Stalin"' in note_text
    assert "series_index: 1" in note_text
    assert 'shelves: ["favorites"]' in note_text
    highlights_md = (
        out / "Exports" / "Stephen Kotkin" / "Stalin_ Volume I" / "Highlights.md"
    ).read_text()
    assert "source: readwise" in highlights_md
    assert "> [!quote]+ p. 3" in highlights_md
    assert "First passage." in highlights_md
    assert "#history" in highlights_md


def test_convert_merges_into_existing_note_by_amazon(tmp_path):
    out = tmp_path / "Obsidian"
    books = out / "Books"
    books.mkdir(parents=True)
    note = books / "Existing.md"
    note.write_text(
        '---\ntype: book\ntitle: "Stalin"\namazon: "B00INIXPYE"\nstatus: read\n---\n\nMy body.\n',
        encoding="utf-8",
    )
    stats = rw.convert(write_csv(tmp_path), out)
    assert stats["books"] == 1
    updated = note.read_text()
    assert "status: read" in updated  # existing value untouched
    assert "My body." in updated  # body preserved
    assert "![[Exports/Stephen Kotkin/Stalin_ Volume I/Highlights.md]]" in updated


def test_convert_idempotent(tmp_path):
    out = tmp_path / "Obsidian"
    rw.convert(write_csv(tmp_path), out)
    before = {p: p.read_text() for p in out.rglob("*.md")}
    rw.convert(write_csv(tmp_path), out)
    after = {p: p.read_text() for p in out.rglob("*.md")}
    assert before == after
```

Note: `safe_filename` turns the `:` in "Stalin: Volume I" into `_`, so the flat
note is `Stalin_ Volume I.md` and the export dir is `Stalin_ Volume I`. The merge
test uses a different note filename (`Existing.md`) to prove matching is by amazon
id, not filename.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_readwise.py::test_convert_writes_highlights_and_frontmatter -v`
Expected: FAIL — `AttributeError: module 'books.readwise_obsidian' has no attribute 'parse_csv'`

- [ ] **Step 3: Implement `parse_csv` and `convert`**

Append to `books/readwise_obsidian.py`:

```python
def parse_csv(path: Path) -> list[dict]:
    """Read the Readwise CSV export into a list of row dicts."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(_csv.DictReader(fh))


def convert(csv_path: Path, output: Path) -> dict:
    """Import every highlight, grouped by book, into the Obsidian vault."""
    stats = {"books": 0, "entries": 0, "authors": set()}
    index = VaultIndex(output)
    authors_dir = output / "Authors"

    # Group rows by book (Amazon id when present, else standardized title),
    # preserving CSV order.
    groups: dict[str, dict] = {}
    for row in parse_csv(csv_path):
        raw_title = (row.get("Book Title") or "").strip()
        if not raw_title:
            continue
        title, series, series_index = split_series(raw_title)
        amazon = (row.get("Amazon Book ID") or "").strip() or None
        author = (row.get("Book Author") or "").strip()
        doc_tags = [t.strip() for t in (row.get("Document tags") or "").split(",") if t.strip()]
        key = amazon or title
        group = groups.setdefault(
            key,
            {
                "title": title,
                "author": author,
                "amazon": amazon,
                "series": series,
                "series_index": series_index,
                "shelves": doc_tags,
                "rows": [],
            },
        )
        group["rows"].append(row)

    for group in groups.values():
        authors = [group["author"]] if group["author"] else []
        ref = BookRef(title=group["title"], authors=authors, amazon=group["amazon"])
        dest = index.find_or_create(ref)

        updates = {
            "title": yaml_quote(group["title"]),
            "authors": link_list(authors) if authors else "",
            "amazon": yaml_quote(group["amazon"]) if group["amazon"] else "",
            "shelves": plain_list(group["shelves"]) if group["shelves"] else "",
            "source": "readwise",
        }
        if group["series"]:
            updates["series"] = yaml_quote(group["series"])
        if group["series_index"]:
            updates["series_index"] = group["series_index"]
        base = dest.note_path.read_text(encoding="utf-8")
        dest.note_path.write_text(update_frontmatter(base, updates), encoding="utf-8")

        highlights = [row_to_highlight(r) for r in group["rows"]]
        write_leaf_with_embed(
            dest.note_path,
            dest.export_dir,
            "Highlights.md",
            with_source("readwise", render_highlights(highlights)),
            "Highlights",
        )

        for author in authors:
            write_stub(authors_dir, author, "author")
            stats["authors"].add(author)
        stats["books"] += 1
        stats["entries"] += len(highlights)

    return stats
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_readwise.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add books/readwise_obsidian.py tests/test_readwise.py
git commit -m "feat(readwise): parse CSV and convert into Obsidian book notes"
```

---

## Task 6: CLI command + `register`

**Files:**
- Modify: `books/readwise_obsidian.py`
- Test: `tests/test_readwise.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_readwise.py`:

```python
from typer.testing import CliRunner  # noqa: E402  (grouped with other imports is fine)

import typer  # noqa: E402


def test_readwise_command_end_to_end(tmp_path):
    app = typer.Typer()
    rw.register(app)
    out = tmp_path / "Obsidian"
    result = CliRunner().invoke(app, ["--csv", str(write_csv(tmp_path)), "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "Books" / "Stalin_ Volume I.md").exists()
    assert "2 highlights" in result.output


def test_readwise_missing_csv_errors(tmp_path):
    app = typer.Typer()
    rw.register(app)
    result = CliRunner().invoke(
        app, ["--csv", str(tmp_path / "nope.csv"), "--output", str(tmp_path / "o")]
    )
    assert result.exit_code != 0
```

(If you prefer, move the two new imports up to the top of the file with the
others — either placement works.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_readwise.py::test_readwise_command_end_to_end -v`
Expected: FAIL — `AttributeError: module 'books.readwise_obsidian' has no attribute 'register'`

- [ ] **Step 3: Add the CLI command, `register`, and `main`**

Append to `books/readwise_obsidian.py`:

```python
def readwise_to_obsidian(
    csv: Path = typer.Option(
        ...,
        "--csv",
        "-c",
        help="Path to the Readwise CSV export. Relative paths resolve against the current directory.",
    ),
    output: Path = typer.Option(
        Path("Obsidian"),
        "--output",
        "-o",
        help="Output Obsidian vault. Relative paths resolve against the current directory.",
    ),
) -> None:
    """Convert a Readwise CSV export into Obsidian book notes.

    Every highlight is imported. For each book a 'Highlights.md' is written into
    'Exports/<Author>/<Title>/' and embedded into the flat note under a
    '## Highlights' heading; books are matched to existing notes by Amazon id,
    then by a strict Author/Title comparison (using the title with any
    '(Series #N)' suffix removed). Existing notes are never overwritten.
    """
    csv = resolve_path(csv, Path.cwd())
    output = resolve_path(output, Path.cwd())

    if not csv.is_file():
        raise typer.BadParameter(f"CSV not found: {csv}", param_hint="--csv")

    output.mkdir(parents=True, exist_ok=True)
    stats = convert(csv, output)
    typer.echo(
        f"Done. {stats['books']} books, {stats['entries']} highlights, "
        f"{len(stats['authors'])} authors.\nOutput: {output}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("readwise")(readwise_to_obsidian)


def main() -> None:
    """Standalone entry point so the shim script keeps working on its own."""
    typer.run(readwise_to_obsidian)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the readwise tests to verify they pass**

Run: `uv run pytest tests/test_readwise.py -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add books/readwise_obsidian.py tests/test_readwise.py
git commit -m "feat(readwise): add readwise CLI command + register/main"
```

---

## Task 7: Wire into the `books` CLI + standalone shim

**Files:**
- Modify: `books/cli.py`
- Create: `scripts/readwise_obsidian.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Update the CLI registration tests first**

In `tests/test_cli.py`, update the three command tuples and the count:

- In `test_all_capabilities_registered`, change the loop to:
  ```python
      for command in ("calibre", "goodreads", "highlighted", "kobo", "readwise"):
  ```
- In `test_capabilities_count_matches_module_list`, change to:
  ```python
      assert len(CAPABILITIES) == 5
  ```
- In `test_subcommand_help`, change the loop to:
  ```python
      for command in ("calibre", "goodreads", "highlighted", "kobo", "readwise"):
  ```

Then add an end-to-end test at the end of `tests/test_cli.py`:

```python
def _readwise_csv(tmp_path: Path) -> Path:
    p = tmp_path / "readwise-data.csv"
    p.write_text(
        "Highlight,Book Title,Book Author,Amazon Book ID,Note,Color,Tags,"
        "Location Type,Location,Highlighted at,Document tags\n"
        '"A passage.","Stalin (Stalin #1)",Stephen Kotkin,B00INIXPYE,,,,'
        "page,3,2026-07-17 14:00:25+00:00,\n",
        encoding="utf-8",
    )
    return p


def test_readwise_end_to_end(tmp_path):
    csv_path = _readwise_csv(tmp_path)
    out = tmp_path / "Obsidian"
    result = runner.invoke(app, ["readwise", "--csv", str(csv_path), "--output", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "Books" / "Stalin.md").exists()
```

- [ ] **Step 2: Run the CLI tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL — `readwise` not registered / `CAPABILITIES` length is 4, and the
end-to-end test errors on an unknown command.

- [ ] **Step 3: Register the module in `cli.py`**

In `books/cli.py`, add the import and the `CAPABILITIES` entry:

```python
from books import (
    calibre_obsidian,
    goodreads_obsidian,
    highlighted_obsidian,
    kobo_export,
    readwise_obsidian,
)

# Modules that expose a register(app) function. Add new capabilities here.
CAPABILITIES = (
    calibre_obsidian,
    goodreads_obsidian,
    highlighted_obsidian,
    kobo_export,
    readwise_obsidian,
)
```

- [ ] **Step 4: Create the standalone shim**

Create `scripts/readwise_obsidian.py`:

```python
#!/usr/bin/env python3
"""Standalone shim: `python readwise_obsidian.py -c readwise-data.csv -o Obsidian`.

The real implementation lives in ``books.readwise_obsidian``. This keeps the
script runnable on its own while there is a single source of truth. For the full
CLI with all capabilities, use ``books`` (see pyproject.toml).
"""

from books.readwise_obsidian import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the CLI tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add books/cli.py scripts/readwise_obsidian.py tests/test_cli.py
git commit -m "feat(cli): register readwise capability + standalone shim"
```

---

## Task 8: Full-suite verification + real-data smoke test

**Files:** none (verification only)

- [ ] **Step 1: Run the complete test suite**

Run: `uv run pytest -q`
Expected: PASS (no failures, no errors)

- [ ] **Step 2: Smoke-test against the real export**

Run:
```bash
uv run books readwise --csv data/readwise-data.csv --output /tmp/readwise-smoke
```
Expected: prints `Done. N books, M highlights, K authors.` and creates
`/tmp/readwise-smoke/Books/*.md` plus `/tmp/readwise-smoke/Exports/.../Highlights.md`.

- [ ] **Step 3: Spot-check the output**

Run: `ls /tmp/readwise-smoke/Books | head` and open one note to confirm the
`## Highlights` embed, `series`/`amazon`/`shelves` frontmatter, and `p.`/`loc.`
labels look right. Clean up: `rm -rf /tmp/readwise-smoke`.

- [ ] **Step 4: Update project docs**

In `CLAUDE.md`, add a bullet under the capabilities list describing the new
`readwise` command (mirroring the `highlighted` bullet). Commit:

```bash
git add CLAUDE.md
git commit -m "docs: describe the readwise capability in CLAUDE.md"
```

---

## Self-Review Notes

- **Spec coverage:** module+command+shim (Tasks 3–7), column mapping incl. amazon/shelves/tags (Tasks 4–5), type-aware location (Tasks 1, 4), title standardization + series fields (Tasks 3, 5), amazon + title/author matching (Tasks 2, 5), tests incl. `test_highlights.py` addition (all tasks). All spec sections map to tasks.
- **No placeholders:** every code step shows complete code; every run step shows the exact command + expected result.
- **Type consistency:** `split_series` returns `(title, series, index)` and is consumed that way in `convert`; `row_to_highlight` sets `location_label` defined in Task 1; `BookRef(amazon=...)` matches the field added in Task 2; `build_index` returns a 3-tuple consumed only by `VaultIndex.__init__`.
