# `highlighted` / `reviewed` Book-Note Flags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two monotonic boolean frontmatter properties — `highlighted` and `reviewed` — to every book note so the Obsidian vault can be filtered on reading progress.

**Architecture:** Both flags live in the canonical `BOOK_PROPERTY_ORDER` and default to `false`. A new `OVERWRITE_KEYS` set makes `update_frontmatter` treat a `"true"` update for these keys as always-writable (flip `false`→`true`), while `"false"` defaults follow the existing never-overwrite path so a flag never regresses. Highlight importers set `highlighted: true`; the goodreads importer sets `reviewed: true` when it writes a review.

**Tech Stack:** Python 3 (standard library only), pytest, Typer CLI.

---

## File Structure

- `books/obsidian.py` — schema constants (`BOOK_PROPERTY_ORDER`, new `OVERWRITE_KEYS`, `BOOK_FLAG_DEFAULTS`), the `update_frontmatter` overwrite rule, and the `find_or_create` stub defaults.
- `books/calibre_obsidian.py` — `_calibre_updates` emits `false` defaults.
- `books/goodreads_obsidian.py` — `_goodreads_updates` emits `false` defaults; `convert` sets `reviewed: true` when a review is written.
- `books/kobo_export.py`, `books/highlighted_obsidian.py`, `books/readwise_obsidian.py` — each adds `highlighted: true` to its frontmatter update dict.
- Tests mirror the modules: `tests/test_obsidian.py`, `tests/test_calibre_to_obsidian.py`, `tests/test_goodreads_obsidian.py`, `tests/test_kobo_export.py`, `tests/test_highlighted_obsidian.py`, `tests/test_readwise.py`.

---

## Task 1: Schema constants + `update_frontmatter` overwrite rule

**Files:**
- Modify: `books/obsidian.py` (`BOOK_PROPERTY_ORDER` ~lines 25-49; add constants after it; `update_frontmatter` ~lines 280-315)
- Test: `tests/test_obsidian.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_obsidian.py`:

```python
def test_property_order_includes_flags_after_status():
    order = ob.BOOK_PROPERTY_ORDER
    assert "highlighted" in order
    assert "reviewed" in order
    assert order.index("highlighted") == order.index("status") + 1
    assert order.index("reviewed") == order.index("status") + 2


def test_overwrite_key_true_flips_existing_false():
    note = "---\ntype: book\nhighlighted: false\n---\n"
    out = ob.update_frontmatter(note, {"highlighted": "true"})
    assert "highlighted: true" in out
    assert "highlighted: false" not in out


def test_overwrite_key_false_default_does_not_downgrade_true():
    note = "---\ntype: book\nhighlighted: true\n---\n"
    out = ob.update_frontmatter(note, {"highlighted": "false"})
    assert "highlighted: true" in out
    assert "highlighted: false" not in out


def test_overwrite_key_false_default_appends_when_absent():
    note = "---\ntype: book\n---\n"
    out = ob.update_frontmatter(note, {"reviewed": "false"})
    assert "reviewed: false" in out


def test_non_overwrite_key_still_never_overwrites():
    note = '---\ntype: book\ntitle: "Keep"\n---\n'
    out = ob.update_frontmatter(note, {"title": ob.yaml_quote("New")})
    assert 'title: "Keep"' in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_obsidian.py -k "flags or overwrite_key" -v`
Expected: FAIL (`highlighted` not in order; `true` not flipping — currently blocked because the value is non-empty but the existing value is non-blank).

- [ ] **Step 3: Add schema constants**

In `books/obsidian.py`, add `"highlighted"` and `"reviewed"` to `BOOK_PROPERTY_ORDER` immediately after `"status"`:

