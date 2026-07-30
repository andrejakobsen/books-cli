# Highlighted CSV → Obsidian Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `books highlighted` capability importing the Highlighted app's physical-book highlights CSV into the shared Obsidian vault, with page-based labels/anchors.

**Architecture:** Extend the source-agnostic `books/highlights.py` with a `page` dimension, then add a thin `books/highlighted_obsidian.py` importer that maps CSV rows into `Highlight`/`BookRef` and reuses `VaultIndex`/`render_highlights`/`write_leaf_with_embed`.

**Tech Stack:** Python 3, stdlib-only + Typer; `uv run pytest`.

---

## Task 1: Add `page` support to the shared highlights layer

**Files:**
- Modify: `books/highlights.py`
- Test: `tests/test_highlights.py`

- [ ] **Step 1: Write the failing tests** — append to `tests/test_highlights.py`:

```python
def test_page_label_and_anchor_single():
    hs = [hl.Highlight(text="x", page="4")]
    out = hl.render_highlights(hs)
    assert "> [!quote]+ p. 4" in out
    assert "^p4" in out


def test_page_label_range_uses_en_dash_anchor_keeps_hyphen():
    hs = [hl.Highlight(text="x", page="45-49")]
    out = hl.render_highlights(hs)
    assert "> [!quote]+ p. 45–49" in out  # en dash in label
    assert "^p45-49" in out  # hyphen in anchor


def test_page_same_page_collisions_dedupe():
    hs = [hl.Highlight(text="a", page="45-49"), hl.Highlight(text="b", page="45-49")]
    assert hl.build_anchors(hs) == ["p45-49", "p45-49-2"]


def test_page_none_is_unchanged():
    hs = [hl.Highlight(text="a", chapter_index=2, block="17", segment="5")]
    assert hl.build_anchors(hs) == ["ch2-b17-5"]
    assert "p. " not in hl.render_highlights(hs)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_highlights.py -q`
Expected: the 4 new tests FAIL (`Highlight` has no `page`).

- [ ] **Step 3: Implement** in `books/highlights.py`:

Add `import re` near the top (after `from __future__ import annotations`).

Add the field to the dataclass (after `segment`, before `date`):

```python
page: str | None = None  # human page/location (physical books), e.g. "45-49"
```

In `build_anchors`, replace the location block:

```python
        if h.block:
            loc = f"b{h.block}" + (f"-{h.segment}" if h.segment else "")
        else:
            loc = f"hl{i}"
```

with:

```python
        page = re.sub(r"[^0-9-]", "", h.page) if h.page else ""
        if page:
            loc = f"p{page}"
        elif h.block:
            loc = f"b{h.block}" + (f"-{h.segment}" if h.segment else "")
        else:
            loc = f"hl{i}"
```

In `_label`, add a page part between the chapter/title block and the progress
block:

```python
    if h.page:
        parts.append(f"p. {h.page.replace('-', '–')}")
```

(placed after the `chapter_index`/`chapter_title` `if/elif` and before the
`progress` `if`.)

- [ ] **Step 4: Run** `uv run pytest tests/test_highlights.py -q` → all PASS.

- [ ] **Step 5: Run full suite** `uv run pytest -q` → all PASS (existing 55 unaffected).

- [ ] **Step 6: Commit**

```bash
git add books/highlights.py tests/test_highlights.py
git commit -m "Add page dimension to shared Highlight (label + anchor)"
```

---

## Task 2: The `highlighted` importer module + registration + shim

**Files:**
- Create: `books/highlighted_obsidian.py`
- Create: `scripts/highlighted_obsidian.py`
- Modify: `books/cli.py`
- Test: `tests/test_highlighted_obsidian.py`

- [ ] **Step 1: Write the failing tests** — create `tests/test_highlighted_obsidian.py`:

