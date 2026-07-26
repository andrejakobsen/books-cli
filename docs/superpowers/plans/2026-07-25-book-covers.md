# `books covers` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `books covers` CLI command that scans an Obsidian vault for book notes with a blank `cover:` field and fetches a cover from Google Books → Open Library → Amazon (ASIN only), preferring paperback where the source reports it.

**Architecture:** A new stdlib-only capability module `booktools/covers.py` exposing `register(app)`, composed of small, independently testable units (scan, per-source candidate builders, image validation, selection, apply-to-vault). All network I/O is injected as `fetch_json`/`fetch_bytes` callables so tests never touch the network. All vault writing reuses `booktools/obsidian.py` (never overwrite, never rename).

**Tech Stack:** Python 3, Typer (CLI), `urllib.request` + `json` (network), pytest (tests). Reuses `booktools.obsidian` and `booktools.resolve_path`.

---

## File Structure

- **Create** `booktools/covers.py` — the whole capability: data types, scan, source builders, validation, selection, apply, CLI command, `register`, `main`.
- **Create** `scripts/covers.py` — standalone shim importing `booktools.covers.main`.
- **Create** `tests/test_covers.py` — unit + CLI tests.
- **Modify** `booktools/cli.py` — import `covers`, add to `CAPABILITIES`.
- **Modify** `CLAUDE.md` — document the new capability (architecture section).

Reused from `booktools/obsidian.py` (do not reimplement): `frontmatter_values`,
`unquote`, `extract_wikilinks`, `BookRef`, `VaultIndex`, `cover_refs`,
`update_frontmatter`, `ensure_top_embed`, `BOOKS_DIRNAME`.

---

## Task 1: Module skeleton + data types

**Files:**
- Create: `booktools/covers.py`
- Test: `tests/test_covers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_covers.py
"""Tests for the `books covers` capability (booktools.covers)."""

from pathlib import Path

from booktools import covers


def test_dataclasses_exist():
    mb = covers.MissingBook(
        note_path=Path("/x/Books/A.md"),
        title="A Title",
        authors=["An Author"],
        isbn="123",
        amazon="B00XYZ",
    )
    assert mb.title == "A Title"
    assert mb.authors == ["An Author"]

    c = covers.Candidate(
        source="google", label="A Title — An Author",
        image_url="https://x/y.jpg", fmt=None,
    )
    assert c.source == "google"
    assert c.fmt is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_covers.py::test_dataclasses_exist -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'booktools.covers'`

- [ ] **Step 3: Write minimal implementation**

```python
# booktools/covers.py
#!/usr/bin/env python3
"""Fill missing book-note covers from Google Books, Open Library, and Amazon.

Scans an Obsidian vault for `type: book` notes whose `cover:` frontmatter is
blank/absent and fetches a cover image. Sources are tried in order — Google
Books, then Open Library (paperback editions preferred where the format is
known), then Amazon (only when the note already carries an `amazon` ASIN, by
constructing the known cover-image URL — no scraping). All network I/O is
injected so the logic is unit-testable; vault writing reuses booktools.obsidian.

Standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class MissingBook:
    """A book note whose `cover:` frontmatter is blank/absent."""
    note_path: Path
    title: str
    authors: list[str]
    isbn: str | None
    amazon: str | None


@dataclass
class Candidate:
    """A candidate cover image found for a book."""
    source: str          # "google" | "openlibrary" | "amazon"
    label: str           # matched title / author, for display
    image_url: str
    fmt: str | None      # "paperback" | "hardcover" | None (unknown)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_covers.py::test_dataclasses_exist -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add booktools/covers.py tests/test_covers.py
git commit -m "feat(covers): module skeleton and data types

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `find_missing` — scan the vault

**Files:**
- Modify: `booktools/covers.py`
- Test: `tests/test_covers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_covers.py — append

def _write_note(vault: Path, name: str, body: str) -> Path:
    books = vault / "Books"
    books.mkdir(parents=True, exist_ok=True)
    p = books / name
    p.write_text(body, encoding="utf-8")
    return p


def test_find_missing_selects_blank_cover_book_notes(tmp_path):
    # blank cover -> included
    _write_note(tmp_path, "A.md",
        '---\ntype: book\ntitle: "A"\nauthors: ["[[Ann Author]]"]\n'
        'isbn: "111"\namazon: "B001"\ncover:\n---\nbody\n')
    # non-empty cover -> excluded
    _write_note(tmp_path, "B.md",
        '---\ntype: book\ntitle: "B"\ncover: "[[Exports/x/cover.jpg]]"\n---\n')
    # absent cover key -> included
    _write_note(tmp_path, "C.md",
        '---\ntype: book\ntitle: "C"\nauthors: ["[[Cee]]"]\n---\n')
    # not a book -> excluded
    _write_note(tmp_path, "D.md", '---\ntype: author\ncover:\n---\n')

    missing = covers.find_missing(tmp_path)
    titles = sorted(m.title for m in missing)
    assert titles == ["A", "C"]

    a = next(m for m in missing if m.title == "A")
    assert a.authors == ["Ann Author"]
    assert a.isbn == "111"
    assert a.amazon == "B001"


def test_find_missing_no_books_dir_returns_empty(tmp_path):
    assert covers.find_missing(tmp_path) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_covers.py -k find_missing -v`
Expected: FAIL with `AttributeError: module 'booktools.covers' has no attribute 'find_missing'`

- [ ] **Step 3: Write minimal implementation**

Add imports and the function to `booktools/covers.py`:

```python
# add to the imports block
from booktools.obsidian import (
    BOOKS_DIRNAME,
    extract_wikilinks,
    frontmatter_values,
    unquote,
)


def _cover_is_blank(fm: dict[str, str]) -> bool:
    """True if the note has no usable `cover:` value."""
    return unquote(fm.get("cover", "")).strip() == ""


