"""`covers` command: find blank-cover notes, pick a cover, write it into the note."""

from __future__ import annotations

from pathlib import Path

import typer

from books.commands.covers.images import (
    default_fetch_bytes,
    default_fetch_json,
    is_valid_image,
)
from books.commands.covers.sources import (
    Candidate,
    MissingBook,
    iter_candidates,
)
from books.core import config, store
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


def books_missing_cover(vault: Path) -> list[MissingBook]:
    """Catalog rows (books.csv) that still need a cover.

    A book needs a cover when its stored ``cover`` is blank *and* no materialized
    ``Data/Covers/<book_id>.jpg`` exists on disk. The on-disk check keeps re-runs
    idempotent even before a re-merge folds a freshly-fetched cover back into
    books.csv.
    """
    out: list[MissingBook] = []
    covers_dir = store.data_dir(vault) / "Covers"
    for row in store.read_books_csv(vault):
        if not row.book_id:
            continue
        if (row.cover or "").strip():
            continue
        if (covers_dir / f"{row.book_id}.jpg").is_file():
            continue
        out.append(MissingBook(
            book_id=row.book_id,
            title=row.title,
            authors=list(row.authors),
            isbn=(row.isbn or "").strip() or None,
            amazon=(row.amazon or "").strip() or None,
        ))
    return out


class QuitRequested(Exception):
    """Raised from pick_cover when the user chooses to quit the whole run."""


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