```python
BOOK_PROPERTY_ORDER = (
    "type",
    "title",
    "authors",
    "topics",
    "series",
    "series_index",
    "publisher",
    "published",
    "language",
    "format",
    "pages",
    "status",
    "highlighted",
    "reviewed",
    "shelves",
    "rating",
    "isbn",
    "amazon",
    "google",
    "uuid",
    "calibre_id",
    "date_added",
    "date_read",
    "source",
    "cover",
)

# Book-note flags that record whether derived content (highlights, a review) has
# been imported. They are monotonic: an update of "true" always wins, but the
# "false" default follows the normal never-overwrite path so a flag never
# regresses true -> false regardless of import order.
OVERWRITE_KEYS = frozenset({"highlighted", "reviewed"})

# Default values every book note carries so two-way filtering works in Obsidian.
BOOK_FLAG_DEFAULTS = {"highlighted": "false", "reviewed": "false"}
```

- [ ] **Step 4: Implement the overwrite rule**

In `update_frontmatter`, replace the "1. Fill blanks in place." loop so a
`"true"` update for an `OVERWRITE_KEYS` key always writes:

```python
    # 1. Fill blanks in place; OVERWRITE_KEYS with a "true" update always win.
    for key, formatted in updates.items():
        if key not in existing or formatted == "":
            continue
        overwrite = key in OVERWRITE_KEYS and formatted == "true"
        if overwrite or _is_blank_value(new_lines[existing[key]]):
            new_lines[existing[key]] = f"{key}: {formatted}"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_obsidian.py -v`
Expected: PASS (all obsidian tests, including the existing `test_update_frontmatter_fills_blank_only`).

- [ ] **Step 6: Commit**

```bash
git add books/obsidian.py tests/test_obsidian.py
git commit -m "feat(obsidian): add highlighted/reviewed flags and overwrite rule"
```

---

## Task 2: New stubs carry `false` defaults

**Files:**
- Modify: `books/obsidian.py` (`VaultIndex.find_or_create` ~lines 446-459)
- Test: `tests/test_obsidian.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_obsidian.py`:

```python
def test_new_stub_carries_flag_defaults(tmp_path):
    idx = ob.VaultIndex(tmp_path)
    bn = idx.find_or_create(ob.BookRef(title="A Book", authors=["An Author"]))
    text = bn.note_path.read_text(encoding="utf-8")
    assert "highlighted: false" in text
    assert "reviewed: false" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_obsidian.py::test_new_stub_carries_flag_defaults -v`
Expected: FAIL (stub has no `highlighted`/`reviewed` lines).

- [ ] **Step 3: Add defaults to the stub**

In `find_or_create`, extend the stub `update_frontmatter` call:

```python
            stub = update_frontmatter("---\ntype: book\n---\n", {
                "title": yaml_quote(ref.title) if ref.title else "",
                "authors": link_list(ref.authors) if ref.authors else "",
                **BOOK_FLAG_DEFAULTS,
            })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_obsidian.py::test_new_stub_carries_flag_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add books/obsidian.py tests/test_obsidian.py
git commit -m "feat(obsidian): new book stubs default highlighted/reviewed to false"
```

---

## Task 3: Calibre + Goodreads writers emit `false` defaults

**Files:**
- Modify: `books/calibre_obsidian.py` (`_calibre_updates` ~lines 167-198; import from `.obsidian`)
- Modify: `books/goodreads_obsidian.py` (`_goodreads_updates` ~lines 139-169)
- Test: `tests/test_calibre_to_obsidian.py`, `tests/test_goodreads_obsidian.py`

Note: `_goodreads_updates` seeds every `BOOK_PROPERTY_ORDER` key to `""`; without an explicit override the new keys would emit as empty placeholders (`highlighted:`), so both writers must set them to `"false"`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_calibre_to_obsidian.py` (adapt the import alias to the file's existing one, e.g. `import books.calibre_obsidian as cal`):

```python
def test_calibre_updates_emit_flag_defaults():
    from books.calibre_obsidian import _calibre_updates
    from books.calibre_obsidian import BookMetadata
    meta = BookMetadata(title="T", authors=["A"])
    u = _calibre_updates(meta, "")
    assert u["highlighted"] == "false"
    assert u["reviewed"] == "false"
