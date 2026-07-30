# Rich Console Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route all `books` CLI output through a single Rich-based presentation layer (`books/core/ui.py`) — colored status lines, report tables, panels, progress bars, and validated prompts — replacing ~35 scattered `typer.secho`/`typer.echo`/`print()` sites.

**Architecture:** A new `books/core/ui.py` owns a module-level Rich `Console` (bound to no explicit file, so it follows `sys.stdout` and `CliRunner` redirection) plus semantic helpers (`info`/`success`/`warn`/`error`), table/panel factories, a `progress` context manager, and `prompt_choice`/`confirm` wrappers. Every command and the obsidian renderer import from it. Non-tty output uses a generous width and disabled progress so existing substring assertions stay valid.

**Tech Stack:** Python 3.11+, Typer, Rich 15 (already transitive via Typer; promoted to an explicit dep), pytest.

---

## File Structure

- **Create** `books/core/ui.py` — the presentation layer (console, helpers, table/panel factories, progress CM, prompt wrappers).
- **Create** `tests/core/test_ui.py` — unit tests for the ui helpers.
- **Modify** `pyproject.toml` — add `rich>=13` to `[project].dependencies`.
- **Modify** `books/commands/sync.py` — report → table.
- **Modify** `books/commands/covers/command.py` — panel + Rich prompt + summary table.
- **Modify** `books/commands/calibre.py` — progress bar + helpers.
- **Modify** `books/commands/render.py` — progress bar + helpers.
- **Modify** `books/renderers/obsidian/note.py` — corrupt-note `warn`.
- **Modify** `books/commands/audible/command.py` — progress + helper sink.
- **Modify** `books/commands/goodreads.py`, `merge.py`, `kobo.py`, `readwise.py`, `highlighted.py` — one-line summaries → helpers.

---

## Task 1: The `books/core/ui.py` presentation layer

**Files:**
- Create: `books/core/ui.py`
- Create: `tests/core/test_ui.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add rich as an explicit dependency**

In `pyproject.toml`, change the `dependencies` list to include rich:

```toml
dependencies = [
    "typer>=0.12",
    "pydantic>=2.6",
    "isbnlib>=3.10",
    "rapidfuzz>=3.6",
    "python-frontmatter>=1.1",
    "ruamel.yaml>=0.18",
    "rich>=13",
]
```

Then run: `uv sync`
Expected: resolves and installs (rich already present, now pinned).

- [ ] **Step 2: Write the failing tests**

Create `tests/core/test_ui.py`:

```python
import io

from rich.panel import Panel
from rich.table import Table

from books.core import ui


def _cap(func, *args, **kwargs):
    """Render a ui helper into a string via a captured console."""
    buf = io.StringIO()
    old = ui.console.file
    ui.console.file = buf
    try:
        func(*args, **kwargs)
    finally:
        ui.console.file = old
    return buf.getvalue()


def test_info_writes_plain_text():
    assert "hello world" in _cap(ui.info, "hello world")


def test_success_has_check_glyph():
    out = _cap(ui.success, "done")
    assert "done" in out
    assert "✓" in out


def test_warn_goes_to_stderr_not_stdout():
    buf = io.StringIO()
    old = ui.err_console.file
    ui.err_console.file = buf
    try:
        ui.warn("careful")
    finally:
        ui.err_console.file = old
    assert "careful" in buf.getvalue()
    assert "⊘" in buf.getvalue()


def test_summary_table_is_a_table():
    assert isinstance(ui.summary_table("Sync"), Table)


def test_panel_is_a_panel():
    assert isinstance(ui.panel("body", title="t"), Panel)


def test_progress_disabled_when_not_terminal():
    # Non-tty (test) => progress must be disabled so no live frames leak.
    with ui.progress("working", total=3) as prog:
        assert prog.disable is True


def test_confirm_reads_from_injected_stream():
    assert ui.confirm("ok?", default=False, stream=io.StringIO("y\n")) is True


