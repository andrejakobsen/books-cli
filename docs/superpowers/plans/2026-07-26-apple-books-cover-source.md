# Apple Books Cover Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Apple Books (via the public iTunes Search API) as the first cover source tried by the `books covers` command, ahead of Google → Open Library → Amazon.

**Architecture:** A new `apple_books_candidates(book, fetch_json)` function in `booktools/covers.py` mirrors the existing source signature and is prepended to the `_API_SOURCES` priority tuple. Two small pure helpers rewrite the iTunes artwork URL to a large render and extract an ISBN from the artwork path. Stats dicts and the CLI summary line gain an `apple` entry. All network I/O stays injected, so everything is unit-tested offline.

**Tech Stack:** Python 3.11+ stdlib only (`urllib`), Typer CLI, pytest. Follows the existing patterns in `booktools/covers.py` and `tests/test_covers.py`.

**Spec:** `docs/superpowers/specs/2026-07-26-apple-books-cover-source-design.md`

---

## Key facts (from the spec's feasibility test)

- iTunes artwork URLs look like `.../<isbn-or-opaque>.jpg/100x100bb.jpg`. The **size token is the last path segment**; the **ISBN (when present) is the second-to-last segment's stem**. Example: `https://is1-ssl.mzstatic.com/image/thumb/Pub126/v4/5c/82/e3/xyz/9781849839037.jpg/100x100bb.jpg`.
- Non-ISBN artwork uses opaque stems like `mzi.mwffatop.jpg` → no ISBN.
- Querying by title + author (including the full subtitled title) works; ISBN-as-term does **not** (iTunes indexes a different edition's ISBN), so the Apple source never uses ISBN as a query term.
- Store hardcoded to `gb`; entity `ebook`; requested render `1400x1400bb`; source name `apple`.

---

## Task 1: Apple Books source function + helpers

**Files:**
- Modify: `booktools/covers.py` (add constants, two helpers, and `apple_books_candidates` after `amazon_candidates`, before `_API_SOURCES` at line ~284)
- Test: `tests/test_covers.py`

- [ ] **Step 1: Add the test fixture and helper-function tests**

Add near the other module-level fixtures in `tests/test_covers.py` (e.g. after `GOOGLE_VOLUME`):

```python
# iTunes Search API shape: results[] with artworkUrl100 (size token = last
# path segment; ISBN, when present, is the second-to-last segment's stem).
ITUNES_RESULTS = {
    "results": [
        {
            "trackName": "The Deluge",
            "artistName": "Adam Tooze",
            "artworkUrl100": (
                "https://is1-ssl.mzstatic.com/image/thumb/Pub3/v4/57/c1/ac/"
                "abc/9780241006115.jpg/100x100bb.jpg"
            ),
        }
    ]
}

# artwork with an opaque (non-ISBN) filename stem -> no ISBN to backfill
ITUNES_RESULTS_NO_ISBN = {
    "results": [
        {
            "collectionName": "The Anatomy of Fascism",
            "artistName": "Robert O. Paxton",
            "artworkUrl100": (
                "https://is1-ssl.mzstatic.com/image/thumb/Publication/52/22/e8/"
                "mzi.mwffatop.jpg/100x100bb.jpg"
            ),
        }
    ]
}


def test_itunes_artwork_upgrades_size_token():
    art = ("https://is1-ssl.mzstatic.com/image/thumb/Pub3/v4/57/c1/ac/"
           "abc/9780241006115.jpg/100x100bb.jpg")
    big = covers._itunes_artwork(art)
    assert big.endswith("/9780241006115.jpg/1400x1400bb.jpg")
    assert "100x100bb" not in big


def test_itunes_isbn_reads_second_to_last_segment():
    art = ("https://is1-ssl.mzstatic.com/image/thumb/Pub3/v4/57/c1/ac/"
           "abc/9780241006115.jpg/100x100bb.jpg")
    assert covers._itunes_isbn(art) == "9780241006115"


def test_itunes_isbn_none_for_opaque_stem():
    art = ("https://is1-ssl.mzstatic.com/image/thumb/Publication/52/22/e8/"
           "mzi.mwffatop.jpg/100x100bb.jpg")
    assert covers._itunes_isbn(art) is None
```

- [ ] **Step 2: Run the helper tests to verify they fail**

Run: `uv run pytest tests/test_covers.py -k "itunes" -q`
Expected: FAIL with `AttributeError: module 'booktools.covers' has no attribute '_itunes_artwork'`

- [ ] **Step 3: Add constants + the two helpers**

In `booktools/covers.py`, immediately after `amazon_candidates` (ends ~line 281) and before the `# The API-backed sources...` comment (~line 284), insert:

```python
ITUNES_API = "https://itunes.apple.com/search"
ITUNES_COUNTRY = "gb"
ITUNES_ENTITY = "ebook"
ITUNES_ART_SIZE = "1400x1400bb"   # iTunes artwork is resizable via this token


def _itunes_artwork(artwork_url: str) -> str:
    """Rewrite an iTunes ``artworkUrl100`` to a large render.

    The size token is the final path segment (``.../<name>.jpg/100x100bb.jpg``),
    so we swap it for ``ITUNES_ART_SIZE`` while keeping the rest of the path.
    """
    base = artwork_url.rsplit("/", 1)[0]
    return f"{base}/{ITUNES_ART_SIZE}.jpg"


def _itunes_isbn(artwork_url: str) -> str | None:
    """Extract an ISBN from an iTunes artwork URL, if the path embeds one.

    iTunes names many artwork paths ``.../<isbn>.jpg/100x100bb.jpg`` — the ISBN
    is the segment *before* the size token. Returns it only when that stem is a
    10- or 13-digit number; opaque stems (e.g. ``mzi.mwffatop``) yield ``None``.
    """
    parts = artwork_url.rsplit("/", 2)   # [prefix, "<isbn>.jpg", "100x100bb.jpg"]
    if len(parts) < 3:
        return None
    stem = parts[1].rsplit(".", 1)[0]
    if stem.isdigit() and len(stem) in (10, 13):
        return stem
    return None
```

- [ ] **Step 4: Run the helper tests to verify they pass**

Run: `uv run pytest tests/test_covers.py -k "itunes" -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Add tests for `apple_books_candidates`**

Append to `tests/test_covers.py`:

```python
def test_apple_books_query_uses_title_and_author_not_isbn():
    book = covers.MissingBook(
        note_path=None, title="The  Deluge", authors=["Adam Tooze"],
        isbn="9781847374530", amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"results": []}

    covers.apple_books_candidates(book, fake_fetch)
    url = captured["url"]
    # title + author in the term, whitespace collapsed
    assert "Deluge" in url and "Adam" in url and "Tooze" in url
    assert "The%20%20Deluge" not in url   # collapsed, not doubled
    # never queries by ISBN (iTunes ISBN-term search is unreliable)
    assert "isbn" not in url.lower()
    assert "9781847374530" not in url
    # ebook entity, GB store
    assert "entity=ebook" in url
    assert "country=gb" in url


def test_apple_books_builds_candidate_with_hires_url_and_isbn():
    book = covers.MissingBook(
        note_path=None, title="The Deluge", authors=["Adam Tooze"],
        isbn=None, amazon=None)
    cands = covers.apple_books_candidates(book, lambda url: ITUNES_RESULTS)
    assert len(cands) == 1
    c = cands[0]
    assert c.source == "apple"
    assert c.fmt is None
    assert c.label == "The Deluge — Adam Tooze"
    assert c.image_url.endswith("/9780241006115.jpg/1400x1400bb.jpg")
    assert c.isbn == "9780241006115"


def test_apple_books_uses_collection_name_and_no_isbn_for_opaque_art():
    book = covers.MissingBook(
        note_path=None, title="The Anatomy of Fascism",
        authors=["Robert O. Paxton"], isbn=None, amazon=None)
    cands = covers.apple_books_candidates(book, lambda url: ITUNES_RESULTS_NO_ISBN)
    assert len(cands) == 1
    assert cands[0].label == "The Anatomy of Fascism — Robert O. Paxton"
    assert cands[0].isbn is None
    assert "1400x1400bb" in cands[0].image_url


def test_apple_books_normalizes_author():
    book = covers.MissingBook(
        note_path=None, title="The Republic",
        authors=["Plato and Benjamin Jowett"], isbn=None, amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"results": []}

    covers.apple_books_candidates(book, fake_fetch)
    assert "Plato" in captured["url"]
    assert "Benjamin" not in captured["url"]   # co-author tail dropped


def test_apple_books_no_results_returns_empty():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn=None, amazon=None)
    assert covers.apple_books_candidates(book, lambda url: {"results": []}) == []


