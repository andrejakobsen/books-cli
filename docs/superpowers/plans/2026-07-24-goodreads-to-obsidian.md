# Goodreads → Obsidian Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `goodreads-to-obsidian` capability to the `books` CLI that turns a Goodreads CSV export (read books only, by default) into Obsidian notes, merging with existing Calibre notes without ever overwriting non-empty data.

**Architecture:** Extract shared Obsidian helpers into a new `booktools/obsidian.py` — including a canonical book-note property schema and an `update_frontmatter()` merge that fills only absent/blank keys. Both `calibre_obsidian.py` (refactored to be merge-based) and the new `goodreads_obsidian.py` build a `{property: formatted_value}` dict and feed it through `update_frontmatter()`. Matching uses ISBN first, then a strict normalized Author/Title fallback.

**Tech Stack:** Python 3.9+ stdlib (`csv`, `re`, `unicodedata`, `xml`, `html.parser`), Typer, pytest, uv.

---

## File Structure

- **Create** `booktools/obsidian.py` — shared formatting/filesystem helpers, canonical schema, `update_frontmatter`, frontmatter reading helpers, HTML→Markdown.
- **Modify** `booktools/calibre_obsidian.py` — import shared helpers; emit full canonical schema; merge-based `convert`.
- **Create** `booktools/goodreads_obsidian.py` — CSV parsing, normalization/matching, `convert`, Typer command, `register`, `main`.
- **Modify** `booktools/cli.py` — add `goodreads_obsidian` to `CAPABILITIES`.
- **Create** `scripts/goodreads_to_obsidian.py` — standalone shim.
- **Create** `tests/test_obsidian.py` — unit tests for the shared module.
- **Create** `tests/test_goodreads_obsidian.py` — importer tests.
- **Modify** `tests/test_calibre_to_obsidian.py` — new-schema + merge assertions.
- **Modify** `README.md` — document the new command + shim.

Run tests throughout with: `uv run pytest -q`

---

## Task 1: Shared `booktools/obsidian.py`

**Files:**
- Create: `booktools/obsidian.py`
- Test: `tests/test_obsidian.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_obsidian.py`:

```python
"""Unit tests for the shared Obsidian helpers."""

from booktools import obsidian as ob


def test_safe_filename_replaces_illegal_chars():
    assert ob.safe_filename("A: B / C?") == "A_ B _ C_"
    assert ob.safe_filename("  spaced  out  ") == "spaced out"
    assert ob.safe_filename("trailing. ") == "trailing"
    assert ob.safe_filename("///") == "_"


def test_yaml_quote_and_links():
    assert ob.yaml_quote('he said "hi"') == '"he said \\"hi\\""'
    assert ob.wikilink("A|B#C") == "[[A-BC]]"
    assert ob.link_list(["X", "Y"]) == '["[[X]]", "[[Y]]"]'
    assert ob.plain_list(["read", "fiction"]) == '["read", "fiction"]'


def test_update_frontmatter_fills_blank_only():
    note = '---\ntype: book\ntitle: "Keep"\nrating:\n---\n\nbody text\n'
    out = ob.update_frontmatter(note, {
        "title": ob.yaml_quote("New"),   # existing non-empty -> untouched
        "rating": "5",                   # existing blank -> filled
        "status": ob.yaml_quote("read"), # absent -> added
    })
    assert 'title: "Keep"' in out
    assert "rating: 5" in out
    assert 'status: "read"' in out
    assert "body text" in out  # body preserved


def test_update_frontmatter_no_frontmatter_prepends_block():
    out = ob.update_frontmatter("just a body\n", {"title": ob.yaml_quote("T")})
    assert out.startswith("---\n")
    assert 'title: "T"' in out
    assert "just a body" in out


def test_update_frontmatter_empty_update_adds_placeholder():
    out = ob.update_frontmatter("---\ntype: book\n---\n", {"pages": ""})
    assert "pages:" in out


def test_frontmatter_values_and_extractors():
    note = '---\ntype: book\ntitle: "Napoleon: A Life"\nisbn: "9780698176287"\nauthors: ["[[Andrew Roberts]]"]\n---\nbody\n'
    fm = ob.frontmatter_values(note)
    assert ob.unquote(fm["title"]) == "Napoleon: A Life"
    assert ob.unquote(fm["isbn"]) == "9780698176287"
    assert ob.extract_wikilinks(fm["authors"]) == ["Andrew Roberts"]


def test_html_to_markdown_list():
    md = ob.html_to_markdown("<p>Intro</p><ul><li>one</li><li>two</li></ul>")
    assert "Intro" in md and "- one" in md and "- two" in md
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_obsidian.py -q`
Expected: FAIL (module `booktools.obsidian` does not exist).

- [ ] **Step 3: Create `booktools/obsidian.py`**