def find_missing(vault: Path) -> list[MissingBook]:
    """Return `type: book` notes under vault/Books whose cover is blank/absent."""
    out: list[MissingBook] = []
    books_dir = vault / BOOKS_DIRNAME
    if not books_dir.is_dir():
        return out
    for md in sorted(books_dir.glob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = frontmatter_values(text)
        if unquote(fm.get("type", "")) != "book":
            continue
        if not _cover_is_blank(fm):
            continue
        out.append(MissingBook(
            note_path=md,
            title=unquote(fm.get("title", "")),
            authors=extract_wikilinks(fm.get("authors", "")),
            isbn=(unquote(fm.get("isbn", "")).strip() or None),
            amazon=(unquote(fm.get("amazon", "")).strip() or None),
        ))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_covers.py -k find_missing -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add booktools/covers.py tests/test_covers.py
git commit -m "feat(covers): scan vault for notes missing a cover

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Google Books candidate builder

**Files:**
- Modify: `booktools/covers.py`
- Test: `tests/test_covers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_covers.py — append

GOOGLE_VOLUME = {
    "items": [
        {
            "volumeInfo": {
                "title": "The Deluge",
                "authors": ["Adam Tooze"],
                "imageLinks": {
                    "smallThumbnail": "http://books.google.com/x?zoom=5&edge=curl",
                    "thumbnail": "http://books.google.com/x?zoom=1&edge=curl",
                    "large": "http://books.google.com/x?zoom=3",
                },
            }
        }
    ]
}


def test_google_books_prefers_largest_and_upgrades_url():
    book = covers.MissingBook(
        note_path=None, title="The Deluge", authors=["Adam Tooze"],
        isbn=None, amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return GOOGLE_VOLUME

    cands = covers.google_books_candidates(book, fake_fetch)
    assert len(cands) == 1
    c = cands[0]
    assert c.source == "google"
    assert c.fmt is None
    # 'large' beats the thumbnails
    assert c.image_url.startswith("https://")   # http -> https
    assert "zoom=3" in c.image_url
    # title/author query when no ISBN
    assert "intitle" in captured["url"]
    assert "inauthor" in captured["url"]


def test_google_books_uses_isbn_query_when_present():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn="9780141032016", amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"items": []}

    covers.google_books_candidates(book, fake_fetch)
    assert "isbn:9780141032016" in captured["url"]


def test_google_books_no_images_returns_empty():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn=None, amazon=None)
    cands = covers.google_books_candidates(
        book, lambda url: {"items": [{"volumeInfo": {"title": "X"}}]})
    assert cands == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_covers.py -k google -v`
Expected: FAIL with `AttributeError: ... has no attribute 'google_books_candidates'`

- [ ] **Step 3: Write minimal implementation**

Add to `booktools/covers.py` (add `from urllib.parse import quote` to imports):

```python
# add to imports
from urllib.parse import quote

GOOGLE_API = "https://www.googleapis.com/books/v1/volumes"

# imageLinks keys from best to worst.
_GOOGLE_IMAGE_KEYS = (
    "extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail",
)


def _label(title: str, authors: list[str]) -> str:
    return f"{title} — {authors[0]}" if authors else title


def _upgrade_google_url(url: str) -> str:
    """Prefer https and a larger zoom; drop the page-curl overlay."""
    url = url.replace("http://", "https://")
    url = url.replace("&edge=curl", "").replace("edge=curl&", "").replace("edge=curl", "")
    return url


def google_books_candidates(book: MissingBook, fetch_json) -> list[Candidate]:
    """Query Google Books; return one candidate per volume that has an image."""
    if book.isbn:
        q = f"isbn:{book.isbn}"
    else:
        parts = [f'intitle:{book.title}']
        if book.authors:
            parts.append(f"inauthor:{book.authors[0]}")
        q = " ".join(parts)
    url = f"{GOOGLE_API}?q={quote(q)}&maxResults=5"
    try:
        data = fetch_json(url)
    except Exception:
        return []
    out: list[Candidate] = []
    for item in data.get("items", []):
        info = item.get("volumeInfo", {})
        links = info.get("imageLinks", {})
        chosen = next((links[k] for k in _GOOGLE_IMAGE_KEYS if links.get(k)), None)
        if not chosen:
            continue
        out.append(Candidate(
            source="google",
            label=_label(info.get("title", book.title), info.get("authors", [])),
            image_url=_upgrade_google_url(chosen),
            fmt=None,
        ))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_covers.py -k google -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add booktools/covers.py tests/test_covers.py
git commit -m "feat(covers): Google Books candidate lookup

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Open Library candidate builder (paperback-first)

**Files:**
- Modify: `booktools/covers.py`
- Test: `tests/test_covers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_covers.py — append

# Open Library search.json shape (title/author path)
OL_SEARCH = {
    "docs": [
        {
            "title": "Napoleon",
            "author_name": ["Andrew Roberts"],
            "cover_i": 8231856,
            "editions": {
                "docs": [
                    {"physical_format": "Hardcover", "cover_i": 111},
                    {"physical_format": "Paperback", "cover_i": 222},
                ]
            },
        }
    ]
}


def test_openlibrary_title_author_paperback_first():
    book = covers.MissingBook(
        note_path=None, title="Napoleon", authors=["Andrew Roberts"],
        isbn=None, amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return OL_SEARCH

    cands = covers.openlibrary_candidates(book, fake_fetch)
    assert cands, "expected at least one candidate"
    assert all(c.source == "openlibrary" for c in cands)
    # paperback edition ranked ahead of hardcover
    fmts = [c.fmt for c in cands]
    assert fmts.index("paperback") < fmts.index("hardcover")
    # paperback candidate points at its own cover id
    pb = next(c for c in cands if c.fmt == "paperback")
    assert "222-L.jpg" in pb.image_url
    assert "title=Napoleon" in captured["url"]
    assert "author=Andrew+Roberts" in captured["url"] or "author=Andrew%20Roberts" in captured["url"]


def test_openlibrary_isbn_path_builds_isbn_cover_url():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn="9780141032016", amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"physical_format": "Paperback"}

    cands = covers.openlibrary_candidates(book, fake_fetch)
    assert "/isbn/9780141032016.json" in captured["url"]
    assert cands and "isbn/9780141032016-L.jpg" in cands[0].image_url
    assert cands[0].fmt == "paperback"


def test_openlibrary_no_cover_returns_empty():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn=None, amazon=None)
    cands = covers.openlibrary_candidates(book, lambda url: {"docs": []})
    assert cands == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_covers.py -k openlibrary -v`
Expected: FAIL with `AttributeError: ... has no attribute 'openlibrary_candidates'`

- [ ] **Step 3: Write minimal implementation**

Add to `booktools/covers.py`:

```python
OL_SEARCH_API = "https://openlibrary.org/search.json"
OL_ISBN_API = "https://openlibrary.org/isbn/{isbn}.json"
OL_COVER_ID = "https://covers.openlibrary.org/b/id/{cid}-L.jpg"
OL_COVER_ISBN = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"


