# `books covers` — Design

**Date:** 2026-07-25
**Status:** Approved (design)

## Problem

Some book notes in the Obsidian vault have no cover. Book notes carry a canonical
`cover:` frontmatter key (see `BOOK_PROPERTY_ORDER`), but importers only fill it
when the source supplied an image (e.g. Calibre's `cover.jpg`). Goodreads/Kobo/
Readwise/Highlighted-only books, and hand-created notes, routinely end up with a
blank `cover:`. We want a command that scans the vault, finds notes missing a
cover, and fetches one — preferring paperback editions where that is knowable.

## Goals

- New capability: `books covers`, following the existing module/`register(app)`
  convention (`booktools/covers.py` + `scripts/covers.py` shim).
- Fill only **blank/absent** `cover:` frontmatter on `type: book` notes. Do **not**
  chase broken cover links (a `cover:` that points at a missing file is left alone).
- Fetch from **Google Books → Open Library → Amazon (ASIN only)**, in that order.
- Prefer paperback editions **where the source reports format** (Open Library);
  never skip a book merely because paperback can't be confirmed.
- Automatic best-pick by default; an `--interactive` mode to reject candidates and
  step to the next; a `--dry-run` mode that writes nothing.
- Reuse the shared `obsidian.py` layer for all vault writing (never overwrite
  existing values or bodies; never rename notes).
- Stdlib-only (Typer remains the sole runtime dependency): `urllib.request` + `json`.

## Non-goals

- Amazon page scraping (fragile, against ToS). Amazon is used **only** when the
  note already has an `amazon` ASIN, by constructing the known cover-image URL.
- Replacing or "upgrading" covers that already exist.
- Detecting/repairing broken cover links.
- Image cropping/processing beyond a lightweight validity check.

## Architecture

Single module `booktools/covers.py`, added to `CAPABILITIES` in `booktools/cli.py`.
Standalone shim `scripts/covers.py` calls the module's `main()`.

The module is split into small, independently testable units. All network I/O is
injected as callables so tests never hit the network.

### Data types

```
@dataclass
class MissingBook:
    note_path: Path
    title: str
    authors: list[str]
    isbn: str | None
    amazon: str | None            # ASIN

@dataclass
class Candidate:
    source: str                   # "google" | "openlibrary" | "amazon"
    label: str                    # matched title / author, for display
    image_url: str
    fmt: str | None               # "paperback" | "hardcover" | None (unknown)
```

### Units

- `find_missing(vault: Path) -> list[MissingBook]`
  Iterate `vault/Books/*.md`, parse frontmatter via `obsidian.frontmatter_values`,
  keep `type == "book"` notes whose `cover:` is blank/absent. Extract title
  (`unquote`), authors (`extract_wikilinks`), isbn, amazon.

- `google_books_candidates(book, fetch_json) -> list[Candidate]`
  Query `https://www.googleapis.com/books/v1/volumes?q=...`:
  `isbn:<isbn>` when an ISBN is present, else `intitle:"…" inauthor:"…"`.
  For each item, take the largest `volumeInfo.imageLinks` entry
  (`extraLarge > large > medium > small > thumbnail > smallThumbnail`), upgrade
  `http` → `https` and bump `zoom`/drop `edge=curl` on thumbnail URLs. `fmt=None`
  (Google Books does not report binding reliably).

- `openlibrary_candidates(book, fetch_json) -> list[Candidate]`
  ISBN path: `https://openlibrary.org/isbn/<isbn>.json`. Title/author path:
  `https://openlibrary.org/search.json?title=…&author=…` (use `cover_i` /
  `cover_edition_key`). Where edition `physical_format` is available, tag `fmt`
  and **sort paperbacks first**. Cover URL:
  `https://covers.openlibrary.org/b/id/<cover_id>-L.jpg` (or `/b/isbn/<isbn>-L.jpg`).

- `amazon_candidates(book) -> list[Candidate]`
  Only when `book.amazon` is set. Construct
  `https://images-na.ssl-images-amazon.com/images/P/<ASIN>.01._SCLZZZZZZZ_.jpg`.
  No network call to build the URL; the image is validated at download time.

- `gather_candidates(book, fetch_json) -> list[Candidate]`
  Concatenate the three sources in priority order (Google, then Open Library, then
  Amazon). Within Open Library, paperbacks already lead. Returns the ordered list.

- `is_valid_image(data: bytes, content_type: str | None) -> bool`
  Reject non-image content types and tiny payloads (Amazon serves a blank
  gif / 1×1 placeholder when no image exists). Threshold: content-type starts with
  `image/` **and** `len(data)` above a small floor (e.g. 1000 bytes).

- `pick_cover(candidates, fetch_bytes, *, interactive, prompt) -> tuple[Candidate, bytes] | None`
  Automatic: return the first candidate whose bytes download and validate.
  Interactive: for each candidate, call `prompt(candidate)` →
  `"accept" | "next" | "skip" | "quit"`; on accept, download+validate (if it fails,
  fall through to the next). Returns `None` if skipped/exhausted; raises a sentinel
  or returns a quit marker to stop the whole run.

- `apply_cover(index: VaultIndex, book, image: bytes) -> None`
  Build a `BookRef(title, authors, isbn, amazon)`; `export_dir = index.export_dir(ref)`
  (deterministic, creates no note); write `export_dir/cover.jpg`; then
  `cover_fm, cover_embed = obsidian.cover_refs(book.note_path, export_dir)`;
  `update_frontmatter` (fills only the blank `cover:`); `ensure_top_embed(cover_embed)`;
  write the note back.

- CLI `covers(output, interactive, dry_run, limit)` orchestrates scan → gather →
  pick → apply, tallies stats, prints a summary.

### Injected I/O (default implementations)

- `fetch_json(url) -> dict`: `urllib.request` GET with a User-Agent header and a
  timeout, `json.loads` the body. Errors (network/HTTP/JSON) raise; callers catch
  per book and continue.
- `fetch_bytes(url) -> tuple[bytes, str | None]`: GET returning `(body, content_type)`.

## CLI

```
books covers [--output/-o PATH] [--interactive] [--dry-run] [--limit N]
```

- `--output/-o` (default `Obsidian`, resolved against cwd via `resolve_path`) — the
  vault to scan. Same option name/semantics as the other importers.
- `--interactive` — prompt per candidate: `[y]` accept / `[n]` next / `[s]` skip
  book / `[q]` quit.
- `--dry-run` — report the chosen candidate per book; write nothing.
- `--limit N` — process at most N missing-cover books (testing/throttling).

Errors per book (no candidates, download failure) are reported and skipped; the run
continues.

## Output

```
Scanned <N> notes, <M> missing covers → <K> fetched
(google <a>, openlibrary <b>, amazon <c>), <J> not found.
```

## Testing (TDD)

All network I/O is injected, so unit tests pass canned JSON/bytes:

- `find_missing`: temp vault with notes that have / lack `cover:`, non-book types,
  malformed frontmatter → returns exactly the blank-cover book notes.
- `google_books_candidates`: canned volumes JSON → largest image chosen, thumbnail
  upgraded, `isbn:` vs `intitle:` query selection.
- `openlibrary_candidates`: canned search/edition JSON → paperbacks ranked first,
  correct cover URL construction, ISBN vs title/author path.
- `amazon_candidates`: ASIN → expected URL; no ASIN → empty list.
- `gather_candidates`: source ordering (Google → OpenLibrary → Amazon).
- `is_valid_image`: rejects non-image content type and sub-threshold bytes; accepts
  a real image payload.
- `pick_cover`: automatic picks first valid; skips invalid to next; interactive with
  a scripted prompt exercises accept/next/skip/quit.
- `apply_cover`: temp vault → `cover.jpg` written under `Exports/<Author>/<Title>/`,
  `cover:` frontmatter filled, body embed added, existing values/body untouched,
  re-run is idempotent.

## Risks / limitations

- Title/author matching (no ISBN) can return a wrong-edition cover; `--interactive`
  and `--dry-run` mitigate. Automatic mode accepts the top match.
- Image validity is a heuristic (content-type + size), not real decoding.
- Amazon's image-URL pattern is unofficial and may change; it is best-effort and
  behind an existing-ASIN gate.
- Google Books / Open Library are rate-limited; a polite per-request timeout and
  sequential processing keep volume low. `--limit` helps.