```python
"""Shared helpers for writing Obsidian book-note vaults.

Both the Calibre and Goodreads importers write book notes with the same YAML
frontmatter schema and the same "never overwrite" rule, so their data (plus your
own manual edits) composes without clobbering. Everything they share lives here.

Standard library only.
"""

from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path


# --- Canonical property schema ---------------------------------------------

# Order in which book-note frontmatter keys are emitted. Every book note carries
# all of these (empty when unknown) so any field can be filled later by the other
# importer or by hand.
BOOK_PROPERTY_ORDER = (
    "type",
    "title",
    "authors",
    "genres",
    "series",
    "series_index",
    "publisher",
    "published",
    "language",
    "pages",
    "status",
    "shelves",
    "rating",
    "isbn",
    "amazon",
    "google",
    "uuid",
    "calibre_id",
    "date_added",
    "date_read",
    "cover",
)


# --- YAML / link formatting -------------------------------------------------

def yaml_quote(value: str) -> str:
    """Double-quote a scalar, escaping backslashes and quotes."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def wikilink(name: str) -> str:
    """Wrap *name* in an Obsidian [[wikilink]], sanitizing illegal chars."""
    clean = name.replace("[", "(").replace("]", ")").replace("|", "-")
    clean = clean.replace("#", "").replace("^", "")
    return f"[[{clean}]]"


def link_list(names: list[str]) -> str:
    """Render a YAML flow list of quoted wikilinks."""
    return "[" + ", ".join(yaml_quote(wikilink(n)) for n in names) + "]"


def plain_list(values: list[str]) -> str:
    """Render a YAML flow list of quoted plain scalars."""
    return "[" + ", ".join(yaml_quote(v) for v in values) + "]"


# --- Filesystem helpers -----------------------------------------------------

_ILLEGAL_FS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def sanitize_folder_name(name: str) -> str:
    """Strip a trailing Calibre ' (NN)' id suffix from a book folder name."""
    return re.sub(r"\s*\(\d+\)$", "", name).strip()


def safe_filename(name: str) -> str:
    """Make *name* safe to use as a single path segment."""
    cleaned = _ILLEGAL_FS.sub("_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(". ")
    return cleaned or "Untitled"


def write_if_absent(path: Path, content: str) -> bool:
    """Write only if the file does not exist yet. Returns True if written."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def write_stub(hub_dir: Path, name: str, note_type: str) -> None:
    """Create a stub hub note (author/genre) if it does not already exist."""
    safe = safe_filename(wikilink(name)[2:-2])
    write_if_absent(hub_dir / f"{safe}.md", f"---\ntype: {note_type}\n---\n")


# --- Frontmatter reading ----------------------------------------------------

def _split_frontmatter(text: str) -> tuple[list[str], str]:
    """Return (frontmatter_lines, body); lines exclude the '---' fences.

    If *text* has no leading frontmatter block, returns ([], text).
    """
    if not text.startswith("---"):
        return [], text
    lines = text.split("\n")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1:])
    return [], text


def _key_of(line: str) -> str | None:
    """Return the YAML key of a 'key: value' line, else None."""
    if not line or line[0] in (" ", "\t", "#", "-"):
        return None
    if ":" not in line:
        return None
    return line.split(":", 1)[0].strip()


def _is_blank_value(line: str) -> bool:
    """True if a 'key:' line has an empty value (eligible to fill)."""
    return line.partition(":")[2].strip() == ""


def frontmatter_values(text: str) -> dict[str, str]:
    """Return top-level frontmatter key -> raw value string."""
    data: dict[str, str] = {}
    for line in _split_frontmatter(text)[0]:
        key = _key_of(line)
        if key is not None:
            data.setdefault(key, line.partition(":")[2].strip())
    return data


def unquote(value: str) -> str:
    """Reverse yaml_quote for a scalar (leaves unquoted values untouched)."""
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def extract_wikilinks(value: str) -> list[str]:
    """Pull the names out of a YAML list of [[wikilinks]]."""
    return re.findall(r"\[\[([^\]]+)\]\]", value or "")


# --- Frontmatter merge ("never overwrite") ---------------------------------

def update_frontmatter(note_text: str, updates: dict[str, str]) -> str:
    """Return *note_text* with *updates* applied, filling only empty/absent keys.

    - *updates* maps a property key to a pre-formatted YAML scalar (e.g. the
      output of ``yaml_quote`` / ``link_list``). ``""`` means "emit an empty
      ``key:`` placeholder".
    - A key already present with a non-empty value is left untouched.
    - A key present but blank is filled from *updates* when that update is
      non-empty.
    - Absent keys are appended in ``BOOK_PROPERTY_ORDER`` order.
    - The note body is preserved exactly.
    """
    fm_lines, body = _split_frontmatter(note_text)

    existing: dict[str, int] = {}
    for idx, line in enumerate(fm_lines):
        key = _key_of(line)
        if key is not None and key not in existing:
            existing[key] = idx

    new_lines = list(fm_lines)

    # 1. Fill blanks in place.
    for key, formatted in updates.items():
        if key in existing and formatted != "" and _is_blank_value(new_lines[existing[key]]):
            new_lines[existing[key]] = f"{key}: {formatted}"

    # 2. Append absent keys (canonical order first, then any extras).
    to_add = [k for k in updates if k not in existing]
    ordered = [k for k in BOOK_PROPERTY_ORDER if k in to_add]
    ordered += [k for k in to_add if k not in BOOK_PROPERTY_ORDER]
    for key in ordered:
        formatted = updates[key]
        new_lines.append(f"{key}:" if formatted == "" else f"{key}: {formatted}")

    return f"---\n" + "\n".join(new_lines) + "\n---\n" + body


# --- HTML -> Markdown -------------------------------------------------------

class _HTMLToMarkdown(HTMLParser):
    """Minimal HTML->Markdown for book descriptions and reviews.

    Handles the simple tags these sources emit: div, p, br, i/em, b/strong,
    ul/ol, li, a.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._list_stack: list[str] = []
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "div"):
            self._newline_block()
        elif tag == "br":
            self.parts.append("\n")
        elif tag in ("i", "em"):
            self.parts.append("*")
        elif tag in ("b", "strong"):
            self.parts.append("**")
        elif tag in ("ul", "ol"):
            self._newline_block()
            self._list_stack.append(tag)
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "a":
            self._href = dict(attrs).get("href")
            self._link_text = []

    def handle_endtag(self, tag):
        if tag in ("p", "div"):
            self._newline_block()
        elif tag in ("i", "em"):
            self.parts.append("*")
        elif tag in ("b", "strong"):
            self.parts.append("**")
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
            self._newline_block()
        elif tag == "a":
            text = "".join(self._link_text).strip()
            if self._href and text:
                self.parts.append(f"[{text}]({self._href})")
            elif text:
                self.parts.append(text)
            self._href = None
            self._link_text = []

    def handle_data(self, data):
        if self._href is not None:
            self._link_text.append(data)
        else:
            self.parts.append(data)

    def _newline_block(self):
        if self.parts and not self.parts[-1].endswith("\n\n"):
            self.parts.append("\n\n")

    def result(self) -> str:
        text = "".join(self.parts)
        lines = [ln.rstrip() for ln in text.split("\n")]
        out: list[str] = []
        blank = 0
        for ln in lines:
            if ln == "":
                blank += 1
                if blank <= 1:
                    out.append("")
            else:
                blank = 0
                out.append(ln)
        return "\n".join(out).strip()


def html_to_markdown(html: str) -> str:
    if not html:
        return ""
    parser = _HTMLToMarkdown()
    parser.feed(html)
    return parser.result()


# --- Matching normalization -------------------------------------------------

def fold(text: str) -> str:
    """Lowercase and strip accents (NFKD + drop combining marks)."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def norm_title(title: str) -> str:
    """Normalized title for matching: folded, punctuation collapsed to spaces."""
    return re.sub(r"[^a-z0-9]+", " ", fold(title)).strip()


def norm_isbn(isbn: str | None) -> str | None:
    """Digits-only ISBN (keeps a trailing X check digit); None if empty."""
    if not isbn:
        return None
    return re.sub(r"[^0-9x]", "", fold(isbn)).upper() or None


def author_key(name: str) -> tuple[str, str]:
    """Reduce an author name to (first, last), ignoring middle names/initials.

    Handles both "First Last" and "Last, First" orderings.
    """
    name = fold(name)
    if "," in name:
        last, _, first = name.partition(",")
        tokens = first.split() + last.split()
    else:
        tokens = name.split()
    tokens = [re.sub(r"[^a-z0-9]", "", t) for t in tokens]
    tokens = [t for t in tokens if t]
    if not tokens:
        return ("", "")
    if len(tokens) == 1:
        return (tokens[0], tokens[0])
    return (tokens[0], tokens[-1])
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_obsidian.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add booktools/obsidian.py tests/test_obsidian.py
git commit -m "Add shared booktools.obsidian module (schema, merge, helpers)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Refactor `calibre_obsidian.py` to shared schema + merge

**Files:**
- Modify: `booktools/calibre_obsidian.py`
- Modify: `tests/test_calibre_to_obsidian.py`

- [ ] **Step 1: Update the Calibre tests for the new schema/merge**

In `tests/test_calibre_to_obsidian.py`, change `test_missing_cover` so it expects an empty `cover:` placeholder instead of no cover key:

```python
def test_missing_cover(tmp_path):
    lib = make_library(tmp_path)
    out = tmp_path / "Obsidian"
    c2o.convert(lib, out)

    note = (out / "Jane Doe" / "No Cover Book" / "No Cover Book.md").read_text()
    assert "cover:\n" in note or note.rstrip().endswith("cover:")  # empty placeholder
    assert "![[cover.jpg]]" not in note                            # no body embed
    assert "rating:" in note
    assert not (out / "Jane Doe" / "No Cover Book" / "cover.jpg").exists()
