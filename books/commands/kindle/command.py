#!/usr/bin/env python3
"""Kindle clippings importer command layer."""

from __future__ import annotations

import glob
from pathlib import Path

import typer

from books.commands.kindle import cache
from books.commands.kindle.dedup import to_highlights
from books.commands.kindle.parser import parse_clippings
from books.core import config, store, ui
from books.core.highlights import Highlight
from books.core.matching import BookRef, author_key, norm_title
from books.core.paths import resolve_path

CLIPPINGS_NAME = "My Clippings.txt"
# Mounted Kindle exposes documents/My Clippings.txt; the volume name varies.
DEVICE_GLOB = "/Volumes/*/documents/My Clippings.txt"


def default_clippings_path(vault: Path, override: str = "") -> Path:
    """Resolve which ``My Clippings.txt`` to read.

    Priority: an explicit *override* (flag/config) wins; otherwise a mounted
    Kindle (first ``DEVICE_GLOB`` match) is used; otherwise the canonical
    ``Data/Imports/kindle/My Clippings.txt`` inside the vault. The returned path
    may not exist (callers check ``is_file``).
    """
    if override:
        return resolve_path(Path(override), Path.home())
    matches = sorted(glob.glob(DEVICE_GLOB))
    if matches:
        return Path(matches[0])
    return config.resolve_imports("kindle", vault) / CLIPPINGS_NAME


def convert(clippings_path: Path | None, output: Path) -> dict:
    """Refresh the cache from the device (if present) and resolve it to the store.

    *Extract* (only when *clippings_path* is a real file): parse, group by
    ``(norm_title, author_key)``, dedup per book, and wholesale-overwrite each
    book's cache file. *Resolve* (always): load the whole cache and resolve every
    book to a book_id via ``store.import_highlights`` (match-only); unmatched books
    stay cached. Returns ``{"books": int, "entries": int, "pending": int}``.
    """
    output.mkdir(parents=True, exist_ok=True)
    cdir = cache.cache_dir(output)

    if clippings_path is not None and clippings_path.is_file():
        entries = parse_clippings(clippings_path.read_text(encoding="utf-8-sig"))
        groups: dict[tuple, list] = {}
        order: list[tuple] = []
        for entry in entries:
            if not entry.title:
                continue
            key = (norm_title(entry.title), author_key(entry.author))
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(entry)
        used: set[str] = set()
        for key in sorted(order):
            group = groups[key]
            highlights = to_highlights(group)
            if not highlights:
                continue
            first = group[0]
            stem = cache.book_stem(first.title, first.author, used)
            cache.save_book(cdir, stem, first.title, first.author, highlights)

    resolved: list[tuple[BookRef, list[Highlight]]] = []
    for record in cache.load_all(cdir):
        if not record["highlights"]:
            continue
        ref = BookRef(
            title=record["title"],
            authors=[record["author"]] if record["author"] else [],
        )
        resolved.append((ref, record["highlights"]))

    stats = store.import_highlights(output, "kindle", resolved)
    return {"books": stats["books"], "entries": stats["entries"], "pending": stats["skipped"]}


def run_import(vault: Path, cfg: config.KindleConfig) -> dict:
    """Import entry point used by ``books import`` (returns store stats).

    Runs when a clippings file is available (device / canonical / override) *or* a
    non-empty cache already exists — so highlights resolve even with the Kindle
    unplugged. Empty stats only when neither is present.
    """
    path = default_clippings_path(vault, cfg.clippings)
    clip = path if path.is_file() else None
    cdir = cache.cache_dir(vault)
    has_cache = cdir.is_dir() and any(cdir.glob("*.json"))
    if clip is None and not has_cache:
        return {"books": 0, "entries": 0, "pending": 0}
    return convert(clip, vault)


def kindle_import(
    clippings: Path | None = typer.Option(
        None,
        "--clippings",
        "-c",
        help="Path to a Kindle 'My Clippings.txt'. Defaults to a mounted Kindle, "
        "then <vault>/Data/Imports/kindle/My Clippings.txt. Relative paths resolve "
        "against the current directory.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
) -> None:
    """Add Kindle 'My Clippings.txt' highlights to the CSV highlights store.

    The parsed highlights go into the per-book CSV store, which ``export`` then
    turns into notes; this command never creates book notes itself. Adjusted
    highlights are deduplicated (latest kept) and notes are attached to their
    highlights. Books are resolved to a book_id via the merged catalog
    (Data/books.csv) by a strict Author/Title comparison. A book with no catalog
    match stays cached and is reported as pending, so import order does not
    matter — run ``import``/``merge`` whenever.
    """
    vault = config.resolve_vault(output)
    if clippings is not None:
        clip = resolve_path(clippings, Path.cwd())
        if not clip.is_file():
            raise typer.BadParameter(f"clippings file not found: {clip}", param_hint="--clippings")
    else:
        auto = default_clippings_path(vault)
        clip = auto if auto.is_file() else None

    cdir = cache.cache_dir(vault)
    has_cache = cdir.is_dir() and any(cdir.glob("*.json"))
    if clip is None and not has_cache:
        raise typer.BadParameter(
            "no Kindle clippings file or cache found", param_hint="--clippings"
        )

    vault.mkdir(parents=True, exist_ok=True)
    stats = convert(clip, vault)
    pending = f", {stats['pending']} pending" if stats["pending"] else ""
    ui.info(
        f"Done. {stats['books']} books{pending}, {stats['entries']} highlights.\nOutput: {vault}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("kindle")(kindle_import)
