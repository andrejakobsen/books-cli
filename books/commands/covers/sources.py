"""Cover candidate model + per-provider lookups (Apple, Google, Open Library, Amazon)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


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
