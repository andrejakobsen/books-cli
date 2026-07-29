#!/usr/bin/env python3
"""`sync` — run every importer in dependency order using default options.

One command to refresh the whole vault. Note-creating importers run first to
establish book identity (`calibre`, then `goodreads`); the highlight enrichers
(`kobo`, `highlighted`, `readwise`) run afterward and only fill existing notes.
Covers are out of scope — run `covers` separately.

Each step is skipped when its source is absent, so `sync` imports whatever it
finds. A step failure is reported but never stops the remaining steps; a colored
summary is printed at the end.

Standard library only (Typer is the sole runtime dependency).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import typer

from books.commands import (
    calibre,
    goodreads,
    highlighted,
    kobo,
    readwise,
)
from books.core import config


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
    """The default Calibre library (mirrors the `calibre` command)."""
    return Path.home() / "Calibre Library"


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
    return _imports_label("highlighted") if _has_csv(_imports_folder("highlighted", vault)) else None


def _detect_readwise(vault: Path) -> str | None:
    return _imports_label("readwise") if _has_csv(_imports_folder("readwise", vault)) else None


# --- Step runners (call each module's core function directly) ----------------

def _run_calibre(vault: Path) -> dict:
    return calibre.convert(_calibre_library(), vault)


def _run_goodreads(vault: Path) -> dict:
    csv = config.newest_csv(_imports_folder("goodreads", vault))
    return goodreads.convert(csv, vault)


def _run_kobo(vault: Path) -> dict:
    db = kobo._default_kobo_db(vault)
    return kobo.export_obsidian(db, vault)


def _run_highlighted(vault: Path) -> dict:
    folder = _imports_folder("highlighted", vault)
    totals = {"books": 0, "entries": 0, "skipped": 0, "authors": set()}
    for path in sorted(folder.glob("*.csv")):
        stats = highlighted.convert(path, vault)
        totals["books"] += stats["books"]
        totals["entries"] += stats["entries"]
        totals["skipped"] += stats["skipped"]
        totals["authors"].update(stats["authors"])
    return totals


def _run_readwise(vault: Path) -> dict:
    csv = config.newest_csv(_imports_folder("readwise", vault))
    return readwise.convert(csv, vault)


# --- Summaries --------------------------------------------------------------

def _summ_calibre(s: dict) -> str:
    return (f"{s.get('books', 0)} books, {s.get('covers', 0)} covers, "
            f"{len(s.get('authors', ()))} authors, {s.get('skipped', 0)} skipped")


def _summ_goodreads(s: dict) -> str:
    return (f"{s.get('created', 0)} created, {s.get('merged', 0)} merged, "
            f"{s.get('reviews', 0)} reviews, {s.get('skipped', 0)} skipped")


def _summ_highlights(s: dict) -> str:
    skipped = f", {s['skipped']} skipped" if s.get("skipped") else ""
    return f"{s.get('books', 0)} books, {s.get('entries', 0)} highlights{skipped}"


# --- Step registry ----------------------------------------------------------

@dataclass(frozen=True)
class Step:
    """One importer stage: how to detect its source, run it, summarize it."""
    name: str
    detect: Callable[[Path], "str | None"]
    run: Callable[[Path], dict]
    summarize: Callable[[dict], str]


def _steps() -> list[Step]:
    """Build the ordered step list, resolving runners at call time.

    Runners are looked up as module globals (not captured) so tests can
    monkeypatch ``_run_<name>`` and have it take effect here.
    """
    return [
        Step("calibre", _detect_calibre, _run_calibre, _summ_calibre),
        Step("goodreads", _detect_goodreads, _run_goodreads, _summ_goodreads),
        Step("kobo", _detect_kobo, _run_kobo, _summ_highlights),
        Step("highlighted", _detect_highlighted, _run_highlighted, _summ_highlights),
        Step("readwise", _detect_readwise, _run_readwise, _summ_highlights),
    ]


@dataclass
class StepResult:
    """Outcome of one step: status is ran / skipped / failed / planned."""
    name: str
    status: str
    summary: str
    error: str | None = None


# --- Colored output ---------------------------------------------------------

def _header(name: str, source: str) -> None:
    typer.secho(f"▶ {name}", fg=typer.colors.CYAN, bold=True, nl=False)
    typer.secho(f"  ({source})", fg=typer.colors.BRIGHT_BLACK)


def _ok(summary: str) -> None:
    typer.secho(f"  ✓ {summary}", fg=typer.colors.GREEN)


def _skip(name: str, reason: str) -> None:
    typer.secho(f"⊘ {name}", fg=typer.colors.YELLOW, bold=True, nl=False)
    typer.secho(f"  skipped — {reason}", fg=typer.colors.BRIGHT_BLACK)


def _fail(error: str) -> None:
    typer.secho(f"  ✗ failed — {error}", fg=typer.colors.RED, bold=True)


def _plan(name: str, source: str) -> None:
    typer.secho(f"• {name}", fg=typer.colors.CYAN, bold=True, nl=False)
    typer.secho(f"  would run from {source}", fg=typer.colors.BRIGHT_BLACK)


def _print_summary(results: list[StepResult]) -> None:
    ran = sum(1 for r in results if r.status == "ran")
    skipped = sum(1 for r in results if r.status == "skipped")
    failed = sum(1 for r in results if r.status == "failed")
    typer.secho("\nSummary", bold=True)
    for r in results:
        if r.status == "failed":
            glyph, color = "✗", typer.colors.RED
        elif r.status == "skipped":
            glyph, color = "⊘", typer.colors.YELLOW
        else:
            glyph, color = "✓", typer.colors.GREEN
        typer.secho(f"  {glyph} {r.name:<12} {r.summary}", fg=color)
    tally = f"{ran} ran, {skipped} skipped, {failed} failed"
    typer.secho(tally, fg=(typer.colors.RED if failed else typer.colors.GREEN), bold=True)


# --- Orchestration ----------------------------------------------------------

def run_sync(vault: Path, *, dry_run: bool = False) -> list[StepResult]:
    """Run every importer whose source is present, in dependency order.

    Returns a ``StepResult`` per step. Failures are recorded and never stop the
    remaining steps. In *dry_run* mode nothing is executed or written; detected
    steps are reported with status ``planned``.
    """
    if not dry_run:
        vault.mkdir(parents=True, exist_ok=True)

    results: list[StepResult] = []
    for step in _steps():
        source = step.detect(vault)
        if source is None:
            _skip(step.name, f"no source in {_imports_label(step.name)}")
            results.append(StepResult(step.name, "skipped",
                                      f"skipped ({_imports_label(step.name)})"))
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
            _fail(message)
            results.append(StepResult(step.name, "failed", "failed", error=message))
            continue
        summary = step.summarize(stats)
        _ok(summary)
        results.append(StepResult(step.name, "ran", summary))

    if not dry_run:
        _print_summary(results)
    return results


def sync(
    output: Path | None = typer.Option(
        None,
        "--output", "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
             "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show which steps would run (and from which source) without writing anything.",
    ),
) -> None:
    """Run all importers in order using default options.

    Runs calibre → goodreads → kobo → highlighted → readwise, skipping any step
    whose source is absent. calibre/goodreads create book notes; the highlight
    importers only enrich existing notes. Covers are not included — run `covers`
    separately. A step that fails is reported but does not stop the others.
    """
    vault = config.resolve_vault(output)
    run_sync(vault, dry_run=dry_run)


def register(app: typer.Typer) -> None:
    app.command("sync")(sync)


def main() -> None:
    typer.run(sync)


if __name__ == "__main__":
    main()