```

Add two new tests to the same file:

```python
def test_book_note_has_goodreads_placeholders(tmp_path):
    lib = make_library(tmp_path)
    out = tmp_path / "Obsidian"
    c2o.convert(lib, out)
    note = (out / "Andrew Roberts" / "Napoleon_ A Life" / "Napoleon_ A Life.md").read_text()
    for key in ("pages:", "status:", "shelves:", "date_read:"):
        assert key in note


def test_rerun_preserves_book_note_edits(tmp_path):
    lib = make_library(tmp_path)
    out = tmp_path / "Obsidian"
    c2o.convert(lib, out)
    note = out / "Andrew Roberts" / "Napoleon_ A Life" / "Napoleon_ A Life.md"
    note.write_text(note.read_text().replace("status:", "status: reading"), encoding="utf-8")

    c2o.convert(lib, out)  # re-run must not clobber the manual edit
    assert "status: reading" in note.read_text()
    assert 'title: "Napoleon: A Life"' in note.read_text()
```

- [ ] **Step 2: Run tests, verify the new/changed ones fail**

Run: `uv run pytest tests/test_calibre_to_obsidian.py -q`
Expected: FAIL (placeholders missing, merge not implemented).

- [ ] **Step 3: Refactor `booktools/calibre_obsidian.py`**

Replace the helper/emission sections. First, replace the imports and delete the now-shared helpers (`_HTMLToMarkdown`, `html_to_markdown`, `_yaml_quote`, `_wikilink`, `_link_list`, `sanitize_folder_name`, `write_if_absent`, `write_stub`). At the top of the file, after the docstring, use:

```python
from __future__ import annotations