```python
"""Tests for the Highlighted -> Obsidian importer."""

from pathlib import Path

from books import highlighted_obsidian as hi

HEADER = (
    "Highlight,Title,Author,ISBN,Collections,Reading Status,"
    "Book Added Date,Location,Tags,Note,Date,Favorite\n"
)
ROWS = (
    '"Fear is the mind-killer",Stalin,Stephen Kotkin,9781594203794,,Reading,'
    "2026-07-24,4,Stalin,That is true,2026-07-24 10:37:51,N\n"
    '"A longer passage.",Stalin,Stephen Kotkin,9781594203794,,Reading,'
    "2026-07-24,45-49,Stalin,,2026-07-24 11:15:47,N\n"
)


def write_csv(tmp_path: Path) -> Path:
    p = tmp_path / "Highlights for Stalin.csv"
    p.write_text(HEADER + ROWS, encoding="utf-8")
    return p


def test_parse_and_map(tmp_path):
    rows = hi.parse_csv(write_csv(tmp_path))
    assert len(rows) == 2
    h0 = hi.row_to_highlight(rows[0])
    assert h0.text == "Fear is the mind-killer"
    assert h0.note == "That is true"
    assert h0.page == "4"
    h1 = hi.row_to_highlight(rows[1])
    assert h1.note is None  # blank Note -> None
    assert h1.page == "45-49"


def test_convert_writes_highlights_and_embed(tmp_path):
    out = tmp_path / "Obsidian"
    stats = hi.convert(write_csv(tmp_path), out)
    assert stats["books"] == 1 and stats["entries"] == 2
    note = out / "Stephen Kotkin" / "Stalin" / "Stalin.md"
    assert note.exists()
    note_text = note.read_text()
    assert "![](Highlights.md)" in note_text
    assert 'isbn: "9781594203794"' in note_text  # ISBN persisted for matching
    body = (note.parent / "Highlights.md").read_text()
    assert "> [!quote]+ p. 4" in body
    assert "^p45-49" in body
    assert "Fear is the mind-killer" in body


def test_convert_merges_into_existing_note_by_isbn(tmp_path):
    out = tmp_path / "Obsidian"
    book_dir = out / "Stephen Kotkin" / "Stalin"
    book_dir.mkdir(parents=True)
    note = book_dir / "Stalin.md"
    note.write_text(
        '---\ntype: book\ntitle: "Stalin"\nisbn: "9781594203794"\nstatus: read\n---\n\nMy body.\n',
        encoding="utf-8",
    )
    stats = hi.convert(write_csv(tmp_path), out)
    assert stats["books"] == 1
    updated = note.read_text()
    assert "status: read" in updated  # existing value untouched
    assert "My body." in updated  # body preserved
    assert "![](Highlights.md)" in updated


def test_convert_idempotent(tmp_path):
    out = tmp_path / "Obsidian"
    hi.convert(write_csv(tmp_path), out)
    before = {p: p.read_text() for p in out.rglob("*.md")}
    hi.convert(write_csv(tmp_path), out)
    after = {p: p.read_text() for p in out.rglob("*.md")}
    assert before == after
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_highlighted_obsidian.py -q`
Expected: FAIL (`No module named books.highlighted_obsidian`).

- [ ] **Step 3: Create `books/highlighted_obsidian.py`:**

