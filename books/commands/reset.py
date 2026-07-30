#!/usr/bin/env python3
"""`reset` — delete the purely-derived CSV store for a clean rebuild.

Removes ``Data/books.csv`` and the ``Data/Highlights/`` folder (the only store
that accumulates orphaned per-``book_id`` files). Source layers under
``Data/Sources/`` and the notes are kept. Run ``sync`` afterward (plus the manual
``audible``/``covers`` steps) to rebuild.
"""

from __future__ import annotations

from pathlib import Path

import typer

from books.core import config, store, ui


def _is_interactive() -> bool:
    """Whether we can prompt the user (wrapped so tests can override)."""
    return ui.console.is_terminal


def _plan_lines(vault: Path, plan: dict) -> list[str]:
    lines: list[str] = []
    if plan["books_csv"]:
        lines.append(f"  - {store.books_csv_path(vault)}")
    if plan["highlight_files"]:
        lines.append(
            f"  - {store.highlights_dir(vault)} ({plan['highlight_files']} highlight file(s))"
        )
    return lines


def reset_command(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the "
        "current directory.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print what would be deleted without deleting anything.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the confirmation prompt.",
    ),
) -> None:
    """Delete the derived store (Data/books.csv + Data/Highlights/) for a clean rebuild."""
    vault = config.resolve_vault(output)
    plan = store.reset_store(vault, dry_run=True)

    if not plan["books_csv"] and not plan["highlight_files"]:
        ui.info(f"Nothing to reset under {store.data_dir(vault)}.")
        return

    if dry_run:
        ui.info("The following would be deleted (dry run):")
    else:
        ui.info("The following will be deleted:")
    for line in _plan_lines(vault, plan):
        ui.info(line)

    if dry_run:
        return

    if not yes:
        if not _is_interactive():
            raise typer.BadParameter(
                "No interactive terminal — pass --yes to confirm deletion.",
                param_hint="--yes",
            )
        if not ui.confirm("Delete the derived store?", default=False):
            ui.info("Aborted.")
            return

    result = store.reset_store(vault)
    removed: list[str] = []
    if result["books_csv"]:
        removed.append("books.csv")
    removed.append(f"{result['highlight_files']} highlight file(s)")
    ui.success(f"Reset: removed {' and '.join(removed)}. Run `books sync` to rebuild.")


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("reset")(reset_command)


def main() -> None:
    typer.run(reset_command)


if __name__ == "__main__":
    main()
