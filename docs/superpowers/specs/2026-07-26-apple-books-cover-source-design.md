# Apple Books cover source

**Date:** 2026-07-26
**Status:** Approved
**Component:** `books/covers.py`

## Goal

Add Apple Books (via the public iTunes Search API) as the **first** cover source
tried by the `covers` command, ahead of the existing chain: Google Books → Open
Library → Amazon.

## Background

The `covers` command fills blank `cover:` frontmatter on `type: book` notes by
trying a priority-ordered list of sources. A feasibility test against the public
iTunes Search API (`https://itunes.apple.com/search`) found it returns accurate,
tall cover images for the vault's history titles, is stdlib-reachable via
`urllib`, and fits the existing injectable-`fetch_json` source design.

The `itunesartwork.bendodson.com` proxy is **not** used: with `type=request` it
only returns the iTunes Search URL it would call. We query Apple's Search API
directly.

### Empirical findings that shaped the design

- **Query by title + author works**, including the full subtitled frontmatter
  title (e.g. `"A Line in the Sand: Britain, France and the Struggle that Shaped
  the Middle East James Barr"` matches). So the Apple source reuses the same
  frontmatter-driven query builder style as Google/Open Library.
- **ISBN-as-term is unreliable.** iTunes indexes a specific edition's ISBN, which
  usually differs from the note's ISBN. A real note ISBN (`9781847374530`)
  returned 0 results, while the edition ISBN iTunes actually carries
  (`9781849839037`) matched. Therefore, unlike Google/Open Library, the Apple
  source does **not** go ISBN-first — it always queries by title + author.
- **Artwork URLs are resizable** by editing the trailing size token
  (`.../100x100bb.jpg` → `.../1400x1400bb.jpg`). 1400px images are ~300–450 KB,
  are real covers (not squares), and comfortably pass `MIN_IMAGE_DIM`.
- **Many artwork URLs are ISBN-named** (`.../9781849839037.jpg`), giving a free
  ISBN to backfill via the existing `Candidate.isbn` path. Others use opaque
  names (`.../mzi.mwffatop.jpg`) and yield no ISBN.

## Decisions

| Decision | Choice |
|---|---|
| Store / country | Hardcode `gb` (matches the GB-heavy library; no config key — YAGNI) |
| Cover resolution | `1400x1400bb` |
| Source name (code/stats/output) | `apple` |
| Priority | First — before google, openlibrary, amazon |
| Query strategy | Always title + author; ISBN **not** used as a query term |
| ISBN backfill | Yes, when the artwork filename is a 10- or 13-digit number |
| Format ranking | None — Apple is ebook-only, `fmt=None` |

## Design

### New source function

Add to `books/covers.py`:

```python
ITUNES_API = "https://itunes.apple.com/search"
ITUNES_COUNTRY = "gb"
ITUNES_ENTITY = "ebook"
ITUNES_ART_SIZE = "1400x1400bb"


def apple_books_candidates(book: MissingBook, fetch_json) -> list[Candidate]:
    """Query the iTunes Search API (Apple Books); one candidate per ebook result.

    Always searches by title + author (iTunes ISBN-term search is unreliable),
    scoped to the GB store. Artwork URLs are upgraded to a large render and, when
    the artwork filename is an ISBN, that ISBN is captured for frontmatter backfill.
    """
```

Behaviour:
- Build `term = _clean(book.title)` plus, when present,
  `" " + normalize_author(book.authors[0])`.
- Request
  `{API}?term=<quoted term>&entity=ebook&country=gb&limit=5`.
- For each result with an `artworkUrl100`:
  - `image_url` = artwork with its trailing `/<size>.jpg` segment replaced by
    `/1400x1400bb.jpg`.
  - `label` = `_label(trackName or collectionName, [artistName])`.
  - `source="apple"`, `fmt=None`.
  - `isbn` = the artwork filename stem when it is all digits and length 10 or 13,
    else `None`.
- Return `[]` when there are no results.

### Helpers

- A small helper to rewrite the artwork size token (replace the last path
  segment with `1400x1400bb.jpg`).
- A small helper to extract an ISBN from an artwork URL (filename stem; digits;
  length 10 or 13).

### Wiring

- Prepend `("apple", apple_books_candidates)` to `_API_SOURCES` so it is tried
  first. `gather_with_errors` already iterates in priority order — this alone
  makes Apple win automatic mode and lead interactive mode.
- Add `"apple": 0` to both the `by_source` and `errored` dicts in `run()`.
- Add `apple {n}` (listed first) to the CLI summary line in `covers_command`.

### Reused unchanged

`pick_cover` validation, `apply_cover` + ISBN backfill (`Candidate.isbn`),
`fetch_with_retry`, dry-run, interactive prompt, and single-`--book` mode all
work without modification.

## Testing (TDD)

Unit tests in `tests/test_covers.py` with an injected `fetch_json` returning a
canned iTunes payload:

1. Builds the correct query — title + author in `term`, `entity=ebook`,
   `country=gb`, and **no** `isbn:` term even when the book has an ISBN.
2. Upgrades the artwork URL to `1400x1400bb`.
3. Extracts the ISBN from an ISBN-named artwork URL.
4. Yields `isbn=None` for a non-ISBN artwork URL (e.g. `mzi.mwffatop.jpg`).
5. Returns `[]` on empty results.
6. `apple` appears first in `gather_candidates` ordering (ahead of google).
7. An Apple source error is recorded under `errored["apple"]` by
   `gather_with_errors` (source-error isolation).

## Docs

Update: `covers.py` module docstring + `covers` command help, the `covers`
bullet in `CLAUDE.md`, and `README.md`.

## Out of scope (YAGNI)

- Configurable country / store.
- Multi-volume disambiguation (e.g. Kotkin *Stalin* volumes) — same limitation
  as the existing sources.
- Physical-format ranking — Apple Books is ebook-only.
- Using the `itunesartwork.bendodson.com` proxy.