import shutil
from pathlib import Path
from xml.etree import ElementTree as ET

import typer

from booktools import resolve_path
from booktools.obsidian import (
    html_to_markdown,
    link_list,
    sanitize_folder_name,
    update_frontmatter,
    write_if_absent,  # noqa: F401  (kept for API compatibility)
    write_stub,
    yaml_quote,
)
```

Keep the `NS`, `IGNORED_NAMES`, `IGNORED_EBOOK_SUFFIXES`, `BookMetadata`, `_date_only`, and `parse_opf` definitions unchanged (parse_opf already calls `html_to_markdown`, now imported).

Replace everything from `# --- YAML emission ---` through the end of `build_note` with:

```python
# --- Frontmatter / note construction ---------------------------------------

def _calibre_updates(meta: BookMetadata, has_cover: bool) -> dict[str, str]:
    """Map a BookMetadata to canonical property -> formatted YAML value.

    Goodreads-only fields (pages/status/shelves/date_read) are emitted empty so
    the Goodreads importer or manual editing can fill them later.
    """
    u: dict[str, str] = {}
    u["title"] = yaml_quote(meta.title) if meta.title else ""
    u["authors"] = link_list(meta.authors) if meta.authors else ""
    u["genres"] = link_list(meta.genres) if meta.genres else ""
    u["series"] = yaml_quote(meta.series) if meta.series else ""
    u["series_index"] = meta.series_index or ""
    u["publisher"] = yaml_quote(meta.publisher) if meta.publisher else ""
    u["published"] = meta.published or ""
    u["language"] = meta.language or ""
    u["pages"] = ""
    u["status"] = ""
    u["shelves"] = ""
    if meta.rating is not None:
        rating = int(meta.rating) if meta.rating == int(meta.rating) else meta.rating
        u["rating"] = str(rating)
    else:
        u["rating"] = ""
    u["isbn"] = yaml_quote(meta.isbn) if meta.isbn else ""
    u["amazon"] = yaml_quote(meta.amazon) if meta.amazon else ""
    u["google"] = yaml_quote(meta.google) if meta.google else ""
    u["uuid"] = yaml_quote(meta.uuid) if meta.uuid else ""
    u["calibre_id"] = meta.calibre_id or ""
    u["date_added"] = meta.date_added or ""
    u["date_read"] = ""
    u["cover"] = yaml_quote("[[cover.jpg]]") if has_cover else ""
    return u


def build_note(meta: BookMetadata, has_cover: bool, existing_text: str | None = None) -> str:
    """Build (or merge into) a book note.

    When *existing_text* is given, only empty/absent frontmatter keys are filled
    and the body is preserved. When it is None, a fresh note is created with the
    cover embed and description body.
    """
    base = existing_text if existing_text is not None else "---\ntype: book\n---\n"
    note = update_frontmatter(base, _calibre_updates(meta, has_cover))
    if existing_text is not None:
        return note  # merge: never touch the existing body

    body: list[str] = []
    if has_cover:
        body += ["![[cover.jpg]]", ""]
    if meta.description:
        body += [meta.description, ""]
    if body:
        note = note.rstrip("\n") + "\n\n" + "\n".join(body) + "\n"
    return note
```

Then update the write in `convert` to be merge-based. Replace:

```python
        note_name = sanitize_folder_name(book_src.name)
        note_path = book_out / f"{note_name}.md"
        note_path.write_text(build_note(meta, has_cover), encoding="utf-8")
        stats["books"] += 1
```

with:

```python
        note_name = sanitize_folder_name(book_src.name)
        note_path = book_out / f"{note_name}.md"
        existing = note_path.read_text(encoding="utf-8") if note_path.exists() else None
        note_path.write_text(build_note(meta, has_cover, existing), encoding="utf-8")
        stats["books"] += 1
```

(Leave the `calibre_to_obsidian` command, `register`, and `main` functions unchanged.)

- [ ] **Step 4: Run the full suite, verify it passes**

Run: `uv run pytest -q`
Expected: PASS (obsidian + calibre tests all green).

- [ ] **Step 5: Commit**

