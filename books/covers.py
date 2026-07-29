#!/usr/bin/env python3
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
books.renderers.obsidian.

Robustness: HTTP fetches retry transient failures (403/429/5xx — 403 covers
iTunes throttling) with exponential backoff, giving up on a persistently throttled
source after a ~1-minute per-source time budget so the run moves on rather than
blocking. A source that errors outright is reported separately from one that simply
found nothing. Sources are also consulted lazily, so once one yields a usable cover
the rest are never contacted (nor their errors counted). Author/title queries are normalized (whitespace collapsed,
translator/co-author tails dropped); fetched images are validated by parsing
their pixel dimensions (rejecting placeholders); and an ISBN learned from a
source is backfilled into the note's frontmatter.

Standard library only.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

import typer

from books.core import config
from books.core.paths import resolve_path
from books.renderers.obsidian import (
    BOOKS_DIRNAME,
    VaultIndex,
    cover_path,
    cover_refs,
    ensure_top_embed,
    extract_wikilinks,
    frontmatter_values,
    unquote,
    update_frontmatter,
    yaml_quote,
)


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
    source: str          # "apple" | "google" | "openlibrary" | "amazon"
    label: str           # matched title / author, for display
    image_url: str
    fmt: str | None      # "paperback" | "hardcover" | None (unknown)
    isbn: str | None = None   # ISBN learned from the source, for frontmatter backfill


def _cover_is_blank(fm: dict[str, str]) -> bool:
    """True if the note has no usable `cover:` value."""
    return unquote(fm.get("cover", "")).strip() == ""


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


GOOGLE_API = "https://www.googleapis.com/books/v1/volumes"

# imageLinks keys from best to worst.
_GOOGLE_IMAGE_KEYS = (
    "extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail",
)


def _label(title: str, authors: list[str]) -> str:
    return f"{title} — {authors[0]}" if authors else title


# Tails that mark a translator / co-author glued onto a single author string;
# everything from the first match onward is dropped for querying.
_AUTHOR_TAILS = (" and ", " with ", ", translated", ", trans.", ", edited")


def normalize_author(name: str) -> str:
    """Clean an author string for querying book-cover APIs.

    Collapses runs of whitespace and drops translator/co-author tails such as
    ``"Plato and Benjamin Jowett"`` → ``"Plato"`` so the query matches the work
    rather than the specific translation.
    """
    name = re.sub(r"\s+", " ", name).strip()
    low = name.lower()
    for sep in _AUTHOR_TAILS:
        idx = low.find(sep)
        if idx != -1:
            name = name[:idx].strip()
            low = name.lower()
    return name


def _clean(text: str) -> str:
    """Collapse whitespace in a free-form string (title) for querying."""
    return re.sub(r"\s+", " ", text).strip()


def _upgrade_google_url(url: str) -> str:
    """Prefer https and drop the page-curl overlay."""
    url = url.replace("http://", "https://")
    url = url.replace("&edge=curl", "").replace("edge=curl&", "").replace("edge=curl", "")
    return url


def google_books_candidates(book: MissingBook, fetch_json) -> list[Candidate]:
    """Query Google Books; return one candidate per volume that has an image."""
    if book.isbn:
        q = f"isbn:{book.isbn}"
    else:
        parts = [f'intitle:{_clean(book.title)}']
        if book.authors:
            parts.append(f"inauthor:{normalize_author(book.authors[0])}")
        q = " ".join(parts)
    url = f"{GOOGLE_API}?q={quote(q, safe=':')}&maxResults=5"
    data = fetch_json(url) or {}
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
            isbn=_google_isbn(info),
        ))
    return out


def _google_isbn(info: dict) -> str | None:
    """Pull an ISBN (13 preferred) from a Google volumeInfo, if present."""
    idents = info.get("industryIdentifiers", []) or []
    by_type = {i.get("type"): i.get("identifier") for i in idents}
    return by_type.get("ISBN_13") or by_type.get("ISBN_10")