def _norm_fmt(raw: str | None) -> str | None:
    """Map a physical_format string to 'paperback'/'hardcover'/None."""
    if not raw:
        return None
    low = raw.lower()
    if "paper" in low or "softcover" in low:
        return "paperback"
    if "hard" in low:
        return "hardcover"
    return None


def _fmt_rank(fmt: str | None) -> int:
    """Sort key: paperback first, then unknown, then hardcover."""
    return {"paperback": 0, None: 1, "hardcover": 2}.get(fmt, 1)


def openlibrary_candidates(book: MissingBook, fetch_json) -> list[Candidate]:
    """Query Open Library; paperback editions (where known) rank first."""
    out: list[Candidate] = []
    label = _label(book.title, book.authors)
    if book.isbn:
        url = OL_ISBN_API.format(isbn=quote(book.isbn))
        try:
            data = fetch_json(url)
        except Exception:
            return []
        fmt = _norm_fmt(data.get("physical_format"))
        out.append(Candidate(
            source="openlibrary", label=label,
            image_url=OL_COVER_ISBN.format(isbn=quote(book.isbn)), fmt=fmt))
        return out

    params = f"title={quote(book.title)}"
    if book.authors:
        params += f"&author={quote(book.authors[0])}"
    url = f"{OL_SEARCH_API}?{params}&fields=title,author_name,cover_i,editions&limit=5"
    try:
        data = fetch_json(url)
    except Exception:
        return []
    for doc in data.get("docs", []):
        editions = doc.get("editions", {}).get("docs", [])
        for ed in editions:
            cid = ed.get("cover_i")
            if cid:
                out.append(Candidate(
                    source="openlibrary", label=label,
                    image_url=OL_COVER_ID.format(cid=cid),
                    fmt=_norm_fmt(ed.get("physical_format"))))
        if not editions and doc.get("cover_i"):
            out.append(Candidate(
                source="openlibrary", label=label,
                image_url=OL_COVER_ID.format(cid=doc["cover_i"]), fmt=None))
    out.sort(key=lambda c: _fmt_rank(c.fmt))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_covers.py -k openlibrary -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add booktools/covers.py tests/test_covers.py
git commit -m "feat(covers): Open Library lookup with paperback preference

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Amazon ASIN candidate + `gather_candidates` ordering

**Files:**
- Modify: `booktools/covers.py`
- Test: `tests/test_covers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_covers.py — append

def test_amazon_candidate_from_asin():
    book = covers.MissingBook(
        note_path=None, title="X", authors=["Y"], isbn=None, amazon="B00ABCDEFG")
    cands = covers.amazon_candidates(book)
    assert len(cands) == 1
    assert cands[0].source == "amazon"
    assert "B00ABCDEFG" in cands[0].image_url


def test_amazon_no_asin_returns_empty():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn=None, amazon=None)
    assert covers.amazon_candidates(book) == []


def test_gather_candidates_source_order():
    book = covers.MissingBook(
        note_path=None, title="Napoleon", authors=["Andrew Roberts"],
        isbn=None, amazon="B00ABCDEFG")

    def fake_fetch(url):
        if "googleapis" in url:
            return GOOGLE_VOLUME
        return OL_SEARCH

    cands = covers.gather_candidates(book, fake_fetch)
    sources = [c.source for c in cands]
    assert sources[0] == "google"
    assert "openlibrary" in sources
    assert sources[-1] == "amazon"
    # google before every openlibrary before amazon
    assert sources.index("google") < sources.index("openlibrary") < sources.index("amazon")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_covers.py -k "amazon or gather" -v`
Expected: FAIL with `AttributeError: ... has no attribute 'amazon_candidates'`

- [ ] **Step 3: Write minimal implementation**

Add to `booktools/covers.py`:

```python
AMAZON_IMAGE = "https://images-na.ssl-images-amazon.com/images/P/{asin}.01._SCLZZZZZZZ_.jpg"


def amazon_candidates(book: MissingBook) -> list[Candidate]:
    """Construct an Amazon cover URL from an existing ASIN (no scraping)."""
    if not book.amazon:
        return []
    return [Candidate(
        source="amazon",
        label=_label(book.title, book.authors),
        image_url=AMAZON_IMAGE.format(asin=book.amazon),
        fmt=None,
    )]


def gather_candidates(book: MissingBook, fetch_json) -> list[Candidate]:
    """All candidates in source-priority order: Google, Open Library, Amazon."""
    return (
        google_books_candidates(book, fetch_json)
        + openlibrary_candidates(book, fetch_json)
        + amazon_candidates(book)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_covers.py -k "amazon or gather" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add booktools/covers.py tests/test_covers.py
git commit -m "feat(covers): Amazon ASIN cover URL and ordered candidate gather

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: `is_valid_image` and `pick_cover` (auto + interactive)

**Files:**
- Modify: `booktools/covers.py`
- Test: `tests/test_covers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_covers.py — append

def test_is_valid_image():
    assert covers.is_valid_image(b"x" * 5000, "image/jpeg") is True
    assert covers.is_valid_image(b"x" * 5000, "text/html") is False   # wrong type
    assert covers.is_valid_image(b"x" * 10, "image/gif") is False      # too small
    assert covers.is_valid_image(b"x" * 5000, None) is False           # unknown type


def _cand(source):
    return covers.Candidate(source=source, label="L", image_url=f"http://{source}", fmt=None)


def test_pick_cover_auto_first_valid():
    cands = [_cand("google"), _cand("openlibrary")]

    def fetch_bytes(url):
        if url.endswith("google"):
            return (b"x" * 5, "image/jpeg")       # too small -> invalid
        return (b"x" * 5000, "image/jpeg")        # valid

    picked = covers.pick_cover(cands, fetch_bytes, interactive=False, prompt=None)
    assert picked is not None
    cand, data = picked
    assert cand.source == "openlibrary"
    assert data == b"x" * 5000


def test_pick_cover_auto_none_when_all_invalid():
    cands = [_cand("google")]
    picked = covers.pick_cover(
        cands, lambda url: (b"", "text/html"), interactive=False, prompt=None)
    assert picked is None


