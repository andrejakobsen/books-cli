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

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

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


GOOGLE_API = "https://www.googleapis.com/books/v1/volumes"

# imageLinks keys from best to worst.
_GOOGLE_IMAGE_KEYS = (
    "extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail",
)


def _label(title: str, authors: list[str]) -> str:
    return f"{title} — {authors[0]}" if authors else title


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
        parts = [f'intitle:{book.title}']
        if book.authors:
            parts.append(f"inauthor:{book.authors[0]}")
        q = " ".join(parts)
    url = f"{GOOGLE_API}?q={quote(q, safe=':')}&maxResults=5"
    try:
        data = fetch_json(url) or {}
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


OL_SEARCH_API = "https://openlibrary.org/search.json"
OL_ISBN_API = "https://openlibrary.org/isbn/{isbn}.json"
OL_COVER_ID = "https://covers.openlibrary.org/b/id/{cid}-L.jpg?default=false"
OL_COVER_ISBN = "https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg?default=false"


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
            data = fetch_json(url) or {}
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
        data = fetch_json(url) or {}
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