```bash
git add booktools/calibre_obsidian.py tests/test_calibre_to_obsidian.py
git commit -m "Refactor Calibre importer onto shared schema + merge writes

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Goodreads CSV parsing + normalization

**Files:**
- Create: `booktools/goodreads_obsidian.py`
- Test: `tests/test_goodreads_obsidian.py`

- [ ] **Step 1: Write failing parse tests**

Create `tests/test_goodreads_obsidian.py`:

```python
"""Tests for the Goodreads -> Obsidian importer."""

from pathlib import Path

from booktools import goodreads_obsidian as gr


HEADER = (
    "Book Id,Title,Author,Author l-f,Additional Authors,ISBN,ISBN13,My Rating,"
    "Publisher,Binding,Number of Pages,Year Published,Original Publication Year,"
    "Date Read,Date Added,Bookshelves,Bookshelves with positions,Exclusive Shelf,"
    "My Review,Spoiler,Private Notes,Read Count,Owned Copies\n"
)

# A read book with review, a to-read book, and a currently-reading book.
ROWS = (
    '1,"Napoleon: A Life",Andrew Roberts,"Roberts, Andrew",,'
    '"=""0141032014""","=""9780141032016""",5.0,Penguin,Paperback,976,2015,2014,'
    '2026/07/17,2026/05/04,history,history (#1),read,'
    '"Great book.<br/><br/>Loved it.",,note-to-self,1,0\n'
    '2,"The Cold War: A New History",John Lewis Gaddis,"Gaddis, John Lewis",,'
    '"=""0143038273""","=""9780143038276""",0,Penguin,Paperback,352,2006,2005,,'
    '2026/07/14,to-read,to-read (#2),to-read,,,,0,0\n'
    '3,"Stalin: Paradoxes of Power",Stephen Kotkin,"Kotkin, Stephen",,'
    '"=""1594203792""","=""9781594203794""",0,Penguin,Hardcover,976,2014,2014,,'
    '2026/04/30,,,currently-reading,,,,1,0\n'
)


def write_csv(tmp_path: Path) -> Path:
    p = tmp_path / "goodreads_library_export.csv"
    p.write_text(HEADER + ROWS, encoding="utf-8")
    return p


def test_parse_csv_fields(tmp_path):
    books = gr.parse_csv(write_csv(tmp_path))
    assert len(books) == 3
    nap = books[0]
    assert nap.title == "Napoleon: A Life"
    assert nap.authors == ["Andrew Roberts"]
    assert nap.isbn13 == "9780698176287" or nap.isbn13 == "9780141032016"
    assert nap.isbn == "0141032014"
    assert nap.rating == 5
    assert nap.pages == "976"
    assert nap.status == "read"
    assert nap.date_read == "2026-07-17"
    assert nap.date_added == "2026-05-04"
    assert nap.shelves == ["history"]
    assert "Great book." in nap.review

    unrated = books[1]
    assert unrated.rating is None          # My Rating 0 -> unrated
    assert unrated.status == "to-read"

    reading = books[2]
    assert reading.status == "reading"     # currently-reading normalized


def test_normalization_helpers():
    from booktools import obsidian as ob
    assert ob.norm_isbn('="9780698176287"') == "9780698176287"
    assert ob.norm_title("The Cold War: A New History") == \
        ob.norm_title("The Cold War - A New History")
    assert ob.author_key("Terry Martin") == ob.author_key("Terry L. Martin")
    assert ob.author_key("Roberts, Andrew") == ob.author_key("Andrew Roberts")
    assert ob.author_key("Broué, Pierre") == ob.author_key("Pierre Broue")
```

(Note: the ISBN13 assertion is deliberately lenient because the fixture's ISBN13 is illustrative; parsing just needs to unescape it.)

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_goodreads_obsidian.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Create `booktools/goodreads_obsidian.py` (parsing portion)**

```python
#!/usr/bin/env python3
"""Convert a Goodreads library CSV export into an Obsidian book vault.

Reads the CSV Goodreads produces from "My Books -> Import and export", and for
each *read* book (by default) creates or merges an Obsidian note in the same
shape as the Calibre importer. Existing information is never overwritten: only
absent/empty properties are filled. Reviews are written to a separate
"<Title> - Review.md" note alongside any highlights.

Standard library only.
"""

from __future__ import annotations

import csv as _csv
from dataclasses import dataclass, field
from pathlib import Path

import typer

from booktools import resolve_path
from booktools.obsidian import (
    author_key,
    extract_wikilinks,
    frontmatter_values,
    html_to_markdown,
    link_list,
    norm_isbn,
    norm_title,
    plain_list,
    safe_filename,
    unquote,
    update_frontmatter,
    write_if_absent,
    write_stub,
    yaml_quote,
)


@dataclass
class GoodreadsBook:
    title: str
    authors: list[str] = field(default_factory=list)
    isbn: str | None = None
    isbn13: str | None = None
    rating: int | None = None
    publisher: str | None = None
    pages: str | None = None
    published: str | None = None      # year only
    date_read: str | None = None
    date_added: str | None = None
    status: str | None = None         # reading status (Exclusive Shelf)
    shelves: list[str] = field(default_factory=list)
    review: str | None = None
    private_notes: str | None = None
    exclusive_shelf: str | None = None