def test_pick_cover_interactive_next_then_accept():
    cands = [_cand("google"), _cand("openlibrary")]
    answers = iter(["next", "accept"])

    def fetch_bytes(url):
        return (b"x" * 5000, "image/jpeg")

    picked = covers.pick_cover(
        cands, fetch_bytes, interactive=True, prompt=lambda c: next(answers))
    assert picked[0].source == "openlibrary"


def test_pick_cover_interactive_quit_raises():
    cands = [_cand("google")]
    import pytest
    with pytest.raises(covers.QuitRequested):
        covers.pick_cover(
            cands, lambda url: (b"x" * 5000, "image/jpeg"),
            interactive=True, prompt=lambda c: "quit")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_covers.py -k "valid_image or pick_cover" -v`
Expected: FAIL with `AttributeError: ... has no attribute 'is_valid_image'`

- [ ] **Step 3: Write minimal implementation**

Add to `booktools/covers.py`:

```python
MIN_IMAGE_BYTES = 1000


class QuitRequested(Exception):
    """Raised from pick_cover when the user chooses to quit the whole run."""


def is_valid_image(data: bytes, content_type: str | None) -> bool:
    """Heuristic: content-type is an image and payload is non-trivially sized."""
    if not content_type or not content_type.lower().startswith("image/"):
        return False
    return len(data) >= MIN_IMAGE_BYTES


def pick_cover(candidates, fetch_bytes, *, interactive, prompt):
    """Choose a cover.

    Automatic (interactive=False): download each candidate in order; return the
    first (candidate, bytes) that validates, else None.

    Interactive: for each candidate call prompt(candidate) ->
    "accept" | "next" | "skip" | "quit". On accept, download+validate; if that
    fails, fall through to the next candidate. "skip" returns None (skip book);
    "quit" raises QuitRequested.
    """
    for cand in candidates:
        if interactive:
            choice = prompt(cand)
            if choice == "skip":
                return None
            if choice == "quit":
                raise QuitRequested()
            if choice == "next":
                continue
            # choice == "accept" -> fall through to download
        try:
            data, ctype = fetch_bytes(cand.image_url)
        except Exception:
            continue
        if is_valid_image(data, ctype):
            return (cand, data)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_covers.py -k "valid_image or pick_cover" -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add booktools/covers.py tests/test_covers.py
git commit -m "feat(covers): image validation and auto/interactive selection

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: `apply_cover` — write image + frontmatter + embed

**Files:**
- Modify: `booktools/covers.py`
- Test: `tests/test_covers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_covers.py — append

def test_apply_cover_writes_file_and_frontmatter(tmp_path):
    from booktools.obsidian import VaultIndex

    note = _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n\nbody\n')
    book = covers.MissingBook(
        note_path=note, title="Napoleon", authors=["Andrew Roberts"],
        isbn=None, amazon=None)
    index = VaultIndex(tmp_path)

    covers.apply_cover(index, book, b"\xff\xd8\xffJPEGDATA" + b"x" * 2000)

    # cover.jpg written under Exports/<Author>/<Title>/
    cover_file = tmp_path / "Exports" / "Andrew Roberts" / "Napoleon" / "cover.jpg"
    assert cover_file.is_file()

    text = note.read_text(encoding="utf-8")
    # frontmatter cover filled with a wikilink to the exported cover
    assert 'cover: "[[Exports/Andrew Roberts/Napoleon/cover.jpg]]"' in text
    # body embed added; original body preserved
    assert "![[Exports/Andrew Roberts/Napoleon/cover.jpg]]" in text
    assert "body" in text


def test_apply_cover_idempotent(tmp_path):
    from booktools.obsidian import VaultIndex

    note = _write_note(tmp_path, "N - A.md",
        '---\ntype: book\ntitle: "N"\nauthors: ["[[A]]"]\ncover:\n---\n')
    book = covers.MissingBook(
        note_path=note, title="N", authors=["A"], isbn=None, amazon=None)
    index = VaultIndex(tmp_path)

    covers.apply_cover(index, book, b"x" * 2000)
    first = note.read_text(encoding="utf-8")
    covers.apply_cover(index, book, b"x" * 2000)
    second = note.read_text(encoding="utf-8")
    assert first == second   # cover already set -> no duplicate embed/frontmatter
    assert second.count("![[Exports/A/N/cover.jpg]]") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_covers.py -k apply_cover -v`
Expected: FAIL with `AttributeError: ... has no attribute 'apply_cover'`

- [ ] **Step 3: Write minimal implementation**

Add to `booktools/covers.py` (extend the obsidian import with `BookRef, VaultIndex, cover_refs, update_frontmatter, ensure_top_embed`):

```python
# extend the booktools.obsidian import block
from booktools.obsidian import (
    BOOKS_DIRNAME,
    BookRef,
    VaultIndex,
    cover_refs,
    ensure_top_embed,
    extract_wikilinks,
    frontmatter_values,
    unquote,
    update_frontmatter,
)


def apply_cover(index: VaultIndex, book: MissingBook, image: bytes) -> None:
    """Write the cover image and fill the note's cover frontmatter + embed."""
    ref = BookRef(
        title=book.title, authors=book.authors,
        isbn=book.isbn, amazon=book.amazon)
    export_dir = index.export_dir(ref)
    export_dir.mkdir(parents=True, exist_ok=True)
    (export_dir / "cover.jpg").write_bytes(image)

    cover_fm, cover_embed = cover_refs(book.note_path, export_dir)
    text = book.note_path.read_text(encoding="utf-8")
    text = update_frontmatter(text, {"cover": cover_fm})
    text = ensure_top_embed(text, cover_embed)
    book.note_path.write_text(text, encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_covers.py -k apply_cover -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add booktools/covers.py tests/test_covers.py
git commit -m "feat(covers): write cover image and fill note frontmatter/embed

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Default network fetchers + terminal prompt

**Files:**
- Modify: `booktools/covers.py`
- Test: `tests/test_covers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_covers.py — append