```python
#!/usr/bin/env python3
"""Convert a Highlighted app CSV export into an Obsidian book vault.

Highlighted captures highlights from *physical* books (OCR). This importer maps
each CSV row into the shared source-agnostic Highlight model and writes a per-book
"Highlights.md" embedded into the canonical note via "![](Highlights.md)". Books
are matched to existing notes by ISBN, then by a strict Author/Title comparison,
so highlights accumulate alongside any Calibre/Goodreads data without clobbering.

CSV columns: Highlight, Title, Author, ISBN, Collections, Reading Status,
Book Added Date, Location, Tags, Note, Date, Favorite. Location is a page number
or range (e.g. "45-49"); Collections/Tags/Reading Status/Favorite are ignored.

Standard library only.
"""

from __future__ import annotations

import csv as _csv
from pathlib import Path

import typer

from books import resolve_path
from books.highlights import Highlight, render_highlights
from books.obsidian import (
    BookRef,
    VaultIndex,
    link_list,
    update_frontmatter,
    write_leaf_with_embed,
    write_stub,
    yaml_quote,
)


def parse_csv(path: Path) -> list[dict]:
    """Read the Highlighted CSV export into a list of row dicts."""
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(_csv.DictReader(fh))


def row_to_highlight(row: dict) -> Highlight:
    """Map a Highlighted CSV row to a source-agnostic Highlight."""
    return Highlight(
        text=(row.get("Highlight") or "").strip(),
        note=(row.get("Note") or "").strip() or None,
        page=(row.get("Location") or "").strip() or None,
        date=(row.get("Date") or "").strip() or None,
    )


def convert(csv_path: Path, output: Path) -> dict:
    """Import every highlight, grouped by book, into the Obsidian vault."""
    stats = {"books": 0, "entries": 0, "authors": set()}
    index = VaultIndex(output)
    authors_dir = output / "Authors"

    # Group rows by book (ISBN when present, else title), preserving CSV order.
    groups: dict[str, dict] = {}
    for row in parse_csv(csv_path):
        title = (row.get("Title") or "").strip()
        if not title:
            continue
        isbn = (row.get("ISBN") or "").strip() or None
        author = (row.get("Author") or "").strip()
        key = isbn or title
        group = groups.setdefault(key, {"title": title, "author": author, "isbn": isbn, "rows": []})
        group["rows"].append(row)

    for group in groups.values():
        authors = [group["author"]] if group["author"] else []
        ref = BookRef(title=group["title"], authors=authors, isbn=group["isbn"])
        note_path, _ = index.find_or_create(ref)

        base = note_path.read_text(encoding="utf-8")
        note_path.write_text(
            update_frontmatter(
                base,
                {
                    "title": yaml_quote(group["title"]),
                    "authors": link_list(authors) if authors else "",
                    "isbn": yaml_quote(group["isbn"]) if group["isbn"] else "",
                },
            ),
            encoding="utf-8",
        )

        highlights = [row_to_highlight(r) for r in group["rows"]]
        write_leaf_with_embed(
            note_path, "Highlights.md", render_highlights(highlights), "Highlights"
        )

        for author in authors:
            write_stub(authors_dir, author, "author")
            stats["authors"].add(author)
        stats["books"] += 1
        stats["entries"] += len(highlights)

    return stats


def highlighted_to_obsidian(
    csv: Path = typer.Option(
        ...,
        "--csv",
        "-c",
        help="Path to the Highlighted CSV export. Relative paths resolve against the current directory.",
    ),
    output: Path = typer.Option(
        Path("Obsidian"),
        "--output",
        "-o",
        help="Output Obsidian vault. Relative paths resolve against the current directory.",
    ),
) -> None:
    """Convert a Highlighted CSV export into Obsidian book notes.

    Every highlight is imported (regardless of reading status). For each book a
    'Highlights.md' is written into the book's folder and embedded into the note
    via '![](Highlights.md)'; books are matched to existing notes by ISBN, then by
    a strict Author/Title comparison. Existing notes are never overwritten.
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
    app.command("highlighted")(highlighted_to_obsidian)


def main() -> None:
    """Standalone entry point so the shim script keeps working on its own."""
    typer.run(highlighted_to_obsidian)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create `scripts/highlighted_obsidian.py`:**

```python
#!/usr/bin/env python3
"""Standalone shim: `python highlighted_obsidian.py -c export.csv -o Obsidian`.

The real implementation lives in ``books.highlighted_obsidian``. This keeps
the script runnable on its own while there is a single source of truth. For the
full CLI with all capabilities, use ``books`` (see pyproject.toml).
"""

from books.highlighted_obsidian import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Register in `books/cli.py`:**

Change the import line:

```python
from books import calibre_obsidian, goodreads_obsidian, kobo_export
```

to:

```python
from books import (
    calibre_obsidian,
    goodreads_obsidian,
    highlighted_obsidian,
    kobo_export,
)
```

and add `highlighted_obsidian,` to the `CAPABILITIES` tuple (keep it grouped with
the others).

