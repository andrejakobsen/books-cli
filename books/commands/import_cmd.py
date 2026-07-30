#!/usr/bin/env python3
"""`import` — ingest raw sources into the CSV store.

One command replaces the per-source importers. With no flags it runs the
*sync-set* (calibre, goodreads, kobo, highlighted, readwise). Passing importer
flags runs exactly that subset; ``--audible`` and ``--covers`` are opt-in and
run only when named. ``merge`` (clustering the source layers into
``Data/books.csv``) is injected automatically so callers never sequence it.

Each importer detects its own source and is skipped (reported, not an error)
when absent. A step failure is reported but never stops the remaining steps.
Rendering notes is a separate command (`books export`).
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
from books.commands.audible import command as audible_cmd
from books.commands.covers import command as covers_cmd
from books.core import config, store, ui

# The out-of-the-box importers run with no flags (overridable via [import].default).
SYNC_SET = config.DEFAULT_IMPORTERS
# Importers that resolve against Data/books.csv (need a current catalog first).
_CONSUMERS = ("audible", "covers", "kobo", "highlighted", "readwise")
# Importers that write a Data/Sources/<name>.csv layer after the phase-A merge.
_ENRICHERS = ("audible", "covers")

# --- Detection helpers ------------------------------------------------------


def _imports_folder(name: str, vault: Path) -> Path:
    return config.resolve_imports(name, vault)


def _imports_label(name: str, cfg: config.Config) -> str:
    return f"{cfg.imports}/{name}"


def _has_csv(folder: Path) -> bool:
    return folder.is_dir() and any(folder.glob("*.csv"))


def _calibre_library(cfg: config.Config) -> Path:
    """The configured Calibre library (``[calibre].library``)."""
    return config._expand_user(cfg.calibre.library)


def _kobo_db(vault: Path, cfg: config.Config) -> Path:
    """The Kobo DB path: config override, else auto-detected."""
    db = cfg.kobo.db
    return config._expand_user(db) if db else kobo.default_kobo_db(vault)


def _detect_calibre(vault: Path, cfg: config.Config) -> str | None:
    library = _calibre_library(cfg)
    return str(library) if library.is_dir() else None


def _detect_goodreads(vault: Path, cfg: config.Config) -> str | None:
    if _has_csv(_imports_folder("goodreads", vault)):
        return _imports_label("goodreads", cfg)
    return None


def _kobo_source(vault: Path, cfg: config.Config) -> str | None:
    override = cfg.kobo.db
    if override:
        p = config._expand_user(override)
        return str(p) if p.is_file() else None
    if kobo.KOBO_DEVICE_DB.is_file():
        return "Kobo device"
    folder = _imports_folder("kobo", vault)
    if folder.is_dir() and any(folder.glob("*.sqlite")):
        return _imports_label("kobo", cfg)
    return None


def _detect_kobo(vault: Path, cfg: config.Config) -> str | None:
    return _kobo_source(vault, cfg)


def _detect_highlighted(vault: Path, cfg: config.Config) -> str | None:
    if _has_csv(_imports_folder("highlighted", vault)):
        return _imports_label("highlighted", cfg)
    return None


def _detect_readwise(vault: Path, cfg: config.Config) -> str | None:
    if _has_csv(_imports_folder("readwise", vault)):
        return _imports_label("readwise", cfg)
    return None


def _detect_merge(vault: Path, cfg: config.Config) -> str | None:
    src = store.sources_dir(vault)
    if src.is_dir() and any(src.glob("*.csv")):
        return "Data/Sources"
    if _detect_calibre(vault, cfg) or _detect_goodreads(vault, cfg):
        return "Data/Sources"
    return None


def _detect_audible(vault: Path, cfg: config.Config) -> str | None:
    return "Audible cloud"


def _detect_covers(vault: Path, cfg: config.Config) -> str | None:
    return "Data/books.csv" if store.books_csv_path(vault).is_file() else None


# --- Step runners -----------------------------------------------------------


def _run_calibre(vault: Path, cfg: config.Config) -> dict:
    return calibre.convert(_calibre_library(cfg), vault)


def _run_goodreads(vault: Path, cfg: config.Config) -> dict:
    csv = config.newest_csv(_imports_folder("goodreads", vault))
    return goodreads.convert(csv, vault)


def _run_kobo(vault: Path, cfg: config.Config) -> dict:
    return kobo.export_obsidian(_kobo_db(vault, cfg), vault)


def _run_highlighted(vault: Path, cfg: config.Config) -> dict:
    folder = _imports_folder("highlighted", vault)
    totals = {"books": 0, "entries": 0, "skipped": 0}
    for path in highlighted.resolve_csv_paths(folder):
        stats = highlighted.convert(path, vault)
        totals["books"] += stats["books"]
        totals["entries"] += stats["entries"]
        totals["skipped"] += stats["skipped"]
    return totals


def _run_readwise(vault: Path, cfg: config.Config) -> dict:
    csv = config.newest_csv(_imports_folder("readwise", vault))
    return readwise.convert(csv, vault)


def _run_merge(vault: Path, cfg: config.Config) -> dict:
    return {"books": len(store.merge(vault))}


def _run_audible(vault: Path, cfg: config.Config) -> dict:
    return audible_cmd.run_import(vault, cfg.audible)


def _run_covers(vault: Path, cfg: config.Config) -> dict:
    return covers_cmd.run_import(vault, cfg.covers)


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


def _summ_audible(s: dict) -> str:
    fail = f", {s['failed']} failed" if s.get("failed") else ""
    return f"{s.get('books', 0)} books, {s.get('entries', 0)} clips{fail}"


def _summ_covers(s: dict) -> str:
    return f"{s.get('fetched', 0)} fetched, {s.get('not_found', 0)} not found"


# --- Step registry ----------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """One pipeline stage: how to detect its source, run it, summarize it."""

    name: str
    detect: Callable[[Path, config.Config], str | None]
    run: Callable[[Path, config.Config], dict]
    summarize: Callable[[dict], str]
    where: str


def _all_steps(cfg: config.Config) -> dict[str, Step]:
    """Every importer step keyed by name (merge handled separately)."""
    return {
        "calibre": Step(
            "calibre", _detect_calibre, _run_calibre, _summ_calibre, "~/Calibre Library"
        ),
        "goodreads": Step(
            "goodreads",
            _detect_goodreads,
            _run_goodreads,
            _summ_goodreads,
            _imports_label("goodreads", cfg),
        ),
        "audible": Step("audible", _detect_audible, _run_audible, _summ_audible, "Audible cloud"),
        "covers": Step("covers", _detect_covers, _run_covers, _summ_covers, "Data/books.csv"),
        "kobo": Step(
            "kobo",
            _detect_kobo,
            _run_kobo,
            _summ_highlights,
            f"{_imports_label('kobo', cfg)} or a mounted Kobo",
        ),
        "highlighted": Step(
            "highlighted",
            _detect_highlighted,
            _run_highlighted,
            _summ_highlights,
            _imports_label("highlighted", cfg),
        ),
        "readwise": Step(
            "readwise",
            _detect_readwise,
            _run_readwise,
            _summ_highlights,
            _imports_label("readwise", cfg),
        ),
    }


def _merge_step() -> Step:
    return Step("merge", _detect_merge, _run_merge, _summ_merge, "Data/Sources")


def build_steps(selection: set[str], cfg: config.Config | None = None) -> list[Step]:
    """Order the selected importers and inject ``merge`` where needed.

    Order: calibre, goodreads, [merge], audible, covers, [merge], kobo,
    highlighted, readwise. A pre-merge runs when any consumer is selected or a
    phase-A layer is written; a post-merge runs when an enricher wrote a layer.
    """
    if cfg is None:
        cfg = config.load_config()
    steps = _all_steps(cfg)
    out: list[Step] = []
    for name in ("calibre", "goodreads"):
        if name in selection:
            out.append(steps[name])
    need_pre = bool(selection & set(_CONSUMERS)) or bool(selection & {"calibre", "goodreads"})
    if need_pre:
        out.append(_merge_step())
    for name in ("audible", "covers"):
        if name in selection:
            out.append(steps[name])
    if selection & set(_ENRICHERS):
        out.append(_merge_step())
    for name in ("kobo", "highlighted", "readwise"):
        if name in selection:
            out.append(steps[name])
    return out


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
    if r.status == "failed":
        return "[red]✗[/red]", f"[red]failed — {escape(r.error or '')}[/red]"
    if r.status == "skipped":
        return "[yellow]⊘[/yellow]", f"[dim]{escape(r.summary)}[/dim]"
    if r.status == "planned":
        return "[cyan]•[/cyan]", f"[dim]{escape(r.summary)}[/dim]"
    return "[green]✓[/green]", escape(r.summary)


def _print_summary(results: list[StepResult], *, dry_run: bool = False) -> None:
    ran = sum(1 for r in results if r.status == "ran")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = sum(1 for r in results if r.status == "failed")

    table = ui.summary_table("Import (dry run)" if dry_run else "Import")
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


def run_import(
    vault: Path,
    *,
    selection: set[str],
    dry_run: bool = False,
    cfg: config.Config | None = None,
) -> list[StepResult]:
    """Run the selected importers (with auto-merge) in dependency order.

    Returns a ``StepResult`` per step. Failures are recorded and never stop the
    remaining steps. In *dry_run* mode nothing is executed or written. The
    config is loaded once here and threaded through every step.
    """
    if cfg is None:
        cfg = config.load_config()
    if not dry_run:
        vault.mkdir(parents=True, exist_ok=True)

    results: list[StepResult] = []
    for step in build_steps(selection, cfg):
        source = step.detect(vault, cfg)
        if source is None:
            results.append(StepResult(step.name, "skipped", f"skipped — no source in {step.where}"))
            continue
        if dry_run:
            _plan(step.name, source)
            results.append(StepResult(step.name, "planned", f"would run from {source}"))
            continue
        _header(step.name, source)
        try:
            stats = step.run(vault, cfg)
        except Exception as exc:  # continue-on-error
            message = str(exc) or exc.__class__.__name__
            results.append(StepResult(step.name, "failed", "failed", error=message))
            continue
        results.append(StepResult(step.name, "ran", step.summarize(stats)))

    _print_summary(results, dry_run=dry_run)
    return results


def _selection_from_flags(flags: dict[str, bool], default: set[str]) -> set[str]:
    """Chosen importers, or the configured *default* set when no flag is set."""
    chosen = {name for name, on in flags.items() if on}
    return chosen or set(default)


def import_command(
    calibre_: bool = typer.Option(False, "--calibre", help="Import the Calibre library."),
    goodreads_: bool = typer.Option(False, "--goodreads", help="Import the Goodreads export."),
    kobo_: bool = typer.Option(False, "--kobo", help="Import Kobo highlights."),
    highlighted_: bool = typer.Option(
        False, "--highlighted", help="Import Highlighted app exports."
    ),
    readwise_: bool = typer.Option(False, "--readwise", help="Import the Readwise export."),
    audible_: bool = typer.Option(
        False, "--audible", help="Import Audible clips (opt-in; needs cloud auth)."
    ),
    covers_: bool = typer.Option(
        False, "--covers", help="Fetch missing covers (opt-in; hits the network)."
    ),
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
) -> None:
    """Ingest raw sources into the CSV store.

    With no flag the configured default set runs (out of the box: calibre,
    goodreads, kobo, highlighted, readwise — set the import.default list in your
    config to change it); flags select an exact subset. `--audible`/`--covers`
    run only when named or added to the default. `merge` runs automatically.
    Rendering notes is a separate command (`books export`).
    """
    cfg = config.load_config()
    selection = _selection_from_flags(
        {
            "calibre": calibre_,
            "goodreads": goodreads_,
            "kobo": kobo_,
            "highlighted": highlighted_,
            "readwise": readwise_,
            "audible": audible_,
            "covers": covers_,
        },
        default=set(cfg.import_.default),
    )
    vault = config.resolve_vault(output)
    run_import(vault, selection=selection, dry_run=dry_run, cfg=cfg)


def register(app: typer.Typer) -> None:
    app.command("import")(import_command)


def main() -> None:
    typer.run(import_command)


if __name__ == "__main__":
    main()