def test_terminal_prompt_maps_keys(monkeypatch):
    answers = iter(["y", "n", "s", "q", "?"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    cand = _cand("google")
    assert covers._terminal_prompt(cand) == "accept"
    assert covers._terminal_prompt(cand) == "next"
    assert covers._terminal_prompt(cand) == "skip"
    assert covers._terminal_prompt(cand) == "quit"
    # unrecognized input defaults to "next" (safe, non-destructive)
    assert covers._terminal_prompt(cand) == "next"
```

Note: the default `fetch_json` / `fetch_bytes` do real network I/O and are not
unit-tested here; they are exercised implicitly and kept tiny.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_covers.py -k terminal_prompt -v`
Expected: FAIL with `AttributeError: ... has no attribute '_terminal_prompt'`

- [ ] **Step 3: Write minimal implementation**

Add to `booktools/covers.py` (add `import json` and `from urllib.request import Request, urlopen`):

```python
# add to imports
import json
from urllib.request import Request, urlopen

USER_AGENT = "booktools-covers/1.0 (+https://github.com/)"
HTTP_TIMEOUT = 15


def default_fetch_json(url: str) -> dict:
    """GET *url* and parse JSON (default injected fetcher)."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def default_fetch_bytes(url: str) -> tuple[bytes, str | None]:
    """GET *url* returning (body, content_type) (default injected fetcher)."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read(), resp.headers.get("Content-Type")


def _terminal_prompt(cand: Candidate) -> str:
    """Ask the user about one candidate; map keys to an action string."""
    fmt = f" [{cand.fmt}]" if cand.fmt else ""
    print(f"  {cand.source}: {cand.label}{fmt}\n    {cand.image_url}")
    ans = input("  accept [y] / next [n] / skip book [s] / quit [q]? ").strip().lower()
    return {"y": "accept", "n": "next", "s": "skip", "q": "quit"}.get(ans, "next")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_covers.py -k terminal_prompt -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add booktools/covers.py tests/test_covers.py
git commit -m "feat(covers): default network fetchers and terminal prompt

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: `run` orchestrator (scan → gather → pick → apply)

**Files:**
- Modify: `booktools/covers.py`
- Test: `tests/test_covers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_covers.py — append

def test_run_fetches_and_applies(tmp_path):
    _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')
    # a note that already has a cover -> untouched, not counted
    _write_note(tmp_path, "Done.md",
        '---\ntype: book\ntitle: "Done"\ncover: "[[x/cover.jpg]]"\n---\n')

    def fetch_json(url):
        return GOOGLE_VOLUME if "googleapis" in url else {"docs": []}

    def fetch_bytes(url):
        return (b"x" * 3000, "image/jpeg")

    stats = covers.run(
        tmp_path, interactive=False, dry_run=False, limit=None,
        fetch_json=fetch_json, fetch_bytes=fetch_bytes, prompt=None)

    assert stats["missing"] == 1
    assert stats["fetched"] == 1
    assert stats["by_source"]["google"] == 1
    cover_file = tmp_path / "Exports" / "Andrew Roberts" / "Napoleon" / "cover.jpg"
    assert cover_file.is_file()


def test_run_dry_run_writes_nothing(tmp_path):
    _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')

    stats = covers.run(
        tmp_path, interactive=False, dry_run=True, limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"), prompt=None)

    assert stats["fetched"] == 1   # would-fetch is still counted
    assert not (tmp_path / "Exports").exists()


def test_run_limit_caps_processing(tmp_path):
    for i in range(3):
        _write_note(tmp_path, f"B{i} - A.md",
            f'---\ntype: book\ntitle: "B{i}"\nauthors: ["[[A]]"]\ncover:\n---\n')

    stats = covers.run(
        tmp_path, interactive=False, dry_run=True, limit=2,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"), prompt=None)
    assert stats["processed"] == 2


def test_run_quit_stops_early(tmp_path):
    for i in range(3):
        _write_note(tmp_path, f"B{i} - A.md",
            f'---\ntype: book\ntitle: "B{i}"\nauthors: ["[[A]]"]\ncover:\n---\n')

    stats = covers.run(
        tmp_path, interactive=True, dry_run=False, limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"),
        prompt=lambda c: "quit")
    assert stats["fetched"] == 0


def test_note_to_missing_eligible_and_ineligible(tmp_path):
    note = _write_note(tmp_path, "A - Ann.md",
        '---\ntype: book\ntitle: "A"\nauthors: ["[[Ann]]"]\ncover:\n---\n')
    mb = covers.note_to_missing(note)
    assert mb is not None
    assert mb.title == "A" and mb.authors == ["Ann"]

    has_cover = _write_note(tmp_path, "B - Bee.md",
        '---\ntype: book\ntitle: "B"\ncover: "[[x/cover.jpg]]"\n---\n')
    assert covers.note_to_missing(has_cover) is None   # cover already set

    not_book = _write_note(tmp_path, "C.md", '---\ntype: author\ncover:\n---\n')
    assert covers.note_to_missing(not_book) is None    # wrong type


def test_run_single_book_only_processes_that_note(tmp_path):
    target = _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')
    # another missing-cover book that must NOT be touched
    _write_note(tmp_path, "Other - X.md",
        '---\ntype: book\ntitle: "Other"\nauthors: ["[[X]]"]\ncover:\n---\n')

    stats = covers.run(
        tmp_path, interactive=False, dry_run=False, limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"),
        prompt=None, book_path=target)

    assert stats["scanned"] == 1
    assert stats["missing"] == 1
    assert stats["fetched"] == 1
    assert (tmp_path / "Exports" / "Andrew Roberts" / "Napoleon" / "cover.jpg").is_file()
    assert not (tmp_path / "Exports" / "X").exists()


def test_run_single_book_ineligible_is_no_op(tmp_path):
    target = _write_note(tmp_path, "Done - Y.md",
        '---\ntype: book\ntitle: "Done"\ncover: "[[x/cover.jpg]]"\n---\n')
    stats = covers.run(
        tmp_path, interactive=False, dry_run=False, limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"),
        prompt=None, book_path=target)
    assert stats["missing"] == 0
    assert stats["fetched"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_covers.py -k "run_ or note_to_missing" -v`
Expected: FAIL with `AttributeError: ... has no attribute 'run'` (and `note_to_missing`)

- [ ] **Step 3: Write minimal implementation**

First add `note_to_missing` and **refactor the existing `find_missing`** (from Task 2)
to reuse it — replace the body of `find_missing` with the version below so the
single-note and full-scan paths share one eligibility check:

```python
def note_to_missing(note_path: Path) -> MissingBook | None:
    """Build a MissingBook for a single note, or None if it is not eligible.

    Eligible means a readable `type: book` note whose `cover:` is blank/absent.
    Returns None for unreadable files, non-book notes, or notes that already have
    a cover.
    """
    try:
        text = note_path.read_text(encoding="utf-8")
    except OSError:
        return None
    fm = frontmatter_values(text)
    if unquote(fm.get("type", "")) != "book":
        return None
    if not _cover_is_blank(fm):
        return None
    return MissingBook(
        note_path=note_path,
        title=unquote(fm.get("title", "")),
        authors=extract_wikilinks(fm.get("authors", "")),
        isbn=(unquote(fm.get("isbn", "")).strip() or None),
        amazon=(unquote(fm.get("amazon", "")).strip() or None),
    )


def find_missing(vault: Path) -> list[MissingBook]:
    """Return `type: book` notes under vault/Books whose cover is blank/absent."""
    out: list[MissingBook] = []
    books_dir = vault / BOOKS_DIRNAME
    if not books_dir.is_dir():
        return out
    for md in sorted(books_dir.glob("*.md")):
        book = note_to_missing(md)
        if book is not None:
            out.append(book)
    return out
```

Then add `run`, which processes a single note when `book_path` is given, else
scans the whole vault:

```python
def run(vault, *, interactive, dry_run, limit,
        fetch_json, fetch_bytes, prompt, book_path=None):
    """Fetch a cover for books missing one.

    When *book_path* is given, only that single note is processed (the rest of the
    vault is left alone); otherwise the whole vault is scanned. Returns a stats
    dict: scanned/missing/processed/fetched/not_found/by_source.
    """
    if book_path is not None:
        one = note_to_missing(book_path)
        missing = [one] if one is not None else []
        scanned = 1
    else:
        missing = find_missing(vault)
        scanned = (len(list((vault / BOOKS_DIRNAME).glob("*.md")))
                   if (vault / BOOKS_DIRNAME).is_dir() else 0)
    index = VaultIndex(vault)
    stats = {
        "scanned": scanned,
        "missing": len(missing),
        "processed": 0,
        "fetched": 0,
        "not_found": 0,
        "by_source": {"google": 0, "openlibrary": 0, "amazon": 0},
    }
    todo = missing if limit is None else missing[:limit]
    for book in todo:
        stats["processed"] += 1
        if interactive:
            print(f"\n{book.title} — {', '.join(book.authors) or 'Unknown'}")
        candidates = gather_candidates(book, fetch_json)
        try:
            picked = pick_cover(
                candidates, fetch_bytes, interactive=interactive, prompt=prompt)
        except QuitRequested:
            print("Quit.")
            break
        if picked is None:
            stats["not_found"] += 1
            print(f"  no cover: {book.title}")
            continue
        cand, data = picked
        stats["fetched"] += 1
        stats["by_source"][cand.source] = stats["by_source"].get(cand.source, 0) + 1
        if dry_run:
            print(f"  [dry-run] {cand.source}: {cand.image_url}")
        else:
            apply_cover(index, book, data)
            print(f"  ✓ {cand.source}: {book.title}")
    return stats
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_covers.py -k "run_ or note_to_missing" -v`
Expected: PASS (6 tests). Also run the whole file to confirm the `find_missing`
refactor didn't regress Task 2: `uv run pytest tests/test_covers.py -v`.

- [ ] **Step 5: Commit**

```bash
git add booktools/covers.py tests/test_covers.py
git commit -m "feat(covers): run orchestrator with single-book, dry-run, limit, quit

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: CLI command, `register`, `main`

**Files:**
- Modify: `booktools/covers.py`
- Test: `tests/test_covers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_covers.py — append

def test_cli_covers_dry_run(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from booktools.cli import app

    _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')

    # stub the network so the CLI test stays offline
    monkeypatch.setattr(covers, "default_fetch_json", lambda url: GOOGLE_VOLUME)
    monkeypatch.setattr(
        covers, "default_fetch_bytes", lambda url: (b"x" * 3000, "image/jpeg"))

    result = CliRunner().invoke(
        app, ["covers", "-o", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "missing" in result.output.lower()
    assert not (tmp_path / "Exports").exists()


def test_cli_covers_registered():
    from booktools.cli import app
    names = {c.name for c in app.registered_commands}
    assert "covers" in names


def test_cli_covers_single_book_interactive_by_default(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from booktools.cli import app

    note = _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')
    # another missing-cover book that must NOT be touched
    _write_note(tmp_path, "Other - X.md",
        '---\ntype: book\ntitle: "Other"\nauthors: ["[[X]]"]\ncover:\n---\n')

    monkeypatch.setattr(covers, "default_fetch_json", lambda url: GOOGLE_VOLUME)
    monkeypatch.setattr(
        covers, "default_fetch_bytes", lambda url: (b"x" * 3000, "image/jpeg"))
    # single-book mode is interactive by default -> the prompt is used; accept it.
    monkeypatch.setattr(covers, "_terminal_prompt", lambda c: "accept")

    result = CliRunner().invoke(app, ["covers", "-b", str(note)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "Exports" / "Andrew Roberts" / "Napoleon" / "cover.jpg").is_file()
    assert not (tmp_path / "Exports" / "X").exists()


def test_cli_covers_single_book_rejects_note_outside_books(tmp_path):
    from typer.testing import CliRunner
    from booktools.cli import app

    stray = tmp_path / "stray.md"
    stray.write_text('---\ntype: book\ntitle: "S"\ncover:\n---\n', encoding="utf-8")
    result = CliRunner().invoke(app, ["covers", "-b", str(stray)])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_covers.py -k "cli_covers" -v`
Expected: FAIL (`covers` command not registered / no `register`)

- [ ] **Step 3: Write minimal implementation**

Add to `booktools/covers.py` (add `import typer` and `from booktools import resolve_path`):

```python
# add to imports
import typer
from booktools import resolve_path


def covers_command(
    output: Path = typer.Option(
        Path("Obsidian"),
        "--output", "-o",
        help="Obsidian vault to scan. Relative paths resolve against the current directory.",
    ),
    book: Path | None = typer.Option(
        None, "--book", "-b",
        help="Fetch a cover for a single book note (path to a file under Books/). "
             "Interactive by default; the vault is inferred from the path, so --output is ignored.",
    ),
    interactive: bool | None = typer.Option(
        None, "--interactive/--no-interactive",
        help="Confirm each candidate: accept / next / skip book / quit. "
             "Defaults on for a single --book, off for a full-vault scan.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Report the chosen cover per book without writing anything.",
    ),
    limit: int | None = typer.Option(
        None, "--limit",
        help="Process at most this many books missing a cover (ignored with --book).",
    ),
) -> None:
    """Find book notes missing a cover and fetch one.

    Scans OUTPUT (an Obsidian vault) for 'type: book' notes whose 'cover:'
    frontmatter is blank and fetches a cover from Google Books, then Open Library
    (paperback editions preferred where known), then Amazon (only when the note
    already carries an 'amazon' ASIN). By default the best match is written
    automatically; use --interactive to approve each candidate, or --dry-run to
    preview. Pass --book PATH to fetch a cover for a single note under Books/
    (interactive by default). Existing covers, note bodies, and filenames are
    never changed.
    """
    if book is not None:
        note = resolve_path(book, Path.cwd())
        if not note.is_file():
            raise typer.BadParameter(f"book note not found: {note}", param_hint="--book")
        if note.parent.name != BOOKS_DIRNAME:
            raise typer.BadParameter(
                f"book note must live under a '{BOOKS_DIRNAME}/' folder: {note}",
                param_hint="--book")
        vault = note.parents[1]
    else:
        note = None
        vault = resolve_path(output, Path.cwd())
        if not (vault / BOOKS_DIRNAME).is_dir():
            raise typer.BadParameter(
                f"no Books/ folder in vault: {vault}", param_hint="--output")

    # Interactive is on by default for a single book, off for a full scan,
    # unless the user set it explicitly with --interactive/--no-interactive.
    if interactive is None:
        interactive = book is not None

    stats = run(
        vault, interactive=interactive, dry_run=dry_run, limit=limit,
        fetch_json=default_fetch_json, fetch_bytes=default_fetch_bytes,
        prompt=_terminal_prompt, book_path=note,
    )
    bs = stats["by_source"]
    typer.echo(
        f"Scanned {stats['scanned']} notes, {stats['missing']} missing covers → "
        f"{stats['fetched']} fetched "
        f"(google {bs['google']}, openlibrary {bs['openlibrary']}, amazon {bs['amazon']}), "
        f"{stats['not_found']} not found."
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("covers")(covers_command)


def main() -> None:
    """Standalone entry point so the shim script keeps working on its own."""
    typer.run(covers_command)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_covers.py -k "cli_covers" -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add booktools/covers.py tests/test_covers.py
git commit -m "feat(covers): Typer command, register, and main entrypoint

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: Wire into the CLI hub

**Files:**
- Modify: `booktools/cli.py`

- [ ] **Step 1: Write the failing test**

The `test_cli_covers_registered` test from Task 10 already covers this, but it
passed via `typer.run` isolation only after Task 10. Confirm it passes through the
shared hub app by running the existing CLI registration test.

Run: `uv run pytest tests/test_cli.py -v`
Expected: currently PASSES but does not yet include `covers` — proceed to wire it.

- [ ] **Step 2: Modify `booktools/cli.py`**

```python
from booktools import (
    calibre_obsidian,
    covers,
    goodreads_obsidian,
    highlighted_obsidian,
    kobo_export,
    readwise_obsidian,
)

# Modules that expose a register(app) function. Add new capabilities here.
CAPABILITIES = (
    calibre_obsidian,
    covers,
    goodreads_obsidian,
    highlighted_obsidian,
    kobo_export,
    readwise_obsidian,
)
```

- [ ] **Step 3: Run the CLI + covers tests**

Run: `uv run pytest tests/test_cli.py tests/test_covers.py -v`
Expected: PASS (including `test_cli_covers_registered` and `test_cli_covers_dry_run`)

- [ ] **Step 4: Verify the command appears in help**

Run: `uv run books --help`
Expected: `covers` listed among the subcommands.

- [ ] **Step 5: Commit**

```bash
git add booktools/cli.py
git commit -m "feat(covers): register the covers command on the books CLI

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12: Standalone shim

**Files:**
- Create: `scripts/covers.py`

- [ ] **Step 1: Create the shim**

```python
# scripts/covers.py
#!/usr/bin/env python3
"""Standalone shim: `python covers.py [-o VAULT] [--interactive] [--dry-run]`.

The real implementation lives in ``booktools.covers``. This keeps the script
runnable on its own while there is a single source of truth. For the full CLI
with all capabilities, use ``books`` (see pyproject.toml).
"""

from booktools.covers import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it imports and shows help**

Run: `uv run python scripts/covers.py --help`
Expected: help text for the covers command (exit code 0).

- [ ] **Step 3: Commit**

```bash
git add scripts/covers.py
git commit -m "feat(covers): standalone shim script

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 13: Documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the capabilities list in `CLAUDE.md`**

In the Architecture section, update the capability count from "Five" to "Six" and
add a bullet describing `covers` after the `readwise` bullet:

```markdown
- `booktools/covers.py` → `covers` — scans an existing vault for `type: book` notes with a blank `cover:` field and fetches a cover image. Sources are tried in order — Google Books, then Open Library (paperback editions preferred where `physical_format` is known), then Amazon (only when the note already has an `amazon` ASIN, by building the known cover-image URL — no scraping). Stdlib-only (`urllib`); all network I/O is injected for testing. Writes `cover.jpg` into `Exports/<Author>/<Title>/` and fills the note's `cover:` frontmatter + top embed via the shared `obsidian.py` helpers (never overwriting an existing cover). Default mode auto-picks the best match; `--interactive` approves each candidate, `--dry-run` previews, `--limit N` caps the run. `--book PATH` targets a single note under `Books/` (vault inferred from the path) and is interactive by default.
```

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest -q`
Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(covers): document the covers capability in CLAUDE.md

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 14: Fix Open Library paperback preference on the title/author path

**Why:** The title/author OL path requested editions inline via
`search.json?...&fields=editions`, but the live API returns an empty
`editions.docs` for that query shape — so the paperback-sorting branch never ran
in production and paperback preference only worked on the ISBN path. The reliable
way to get editions (with `physical_format` and `covers`) is the works-editions
endpoint: `search.json` gives a work `key` (`/works/OL…W`), then
`https://openlibrary.org/works/OL…W/editions.json` returns `entries` each with
`physical_format` and a `covers` list. The old unit test masked the gap by using
hand-crafted `editions.docs` that don't match the real API.

**Files:**
- Modify: `booktools/covers.py`
- Test: `tests/test_covers.py`

- [ ] **Step 1: Replace the misleading test and add coverage**

Replace the existing `test_openlibrary_title_author_paperback_first` and the
`OL_SEARCH` fixture with realistic ones, and add a fallback test. Find the current
`OL_SEARCH = {...}` fixture and `test_openlibrary_title_author_paperback_first`
function in `tests/test_covers.py` and replace BOTH with:

```python
# Open Library title/author path: search.json returns a work key; then
# /works/<id>/editions.json returns editions with physical_format + covers.
OL_SEARCH = {"docs": [{"key": "/works/OL1W", "cover_i": 999}]}
OL_EDITIONS = {"entries": [
    {"physical_format": "Hardcover", "covers": [111]},
    {"physical_format": "Paperback", "covers": [222]},
]}


def test_openlibrary_title_author_paperback_first():
    book = covers.MissingBook(
        note_path=None, title="Napoleon", authors=["Andrew Roberts"],
        isbn=None, amazon=None)
    urls = []

    def fake_fetch(url):
        urls.append(url)
        return OL_EDITIONS if "editions.json" in url else OL_SEARCH

    cands = covers.openlibrary_candidates(book, fake_fetch)
    assert cands, "expected at least one candidate"
    assert all(c.source == "openlibrary" for c in cands)
    # paperback edition ranked ahead of hardcover
    fmts = [c.fmt for c in cands]
    assert fmts.index("paperback") < fmts.index("hardcover")
    pb = next(c for c in cands if c.fmt == "paperback")
    assert "222-L.jpg" in pb.image_url
    # search queried by title/author, then editions fetched for the work key
    assert any("title=Napoleon" in u for u in urls)
    assert any("/works/OL1W/editions.json" in u for u in urls)


def test_openlibrary_falls_back_to_search_cover_when_no_editions():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn=None, amazon=None)

    def fake_fetch(url):
        if "editions.json" in url:
            return {"entries": []}
        return {"docs": [{"key": "/works/OL9W", "cover_i": 555}]}

    cands = covers.openlibrary_candidates(book, fake_fetch)
    assert cands and "555-L.jpg" in cands[0].image_url
    assert cands[0].fmt is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_covers.py -k openlibrary -v`
Expected: `test_openlibrary_title_author_paperback_first` FAILS (old code fetches
`fields=editions` and never hits `/works/.../editions.json`); the fallback test
may also fail.

- [ ] **Step 3: Rewrite the title/author branch of `openlibrary_candidates`**

Add the editions-endpoint constant near the other OL constants:

```python
OL_WORK_EDITIONS = "https://openlibrary.org{work}/editions.json?limit=50"
```

Leave the ISBN path unchanged. Replace the title/author search block (the part
after the `if book.isbn:` branch) with this version, which fetches the best work's
editions for format-aware, paperback-first candidates and falls back to the
work-level `cover_i` when no edition cover is found:

```python
    params = f"title={quote(book.title)}"
    if book.authors:
        params += f"&author={quote(book.authors[0])}"
    url = f"{OL_SEARCH_API}?{params}&fields=key,cover_i&limit=5"
    try:
        data = fetch_json(url) or {}
    except Exception:
        return []
    docs = data.get("docs", [])

    # Expand the best-matching work's editions so we can prefer paperback where
    # the format is known. Only the first work with editions is expanded (bounds
    # the number of requests); other works fall back to their work-level cover.
    for doc in docs:
        work_key = doc.get("key")
        if not work_key:
            continue
        try:
            eds = fetch_json(OL_WORK_EDITIONS.format(work=work_key)) or {}
        except Exception:
            eds = {}
        seen: set[int] = set()
        for ed in eds.get("entries", []):
            covers_list = ed.get("covers") or []
            cid = next((c for c in covers_list if isinstance(c, int) and c > 0), None)
            if cid is None or cid in seen:
                continue
            seen.add(cid)
            out.append(Candidate(
                source="openlibrary", label=label,
                image_url=OL_COVER_ID.format(cid=cid),
                fmt=_norm_fmt(ed.get("physical_format"))))
        if out:
            break

    # Fallback: no edition covers found -> use work-level cover thumbnails.
    if not out:
        for doc in docs:
            if doc.get("cover_i"):
                out.append(Candidate(
                    source="openlibrary", label=label,
                    image_url=OL_COVER_ID.format(cid=doc["cover_i"]), fmt=None))
    out.sort(key=lambda c: _fmt_rank(c.fmt))
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_covers.py -k openlibrary -v`
Expected: PASS. Then run the whole file: `uv run pytest tests/test_covers.py -v`
(the `gather_candidates` test still passes because its OL fetcher returns a doc
with `cover_i`, so the fallback yields one OL candidate).

- [ ] **Step 5: Commit**

```bash
git add booktools/covers.py tests/test_covers.py
git commit -m "fix(covers): real Open Library paperback preference via editions endpoint

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Run the whole suite:** `uv run pytest -q` → all green.
- [ ] **Smoke-test help:** `uv run books covers --help` → shows `--output`, `--interactive`, `--dry-run`, `--limit`.
- [ ] **Optional live run:** `uv run books covers -o path/to/vault --dry-run --limit 3` against a real vault to confirm network paths work end-to-end.

---

## Self-Review Notes

- **Spec coverage:** module+shim+register (Tasks 1,10,11,12); find_missing/blank-cover-only (Task 2); Google/OpenLibrary-paperback/Amazon-ASIN + ordering (Tasks 3,4,5); image validation heuristic (Task 6); auto + interactive selection with reject-to-next (Task 6,9); dry-run + limit (Task 9,10); reuse of obsidian layer, never-overwrite (Task 7); stdlib-only injected I/O (Task 8); output summary (Task 10); docs (Task 13). All spec sections mapped.
- **Type consistency:** `MissingBook`/`Candidate` fields, `fetch_json(url)->dict`, `fetch_bytes(url)->(bytes, str|None)`, `pick_cover(...)->(Candidate,bytes)|None`, `QuitRequested`, and `run(...)->stats` are used consistently across tasks.
- **No placeholders:** every code step contains full code; every run step has an expected result.