OL_SEARCH_API = "https://openlibrary.org/search.json"
OL_ISBN_API = "https://openlibrary.org/isbn/{isbn}.json"
OL_COVER_ID = "https://covers.openlibrary.org/b/id/{cid}-L.jpg?default=false"
OL_COVER_ISBN = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"
OL_WORK_EDITIONS = "https://openlibrary.org{work}/editions.json?limit=50"


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
        data = fetch_json(url) or {}
        fmt = _norm_fmt(data.get("physical_format"))
        out.append(Candidate(
            source="openlibrary", label=label,
            image_url=OL_COVER_ISBN.format(isbn=quote(book.isbn)), fmt=fmt))
        return out

    params = f"title={quote(_clean(book.title))}"
    if book.authors:
        params += f"&author={quote(normalize_author(book.authors[0]))}"
    url = f"{OL_SEARCH_API}?{params}&fields=key,cover_i&limit=5"
    data = fetch_json(url) or {}
    docs = data.get("docs", [])
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
    if not out:
        for doc in docs:
            if doc.get("cover_i"):
                out.append(Candidate(
                    source="openlibrary", label=label,
                    image_url=OL_COVER_ID.format(cid=doc["cover_i"]), fmt=None))
    out.sort(key=lambda c: _fmt_rank(c.fmt))
    return out


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
    13-digit ISBN-13 or a 10-character ISBN-10 (last char may be an ``X`` check
    digit); opaque stems (e.g. ``mzi.mwffatop``) yield ``None``.
    """
    parts = artwork_url.rsplit("/", 2)   # [prefix, "<isbn>.jpg", "100x100bb.jpg"]
    if len(parts) < 3:
        return None
    stem = parts[1].rsplit(".", 1)[0]
    if re.fullmatch(r"\d{13}|\d{9}[\dX]", stem):
        return stem
    return None


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


# The API-backed sources, in priority order; amazon is URL-only (no fetch).
_API_SOURCES = (
    ("apple", apple_books_candidates),
    ("google", google_books_candidates),
    ("openlibrary", openlibrary_candidates),
)


def iter_candidates(book: MissingBook, fetch_json, errored: list[str]):
    """Yield candidates source-by-source in priority order (Apple, Google, Open
    Library, Amazon), *lazily*.

    A source is only queried when the consumer asks for candidates beyond the
    previous source's — so if an earlier source already yields a usable cover and
    the consumer stops, later sources are never contacted (and a later rate-limit
    never gets counted as an error). The name of any source that raises is
    appended to *errored* as it happens.
    """
    for name, fn in _API_SOURCES:
        try:
            cands = fn(book, fetch_json)
        except Exception:
            errored.append(name)
            continue
        yield from cands
    yield from amazon_candidates(book)


def gather_with_errors(book: MissingBook, fetch_json):
    """Gather *all* candidates and report which sources errored outright.

    Returns ``(candidates, errored)`` where *candidates* are in source-priority
    order (Apple, Google, Open Library, Amazon) and *errored* is the list of source
    names that raised (e.g. a rate-limit / network failure) — distinct from a
    source that simply found nothing. Every source is queried eagerly; prefer
    :func:`iter_candidates` when a later source's error should not be counted once
    an earlier source suffices.
    """
    errored: list[str] = []
    candidates = list(iter_candidates(book, fetch_json, errored))
    return candidates, errored


def gather_candidates(book: MissingBook, fetch_json) -> list[Candidate]:
    """All candidates in source-priority order: Apple, Google, Open Library, Amazon."""
    return gather_with_errors(book, fetch_json)[0]


MIN_IMAGE_BYTES = 1000
MIN_IMAGE_DIM = 100   # px; anything smaller is a placeholder/thumbnail, not a cover

_JPEG_SOF_MARKERS = frozenset(
    range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}   # SOF0..SOF15 except DHT/JPG/DAC


class QuitRequested(Exception):
    """Raised from pick_cover when the user chooses to quit the whole run."""


def _jpeg_dimensions(data: bytes) -> tuple[int, int] | None:
    """Scan JPEG segments for a Start-Of-Frame marker and read its size."""
    i, n = 2, len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in _JPEG_SOF_MARKERS:
            height = int.from_bytes(data[i + 5:i + 7], "big")
            width = int.from_bytes(data[i + 7:i + 9], "big")
            return (width, height)
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2   # standalone markers carry no length
            continue
        seg_len = int.from_bytes(data[i + 2:i + 4], "big")
        if seg_len < 2:
            break
        i += 2 + seg_len
    return None


def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Return (width, height) parsed from a PNG/GIF/JPEG header, else None.

    Header-only parsing (stdlib, no image library); returns None when the bytes
    are not a recognizable image so callers can fall back to a size heuristic.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return (int.from_bytes(data[16:20], "big"),
                int.from_bytes(data[20:24], "big"))
    if data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        return (int.from_bytes(data[6:8], "little"),
                int.from_bytes(data[8:10], "little"))
    if data[:2] == b"\xff\xd8":
        return _jpeg_dimensions(data)
    return None


def is_valid_image(data: bytes, content_type: str | None) -> bool:
    """True if *data* looks like a real cover image.

    Requires an image content-type. When the dimensions are parseable, both must
    be at least MIN_IMAGE_DIM (rejects 1x1 placeholders); when they are not
    parseable, falls back to the byte-size heuristic.
    """
    if not content_type or not content_type.lower().startswith("image/"):
        return False
    dims = image_dimensions(data)
    if dims is not None:
        width, height = dims
        return width >= MIN_IMAGE_DIM and height >= MIN_IMAGE_DIM
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


def apply_cover(index: VaultIndex, book: MissingBook, image: bytes,
                isbn: str | None = None) -> None:
    """Write the cover image and fill the note's cover frontmatter + embed.

    When *isbn* is supplied (learned from a source), it is backfilled into the
    note's frontmatter; the never-overwrite merge leaves any existing ISBN alone.
    """
    dst = cover_path(book.note_path)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(image)

    cover_fm, cover_embed = cover_refs(book.note_path)
    updates = {"cover": cover_fm}
    if isbn:
        updates["isbn"] = yaml_quote(isbn)
    text = book.note_path.read_text(encoding="utf-8")
    text = update_frontmatter(text, updates)
    text = ensure_top_embed(text, cover_embed)
    book.note_path.write_text(text, encoding="utf-8")


USER_AGENT = "books-covers/1.0 (+https://github.com/)"
HTTP_TIMEOUT = 15
HTTP_RETRIES = 10          # attempt cap; the time budget below usually binds first
HTTP_BACKOFF = 1.0         # base seconds; doubles each attempt (1s, 2s, 4s, …)
HTTP_MAX_SECONDS = 60.0    # per-source time budget: stop retrying and move on after ~1 min

# Transient HTTP statuses worth retrying: rate limiting + server errors.
# 403 is included because the iTunes Search API (Apple Books) returns Forbidden
# when it throttles, rather than the standard 429.
RETRYABLE_STATUS = frozenset({403, 429, 500, 502, 503, 504})


def fetch_with_retry(do_fetch, *, retries=HTTP_RETRIES, backoff=HTTP_BACKOFF,
                     max_seconds=HTTP_MAX_SECONDS, sleep=time.sleep,
                     clock=time.monotonic):
    """Call *do_fetch* (a zero-arg fetcher), retrying transient failures.

    Retries on retryable HTTP statuses (403/429/5xx — 403 covers iTunes
    throttling) and connection errors with exponential backoff, then re-raises the
    last error. Retrying stops — and the caller moves on to the next source — once
    either *retries* attempts are made or *max_seconds* of wall-clock time has
    elapsed (a persistently throttled source is abandoned after ~1 minute rather
    than blocking the whole run). Non-retryable errors (e.g. 404) are re-raised
    immediately.
    """
    start = clock()
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return do_fetch()
        except HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS:
                raise
            last_exc = exc
        except URLError as exc:
            last_exc = exc
        if attempt == retries - 1:
            break
        delay = backoff * (2 ** attempt)
        # Stop if the next backoff would push us past the per-source time budget.
        if (clock() - start) + delay >= max_seconds:
            break
        sleep(delay)
    assert last_exc is not None   # loop only exits here after a caught error
    raise last_exc


def default_fetch_json(url: str) -> dict:
    """GET *url* and parse JSON, retrying transient failures."""
    def do():
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    return fetch_with_retry(do)


def default_fetch_bytes(url: str) -> tuple[bytes, str | None]:
    """GET *url* returning (body, content_type), retrying transient failures."""
    def do():
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.read(), resp.headers.get("Content-Type")
    return fetch_with_retry(do)


def _terminal_prompt(cand: Candidate) -> str:
    """Ask the user about one candidate; map keys to an action string."""
    fmt = f" [{cand.fmt}]" if cand.fmt else ""
    print(f"  {cand.source}: {cand.label}{fmt}\n    {cand.image_url}")
    ans = input("  accept [y] / next [n] / skip book [s] / quit [q]? ").strip().lower()
    return {"y": "accept", "n": "next", "s": "skip", "q": "quit"}.get(ans, "next")


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
        "by_source": {"apple": 0, "google": 0, "openlibrary": 0, "amazon": 0},
        "errored": {"apple": 0, "google": 0, "openlibrary": 0, "amazon": 0},
    }
    todo = missing if (book_path is not None or limit is None) else missing[:limit]
    for book in todo:
        stats["processed"] += 1
        if interactive:
            print(f"\n{book.title} — {', '.join(book.authors) or 'Unknown'}")
        errored: list[str] = []
        candidates = iter_candidates(book, fetch_json, errored)
        try:
            picked = pick_cover(
                candidates, fetch_bytes, interactive=interactive, prompt=prompt)
        except QuitRequested:
            print("Quit.")
            break
        finally:
            # `errored` is populated lazily as pick_cover consumes candidates, so
            # it only holds sources actually reached before a cover was found.
            for src in errored:
                stats["errored"][src] = stats["errored"].get(src, 0) + 1
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
            apply_cover(index, book, data, isbn=cand.isbn)
            print(f"  ✓ {cand.source}: {book.title}")
    return stats


def covers_command(
    output: Path | None = typer.Option(
        None,
        "--output", "-o",
        help="Obsidian vault to scan. Defaults to the vault from your config file "
             "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
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
    frontmatter is blank and fetches a cover from Apple Books, then Google Books,
    then Open Library (paperback editions preferred where known), then Amazon
    (only when the note already carries an 'amazon' ASIN). By default the best
    match is written automatically; use --interactive to approve each candidate,
    or --dry-run to preview. Pass --book PATH to fetch a cover for a single note under Books/
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
        vault = config.resolve_vault(output)
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
        f"(apple {bs['apple']}, google {bs['google']}, "
        f"openlibrary {bs['openlibrary']}, amazon {bs['amazon']}), "
        f"{stats['not_found']} not found."
    )
    errored = {src: n for src, n in stats.get("errored", {}).items() if n}
    if errored:
        detail = ", ".join(f"{src} {n}" for src, n in errored.items())
        typer.secho(
            f"⚠ source errors (rate-limited / unreachable, not 'no match'): {detail}",
            fg=typer.colors.YELLOW,
        )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("covers")(covers_command)


def main() -> None:
    """Standalone entry point so the shim script keeps working on its own."""
    typer.run(covers_command)


if __name__ == "__main__":
    main()