def test_apple_books_skips_results_without_artwork():
    book = covers.MissingBook(
        note_path=None, title="X", authors=["Y"], isbn=None, amazon=None)
    data = {"results": [{"trackName": "X", "artistName": "Y"}]}   # no artworkUrl100
    assert covers.apple_books_candidates(book, lambda url: data) == []
```

- [ ] **Step 6: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_covers.py -k "apple_books" -q`
Expected: FAIL with `AttributeError: module 'booktools.covers' has no attribute 'apple_books_candidates'`

- [ ] **Step 7: Implement `apple_books_candidates`**

In `booktools/covers.py`, immediately after `_itunes_isbn` (from Step 3), add:

```python
def apple_books_candidates(book: MissingBook, fetch_json) -> list[Candidate]:
    """Query the iTunes Search API (Apple Books); one candidate per ebook result.

    Always searches by title + author, scoped to the GB store — iTunes ISBN-term
    search is unreliable, so the note's ISBN is not used as a query term. Artwork
    URLs are upgraded to a large render, and an ISBN embedded in the artwork path
    is captured for frontmatter backfill.
    """
    parts = [_clean(book.title)]
    if book.authors:
        parts.append(normalize_author(book.authors[0]))
    term = " ".join(p for p in parts if p)
    url = (f"{ITUNES_API}?term={quote(term)}"
           f"&entity={ITUNES_ENTITY}&country={ITUNES_COUNTRY}&limit=5")
    data = fetch_json(url) or {}
    out: list[Candidate] = []
    for result in data.get("results", []):
        artwork = result.get("artworkUrl100")
        if not artwork:
            continue
        name = result.get("trackName") or result.get("collectionName") or book.title
        artist = result.get("artistName")
        out.append(Candidate(
            source="apple",
            label=_label(name, [artist] if artist else []),
            image_url=_itunes_artwork(artwork),
            fmt=None,
            isbn=_itunes_isbn(artwork),
        ))
    return out
```