def _strip_isbn(raw: str) -> str | None:
    """Unwrap Goodreads' ="..." Excel escaping; '=""' -> None."""
    raw = (raw or "").strip()
    if raw.startswith('="') and raw.endswith('"'):
        raw = raw[2:-1]
    return raw.strip('"').strip() or None


def _norm_date(raw: str) -> str | None:
    raw = (raw or "").strip()
    return raw.replace("/", "-") or None


def _split_authors(author: str, additional: str) -> list[str]:
    authors = [author.strip()] if (author or "").strip() else []
    for extra in (additional or "").split(","):
        if extra.strip():
            authors.append(extra.strip())
    return authors


def _norm_status(shelf: str) -> str | None:
    shelf = (shelf or "").strip()
    if not shelf:
        return None
    return "reading" if shelf == "currently-reading" else shelf


def parse_csv(path: Path) -> list[GoodreadsBook]:
    books: list[GoodreadsBook] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in _csv.DictReader(fh):
            rating_raw = (row.get("My Rating") or "").strip()
            try:
                rating = int(float(rating_raw))
            except ValueError:
                rating = 0
            shelves = [s.strip() for s in (row.get("Bookshelves") or "").split(",") if s.strip()]
            books.append(GoodreadsBook(
                title=(row.get("Title") or "").strip(),
                authors=_split_authors(row.get("Author", ""), row.get("Additional Authors", "")),
                isbn=_strip_isbn(row.get("ISBN", "")),
                isbn13=_strip_isbn(row.get("ISBN13", "")),
                rating=rating if rating > 0 else None,
                publisher=(row.get("Publisher") or "").strip() or None,
                pages=(row.get("Number of Pages") or "").strip() or None,
                published=(row.get("Year Published") or "").strip() or None,
                date_read=_norm_date(row.get("Date Read", "")),
                date_added=_norm_date(row.get("Date Added", "")),
                status=_norm_status(row.get("Exclusive Shelf", "")),
                shelves=shelves,
                review=(row.get("My Review") or "").strip() or None,
                private_notes=(row.get("Private Notes") or "").strip() or None,
                exclusive_shelf=(row.get("Exclusive Shelf") or "").strip() or None,
            ))
    return books
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_goodreads_obsidian.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add booktools/goodreads_obsidian.py tests/test_goodreads_obsidian.py
git commit -m "Add Goodreads CSV parsing + normalization

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Goodreads matching + `convert`

**Files:**
- Modify: `booktools/goodreads_obsidian.py`
- Modify: `tests/test_goodreads_obsidian.py`

- [ ] **Step 1: Write failing convert tests**

Append to `tests/test_goodreads_obsidian.py`:

```python
def test_convert_creates_only_read_books(tmp_path):
    out = tmp_path / "Obsidian"
    stats = gr.convert(write_csv(tmp_path), out)
    # Only the "read" book (Napoleon) is created by default.
    assert stats["created"] == 1
    assert (out / "Andrew Roberts" / "Napoleon_ A Life" / "Napoleon_ A Life.md").exists() is False
    note = out / "Andrew Roberts" / "Napoleon: A Life"  # safe_filename keeps most chars
    assert (out / "Andrew Roberts" / "Napoleon_ A Life").exists() is False
    # Folder uses safe_filename of the title.
    created = list(out.rglob("*.md"))
    assert any("Napoleon" in p.name for p in created)


def test_convert_shelf_all_imports_everything(tmp_path):
    out = tmp_path / "Obsidian"
    stats = gr.convert(write_csv(tmp_path), out, shelf="all")
    assert stats["created"] == 3


def test_convert_writes_review_file(tmp_path):
    out = tmp_path / "Obsidian"
    gr.convert(write_csv(tmp_path), out)
    reviews = list(out.rglob("*- Review.md"))
    assert len(reviews) == 1
    text = reviews[0].read_text()
    assert "Great book." in text and "Loved it." in text


def test_convert_merges_into_existing_note_by_isbn(tmp_path):
    out = tmp_path / "Obsidian"
    # Pre-create a note as if from Calibre: has title, empty status/pages.
    book_dir = out / "Andrew Roberts" / "Napoleon_ A Life"
    book_dir.mkdir(parents=True)
    note = book_dir / "Napoleon_ A Life.md"
    note.write_text(
        '---\ntype: book\ntitle: "Napoleon: A Life"\nisbn: "9780141032016"\n'
        'status:\npages:\nrating: 4\n---\n\nMy body.\n',
        encoding="utf-8",
    )
    stats = gr.convert(write_csv(tmp_path), out)
    assert stats["merged"] == 1 and stats["created"] == 0
    updated = note.read_text()
    assert "status: read" in updated       # blank filled
    assert "pages: 976" in updated         # blank filled
    assert "rating: 4" in updated          # existing value NOT overwritten (was 4, GR is 5)
    assert "My body." in updated           # body preserved


def test_convert_merges_by_strict_title_author(tmp_path):
    out = tmp_path / "Obsidian"
    book_dir = out / "Andrew Roberts" / "Napoleon A Life"
    book_dir.mkdir(parents=True)
    note = book_dir / "Napoleon A Life.md"
    # No ISBN -> must match on normalized title + author.
    note.write_text(
        '---\ntype: book\ntitle: "Napoleon - A Life"\n'
        'authors: ["[[Andrew Roberts]]"]\nstatus:\n---\n\nBody.\n',
        encoding="utf-8",
    )
    stats = gr.convert(write_csv(tmp_path), out)
    assert stats["merged"] == 1 and stats["created"] == 0
    assert "status: read" in note.read_text()


def test_convert_idempotent(tmp_path):
    out = tmp_path / "Obsidian"
    gr.convert(write_csv(tmp_path), out)
    before = {p: p.read_text() for p in out.rglob("*.md")}
    gr.convert(write_csv(tmp_path), out)  # second run
    after = {p: p.read_text() for p in out.rglob("*.md")}
    assert before == after
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `uv run pytest tests/test_goodreads_obsidian.py -q`
Expected: FAIL (`convert` not defined).

- [ ] **Step 3: Add matching + `convert` to `booktools/goodreads_obsidian.py`**

Append after `parse_csv`:

```python
# --- Matching against an existing vault -------------------------------------

