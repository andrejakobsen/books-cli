# CSV Store (Plan A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `books/store.py` — the canonical CSV store that owns book metadata and highlights, with per-source layers, a precedence merge, an identity `Catalog`, and per-book highlight I/O.

**Architecture:** Plain CSV on disk under `<vault>/Data/`. Per-source metadata layers (`Data/sources/<source>.csv`) are merged by fixed source-precedence into a derived `Data/books.csv`; each book gets a stable `book_id` (the note stem `<Title> - <Author>`). Highlights are a per-book union (`Data/Highlights/<book-id>.csv`) with a `source` column. All rows are `pydantic` models with CSV (de)serialization. This plan is pure data layer — no Obsidian/markdown writing (that is Plan B).

**Tech Stack:** Python 3.11, `pydantic` v2 (row models), `isbnlib` (canonical ISBN), `rapidfuzz` (fuzzy title match), stdlib `csv`. Reuses `books/obsidian.py` matching helpers (`author_key`, `norm_title`, `norm_amazon`, `strip_subtitle`, `safe_filename`) and `books/highlights.py` `Highlight`.

**Design reference:** `docs/superpowers/specs/2026-07-29-csv-source-of-truth-design.md`

---

## File structure

- Create: `books/store.py` — the entire store (models, paths, layer I/O, matching, merge, `Catalog`, highlight I/O). One module; it is the single data-layer boundary.
- Create: `tests/test_store.py` — unit tests for every public function.
- Modify: `pyproject.toml` — add runtime deps `pydantic`, `isbnlib`, `rapidfuzz`; add dev dep + config for `ruff`.

`books/store.py` public surface (defined across the tasks below):

```
# constants
DATA_DIRNAME, SOURCES_DIRNAME, HIGHLIGHTS_DIRNAME, BOOKS_CSV
METADATA_COLUMNS, CATALOG_COLUMNS, LIST_FIELDS, LIST_SEP
HIGHLIGHT_COLUMNS, HL_LIST_FIELDS
PRECEDENCE, TITLE_MATCH_THRESHOLD

# models
class BookRow(BaseModel)        # + to_csv_dict / from_csv_dict
class HighlightRow(BaseModel)   # + to_csv_dict / from_csv_dict

# paths
data_dir(vault) sources_dir(vault) layer_path(vault, source)
books_csv_path(vault) highlights_dir(vault) highlight_path(vault, book_id)

# layer I/O
write_layer(vault, source, rows)  read_layer(vault, source)  read_all_layers(vault)

# matching
canonical_isbn(isbn)  same_book(a, b)

# merge
assign_book_id(title, author, used)  coalesce(members)  merge(vault)
write_books_csv(vault, rows)  read_books_csv(vault)

# catalog
class Catalog          # .find(ref) -> book_id | None

# highlights
highlight_to_row(h, source, annotation_id)  row_to_highlight(row)
read_highlights(vault, book_id)  write_highlights(vault, book_id, source, rows)
```

---

## Task 1: Add dependencies and ruff config

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add runtime deps and ruff**

Edit `[project].dependencies` and add a dev dep + ruff config. The `dependencies` array becomes:

```toml
[project]
dependencies = [
    "typer>=0.12",
    "pydantic>=2.6",
    "isbnlib>=3.10",
    "rapidfuzz>=3.6",
]
```

Add ruff to the dev group:

```toml
[dependency-groups]
dev = ["pytest>=8", "ruff>=0.5"]
```

Append a ruff config block at the end of the file:

```toml
[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
```

- [ ] **Step 2: Sync and verify imports resolve**

Run: `uv sync && uv run python -c "import pydantic, isbnlib, rapidfuzz; print('ok')"`
Expected: prints `ok` (deps installed).

- [ ] **Step 3: Verify existing suite still passes**

Run: `uv run pytest -q`
Expected: PASS (no code changed yet).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add pydantic, isbnlib, rapidfuzz, ruff for the CSV store"
```

---

## Task 2: Row models and CSV column constants

**Files:**
- Create: `books/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_store.py`:

```python
from books import store


def test_bookrow_csv_roundtrip_joins_list_fields():
    row = store.BookRow(
        title="The Deluge",
        authors=["Adam Tooze"],
        shelves=["read", "history"],
        format="ebook",
        isbn="9780141032184",
    )
    d = row.to_csv_dict()
    assert d["authors"] == "Adam Tooze"
    assert d["shelves"] == "read;history"
    assert d["title"] == "The Deluge"
    back = store.BookRow.from_csv_dict(d)
    assert back.authors == ["Adam Tooze"]
    assert back.shelves == ["read", "history"]
    assert back.format == "ebook"


def test_bookrow_from_csv_dict_tolerates_missing_and_blank():
    back = store.BookRow.from_csv_dict({"title": "X"})
    assert back.title == "X"
    assert back.authors == []
    assert back.rating == ""