- [ ] **Step 8: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_covers.py -k "apple_books or itunes" -q`
Expected: PASS (9 tests)

- [ ] **Step 9: Commit**

```bash
git add booktools/covers.py tests/test_covers.py
git commit -m "feat(covers): add Apple Books (iTunes) cover source function

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Wire Apple in first — source order, stats, CLI summary

**Files:**
- Modify: `booktools/covers.py` — `_API_SOURCES` (~line 285), `gather_with_errors` docstring (~line 291), `run()` stats dict (~lines 511-512), `covers_command` echo (~lines 606-611)
- Modify: `tests/test_covers.py` — `test_gather_candidates_source_order` (~line 409)
- Test: `tests/test_covers.py`

- [ ] **Step 1: Add a failing ordering test for Apple-first**

Append to `tests/test_covers.py`:

```python
def test_gather_candidates_apple_first():
    book = covers.MissingBook(
        note_path=None, title="The Deluge", authors=["Adam Tooze"],
        isbn=None, amazon="B00ABCDEFG")

    def fake_fetch(url):
        if "itunes.apple.com" in url:
            return ITUNES_RESULTS
        if "googleapis" in url:
            return GOOGLE_VOLUME
        if "editions.json" in url:
            return OL_EDITIONS
        return OL_SEARCH

    cands = covers.gather_candidates(book, fake_fetch)
    sources = [c.source for c in cands]
    assert sources[0] == "apple"
    assert sources[-1] == "amazon"
    # apple before google before openlibrary before amazon
    assert (sources.index("apple") < sources.index("google")
            < sources.index("openlibrary") < sources.index("amazon"))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_covers.py::test_gather_candidates_apple_first -q`