def build_index(output: Path) -> tuple[dict[str, Path], dict[tuple, Path]]:
    """Index existing book notes by normalized ISBN and (title, author)."""
    by_isbn: dict[str, Path] = {}
    by_title_author: dict[tuple, Path] = {}
    for md in output.rglob("*.md"):
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


def match_note(book: GoodreadsBook, by_isbn, by_title_author) -> Path | None:
    for isbn in (norm_isbn(book.isbn13), norm_isbn(book.isbn)):
        if isbn and isbn in by_isbn:
            return by_isbn[isbn]
    if book.title and book.authors:
        key = (norm_title(book.title), author_key(book.authors[0]))
        if key in by_title_author:
            return by_title_author[key]
    return None


# --- Note construction ------------------------------------------------------

def _goodreads_updates(book: GoodreadsBook) -> dict[str, str]:
    """Canonical property -> formatted value; empty for fields Goodreads lacks."""
    from booktools.obsidian import BOOK_PROPERTY_ORDER
    u = {k: "" for k in BOOK_PROPERTY_ORDER if k != "type"}
    if book.title:
        u["title"] = yaml_quote(book.title)
    if book.authors:
        u["authors"] = link_list(book.authors)
    if book.publisher:
        u["publisher"] = yaml_quote(book.publisher)
    if book.published:
        u["published"] = book.published
    if book.pages:
        u["pages"] = book.pages
    if book.status:
        u["status"] = yaml_quote(book.status)
    if book.shelves:
        u["shelves"] = plain_list(book.shelves)
    if book.rating is not None:
        u["rating"] = str(book.rating)
    isbn = book.isbn13 or book.isbn
    if isbn:
        u["isbn"] = yaml_quote(isbn)
    if book.date_added:
        u["date_added"] = book.date_added
    if book.date_read:
        u["date_read"] = book.date_read
    return u


def _review_markdown(book: GoodreadsBook) -> str | None:
    if not book.review and not book.private_notes:
        return None
    parts = [f"# {book.title} — Review", ""]
    if book.date_read:
        parts += [f"*Read: {book.date_read}*", ""]
    if book.review:
        parts += [html_to_markdown(book.review), ""]
    if book.private_notes:
        parts += ["## Private Notes", "", html_to_markdown(book.private_notes), ""]
    return "\n".join(parts)


def convert(csv_path: Path, output: Path, shelf: str = "read") -> dict:
    stats = {"created": 0, "merged": 0, "reviews": 0, "skipped": 0, "authors": set()}
    by_isbn, by_ta = build_index(output)
    authors_dir = output / "Authors"

    for book in parse_csv(csv_path):
        if shelf != "all" and (book.exclusive_shelf or "") != shelf:
            stats["skipped"] += 1
            continue
        if not book.title or not book.authors:
            stats["skipped"] += 1
            continue

        note_path = match_note(book, by_isbn, by_ta)
        if note_path is not None:
            base = note_path.read_text(encoding="utf-8")
            stats["merged"] += 1
        else:
            folder = output / safe_filename(book.authors[0]) / safe_filename(book.title)
            note_path = folder / f"{safe_filename(book.title)}.md"
            base = "---\ntype: book\n---\n"
            stats["created"] += 1

        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(update_frontmatter(base, _goodreads_updates(book)), encoding="utf-8")

        # Keep the index current so later rows can match this note.
        isbn = norm_isbn(book.isbn13) or norm_isbn(book.isbn)
        if isbn:
            by_isbn.setdefault(isbn, note_path)
        by_ta.setdefault((norm_title(book.title), author_key(book.authors[0])), note_path)

        for author in book.authors:
            write_stub(authors_dir, author, "author")
            stats["authors"].add(author)

        review = _review_markdown(book)
        if review and write_if_absent(note_path.parent / f"{note_path.stem} - Review.md", review):
            stats["reviews"] += 1

    return stats
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `uv run pytest tests/test_goodreads_obsidian.py -q`
Expected: PASS (all Goodreads tests).