def test_highlightrow_csv_roundtrip():
    hl = store.HighlightRow(
        source="readwise",
        annotation_id="42",
        location="45-49",
        location_kind="page",
        text="Hello",
        tags=["war", "peace"],
        links=["Trotsky"],
    )
    d = hl.to_csv_dict()
    assert d["tags"] == "war;peace"
    assert d["links"] == "Trotsky"
    back = store.HighlightRow.from_csv_dict(d)
    assert back.tags == ["war", "peace"]
    assert back.links == ["Trotsky"]
    assert back.location_kind == "page"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'books.store'`.

- [ ] **Step 3: Write minimal implementation**

Create `books/store.py`:

```python
"""Canonical CSV store for book metadata and highlights.

On-disk source of truth under ``<vault>/Data/``:

- ``Data/sources/<source>.csv``  -- raw per-source metadata layers.
- ``Data/books.csv``             -- derived merged catalog (one row per book).
- ``Data/Highlights/<book-id>.csv`` -- per-book union of highlights (``source`` column).

Metadata layers are merged by fixed source precedence into ``books.csv``; each
book is assigned a stable ``book_id`` (the note stem ``<Title> - <Author>``).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

LIST_SEP = ";"

# Shared metadata columns (layers + books.csv). ``book_id`` is catalog-only.
METADATA_COLUMNS = (
    "title",
    "authors",
    "series",
    "series_index",
    "publisher",
    "published",
    "language",
    "format",
    "pages",
    "status",
    "shelves",
    "rating",
    "isbn",
    "amazon",
    "google",
    "goodreads",
    "uuid",
    "calibre_id",
    "date_added",
    "date_read",
    "review",
    "cover",
)
CATALOG_COLUMNS = ("book_id", *METADATA_COLUMNS)
LIST_FIELDS = ("authors", "shelves")

HIGHLIGHT_COLUMNS = (
    "source",
    "annotation_id",
    "chapter_index",
    "chapter_title",
    "location",
    "location_kind",
    "block",
    "segment",
    "date",
    "text",
    "note",
    "tags",
    "links",
)
HL_LIST_FIELDS = ("tags", "links")


class BookRow(BaseModel):
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    series: str = ""
    series_index: str = ""
    publisher: str = ""
    published: str = ""
    language: str = ""
    format: str = ""
    pages: str = ""
    status: str = ""
    shelves: list[str] = Field(default_factory=list)
    rating: str = ""
    isbn: str = ""
    amazon: str = ""
    google: str = ""
    goodreads: str = ""
    uuid: str = ""
    calibre_id: str = ""
    date_added: str = ""
    date_read: str = ""
    review: str = ""
    cover: str = ""
    book_id: str = ""  # populated only in the merged catalog

    def to_csv_dict(self) -> dict[str, str]:
        out: dict[str, str] = {"book_id": self.book_id}
        for col in METADATA_COLUMNS:
            val = getattr(self, col)
            out[col] = LIST_SEP.join(val) if col in LIST_FIELDS else str(val or "")
        return out

    @classmethod
    def from_csv_dict(cls, row: dict[str, str]) -> "BookRow":
        data: dict[str, object] = {}
        if row.get("book_id"):
            data["book_id"] = row["book_id"].strip()
        for col in METADATA_COLUMNS:
            raw = (row.get(col) or "").strip()
            if col in LIST_FIELDS:
                data[col] = [p.strip() for p in raw.split(LIST_SEP) if p.strip()]
            else:
                data[col] = raw
        return cls(**data)


class HighlightRow(BaseModel):
    source: str = ""
    annotation_id: str = ""
    chapter_index: str = ""
    chapter_title: str = ""
    location: str = ""
    location_kind: str = ""  # percent | page | kindle_loc | timestamp
    block: str = ""
    segment: str = ""
    date: str = ""
    text: str = ""
    note: str = ""
    tags: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)

    def to_csv_dict(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for col in HIGHLIGHT_COLUMNS:
            val = getattr(self, col)
            out[col] = LIST_SEP.join(val) if col in HL_LIST_FIELDS else str(val or "")
        return out

    @classmethod
    def from_csv_dict(cls, row: dict[str, str]) -> "HighlightRow":
        data: dict[str, object] = {}
        for col in HIGHLIGHT_COLUMNS:
            raw = (row.get(col) or "").strip()
            if col in HL_LIST_FIELDS:
                data[col] = [p.strip() for p in raw.split(LIST_SEP) if p.strip()]
            else:
                data[col] = raw
        return cls(**data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add books/store.py tests/test_store.py
git commit -m "feat(store): pydantic BookRow/HighlightRow models with CSV serialization"
```

---

## Task 3: Path helpers

**Files:**
- Modify: `books/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py`:

```python
from pathlib import Path


def test_path_helpers(tmp_path):
    vault = tmp_path / "vault"
    assert store.data_dir(vault) == vault / "Data"
    assert store.sources_dir(vault) == vault / "Data" / "sources"
    assert store.layer_path(vault, "calibre") == vault / "Data" / "sources" / "calibre.csv"
    assert store.books_csv_path(vault) == vault / "Data" / "books.csv"
    assert store.highlights_dir(vault) == vault / "Data" / "Highlights"
    assert store.highlight_path(vault, "The Deluge - Adam Tooze") == (
        vault / "Data" / "Highlights" / "The Deluge - Adam Tooze.csv"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py::test_path_helpers -q`
Expected: FAIL with `AttributeError: module 'books.store' has no attribute 'data_dir'`.

- [ ] **Step 3: Write minimal implementation**

Add to `books/store.py` (after the imports add `from pathlib import Path`, and append these functions):

```python
DATA_DIRNAME = "Data"
SOURCES_DIRNAME = "sources"
HIGHLIGHTS_DIRNAME = "Highlights"
BOOKS_CSV = "books.csv"


def data_dir(vault: Path) -> Path:
    return vault / DATA_DIRNAME


def sources_dir(vault: Path) -> Path:
    return data_dir(vault) / SOURCES_DIRNAME


def layer_path(vault: Path, source: str) -> Path:
    return sources_dir(vault) / f"{source}.csv"


def books_csv_path(vault: Path) -> Path:
    return data_dir(vault) / BOOKS_CSV


def highlights_dir(vault: Path) -> Path:
    return data_dir(vault) / HIGHLIGHTS_DIRNAME


def highlight_path(vault: Path, book_id: str) -> Path:
    return highlights_dir(vault) / f"{book_id}.csv"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py::test_path_helpers -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add books/store.py tests/test_store.py
git commit -m "feat(store): Data/ path helpers"
```

---

## Task 4: Layer read/write round-trip

**Files:**
- Modify: `books/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py`:

```python
def test_write_and_read_layer_roundtrip(tmp_path):
    vault = tmp_path / "vault"
    rows = [
        store.BookRow(title="The Deluge", authors=["Adam Tooze"], format="ebook"),
        store.BookRow(title="Stalin", authors=["Stephen Kotkin"], shelves=["read"]),
    ]
    store.write_layer(vault, "calibre", rows)
    assert store.layer_path(vault, "calibre").is_file()
    back = store.read_layer(vault, "calibre")
    assert [r.title for r in back] == ["The Deluge", "Stalin"]
    assert back[0].authors == ["Adam Tooze"]
    assert back[1].shelves == ["read"]


def test_read_layer_missing_returns_empty(tmp_path):
    assert store.read_layer(tmp_path / "vault", "goodreads") == []


def test_write_layer_overwrites_previous(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "calibre", [store.BookRow(title="A")])
    store.write_layer(vault, "calibre", [store.BookRow(title="B")])
    back = store.read_layer(vault, "calibre")
    assert [r.title for r in back] == ["B"]


def test_read_all_layers_returns_precedence_order(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "audible", [store.BookRow(title="Aud")])
    store.write_layer(vault, "calibre", [store.BookRow(title="Cal")])
    layers = store.read_all_layers(vault)
    assert list(layers.keys()) == [s for s in store.PRECEDENCE if s in layers]
    assert list(layers.keys())[0] == "calibre"  # lowest precedence first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -k "layer" -q`
Expected: FAIL with `AttributeError: ... 'write_layer'`.

- [ ] **Step 3: Write minimal implementation**

Add to `books/store.py` (add `import csv` to imports; append functions):

```python
PRECEDENCE = ("calibre", "goodreads", "covers", "kobo", "highlighted", "readwise", "audible")


def _write_csv(path: Path, fieldnames, dict_rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in dict_rows:
            writer.writerow(row)


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def write_layer(vault: Path, source: str, rows: list[BookRow]) -> None:
    _write_csv(layer_path(vault, source), METADATA_COLUMNS, (r.to_csv_dict() for r in rows))


def read_layer(vault: Path, source: str) -> list[BookRow]:
    return [BookRow.from_csv_dict(r) for r in _read_csv(layer_path(vault, source))]


def read_all_layers(vault: Path) -> dict[str, list[BookRow]]:
    """All present source layers, keyed in ascending precedence order."""
    out: dict[str, list[BookRow]] = {}
    for source in PRECEDENCE:
        if layer_path(vault, source).is_file():
            out[source] = read_layer(vault, source)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py -k "layer" -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add books/store.py tests/test_store.py
git commit -m "feat(store): per-source layer CSV read/write"
```

---

## Task 5: Canonical ISBN and same_book matching

**Files:**
- Modify: `books/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py`:

```python
def test_canonical_isbn_normalizes_isbn10_to_13():
    # 0141032189 (ISBN-10) == 9780141032184 (ISBN-13) for the same edition.
    assert store.canonical_isbn("0-14-103218-9") == store.canonical_isbn("9780141032184")
    assert store.canonical_isbn("") is None
    assert store.canonical_isbn(None) is None


def test_same_book_matches_on_isbn():
    a = store.BookRow(title="X", isbn="0-14-103218-9")
    b = store.BookRow(title="Totally Different", isbn="9780141032184")
    assert store.same_book(a, b) is True


def test_same_book_isbn_conflict_is_not_a_match():
    a = store.BookRow(title="X", authors=["A"], isbn="9780000000001")
    b = store.BookRow(title="X", authors=["A"], isbn="9780000000002")
    assert store.same_book(a, b) is False


def test_same_book_matches_on_amazon_when_no_isbn():
    a = store.BookRow(title="X", amazon="B00ABC")
    b = store.BookRow(title="Y", amazon="b00abc")
    assert store.same_book(a, b) is True


def test_same_book_bare_title_merges_with_subtitled_edition():
    # Same book, one source carries the subtitle and the other does not.
    a = store.BookRow(title="The Deluge: The Great War", authors=["Adam Tooze"])
    b = store.BookRow(title="The Deluge", authors=["Tooze, Adam"])
    assert store.same_book(a, b) is True


def test_same_book_distinct_subtitled_volumes_do_not_merge():
    # Both carry a (different) subtitle -> compared in full -> distinct volumes.
    a = store.BookRow(title="Stalin: Paradoxes of Power", authors=["Stephen Kotkin"])
    b = store.BookRow(title="Stalin: Waiting for Hitler", authors=["Stephen Kotkin"])
    assert store.same_book(a, b) is False


def test_same_book_bare_sequel_titles_do_not_merge():
    # No subtitles anywhere; a sequel is not the same book as its predecessor.
    a = store.BookRow(title="Dune", authors=["Frank Herbert"])
    b = store.BookRow(title="Dune Messiah", authors=["Frank Herbert"])
    assert store.same_book(a, b) is False


def test_same_book_bare_title_merges_with_subtitled_same_book():
    a = store.BookRow(title="1984", authors=["George Orwell"])
    b = store.BookRow(title="1984: A Novel", authors=["George Orwell"])
    assert store.same_book(a, b) is True
```

> **Matching is subtitle-aware, using the symmetric `fuzz.ratio`.** This is the crux
> of the spec's "conservative merge" guarantee. Two requirements look contradictory —
> "The Deluge" must merge with "The Deluge: The Great War", yet "Dune" must NOT merge
> with "Dune Messiah" and the two subtitled "Stalin" volumes must stay separate. They
> reconcile only by treating the subtitle specially:
> - When **both** titles have a subtitle (contain `:`), compare the **full** titles —
>   so two different subtitles separate distinct volumes.
> - Otherwise, compare the **subtitle-stripped base** titles — so a bare title merges
>   with the subtitled edition of the same book.
>
> `fuzz.partial_ratio` MUST NOT be used here: it scores any prefix/substring as 100 and
> silently merges "Dune"/"Dune Messiah", "Stalin"/"Stalin: Waiting for Hitler", etc.
> (The genuinely ambiguous bare-title-of-a-multivolume-work case, e.g. a source giving
> only "Stalin", is accepted as a merge — it is rare and only reached when neither side
> has an ISBN or Amazon id to anchor on.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -k "isbn or same_book" -q`
Expected: FAIL with `AttributeError: ... 'canonical_isbn'`.

- [ ] **Step 3: Write minimal implementation**

Add to `books/store.py` (add imports `import isbnlib`, `from rapidfuzz import fuzz`, and `from books.obsidian import author_key, norm_amazon, norm_isbn, norm_title`; append):

```python
TITLE_MATCH_THRESHOLD = 90  # rapidfuzz ratio 0-100; conservative to avoid false merges


def canonical_isbn(isbn: str | None) -> str | None:
    """Canonical ISBN-13 for matching, or None. Falls back to digit-normalization."""
    if not isbn:
        return None
    c = isbnlib.canonical(str(isbn))
    if c and isbnlib.is_isbn10(c):
        c = isbnlib.to_isbn13(c) or c
    return c or norm_isbn(isbn)


def _has_subtitle(title: str) -> bool:
    return strip_subtitle(title).strip().casefold() != (title or "").strip().casefold()


def title_similar(t1: str, t2: str) -> bool:
    """Subtitle-aware fuzzy title match with the symmetric ``fuzz.ratio``.

    When both titles carry a subtitle, compare them in full (differing subtitles
    separate distinct volumes); otherwise compare the subtitle-stripped bases (a
    bare title merges with the subtitled edition of the same book). Never uses
    ``partial_ratio`` — it would merge "Dune"/"Dune Messiah" and the like.
    """
    if _has_subtitle(t1) and _has_subtitle(t2):
        left, right = norm_title(t1), norm_title(t2)
    else:
        left, right = norm_title(strip_subtitle(t1)), norm_title(strip_subtitle(t2))
    return fuzz.ratio(left, right) >= TITLE_MATCH_THRESHOLD


def same_book(a: BookRow, b: BookRow) -> bool:
    """True when two rows denote the same book.

    ISBN and Amazon id are authoritative when both sides have them (a conflict
    means *different* books). Otherwise fall back to same author + subtitle-aware
    fuzzy title (:func:`title_similar`).
    """
    ia, ib = canonical_isbn(a.isbn), canonical_isbn(b.isbn)
    if ia and ib:
        return ia == ib
    aa, ab = norm_amazon(a.amazon), norm_amazon(b.amazon)
    if aa and ab:
        return aa == ab
    if not (a.authors and b.authors):
        return False
    if author_key(a.authors[0]) != author_key(b.authors[0]):
        return False
    return title_similar(a.title, b.title)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py -k "isbn or same_book" -q`
Expected: PASS (6 tests). If `test_same_book_different_titles_do_not_merge` fails because the score is unexpectedly high, that indicates the threshold needs raising — bump `TITLE_MATCH_THRESHOLD` to 92 and re-run.

- [ ] **Step 5: Commit**

```bash
git add books/store.py tests/test_store.py
git commit -m "feat(store): canonical ISBN + same_book matching (isbnlib + rapidfuzz)"
```

---

## Task 6: book_id assignment (note-stem + collision handling)

**Files:**
- Modify: `books/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py`:

```python
def test_assign_book_id_basic_stem_drops_subtitle():
    used = set()
    bid = store.assign_book_id("The Deluge: The Great War", "Adam Tooze", used)
    assert bid == "The Deluge - Adam Tooze"


def test_assign_book_id_collision_restores_subtitle():
    used = set()
    first = store.assign_book_id("Stalin: Paradoxes of Power", "Stephen Kotkin", used)
    second = store.assign_book_id("Stalin: Waiting for Hitler, 1929-1941", "Stephen Kotkin", used)
    assert first == "Stalin - Stephen Kotkin"
    assert second == "Stalin, Waiting for Hitler, 1929-1941 - Stephen Kotkin"


def test_assign_book_id_numeric_suffix_last_resort():
    used = set()
    a = store.assign_book_id("Poems", "Anon", used)
    b = store.assign_book_id("Poems", "Anon", used)
    assert a == "Poems - Anon"
    assert b == "Poems - Anon (2)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -k "assign_book_id" -q`
Expected: FAIL with `AttributeError: ... 'assign_book_id'`.

- [ ] **Step 3: Write minimal implementation**

Add to `books/store.py` (add `from books.obsidian import safe_filename, strip_subtitle` to the obsidian import line; append):

```python
def _stem(title: str, author: str) -> str:
    clean = strip_subtitle(title).strip()
    base = f"{clean} - {author}".strip() if author else clean
    return safe_filename(base)


def assign_book_id(title: str, author: str, used: set[str]) -> str:
    """Stable, collision-free book id = the note stem ``<Title> - <Author>``.

    Mirrors ``obsidian.VaultIndex._new_note_path``: subtitle dropped; on collision
    the subtitle is restored (``:`` -> ``,``); a numeric ``(n)`` suffix is last resort.
    """
    clean_stem = _stem(title, author)
    if clean_stem not in used:
        used.add(clean_stem)
        return clean_stem

    full = title.replace(":", ",").strip()
    full_stem = safe_filename(f"{full} - {author}".strip() if author else full)
    if full_stem not in used:
        used.add(full_stem)
        return full_stem

    n = 2
    while f"{clean_stem} ({n})" in used:
        n += 1
    stem = f"{clean_stem} ({n})"
    used.add(stem)
    return stem
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py -k "assign_book_id" -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add books/store.py tests/test_store.py
git commit -m "feat(store): book_id assignment mirroring VaultIndex stem scheme"
```

---

## Task 7: Precedence coalesce

**Files:**
- Modify: `books/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py`:

```python
def test_coalesce_higher_precedence_wins_and_fills_blanks():
    members = [
        ("goodreads", store.BookRow(title="X", format="ebook", rating="4")),
        ("audible", store.BookRow(title="X", format="audiobook")),
    ]
    merged = store.coalesce(members)
    assert merged.format == "audiobook"  # audible > goodreads
    assert merged.rating == "4"  # only goodreads had it


def test_coalesce_is_order_independent():
    m1 = [
        ("audible", store.BookRow(title="X", format="audiobook")),
        ("goodreads", store.BookRow(title="X", format="ebook")),
    ]
    m2 = list(reversed(m1))
    assert store.coalesce(m1).format == "audiobook"
    assert store.coalesce(m2).format == "audiobook"


def test_coalesce_merges_list_fields_by_precedence():
    members = [
        ("calibre", store.BookRow(title="X", shelves=["a"])),
        ("goodreads", store.BookRow(title="X", shelves=["b", "c"])),
    ]
    # goodreads outranks calibre and has a non-empty list -> it wins wholesale
    assert store.coalesce(members).shelves == ["b", "c"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -k "coalesce" -q`
Expected: FAIL with `AttributeError: ... 'coalesce'`.

- [ ] **Step 3: Write minimal implementation**

Append to `books/store.py`:

```python
def _rank(source: str) -> int:
    return PRECEDENCE.index(source) if source in PRECEDENCE else -1


def coalesce(members: list[tuple[str, BookRow]]) -> BookRow:
    """Merge ``(source, row)`` members into one row.

    Each field takes the value from the highest-precedence source that has a
    non-blank value. Pure and order-independent (rank depends only on source).
    """
    ordered = sorted(members, key=lambda sr: _rank(sr[0]))
    merged = BookRow()
    for _source, row in ordered:
        for col in METADATA_COLUMNS:
            val = getattr(row, col)
            if col in LIST_FIELDS:
                if val:
                    setattr(merged, col, list(val))
            elif val not in (None, ""):
                setattr(merged, col, val)
    return merged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py -k "coalesce" -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add books/store.py tests/test_store.py
git commit -m "feat(store): precedence coalesce of merged book rows"
```

---

## Task 8: Clustering + merge() writing books.csv

**Files:**
- Modify: `books/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py`:

```python
def test_merge_clusters_across_layers_and_assigns_book_id(tmp_path):
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
    store.write_layer(
        vault,
        "audible",
        [
            store.BookRow(
                title="The Deluge", authors=["Adam Tooze"], format="audiobook", isbn="0-14-103218-9"
            ),  # same edition, ISBN-10 form
        ],
    )
    catalog = store.merge(vault)
    assert len(catalog) == 1
    book = catalog[0]
    assert book.book_id == "The Deluge - Adam Tooze"
    assert book.format == "audiobook"  # audible wins format
    assert store.books_csv_path(vault).is_file()


def test_merge_is_order_independent(tmp_path):
    def build(vault, first, second):
        store.write_layer(vault, first[0], first[1])
        store.write_layer(vault, second[0], second[1])
        return {b.book_id: b.format for b in store.merge(vault)}

    cal = ("calibre", [store.BookRow(title="X", authors=["A"], format="ebook")])
    aud = ("audible", [store.BookRow(title="X", authors=["A"], format="audiobook")])
    r1 = build(tmp_path / "v1", cal, aud)
    r2 = build(tmp_path / "v2", aud, cal)
    assert r1 == r2
    assert list(r1.values()) == ["audiobook"]


def test_merge_read_books_csv_roundtrip(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "calibre", [store.BookRow(title="X", authors=["A"], shelves=["read"])])
    store.merge(vault)
    rows = store.read_books_csv(vault)
    assert rows[0].book_id == "X - A"
    assert rows[0].shelves == ["read"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -k "merge" -q`
Expected: FAIL with `AttributeError: ... 'merge'`.

- [ ] **Step 3: Write minimal implementation**

Append to `books/store.py`:

```python
def _cluster(tagged: list[tuple[str, BookRow]]) -> list[list[tuple[str, BookRow]]]:
    clusters: list[list[tuple[str, BookRow]]] = []
    for item in tagged:
        _src, row = item
        for c in clusters:
            if any(same_book(row, member) for _s, member in c):
                c.append(item)
                break
        else:
            clusters.append([item])
    return clusters


def write_books_csv(vault: Path, rows: list[BookRow]) -> None:
    _write_csv(books_csv_path(vault), CATALOG_COLUMNS, (r.to_csv_dict() for r in rows))


def read_books_csv(vault: Path) -> list[BookRow]:
    return [BookRow.from_csv_dict(r) for r in _read_csv(books_csv_path(vault))]


def merge(vault: Path) -> list[BookRow]:
    """Cluster all layers, coalesce by precedence, assign book_id, write books.csv."""
    layers = read_all_layers(vault)
    tagged = [(source, row) for source, rows in layers.items() for row in rows]
    used: set[str] = set()
    catalog: list[BookRow] = []
    for cluster in _cluster(tagged):
        merged = coalesce(cluster)
        author = merged.authors[0] if merged.authors else ""
        merged.book_id = assign_book_id(merged.title, author, used)
        catalog.append(merged)
    write_books_csv(vault, catalog)
    return catalog
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py -k "merge" -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add books/store.py tests/test_store.py
git commit -m "feat(store): clustering + precedence merge writing books.csv"
```

---

## Task 9: Catalog.find identity lookup

**Files:**
- Modify: `books/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py`:

```python
from books.obsidian import BookRef


def test_catalog_find_by_isbn_amazon_and_title_author(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(
        vault,
        "calibre",
        [
            store.BookRow(
                title="The Deluge", authors=["Adam Tooze"], isbn="9780141032184", amazon="B00DELUGE"
            ),
        ],
    )
    store.merge(vault)
    cat = store.Catalog(vault)

    assert cat.find(BookRef(title="whatever", isbn="0-14-103218-9")) == "The Deluge - Adam Tooze"
    assert cat.find(BookRef(title="whatever", amazon="b00deluge")) == "The Deluge - Adam Tooze"
    assert (
        cat.find(BookRef(title="The Deluge", authors=["Tooze, Adam"])) == "The Deluge - Adam Tooze"
    )
    assert cat.find(BookRef(title="Nonexistent", authors=["Nobody"])) is None


def test_catalog_find_fuzzy_title(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(
        vault, "calibre", [store.BookRow(title="The Deluge: The Great War", authors=["Adam Tooze"])]
    )
    store.merge(vault)
    cat = store.Catalog(vault)
    assert (
        cat.find(BookRef(title="The Deluge", authors=["Adam Tooze"]))
        == "The Deluge: The Great War - Adam Tooze"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -k "catalog_find" -q`
Expected: FAIL with `AttributeError: ... 'Catalog'`.

- [ ] **Step 3: Write minimal implementation**

Append to `books/store.py` (add `from books.obsidian import BookRef` to the obsidian import line):

```python
class Catalog:
    """Identity lookup over ``books.csv`` for the highlight importers.

    ``find(ref)`` returns the ``book_id`` of the matching book or None; it never
    creates anything. Matches by canonical ISBN, then Amazon id, then exact
    normalized (title, author), then a conservative fuzzy title fallback.
    """

    def __init__(self, vault: Path) -> None:
        self.rows = read_books_csv(vault)
        self._by_isbn: dict[str, str] = {}
        self._by_amazon: dict[str, str] = {}
        self._by_ta: dict[tuple[str, tuple[str, str]], str] = {}
        for r in self.rows:
            ci = canonical_isbn(r.isbn)
            if ci:
                self._by_isbn.setdefault(ci, r.book_id)
            na = norm_amazon(r.amazon)
            if na:
                self._by_amazon.setdefault(na, r.book_id)
            if r.authors:
                key = (norm_title(r.title), author_key(r.authors[0]))
                self._by_ta.setdefault(key, r.book_id)

    def find(self, ref: BookRef) -> str | None:
        ci = canonical_isbn(ref.isbn)
        if ci and ci in self._by_isbn:
            return self._by_isbn[ci]
        na = norm_amazon(ref.amazon)
        if na and na in self._by_amazon:
            return self._by_amazon[na]
        if ref.authors:
            key = (norm_title(ref.title), author_key(ref.authors[0]))
            if key in self._by_ta:
                return self._by_ta[key]
            akey = author_key(ref.authors[0])
            for r in self.rows:
                if not r.authors or author_key(r.authors[0]) != akey:
                    continue
                if title_similar(ref.title, r.title):
                    return r.book_id
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py -k "catalog_find" -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add books/store.py tests/test_store.py
git commit -m "feat(store): Catalog.find identity lookup over books.csv"
```

---

## Task 10: Highlight <-> HighlightRow conversion

**Files:**
- Modify: `books/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py`:

```python
from books.highlights import Highlight


def test_highlight_to_row_percent():
    h = Highlight(
        text="t",
        progress=0.42,
        chapter_index=3,
        chapter_title="Ch",
        tags=["war"],
        links=["Trotsky"],
        note="n",
        date="2020",
    )
    row = store.highlight_to_row(h, "kobo", "a1")
    assert row.source == "kobo"
    assert row.annotation_id == "a1"
    assert row.location == "42"
    assert row.location_kind == "percent"
    assert row.chapter_index == "3"
    assert row.tags == ["war"]


def test_highlight_to_row_page_and_kindle_and_timestamp():
    page = store.highlight_to_row(Highlight(text="t", page="45-49"), "highlighted", "1")
    assert (page.location, page.location_kind) == ("45-49", "page")

    kindle = store.highlight_to_row(
        Highlight(text="t", page="1234", location_label="loc."), "readwise", "2"
    )
    assert (kindle.location, kindle.location_kind) == ("1234", "kindle_loc")

    ts = store.highlight_to_row(
        Highlight(text="t", page="3:24:15", location_label=""), "audible", "3"
    )
    assert (ts.location, ts.location_kind) == ("3:24:15", "timestamp")


def test_row_to_highlight_reverses_each_kind():
    for kind, loc, want in [
        ("percent", "42", ("progress", 0.42)),
        ("page", "45-49", ("page", "45-49")),
        ("kindle_loc", "1234", ("location_label", "loc.")),
        ("timestamp", "3:24:15", ("location_label", "")),
    ]:
        row = store.HighlightRow(text="t", location=loc, location_kind=kind)
        h = store.row_to_highlight(row)
        attr, value = want
        assert getattr(h, attr) == value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -k "highlight_to_row or row_to_highlight" -q`
Expected: FAIL with `AttributeError: ... 'highlight_to_row'`.

- [ ] **Step 3: Write minimal implementation**

Append to `books/store.py` (add `from books.highlights import Highlight`):

```python
def highlight_to_row(h: Highlight, source: str, annotation_id: str) -> HighlightRow:
    """Map a source-agnostic Highlight to a CSV HighlightRow.

    location/location_kind unify progress/page/timestamp:
      progress            -> ("percent", "<pct>")
      page + label "loc." -> ("kindle_loc", page)
      page + label ""     -> ("timestamp", page)   (audio; suppressed prefix)
      page (default)      -> ("page", page)
    """
    location = ""
    kind = ""
    if h.progress is not None:
        location, kind = str(round(h.progress * 100)), "percent"
    elif h.page:
        location = h.page
        if h.location_label == "loc.":
            kind = "kindle_loc"
        elif h.location_label == "":
            kind = "timestamp"
        else:
            kind = "page"
    return HighlightRow(
        source=source,
        annotation_id=annotation_id,
        chapter_index=str(h.chapter_index) if h.chapter_index is not None else "",
        chapter_title=h.chapter_title or "",
        location=location,
        location_kind=kind,
        block=h.block or "",
        segment=h.segment or "",
        date=h.date or "",
        text=h.text,
        note=h.note or "",
        tags=list(h.tags),
        links=list(h.links),
    )


def row_to_highlight(row: HighlightRow) -> Highlight:
    """Reverse of :func:`highlight_to_row`."""
    progress = None
    page = None
    label = None
    if row.location_kind == "percent" and row.location:
        progress = round(int(row.location)) / 100
    elif row.location_kind == "kindle_loc":
        page, label = row.location or None, "loc."
    elif row.location_kind == "timestamp":
        page, label = row.location or None, ""
    elif row.location_kind == "page":
        page = row.location or None
    return Highlight(
        text=row.text,
        note=row.note or None,
        chapter_index=int(row.chapter_index) if row.chapter_index else None,
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

Run: `uv run pytest tests/test_store.py -k "highlight_to_row or row_to_highlight" -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add books/store.py tests/test_store.py
git commit -m "feat(store): Highlight <-> HighlightRow conversion (location/location_kind)"
```

---

## Task 11: Per-book highlight read/write (replace-by-source)

**Files:**
- Modify: `books/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py`:

```python
def test_write_and_read_highlights_roundtrip(tmp_path):
    vault = tmp_path / "vault"
    bid = "The Deluge - Adam Tooze"
    rows = [
        store.HighlightRow(
            source="kobo", annotation_id="1", text="a", location="10", location_kind="percent"
        ),
        store.HighlightRow(
            source="kobo", annotation_id="2", text="b", location="20", location_kind="percent"
        ),
    ]
    store.write_highlights(vault, bid, "kobo", rows)
    back = store.read_highlights(vault, bid)
    assert [r.text for r in back] == ["a", "b"]


def test_write_highlights_replaces_only_its_own_source(tmp_path):
    vault = tmp_path / "vault"
    bid = "X - A"
    store.write_highlights(
        vault, bid, "kobo", [store.HighlightRow(source="kobo", annotation_id="1", text="kobo1")]
    )
    store.write_highlights(
        vault,
        bid,
        "readwise",
        [store.HighlightRow(source="readwise", annotation_id="1", text="rw1")],
    )
    # re-run kobo with new content: only kobo rows replaced, readwise preserved
    store.write_highlights(
        vault, bid, "kobo", [store.HighlightRow(source="kobo", annotation_id="1", text="kobo2")]
    )
    back = store.read_highlights(vault, bid)
    texts = {(r.source, r.text) for r in back}
    assert texts == {("kobo", "kobo2"), ("readwise", "rw1")}


def test_read_highlights_missing_returns_empty(tmp_path):
    assert store.read_highlights(tmp_path / "vault", "Nope - Nobody") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py -k "highlights_roundtrip or replaces_only or highlights_missing" -q`
Expected: FAIL with `AttributeError: ... 'write_highlights'`.

- [ ] **Step 3: Write minimal implementation**

Append to `books/store.py`:

```python
def read_highlights(vault: Path, book_id: str) -> list[HighlightRow]:
    return [HighlightRow.from_csv_dict(r) for r in _read_csv(highlight_path(vault, book_id))]


def write_highlights(vault: Path, book_id: str, source: str, rows: list[HighlightRow]) -> None:
    """Replace this source's rows in the per-book file, preserving other sources."""
    existing = [r for r in read_highlights(vault, book_id) if r.source != source]
    combined = existing + list(rows)
    _write_csv(
        highlight_path(vault, book_id), HIGHLIGHT_COLUMNS, (r.to_csv_dict() for r in combined)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py -k "highlights_roundtrip or replaces_only or highlights_missing" -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add books/store.py tests/test_store.py
git commit -m "feat(store): per-book highlight read/write (replace-by-source)"
```

---

## Task 12: Full-suite check + lint

**Files:**
- (none — verification only)

- [ ] **Step 1: Run the entire test suite**

Run: `uv run pytest -q`
Expected: PASS (all pre-existing tests plus the new `tests/test_store.py`).

- [ ] **Step 2: Run ruff over the new module**

Run: `uv run ruff check books/store.py tests/test_store.py`
Expected: no errors (fix any import-order/unused-import issues ruff reports, then re-run).

- [ ] **Step 3: Commit any lint fixes**

```bash
git add books/store.py tests/test_store.py
git commit -m "style(store): ruff clean"
```

(If nothing changed, skip the commit.)

---

## Self-review notes (author)

- **Spec coverage:** storage layout (Task 3), per-source layers (Task 4), precedence merge + order-independence (Tasks 7-8), canonical ISBN + fuzzy matching (Task 5), book_id note-stem + collisions (Task 6), `Catalog.find` (Task 9), highlight union with `source` column + replace-by-source (Task 11), `location`/`location_kind` schema (Task 10). Not in this plan (by design): topics handling, review write-once, renderer, importer changes, backfill — those are Plans B and C.
- **Type consistency:** `BookRow`/`HighlightRow` field names match `METADATA_COLUMNS`/`HIGHLIGHT_COLUMNS`; `merge()` returns `list[BookRow]` consumed by `Catalog`; `highlight_to_row`/`row_to_highlight` are inverses used by Plan C importers and Plan B renderer.
- **Follow-on:** Plan B (renderer) depends on `read_books_csv`, `read_highlights`, `row_to_highlight`. Plan C (importers) depends on `write_layer`, `Catalog.find`, `write_highlights`, `highlight_to_row`, `merge`.