def test_prompt_choice_validates_and_returns():
    got = ui.prompt_choice("pick", choices=["y", "n"], default="y", stream=io.StringIO("n\n"))
    assert got == "n"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_ui.py -q`
Expected: FAIL with `ModuleNotFoundError: books.core.ui` (or attribute errors).

- [ ] **Step 4: Implement `books/core/ui.py`**

Create `books/core/ui.py`:

```python
"""Rich-based console presentation layer for the ``books`` CLI.

Every command and the obsidian renderer route their output through here so the
CLI reads as one coherent tool. The module-level ``console`` is created with no
bound ``file``, so its ``file`` property resolves ``sys.stdout`` at write time —
that is what lets Typer's ``CliRunner`` output redirection and non-tty color
suppression both work without extra wiring.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import IO

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.prompt import Confirm, Prompt
from rich.table import Table

# Generous width so non-tty output (tests, pipes) does not wrap and break
# substring assertions; a real terminal auto-detects its own width.
_NON_TTY_WIDTH = 200
_IS_TTY = Console().is_terminal

console = Console(width=None if _IS_TTY else _NON_TTY_WIDTH)
err_console = Console(stderr=True, width=None if _IS_TTY else _NON_TTY_WIDTH)


def info(msg: str) -> None:
    """Plain informational line to stdout."""
    console.print(msg)


def dim(msg: str) -> None:
    """Dimmed line to stdout."""
    console.print(f"[dim]{msg}[/dim]")


def success(msg: str) -> None:
    """Green check line to stdout."""
    console.print(f"[green]✓[/green] {msg}")


def warn(msg: str) -> None:
    """Yellow warning line to stderr."""
    err_console.print(f"[yellow]⊘ {msg}[/yellow]")


def error(msg: str) -> None:
    """Red error line to stderr."""
    err_console.print(f"[red]✗ {msg}[/red]")


def summary_table(title: str, subtitle: str | None = None) -> Table:
    """A pre-styled table for per-step / per-source run reports."""
    from rich import box

    table = Table(box=box.SIMPLE_HEAD, title=title, caption=subtitle, pad_edge=False)
    return table


def panel(body: str, title: str | None = None, style: str = "blue") -> Panel:
    """A pre-styled panel (used for e.g. a cover candidate)."""
    from rich import box

    return Panel(
        body,
        title=title,
        title_align="left",
        border_style=style,
        box=box.ROUNDED,
        padding=(0, 1),
    )


@contextmanager
def progress(description: str, total: int | None = None):
    """Yield a started Rich Progress with one task.

    ``total=None`` renders a spinner; a number renders a determinate bar. The
    progress is disabled off-tty so tests / pipes render no live frames.
    """
    columns = [SpinnerColumn(), TextColumn("[progress.description]{task.description}")]
    if total is not None:
        columns += [BarColumn(), TimeRemainingColumn()]
    prog = Progress(*columns, console=console, disable=not console.is_terminal)
    with prog:
        prog.add_task(description, total=total)
        yield prog


def prompt_choice(
    question: str,
    choices: list[str],
    default: str,
    stream: IO[str] | None = None,
) -> str:
    """Ask a validated single-choice question (re-asks on invalid input)."""
    return Prompt.ask(question, choices=choices, default=default, console=console, stream=stream)


def confirm(question: str, default: bool = False, stream: IO[str] | None = None) -> bool:
    """Ask a yes/no question."""
    return Confirm.ask(question, default=default, console=console, stream=stream)
```

Note: `Progress.add_task` advances via `prog.advance(task_id)`; a single task's id
is `0` for the first task, so callers use `prog.advance(0)` per item.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_ui.py -q`
Expected: PASS (all 8 tests).

- [ ] **Step 6: Lint, format, commit**

```bash
uv run ruff check --fix
uv run ruff format
uv run pytest -q
git add books/core/ui.py tests/core/test_ui.py pyproject.toml uv.lock
git commit -m "feat(ui): add rich console presentation layer"
```

---

## Task 2: Convert `sync.py` report to a Rich table

**Files:**
- Modify: `books/commands/sync.py` (the `_step_*` / summary helpers, ~lines 270–306)
- Test: `tests/commands/test_sync.py` (existing assertions must still pass)

- [ ] **Step 1: Read the current reporting helpers**

Run: `sed -n '260,310p' books/commands/sync.py`
Expected: see `typer.secho` calls for running/ok/skipped/failed/dry-run/summary.

- [ ] **Step 2: Add a table-based report**

Replace the per-step `typer.secho` reporting so a single `ui.summary_table` collects
all step rows and is printed once at the end (keep the existing result dataclass /
loop structure — only change how rows are emitted). Concretely, build the table from
the collected step results:

```python
from books.core import ui


def _print_report(results, *, dry_run: bool) -> None:
    table = ui.summary_table("Sync" + (" (dry run)" if dry_run else ""))
    table.add_column("", width=2)
    table.add_column("Step", style="cyan", no_wrap=True)
    table.add_column("Result")
    ok = skipped = failed = 0
    for r in results:
        if r.status == "ok":
            glyph, ok = "[green]✓[/green]", ok + 1
            result = r.summary
        elif r.status == "skipped":
            glyph, skipped = "[yellow]⊘[/yellow]", skipped + 1
            result = f"[dim]skipped — {r.reason}[/dim]"
        elif r.status == "planned":
            glyph = "[cyan]•[/cyan]"
            result = f"[dim]would run from {r.source}[/dim]"
        else:  # failed
            glyph, failed = "[red]✗[/red]", failed + 1
            result = f"[red]failed — {r.error}[/red]"
        table.add_row(glyph, r.name, result)
    ui.console.print(table)
    tally = f"{ok} ok · {skipped} skipped · {failed} failed"
    (ui.error if failed else ui.success)(tally)
```

Adapt the attribute names (`r.status`, `r.summary`, `r.reason`, `r.source`, `r.error`)
to the actual result dataclass in `sync.py`; if the current code prints per-step live
(not collected), collect the results into a list first and call `_print_report` once.
Keep the existing `typer.secho(f"▶ {name}", ...)` *live* progress line if you want
per-step feedback, or drop it in favor of the final table — prefer the final table
only, to keep output clean.

- [ ] **Step 3: Run the sync tests**

Run: `uv run pytest tests/commands/test_sync.py -q`
Expected: PASS. The one assertion `assert "sync" in result.output` (line 218) still
holds because the table title contains "Sync"/"sync" — if it checks lowercase exactly,
confirm the substring; if needed, ensure the printed text includes `sync`.

- [ ] **Step 4: Lint, format, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run pytest -q
git add books/commands/sync.py
git commit -m "feat(sync): render step report as a rich table"
```

---

## Task 3: Convert `covers` to panel + Rich prompt + summary table

**Files:**
- Modify: `books/commands/covers/command.py` (`_terminal_prompt` ~85–90; result lines ~121–173; summary ~244–254)
- Test: `tests/commands/test_covers.py` (existing assertions must still pass)

- [ ] **Step 1: Convert the candidate prompt to a panel + Rich choice**

Replace `_terminal_prompt` (lines ~85–90):

```python
from books.core import ui


def _terminal_prompt(cand: Candidate) -> str:
    """Ask the user about one candidate; map keys to an action string."""
    fmt = f" · {cand.fmt}" if cand.fmt else ""
    body = f"[cyan]{cand.source}[/cyan]  {cand.label}[dim]{fmt}[/dim]\n[dim]{cand.image_url}[/dim]"
    ui.console.print(ui.panel(body, title="candidate", style="blue"))
    ans = ui.prompt_choice("Use this cover?", choices=["y", "n", "s", "q"], default="y")
    return {"y": "accept", "n": "next", "s": "skip", "q": "quit"}.get(ans, "next")
```

Note: tests inject their own `prompt=` callable into `pick_cover`, so this production
default is never exercised by `test_covers.py` — no input shim needed there.

- [ ] **Step 2: Convert the run() output lines**

In `run(...)`, replace the bare `print(...)` calls:

```python
# book header (line ~144):
ui.info(f"\n[bold]{book.title}[/bold] [dim]— {', '.join(book.authors) or 'Unknown'}[/dim]")
# quit (line ~150):
ui.dim("Quit.")
# no cover (line ~157):
ui.warn(f"no cover: {book.title}")
# dry-run (line ~163):
ui.dim(f"[dry-run] {cand.source}: {cand.image_url}")
# success (line ~173):
ui.success(f"[cyan]{cand.source}[/cyan] → {book.title}")
# missing-book id (line ~121):
ui.warn(f"no cover-less book with book_id {book_id!r} (unknown id, or it already has a cover)")
```

- [ ] **Step 3: Convert the final summary (lines ~244–254) to helpers/table**

Replace the `typer.echo`/`typer.secho` summary with a small `ui.summary_table`
(columns: source, fetched, errored) built from `stats["by_source"]` and
`stats["errored"]`, printed via `ui.console.print(table)`, then an `ui.info` line with
`scanned`/`missing`/`fetched`/`not_found`. Keep the words `missing` and `books.csv`
present in output where the current code prints them (asserted at test lines 801, 812).

- [ ] **Step 4: Run covers tests**

Run: `uv run pytest tests/commands/test_covers.py -q`
Expected: PASS. Verify `"missing" in output.lower()` and `"books.csv" in output.lower()`
still hold; adjust the summary text to preserve those substrings if a test fails.

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run pytest -q
git add books/commands/covers/command.py
git commit -m "feat(covers): rich panel + prompt + summary table"
```

---

## Task 4: Add a progress bar + helpers to `calibre`

**Files:**
- Modify: `books/commands/calibre.py` (warn ~226; summary ~289; the per-book loop)
- Test: `tests/commands/test_calibre.py` (assertion `"0 books"` must still pass)

- [ ] **Step 1: Wrap the per-book scan loop in a progress bar**

Find the loop that iterates the library's book folders (the one that calls the OPF
parse). Wrap it:

```python
from books.core import ui

with ui.progress("Scanning Calibre library", total=len(book_dirs)) as prog:
    for book_dir in book_dirs:
        ...  # existing body
        prog.advance(0)
```

Use the actual variable name for the iterable (e.g. `book_dirs`/`entries`). If the
count is not known up front, pass `total=None` for a spinner instead.

- [ ] **Step 2: Convert the warn and summary lines**

```python
# line ~226:
ui.warn(f"could not parse {opf_path}: {exc}")
# summary line ~289 (keep the "N books" phrasing that tests assert):
ui.info(f"{count} books → {store.sources_layer_path(vault, 'calibre')}")
```

Keep the exact `"0 books"` / `"N books"` wording (asserted at test line 113).

- [ ] **Step 3: Run calibre tests**

Run: `uv run pytest tests/commands/test_calibre.py -q`
Expected: PASS (`"0 books" in result.output` still holds — progress is disabled off-tty).

- [ ] **Step 4: Lint, format, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run pytest -q
git add books/commands/calibre.py
git commit -m "feat(calibre): progress bar + ui helpers"
```

---

## Task 5: Add a progress bar to `render` + fix `note.py` warn

**Files:**
- Modify: `books/commands/render.py` (summary ~69; the per-book loop)
- Modify: `books/renderers/obsidian/note.py` (line ~220 corrupt-note warn)
- Test: `tests/commands/test_render.py`

- [ ] **Step 1: Convert the corrupt-note line in note.py**

Replace `books/renderers/obsidian/note.py:220`:

```python
from books.core import ui
...
            ui.warn(f"{row.book_id}: {exc}")
```

(renderer → core is an allowed dependency direction.)

- [ ] **Step 2: Wrap the render loop in a progress bar**

In `render.py` (or wherever `render(vault)` iterates rows), wrap the per-book loop:

```python
from books.core import ui

with ui.progress("Rendering notes", total=len(rows)) as prog:
    for row in rows:
        ...  # existing render_note call + counting
        prog.advance(0)
```

Use the real iterable name. If the loop lives in `books/renderers/obsidian/note.py`
rather than the command, add the progress there and keep the command summary as-is.

- [ ] **Step 3: Convert the render summary (line ~69)**

```python
ui.info(f"{written} notes written{fail_note}")
```

Preserve whatever count phrasing the existing tests assert (check
`tests/commands/test_render.py` around line 297; keep matching substrings).

- [ ] **Step 4: Run render tests**

Run: `uv run pytest tests/commands/test_render.py tests/renderers/obsidian -q`
Expected: PASS.

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run pytest -q
git add books/commands/render.py books/renderers/obsidian/note.py
git commit -m "feat(render): progress bar + ui warn for corrupt notes"
```

---

## Task 6: Convert `audible` output + progress

**Files:**
- Modify: `books/commands/audible/command.py` (echo sink ~427; summaries ~432, ~442; download/transcribe loop)
- Test: `tests/commands/test_audible*.py` (if present) — run whatever exists.

- [ ] **Step 1: Point the injected echo sink at ui.info**

Change the `echo=typer.echo` argument (line ~427) to `echo=ui.info` (import
`from books.core import ui`). This keeps the injection seam intact for tests while
routing production output through Rich.

- [ ] **Step 2: Wrap the download/transcribe loop in a spinner/progress**

Inside the function that iterates library books downloading + transcribing clips, wrap
it with a progress. Because per-clip network + ffmpeg time is unpredictable, use a
spinner with a per-book description:

```python
with ui.progress("Processing audiobooks", total=None) as prog:
    for lib_book in library:
        prog.update(0, description=f"Processing {lib_book.title}")
        ...  # existing download/transcribe body
```

If that loop lives behind the injected `echo` sink (in a helper that already takes
`echo`), leave the loop as-is and rely on the `echo=ui.info` change from Step 1 — do
not force progress into an injected-sink helper if it complicates the signature.

- [ ] **Step 3: Convert the two summary blocks (lines ~432, ~442)**

Replace `typer.echo(...)` with `ui.info(...)` for the dry-run estimate and the final
`Done. …` line (keep the exact wording so any tests asserting on it still pass).

- [ ] **Step 4: Run audible tests (if any) + full suite**

Run: `uv run pytest -k audible -q`
Expected: PASS (or "no tests ran" if none exist — then rely on the full suite).

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run pytest -q
git add books/commands/audible/command.py
git commit -m "feat(audible): route output through ui + spinner"
```

---

## Task 7: Convert remaining one-line summaries

**Files:**
- Modify: `books/commands/goodreads.py` (line ~209)
- Modify: `books/commands/merge.py` (line ~38)
- Modify: `books/commands/kobo.py` (lines ~248–255)
- Modify: `books/commands/readwise.py` (line ~158)
- Modify: `books/commands/highlighted.py` (lines ~145–155)
- Test: their respective `tests/commands/test_*.py`

- [ ] **Step 1: Replace each summary echo with a ui helper**

In each file, `from books.core import ui` and swap:

```python
# goodreads.py:209 / merge.py:38 / readwise.py:158 / kobo.py:255 : typer.echo(...) -> ui.info(...)
# kobo.py:253 "No highlights or notes found." -> ui.warn(...)
# highlighted.py:145 (err=True skip line) -> ui.warn(f"Skipped {path.name}: {exc}")
# highlighted.py:155 summary -> ui.info(...)
```

Keep every existing summary string verbatim so these assertions still pass:
`"2 highlights"`, `"authors" not in output`, `"2 files"`, `"2 books"`, `"3 highlights"`,
`"1 skipped"`, `"1 file"`, `"Merged N books"`.

- [ ] **Step 2: Run each affected test file**

Run: `uv run pytest tests/commands/test_goodreads.py tests/commands/test_merge.py tests/commands/test_kobo.py tests/commands/test_readwise.py tests/commands/test_highlighted.py -q`
Expected: PASS.

- [ ] **Step 3: Verify no stray output calls remain**

Run: `grep -rn "typer.secho\|typer.echo\|[^.]print(" books/ | grep -v "def register"`
Expected: no matches in `books/` (all output now routes through `books.core.ui`). If any
remain, convert them.

- [ ] **Step 4: Lint, format, full suite, commit**

```bash
uv run ruff check --fix && uv run ruff format && uv run pytest -q
git add books/commands/goodreads.py books/commands/merge.py books/commands/kobo.py books/commands/readwise.py books/commands/highlighted.py
git commit -m "feat(cli): route remaining command summaries through ui"
```

---

## Self-Review Notes

- **Spec coverage:** ui module (Task 1) ✓; sync table (Task 2) ✓; covers panel+prompt+summary (Task 3) ✓; calibre progress (Task 4) ✓; render progress + note.py warn (Task 5) ✓; audible (Task 6) ✓; goodreads/merge/kobo/readwise/highlighted (Task 7) ✓; rich dep (Task 1 step 1) ✓; testing seam via generous width + disabled progress + injected `stream` (Task 1) ✓.
- **Out-of-scope respected:** no Typer help changes, no markup in notes/CSV, `tests/renderers/` content assertions untouched.
- **Type consistency:** `ui.info/success/warn/error/dim/summary_table/panel/progress/prompt_choice/confirm/console/err_console` used consistently across all tasks with the signatures defined in Task 1.
- **Assertion preservation:** every task step calls out the substrings its existing tests assert and requires preserving them.
