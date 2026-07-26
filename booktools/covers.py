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

import typer

from booktools import config, resolve_path
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
    url = f"{OL_SEARCH_API}?{params}&fields=key,cover_i&limit=5"
    try:
        data = fetch_json(url) or {}
    except Exception:
        return []
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
    todo = missing if (book_path is not None or limit is None) else missing[:limit]
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


def covers_command(
    output: Path | None = typer.Option(
        None,
        "--output", "-o",
        help="Obsidian vault to scan. Defaults to the vault from your config file "
             "(~/.config/booktools/config.toml). Relative paths resolve against the current directory.",
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