```

If `BookMetadata` requires more fields, construct it the same way the existing calibre tests in this file do (copy their construction). Add to `tests/test_goodreads_obsidian.py`:

```python
def test_goodreads_updates_emit_flag_defaults():
    from books.goodreads_obsidian import _goodreads_updates, GoodreadsBook
    book = GoodreadsBook(title="T", authors=["A"])
    u = _goodreads_updates(book)
    assert u["highlighted"] == "false"
    assert u["reviewed"] == "false"
```

If `GoodreadsBook` requires more fields, copy the construction from an existing test in that file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_calibre_to_obsidian.py::test_calibre_updates_emit_flag_defaults tests/test_goodreads_obsidian.py::test_goodreads_updates_emit_flag_defaults -v`
Expected: FAIL (`highlighted` is `""` for goodreads / KeyError for calibre).

- [ ] **Step 3: Implement calibre defaults**

In `books/calibre_obsidian.py` `_calibre_updates`, before `return u`:

```python
    u["highlighted"] = "false"
    u["reviewed"] = "false"
    return u
```

- [ ] **Step 4: Implement goodreads defaults**

In `books/goodreads_obsidian.py` `_goodreads_updates`, before `return u`:

```python
    u["highlighted"] = "false"
    u["reviewed"] = "false"
    return u
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_calibre_to_obsidian.py tests/test_goodreads_obsidian.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add books/calibre_obsidian.py books/goodreads_obsidian.py tests/test_calibre_to_obsidian.py tests/test_goodreads_obsidian.py
git commit -m "feat: calibre/goodreads writers emit highlighted/reviewed defaults"
```

---

## Task 4: Highlight importers set `highlighted: true`

**Files:**
- Modify: `books/kobo_export.py` (updates dict ~lines 236-241)
- Modify: `books/highlighted_obsidian.py` (updates dict ~lines 104-109)
- Modify: `books/readwise_obsidian.py` (updates dict ~lines 122-128)
- Test: `tests/test_kobo_export.py`, `tests/test_highlighted_obsidian.py`, `tests/test_readwise.py`

- [ ] **Step 1: Write the failing tests**

For each importer, add an assertion mirroring that file's existing end-to-end test. The pattern: run the importer against a vault that already has a matching book note (created by the existing test fixtures), then assert the note contains `highlighted: true`. Example for `tests/test_kobo_export.py` — locate the existing test that runs the obsidian-mode export and reuse its setup, then add:

```python
def test_kobo_sets_highlighted_true(tmp_path):
    # Reuse the same fixture setup as the existing obsidian-mode test in this
    # file (create the sqlite db + a matching book note under vault/Books/),
    # then run the exporter in obsidian mode.
    # ... arrange (copy from existing test) ...
    note_text = note_path.read_text(encoding="utf-8")
    assert "highlighted: true" in note_text
```

Add the analogous `test_highlighted_sets_highlighted_true` to `tests/test_highlighted_obsidian.py` and `test_readwise_sets_highlighted_true` to `tests/test_readwise.py`, each copying the arrange/act from that file's existing importer test and asserting `"highlighted: true" in note_text`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_kobo_export.py -k highlighted_true tests/test_highlighted_obsidian.py -k highlighted_true tests/test_readwise.py -k highlighted_true -v`
Expected: FAIL (note has no `highlighted: true`).

- [ ] **Step 3: Add the flag in kobo_export**

In `books/kobo_export.py`, add to the `updates` dict:

```python
        updates = {
            "title": yaml_quote(title),
            "authors": link_list(authors) if authors else "",
            "isbn": yaml_quote(isbn) if isbn else "",
            "source": "kobo",
            "highlighted": "true",
        }
```

- [ ] **Step 4: Add the flag in highlighted_obsidian**

In `books/highlighted_obsidian.py`, add `"highlighted": "true"` to the update dict passed to `update_frontmatter`:

```python
        dest.note_path.write_text(update_frontmatter(base, {
            "title": yaml_quote(group["title"]),
            "authors": link_list(authors) if authors else "",
            "isbn": yaml_quote(group["isbn"]) if group["isbn"] else "",
            "source": "highlighted",
            "highlighted": "true",
        }), encoding="utf-8")
```

- [ ] **Step 5: Add the flag in readwise_obsidian**

In `books/readwise_obsidian.py`, add to the `updates` dict:

```python
        updates = {
            "title": yaml_quote(group["title"]),
            "authors": link_list(authors) if authors else "",
            "amazon": yaml_quote(group["amazon"]) if group["amazon"] else "",
            "shelves": plain_list(group["shelves"]) if group["shelves"] else "",
            "source": "readwise",
            "highlighted": "true",
        }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_kobo_export.py tests/test_highlighted_obsidian.py tests/test_readwise.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add books/kobo_export.py books/highlighted_obsidian.py books/readwise_obsidian.py tests/test_kobo_export.py tests/test_highlighted_obsidian.py tests/test_readwise.py
git commit -m "feat: highlight importers set highlighted: true"
```

---

## Task 5: Goodreads sets `reviewed: true` when a review is written

**Files:**
- Modify: `books/goodreads_obsidian.py` (`convert` review branch ~lines 226-232)
- Test: `tests/test_goodreads_obsidian.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_goodreads_obsidian.py`, reusing the existing convert-with-review test setup in that file:

```python
def test_goodreads_sets_reviewed_true_when_review_written(tmp_path):
    # Arrange: write a Goodreads CSV containing a row with a non-empty
    # "My Review", then run gr.convert(csv_path, vault). Copy the CSV/vault
    # setup from the existing review test in this file.
    # ... arrange (copy from existing review test) ...
    note_text = note_path.read_text(encoding="utf-8")
    assert "## Review" in note_text
    assert "reviewed: true" in note_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_goodreads_obsidian.py::test_goodreads_sets_reviewed_true_when_review_written -v`
Expected: FAIL (note has `reviewed: false`).

- [ ] **Step 3: Set `reviewed: true` on the review branch**

In `books/goodreads_obsidian.py` `convert`, update the review-written branch so the flag flips only when the review section is actually added:

```python
        review = _review_markdown(book)
        if review:
            text = dest.note_path.read_text(encoding="utf-8")
            updated = ensure_section(text, "Review", review)
            if updated != text:
                updated = update_frontmatter(updated, {"reviewed": "true"})
                dest.note_path.write_text(updated, encoding="utf-8")
                stats["reviews"] += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_goodreads_obsidian.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add books/goodreads_obsidian.py tests/test_goodreads_obsidian.py
git commit -m "feat(goodreads): set reviewed: true when a review is written"
```

---

## Task 6: Full suite + CLAUDE.md schema note

**Files:**
- Modify: `CLAUDE.md` (book-note property schema description, if present)
- Test: whole suite

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/pytest -q`
Expected: PASS (no regressions).

- [ ] **Step 2: Update schema docs**

Search `CLAUDE.md` for the frontmatter/property-schema description and add `highlighted` and `reviewed` (booleans, default `false`, flip to `true` when highlights/a review are imported) alongside the other properties. If no such section exists, skip this step.

Run: `grep -n "BOOK_PROPERTY_ORDER\|frontmatter\|property" CLAUDE.md`

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document highlighted/reviewed book-note flags"
```

---

## Notes for the implementer

- Use the project's virtualenv: `.venv/bin/pytest`. If a bare `pytest` is on PATH and configured, that works too.
- Each importer test file already has a working end-to-end test for its obsidian/import path — copy its arrange/act rather than inventing new fixtures; only the final assertion is new.
- YAML booleans are rendered bare (`true`/`false`), matching how `format` and other plain scalars are emitted — do not wrap them in `yaml_quote`.
