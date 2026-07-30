"""`covers` command: find cover-less catalog books and write a `covers` store layer."""

from __future__ import annotations

from pathlib import Path

from rich.markup import escape

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
from books.core import store, ui


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
        out.append(
            MissingBook(
                book_id=row.book_id,
                title=row.title,
                authors=list(row.authors),
                isbn=(row.isbn or "").strip() or None,
                amazon=(row.amazon or "").strip() or None,
            )
        )
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


def _terminal_prompt(cand: Candidate) -> str:
    """Ask the user about one candidate; map keys to an action string."""
    fmt = f" · {escape(cand.fmt)}" if cand.fmt else ""
    body = (
        f"[cyan]{escape(cand.source)}[/cyan]  {escape(cand.label)}[dim]{fmt}[/dim]\n"
        f"[dim]{escape(cand.image_url)}[/dim]"
    )
    ui.console.print(ui.panel(body, title="candidate", style="blue"))
    ans = ui.prompt_choice("Use this cover?", choices=["y", "n", "s", "q"], default="y")
    return {"y": "accept", "n": "next", "s": "skip", "q": "quit"}.get(ans, "next")


def _existing_covers_layer(vault: Path) -> dict[str, store.BookRow]:
    """Prior covers-layer rows keyed by the book_id embedded in their staged path.

    Lets a partial run (``--limit``/``--book``) preserve covers fetched earlier
    instead of overwriting the layer with only this run's rows.
    """
    out: dict[str, store.BookRow] = {}
    for row in store.read_layer(vault, "covers"):
        if row.cover:
            out[Path(row.cover).stem] = row
    return out


def run(vault, *, interactive, dry_run, limit, fetch_json, fetch_bytes, prompt, book_id=None):
    """Fetch covers for catalog books missing one, into the ``covers`` layer.

    Reads books.csv for cover-less books (:func:`books_missing_cover`), fetches an
    image per book (network unchanged), stages it under
    ``Data/Sources/_covers/covers/<book_id>.jpg`` and records a ``covers`` layer
    row (identity + learned isbn + staged path). ``merge`` folds it in and
    ``render`` materializes it. When *book_id* is given, only that catalog book is
    processed. Returns a stats dict.
    """
    all_missing = books_missing_cover(vault)
    if book_id is not None:
        missing = [m for m in all_missing if m.book_id == book_id]
        scanned = 1
        if not missing:
            ui.warn(
                f"no cover-less book with book_id {book_id!r} "
                "(unknown id, or it already has a cover)"
            )
    else:
        missing = all_missing
        scanned = len(store.read_books_csv(vault))

    stats = {
        "scanned": scanned,
        "missing": len(missing),
        "processed": 0,
        "fetched": 0,
        "not_found": 0,
        "by_source": {"apple": 0, "google": 0, "openlibrary": 0, "amazon": 0},
        "errored": {"apple": 0, "google": 0, "openlibrary": 0, "amazon": 0},
    }

    layer = _existing_covers_layer(vault) if not dry_run else {}
    todo = missing if (book_id is not None or limit is None) else missing[:limit]
    for book in todo:
        stats["processed"] += 1
        if interactive:
            ui.console.print(
                f"\n[bold]{escape(book.title)}[/bold] "
                f"[dim]— {escape(', '.join(book.authors) or 'Unknown')}[/dim]"
            )
        errored: list[str] = []
        candidates = iter_candidates(book, fetch_json, errored)
        try:
            picked = pick_cover(candidates, fetch_bytes, interactive=interactive, prompt=prompt)
        except QuitRequested:
            ui.dim("Quit.")
            break
        finally:
            for src in errored:
                stats["errored"][src] = stats["errored"].get(src, 0) + 1
        if picked is None:
            stats["not_found"] += 1
            ui.warn(f"no cover: {book.title}")
            continue
        cand, data = picked
        stats["fetched"] += 1
        stats["by_source"][cand.source] = stats["by_source"].get(cand.source, 0) + 1
        if dry_run:
            ui.dim(f"[dry-run] {cand.source}: {cand.image_url}")
            continue
        cover_rel = store.stage_cover(vault, "covers", book.book_id, data=data)
        layer[book.book_id] = store.BookRow(
            title=book.title,
            authors=list(book.authors),
            isbn=(cand.isbn or book.isbn or ""),
            amazon=(book.amazon or ""),
            cover=cover_rel,
        )
        ui.success(f"{cand.source}: {book.title}")

    if not dry_run:
        store.write_layer(vault, "covers", list(layer.values()))
    return stats


def run_import(vault, cfg, *, dry_run: bool = False) -> dict:
    """Run the covers fetch using values from the ``[covers]`` config section.

    *cfg* is a :class:`books.core.config.CoversConfig`. ``limit == 0`` means no
    limit. Always a full scan (no single-book targeting from ``import``).
    """
    limit = None if cfg.limit <= 0 else cfg.limit
    return run(
        vault,
        interactive=cfg.interactive,
        dry_run=dry_run,
        limit=limit,
        fetch_json=default_fetch_json,
        fetch_bytes=default_fetch_bytes,
        prompt=_terminal_prompt,
        book_id=None,
    )
