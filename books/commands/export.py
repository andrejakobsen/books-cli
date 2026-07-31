#!/usr/bin/env python3
"""The ``export`` command: turn the merged CSV store into notes for one target.

This module is a thin CLI dispatcher over the renderer seam. It resolves the
vault, checks that ``Data/books.csv`` exists, picks a renderer by flag
(``--obsidian`` today; ``--notion``/``--evernote`` slot in beside it later), and
calls :meth:`Renderer.render`. All Obsidian note-assembly logic lives in
``books/renderers/obsidian/`` — nothing format-specific lives here.
"""

from __future__ import annotations

from pathlib import Path

import typer

from books.core import config, store, ui
from books.renderers import get_renderer

# CLI flag name -> registered renderer name. One entry per output target; the
# default target is the first. Adding a format is a one-line entry here plus its
# registration in ``books/renderers``.
_FORMAT_FLAGS: tuple[tuple[str, str], ...] = (("obsidian", "obsidian"),)


def export_command(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the "
        "current directory.",
    ),
    obsidian: bool = typer.Option(
        True,
        "--obsidian",
        help="Render the CSV store as Obsidian book notes (the default and only "
        "output format today; future formats slot in beside it as their own flag).",
    ),
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help="Delete Books/ and Authors/ before rendering (a clean rebuild that "
        "removes stale notes/stubs). Your topics/aliases/cssclasses are cached and "
        "restored for books still in the catalog.",
    ),
) -> None:
    """Render the CSV store into book notes for the chosen output format.

    Reads <vault>/Data/books.csv and <vault>/Data/Highlights/<book-id>.csv (built
    by the importers + merge) and writes one note per book. The output format is
    selected by a flag (`--obsidian`, the default and only format for now).
    Frontmatter is written authoritatively from the store; your hand-edited
    `topics` and any `## Review` section are preserved, as is note body outside the
    managed Highlights markers.
    """
    flags = {"obsidian": obsidian}
    selected = [name for flag, name in _FORMAT_FLAGS if flags.get(flag)]
    if not selected:
        raise typer.BadParameter(
            "no output format selected — pass --obsidian (the only format today)",
            param_hint="--obsidian",
        )
    renderer = get_renderer(selected[0])

    vault = config.resolve_vault(output)
    if not store.books_csv_path(vault).is_file():
        raise typer.BadParameter(
            f"no books.csv under {store.data_dir(vault)} — run the importers + merge first",
            param_hint="--output",
        )
    vault.mkdir(parents=True, exist_ok=True)
    cfg = config.load_config()
    stats = renderer.render(vault, refresh=refresh, timezone=cfg.export.timezone)
    suffix = f" ({stats['failed']} failed)" if stats.get("failed") else ""
    ui.info(
        f"Done. {stats['notes']} notes, {stats['highlights']} highlights, "
        f"{stats['reviews']} reviews, {stats['authors']} authors{suffix}.\n"
        f"Output: {vault}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("export")(export_command)