Expected: FAIL — `sources[0]` is `"google"`, not `"apple"` (apple not yet wired in)

- [ ] **Step 3: Prepend Apple to `_API_SOURCES`**

In `booktools/covers.py`, change (~line 284):

```python
# The API-backed sources, in priority order; amazon is URL-only (no fetch).
_API_SOURCES = (
    ("google", google_books_candidates),
    ("openlibrary", openlibrary_candidates),
)
```

to:

```python
# The API-backed sources, in priority order; amazon is URL-only (no fetch).
_API_SOURCES = (
    ("apple", apple_books_candidates),
    ("google", google_books_candidates),
    ("openlibrary", openlibrary_candidates),
)
```

- [ ] **Step 4: Update `gather_with_errors` docstring**

In `booktools/covers.py`, in `gather_with_errors` (~line 296), update the parenthetical source list:

```python
    order (Apple, Google, Open Library, Amazon) and *errored* is the list of source
```

(was `order (Google, Open Library, Amazon)`; also update the identical phrasing in `gather_candidates`'s docstring at ~line 311 to `All candidates in source-priority order: Apple, Google, Open Library, Amazon.`)

- [ ] **Step 5: Add `apple` to the stats dicts in `run()`**

In `booktools/covers.py`, in `run()` (~lines 511-512), change:

```python
        "by_source": {"google": 0, "openlibrary": 0, "amazon": 0},
        "errored": {"google": 0, "openlibrary": 0, "amazon": 0},
```

to:

```python
        "by_source": {"apple": 0, "google": 0, "openlibrary": 0, "amazon": 0},
        "errored": {"apple": 0, "google": 0, "openlibrary": 0, "amazon": 0},
```

- [ ] **Step 6: Add `apple` to the CLI summary line**

In `booktools/covers.py`, in `covers_command` (~lines 607-611), change:

```python
    typer.echo(
        f"Scanned {stats['scanned']} notes, {stats['missing']} missing covers → "
        f"{stats['fetched']} fetched "
        f"(google {bs['google']}, openlibrary {bs['openlibrary']}, amazon {bs['amazon']}), "
        f"{stats['not_found']} not found."
    )
```

to:

```python
    typer.echo(
        f"Scanned {stats['scanned']} notes, {stats['missing']} missing covers → "
        f"{stats['fetched']} fetched "
        f"(apple {bs['apple']}, google {bs['google']}, "
        f"openlibrary {bs['openlibrary']}, amazon {bs['amazon']}), "
        f"{stats['not_found']} not found."
    )
```

- [ ] **Step 7: Update the existing source-order test for the new lead source**

In `tests/test_covers.py`, `test_gather_candidates_source_order` (~line 409) currently asserts `sources[0] == "google"`. Because Apple is now first but this test's `fake_fetch` returns `GOOGLE_VOLUME`/OL shapes (no iTunes `results`), Apple yields no candidates and Google remains the first *present* source — so the assertions still hold. Confirm by re-running; no edit needed unless it fails.

Run: `uv run pytest tests/test_covers.py::test_gather_candidates_source_order -q`
Expected: PASS (Apple contributes nothing here, so Google is still first)

- [ ] **Step 8: Run the full covers test suite**

Run: `uv run pytest tests/test_covers.py -q`
Expected: PASS (all tests, including `test_gather_candidates_apple_first`)

- [ ] **Step 9: Commit**

```bash
git add booktools/covers.py tests/test_covers.py
git commit -m "feat(covers): try Apple Books first, ahead of google/openlibrary/amazon

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Documentation

**Files:**
- Modify: `booktools/covers.py` — module docstring (~lines 2-10) and `covers_command` help (~lines 569-579)
- Modify: `CLAUDE.md` — the `covers` capability bullet
- Modify: `README.md` — any `covers` source description

- [ ] **Step 1: Update the module docstring**

In `booktools/covers.py`, update the opening docstring so the source order reads Apple first. Change the first sentence + the "Sources are tried in order" sentence to name Apple Books:

```python
"""Fill missing book-note covers from Apple Books, Google, Open Library, and Amazon.

Scans an Obsidian vault for `type: book` notes whose `cover:` frontmatter is
blank/absent and fetches a cover image. Sources are tried in order — Apple Books
(iTunes Search API, title+author, GB store), then Google Books, then Open Library
(paperback editions preferred where the format is known), then Amazon (only when
the note already carries an `amazon` ASIN, by constructing the known cover-image
URL — no scraping). When a note has an ISBN it drives the Google/Open Library
lookup directly (Google `isbn:` query / Open Library `/b/isbn/` cover); Apple is
always queried by title+author because its ISBN-term search is unreliable. All
network I/O is injected so the logic is unit-testable; vault writing reuses
booktools.obsidian.
```

(Keep the remaining paragraphs of the docstring as-is.)

- [ ] **Step 2: Update the `covers` command help text**

In `booktools/covers.py`, in `covers_command`'s docstring (~lines 570-578), change the source sentence to lead with Apple:

```python
    frontmatter is blank and fetches a cover from Apple Books, then Google Books,
    then Open Library (paperback editions preferred where known), then Amazon
    (only when the note already carries an 'amazon' ASIN). By default the best
```

- [ ] **Step 3: Update CLAUDE.md**

In `CLAUDE.md`, find the `booktools/covers.py → covers` bullet. Update the "Sources are tried in order" sentence to:

> Sources are tried in order — Apple Books (iTunes Search API, queried by title+author against the GB store), then Google Books, then Open Library (paperback editions preferred where `physical_format` is known), then Amazon (only when the note already has an `amazon` ASIN, by building the known cover-image URL — no scraping).

Also, if the bullet mentions ISBN-driven lookup, add: an Apple artwork path often embeds the edition ISBN, which is backfilled into the note like any other learned ISBN.

- [ ] **Step 4: Update README.md**

In `README.md`, find the `covers` description and update any ordered source list to put Apple Books first (matching the CLAUDE.md wording above). If README only mentions covers generically, add "Apple Books" to the front of the source list.

- [ ] **Step 5: Run the full suite as a final check**

Run: `uv run pytest -q`
Expected: PASS (entire suite)

- [ ] **Step 6: Commit**

```bash
git add booktools/covers.py CLAUDE.md README.md
git commit -m "docs(covers): document Apple Books as the first cover source

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** New source function (Task 1), first-priority wiring + stats + CLI (Task 2), docs (Task 3). All seven spec test cases are covered: query shape/no-ISBN-term (test_apple_books_query_uses_title_and_author_not_isbn), 1400x1400bb upgrade (test_itunes_artwork_upgrades_size_token / candidate test), ISBN extraction (test_itunes_isbn_reads_second_to_last_segment), non-ISBN → None (test_itunes_isbn_none_for_opaque_stem / opaque candidate test), empty results (test_apple_books_no_results_returns_empty), apple-first ordering (test_gather_candidates_apple_first), and source-error isolation (already covered by the generic `gather_with_errors`/`run` error tests, which now include an `apple` stats key).
- **ISBN path subtlety:** `_itunes_isbn` reads the **second-to-last** path segment (size token is last). `_itunes_artwork` swaps only the last segment. Tests pin both.
- **No placeholders:** every code and doc step shows the exact content.
- **Type consistency:** `apple_books_candidates(book, fetch_json) -> list[Candidate]` matches `google_books_candidates`/`openlibrary_candidates`; `source="apple"` matches the stats keys and CLI summary.