- [ ] **Step 5: Commit**

```bash
git add booktools/goodreads_obsidian.py tests/test_goodreads_obsidian.py
git commit -m "Add Goodreads matching and merge-based convert

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: CLI wiring, standalone shim, README

**Files:**
- Modify: `booktools/goodreads_obsidian.py` (add command/register/main)
- Modify: `booktools/cli.py`
- Create: `scripts/goodreads_to_obsidian.py`
- Modify: `README.md`

- [ ] **Step 1: Add the Typer command, `register`, and `main` to `booktools/goodreads_obsidian.py`**

Append at the end of the module:

```python
def goodreads_to_obsidian(
    csv: Path = typer.Option(
        ...,
        "--csv", "-c",
        help="Path to the Goodreads library CSV export. Relative paths resolve against the current directory.",
    ),
    output: Path = typer.Option(
        Path("Obsidian"),
        "--output", "-o",
        help="Output Obsidian vault. Relative paths resolve against the current directory.",
    ),
    shelf: str = typer.Option(
        "read",
        "--shelf",
        help="Only import books on this Goodreads exclusive shelf (read/currently-reading/to-read). Use 'all' for every book.",
    ),
) -> None:
    """Convert a Goodreads CSV export into Obsidian book notes.

    By default only books on the 'read' shelf are imported. Existing notes are
    never overwritten: only empty/absent properties are filled, and reviews are
    written to a separate '<Title> - Review.md' note. Books are matched to
    existing notes by ISBN, then by a strict Author/Title comparison.
    """
    csv = resolve_path(csv, Path.cwd())
    output = resolve_path(output, Path.cwd())

    if not csv.is_file():
        raise typer.BadParameter(f"CSV not found: {csv}", param_hint="--csv")

    output.mkdir(parents=True, exist_ok=True)
    stats = convert(csv, output, shelf=shelf)
    typer.echo(
        f"Done. {stats['created']} created, {stats['merged']} merged, "
        f"{stats['reviews']} reviews, {len(stats['authors'])} authors, "
        f"{stats['skipped']} skipped.\nOutput: {output}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("goodreads-to-obsidian")(goodreads_to_obsidian)


def main() -> None:
    """Standalone entry point so the shim script keeps working on its own."""
    typer.run(goodreads_to_obsidian)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Register the capability in `booktools/cli.py`**

Change the import:

```python
from booktools import calibre_obsidian, goodreads_obsidian, kobo_export
```

and the tuple:

```python
CAPABILITIES = (
    calibre_obsidian,
    goodreads_obsidian,
    kobo_export,
)
```

- [ ] **Step 3: Create the standalone shim `scripts/goodreads_to_obsidian.py`**

```python
#!/usr/bin/env python3
"""Standalone shim: `python scripts/goodreads_to_obsidian.py --csv ... [--output ...]`.

The real implementation lives in ``booktools.goodreads_obsidian``. This keeps the
script runnable on its own while there is a single source of truth. For the full
CLI with all capabilities, use ``books`` (see pyproject.toml).
"""

from booktools.goodreads_obsidian import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Verify the CLI and shim wire up**

Run:
```bash
uv run books --help
uv run books goodreads-to-obsidian --help
uv run python scripts/goodreads_to_obsidian.py --help
```
Expected: `goodreads-to-obsidian` listed under `books`; both help screens show `--csv`, `--output`, `--shelf`.

- [ ] **Step 5: Update `README.md`**

Under the `## Commands` examples block, add:

```bash
books goodreads-to-obsidian --csv ~/goodreads_library_export.csv --output ~/Obsidian
```

Add a bullet after the `kobo-export` bullet:

```markdown
- **`goodreads-to-obsidian`** — Convert a Goodreads CSV export into Obsidian
  book notes (read books by default; `--shelf all` for everything). Merges with
  existing Calibre notes without overwriting, and extracts each review into a
  separate `<Title> - Review.md`.
```

In the "standalone scripts" block, add:

```bash
uv run python scripts/goodreads_to_obsidian.py --csv ~/goodreads_library_export.csv
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (all obsidian, calibre, goodreads tests).

- [ ] **Step 7: Commit**

```bash
git add booktools/goodreads_obsidian.py booktools/cli.py scripts/goodreads_to_obsidian.py README.md
git commit -m "Wire goodreads-to-obsidian into CLI + standalone shim + docs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** read-only `--shelf` filter (Task 4/5); create+merge (Task 4); ISBN→strict Author/Title match with accent folding + middle-name tolerance (Task 1 helpers, Task 4 matching); status+shelves, pages, date_read, rating(0→empty), ISBN unescape (Task 3); review file never overwritten (Task 4); Calibre shared schema + merge re-runs (Task 2); shared module extraction (Task 1); standalone shim + CLI (Task 5).
- **Never-overwrite guarantee** is centralized in `update_frontmatter` and covered by tests in Tasks 1, 2, and 4.
- **Naming consistency:** `update_frontmatter`, `frontmatter_values`, `norm_title`, `norm_isbn`, `author_key`, `safe_filename`, `build_index`, `match_note`, `convert(csv_path, output, shelf="read")` are used identically across tasks.
```