- [ ] **Step 6: Run** `uv run pytest tests/test_highlighted_obsidian.py -q` → all PASS.

- [ ] **Step 7: Commit**

```bash
git add books/highlighted_obsidian.py scripts/highlighted_obsidian.py books/cli.py tests/test_highlighted_obsidian.py
git commit -m "Add highlighted capability: Highlighted CSV -> Obsidian highlights"
```

---

## Task 3: CLI wiring tests + README

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `README.md`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Update CLI tests.** In `tests/test_cli.py`:

Update the capability count assertion:

```python
def test_capabilities_count_matches_module_list():
    # One command name per registered capability module.
    assert len(CAPABILITIES) == 4
```

Add `"highlighted"` to the command tuple in `test_all_capabilities_registered`
and `test_subcommand_help` (both iterate over
`("calibre", "goodreads", "kobo")` → make it
`("calibre", "goodreads", "highlighted", "kobo")`).

Append an end-to-end test:

```python
def _highlighted_csv(tmp_path: Path) -> Path:
    header = (
        "Highlight,Title,Author,ISBN,Collections,Reading Status,"
        "Book Added Date,Location,Tags,Note,Date,Favorite\n"
    )
    row = (
        '"Fear is the mind-killer",Stalin,Stephen Kotkin,9781594203794,,'
        "Reading,2026-07-24,45-49,Stalin,,2026-07-24 11:15:47,N\n"
    )
    p = tmp_path / "Highlights for Stalin.csv"
    p.write_text(header + row, encoding="utf-8")
    return p


def test_highlighted_end_to_end(tmp_path):
    csv_path = _highlighted_csv(tmp_path)
    out = tmp_path / "Obsidian"
    result = runner.invoke(app, ["highlighted", "--csv", str(csv_path), "--output", str(out)])
    assert result.exit_code == 0, result.output
    note = out / "Stephen Kotkin" / "Stalin" / "Stalin.md"
    assert note.exists()
    assert "![](Highlights.md)" in note.read_text()
    hl = (note.parent / "Highlights.md").read_text()
    assert "> [!quote]+ p. 45–49" in hl
    assert "^p45-49" in hl
```

- [ ] **Step 2: Run** `uv run pytest tests/test_cli.py -q` → all PASS.

- [ ] **Step 3: Run full suite** `uv run pytest -q` → all PASS.

- [ ] **Step 4: Update `README.md`.** Add the `highlighted` capability to the
capability bullet list, and add a section (match the heading level of the
existing "Kobo → Obsidian highlights" section):

```markdown
### Highlighted → Obsidian highlights

Import highlights captured from *physical* books with the
[Highlighted](https://highlighted.app) app (CSV export):

​```bash
books highlighted --csv "Highlights for Stalin.csv" --output ~/Obsidian
​```

Every highlight is imported and grouped by book. For each book this writes
`<Author>/<Title>/Highlights.md` — Obsidian `[!quote]`/`[!note]` callouts labelled
by page (`p. 45–49`) with stable `^p45-49` block anchors — and embeds it into the
book note via `![](Highlights.md)`. Books are matched to existing notes by ISBN,
so highlights land alongside any Calibre/Goodreads data for the same book.
```

(Use normal triple-backtick fences in the actual README.)

- [ ] **Step 5: Commit**

```bash
git add tests/test_cli.py README.md
git commit -m "Wire highlighted into CLI tests + document in README"
```

---

## Self-Review Notes

- **Spec coverage:** command name (T2), page label/anchor (T1), import-all (T2
  convert), ISBN-first match/merge (T2), wholesale regen + never-overwrite (T2
  tests), shim + registration (T2), README + CLI tests (T3). All covered.
- **Type consistency:** `Highlight.page: str | None`; `parse_csv -> list[dict]`;
  `row_to_highlight(row: dict) -> Highlight`; `convert(csv_path, output) -> dict`
  with keys `books`/`entries`/`authors` used consistently in tests and echo.
- **Shim:** `scripts/highlighted_obsidian.py` calls `main()`, mirroring the others.
