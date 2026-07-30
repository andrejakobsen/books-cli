#!/usr/bin/env python3
"""`sync` — run the two-phase import→render pipeline using default options.

One command to regenerate the whole vault from raw imports. The pipeline runs in
dependency order:

    Phase A (metadata):  calibre → goodreads → merge   (build Data/books.csv)
    Phase B (highlights): kobo → highlighted → readwise → render

The metadata importers write per-source CSV layers; `merge` clusters them into
`Data/books.csv` (assigning each book a stable id); the highlight importers
resolve each book to that id and write the highlights store; `render` turns the
store into the flat Obsidian notes under `Books/`. Covers are out of scope — run
`covers` separately.

Each step is skipped when its source is absent, so `sync` imports whatever it
finds. A step failure is reported but never stops the remaining steps; a colored
summary is printed at the end.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import typer
from rich.markup import escape

from books.commands import (
    calibre,
    goodreads,
    highlighted,
    kobo,
    readwise,
)
from books.core import config, store, ui
from books.renderers import get_renderer

# --- Detection helpers ------------------------------------------------------


def _imports_folder(name: str, vault: Path) -> Path:
    """The canonical `.imports/<name>` folder inside *vault*."""
    return config.resolve_imports(name, vault)


def _imports_label(name: str) -> str:
    """A friendly source label like `.imports/goodreads`."""
    cfg = config.load_config()
    return f"{cfg.imports}/{name}"


def _has_csv(folder: Path) -> bool:
    """True when *folder* exists and holds a top-level ``*.csv``."""
    return folder.is_dir() and any(folder.glob("*.csv"))


def _calibre_library() -> Path:
    """The default Calibre library (delegates to the `calibre` command)."""
    return calibre.default_library()


def _detect_calibre(vault: Path) -> str | None:
    library = _calibre_library()
    return str(library) if library.is_dir() else None


def _detect_goodreads(vault: Path) -> str | None:
    return _imports_label("goodreads") if _has_csv(_imports_folder("goodreads", vault)) else None


def _kobo_source(vault: Path) -> str | None:
    """Kobo source: a mounted device, else a `*.sqlite` in `.imports/kobo`."""
    if kobo.KOBO_DEVICE_DB.is_file():
        return "Kobo device"
    folder = _imports_folder("kobo", vault)
    if folder.is_dir() and any(folder.glob("*.sqlite")):
        return _imports_label("kobo")
    return None


def _detect_kobo(vault: Path) -> str | None:
    return _kobo_source(vault)


def _detect_highlighted(vault: Path) -> str | None:
    return (
        _imports_label("highlighted") if _has_csv(_imports_folder("highlighted", vault)) else None
    )


def _detect_readwise(vault: Path) -> str | None:
    return _imports_label("readwise") if _has_csv(_imports_folder("readwise", vault)) else None


def _detect_merge(vault: Path) -> str | None:
    """Merge runs when source layers exist, or a Phase-A importer will create them.

    Checking the upstream detectors (not just on-disk layers) lets a fresh
    ``--dry-run`` predict that merge would run after calibre/goodreads.
    """
    src = store.sources_dir(vault)
    if src.is_dir() and any(src.glob("*.csv")):
        return "Data/Sources"
    if _detect_calibre(vault) or _detect_goodreads(vault):
        return "Data/Sources"
    return None


def _detect_render(vault: Path) -> str | None:
    """Render runs when books.csv exists, or merge will create it."""
    if store.books_csv_path(vault).is_file():
        return "Data/books.csv"
    if _detect_merge(vault):
        return "Data/books.csv"
    return None


# --- Step runners (call each module's core function directly) ----------------


def _run_calibre(vault: Path) -> dict:
    return calibre.convert(_calibre_library(), vault)


def _run_goodreads(vault: Path) -> dict:
    csv = config.newest_csv(_imports_folder("goodreads", vault))
    return goodreads.convert(csv, vault)


def _run_kobo(vault: Path) -> dict:
    db = kobo.default_kobo_db(vault)
    return kobo.export_obsidian(db, vault)


def _run_highlighted(vault: Path) -> dict:
    # Highlighted exports one CSV per book, so import every file in the folder
    # (unlike goodreads/readwise, whose single snapshot uses newest-wins).
    folder = _imports_folder("highlighted", vault)
    totals = {"books": 0, "entries": 0, "skipped": 0}
    for path in highlighted.resolve_csv_paths(folder):
        stats = highlighted.convert(path, vault)
        totals["books"] += stats["books"]
        totals["entries"] += stats["entries"]
        totals["skipped"] += stats["skipped"]
    return totals


def _run_readwise(vault: Path) -> dict:
    csv = config.newest_csv(_imports_folder("readwise", vault))
    return readwise.convert(csv, vault)


def _run_merge(vault: Path) -> dict:
    return {"books": len(store.merge(vault))}


def _run_render(vault: Path, refresh: bool = False) -> dict:
    return get_renderer("obsidian").render(vault, refresh=refresh)


# --- Summaries --------------------------------------------------------------


def _summ_calibre(s: dict) -> str:
    return (
        f"{s.get('books', 0)} books, {s.get('covers', 0)} covers, "
        f"{len(s.get('authors', ()))} authors, {s.get('skipped', 0)} skipped"
    )


def _summ_goodreads(s: dict) -> str:
    return (
        f"{s.get('books', 0)} books, {s.get('reviews', 0)} reviews, {s.get('skipped', 0)} skipped"
    )


def _summ_highlights(s: dict) -> str:
    skipped = f", {s['skipped']} skipped" if s.get("skipped") else ""
    return f"{s.get('books', 0)} books, {s.get('entries', 0)} highlights{skipped}"


def _summ_merge(s: dict) -> str:
    return f"{s.get('books', 0)} books in catalog"


def _summ_render(s: dict) -> str:
    failed = f", {s['failed']} failed" if s.get("failed") else ""
    return (
        f"{s.get('notes', 0)} notes, {s.get('highlights', 0)} highlights, "
        f"{s.get('reviews', 0)} reviews, {s.get('authors', 0)} authors{failed}"
    )


# --- Step registry ----------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """One pipeline stage: how to detect its source, run it, summarize it.

    ``where`` is a human description of the source location, used in the
    "skipped — no source in ..." message.
    """

    name: str
    detect: Callable[[Path], str | None]
    run: Callable[[Path], dict]
    summarize: Callable[[dict], str]
    where: str


def _steps(refresh: bool = False) -> list[Step]:
    """Build the ordered two-phase step list, resolving runners at call time.

    Runners/detectors are looked up as module globals via ``_run_<name>`` /
    ``_detect_<name>`` (not captured here) so tests can monkeypatch them and have
    it take effect. Order is Phase A (calibre → goodreads → merge) then Phase B
    (kobo → highlighted → readwise → render).
    """
    return [
        Step("calibre", _detect_calibre, _run_calibre, _summ_calibre, "~/Calibre Library"),
        Step(
            "goodreads",
            _detect_goodreads,
            _run_goodreads,
            _summ_goodreads,
            _imports_label("goodreads"),
        ),
        Step("merge", _detect_merge, _run_merge, _summ_merge, "Data/Sources"),
        Step(
            "kobo",
            _detect_kobo,
            _run_kobo,
            _summ_highlights,
            f"{_imports_label('kobo')} or a mounted Kobo",
        ),
        Step(
            "highlighted",
            _detect_highlighted,
            _run_highlighted,
            _summ_highlights,
            _imports_label("highlighted"),
        ),
        Step(
            "readwise",
            _detect_readwise,
            _run_readwise,
            _summ_highlights,
            _imports_label("readwise"),
        ),
        Step(
            "render",
            _detect_render,
            lambda v: _run_render(v, refresh),
            _summ_render,
            "Data/books.csv",
        ),
    ]


@dataclass
class StepResult:
    """Outcome of one step: status is ran / skipped / failed / planned."""

    name: str
    status: str
    summary: str
    error: str | None = None


# --- Rich output ------------------------------------------------------------


def _header(name: str, source: str) -> None:
    ui.console.print(f"[cyan]▶[/cyan] [bold]{escape(name)}[/bold] [dim]({escape(source)})[/dim]")


def _plan(name: str, source: str) -> None:
    ui.console.print(
        f"[cyan]•[/cyan] [bold]{escape(name)}[/bold] [dim]would run from {escape(source)}[/dim]"
    )


def _result_row(r: StepResult) -> tuple[str, str]:
    """Map a ``StepResult`` to its (glyph, result-cell) pair for the summary table.

    Both returned strings are Rich markup (glyph is colored; the result cell may
    carry `[dim]`/`[red]` styling). Dynamic payloads (summary/error) are escaped.
    """
    if r.status == "failed":
        return "[red]✗[/red]", f"[red]failed — {escape(r.error or '')}[/red]"
    if r.status == "skipped":
        return "[yellow]⊘[/yellow]", f"[dim]{escape(r.summary)}[/dim]"
    if r.status == "planned":
        return "[cyan]•[/cyan]", f"[dim]{escape(r.summary)}[/dim]"
    # "ran"
    return "[green]✓[/green]", escape(r.summary)


def _print_summary(results: list[StepResult], *, dry_run: bool = False) -> None:
    ran = sum(1 for r in results if r.status == "ran")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = sum(1 for r in results if r.status == "failed")

    table = ui.summary_table("Sync (dry run)" if dry_run else "Sync")
    table.add_column("", width=2)
    table.add_column("Step", style="cyan", no_wrap=True)
    table.add_column("Result")
    for r in results:
        glyph, result = _result_row(r)
        table.add_row(glyph, r.name, result)
    ui.console.print(table)

    tally = f"{ran} ok · {skipped} skipped · {failed} failed"
    (ui.error if failed else ui.success)(tally)


# --- Orchestration ----------------------------------------------------------


def run_sync(vault: Path, *, dry_run: bool = False, refresh: bool = False) -> list[StepResult]:
    """Run every importer whose source is present, in dependency order.

    Returns a ``StepResult`` per step. Failures are recorded and never stop the
    remaining steps. In *dry_run* mode nothing is executed or written; detected
    steps are reported with status ``planned``. When *refresh* is set the render
    step deletes ``Books/`` and ``Authors/`` for a clean rebuild.
    """
    if not dry_run:
        vault.mkdir(parents=True, exist_ok=True)

    results: list[StepResult] = []
    for step in _steps(refresh):
        source = step.detect(vault)
        if source is None:
            results.append(StepResult(step.name, "skipped", f"skipped — no source in {step.where}"))
            continue
        if dry_run:
            _plan(step.name, source)
            results.append(StepResult(step.name, "planned", f"would run from {source}"))
            continue
        _header(step.name, source)
        try:
            stats = step.run(vault)
        except Exception as exc:  # continue-on-error
            message = str(exc) or exc.__class__.__name__
            results.append(StepResult(step.name, "failed", "failed", error=message))
            continue
        summary = step.summarize(stats)
        results.append(StepResult(step.name, "ran", summary))

    _print_summary(results, dry_run=dry_run)
    return results


def sync(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show which steps would run (and from which source) without writing anything.",
    ),
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help="Delete Books/ and Authors/ before the render step (a clean rebuild). "
        "Your topics/aliases/cssclasses are cached and restored for books still in "
        "the catalog. Ignored under --dry-run.",
    ),
) -> None:
    """Run the two-phase import→render pipeline using default options.

    Phase A builds the catalog (calibre → goodreads → merge); Phase B writes the
    highlights and renders the notes (kobo → highlighted → readwise → render).
    Any step whose source is absent is skipped. Covers are not included — run
    `covers` separately. A step that fails is reported but does not stop the
    others.
    """
    vault = config.resolve_vault(output)
    run_sync(vault, dry_run=dry_run, refresh=refresh)


def register(app: typer.Typer) -> None:
    app.command("sync")(sync)


def main() -> None:
    typer.run(sync)


if __name__ == "__main__":
    main()
