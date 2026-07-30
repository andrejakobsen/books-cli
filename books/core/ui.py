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

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)
from rich.prompt import Confirm, Prompt
from rich.spinner import Spinner
from rich.table import Table

# Generous width so non-tty output (tests, pipes) does not wrap and break
# substring assertions; a real terminal auto-detects its own width.
_NON_TTY_WIDTH = 200
_IS_TTY = Console().is_terminal

console = Console(width=None if _IS_TTY else _NON_TTY_WIDTH)
err_console = Console(stderr=True, width=None if _IS_TTY else _NON_TTY_WIDTH)


def info(msg: str) -> None:
    """Plain informational line to stdout."""
    console.print(escape(msg))


def dim(msg: str) -> None:
    """Dimmed line to stdout."""
    console.print(f"[dim]{escape(msg)}[/dim]")


def success(msg: str) -> None:
    """Green check line to stdout."""
    console.print(f"[green]✓[/green] {escape(msg)}")


def warn(msg: str) -> None:
    """Yellow warning line to stderr."""
    err_console.print(f"[yellow]⊘ {escape(msg)}[/yellow]")


def error(msg: str) -> None:
    """Red error line to stderr."""
    err_console.print(f"[red]✗ {escape(msg)}[/red]")


def summary_table(title: str, subtitle: str | None = None) -> Table:
    """A pre-styled table for per-step / per-source run reports."""
    table = Table(box=box.SIMPLE_HEAD, title=title, caption=subtitle, pad_edge=False)
    return table


def panel(body: str, title: str | None = None, style: str = "blue") -> Panel:
    """A pre-styled panel (used for e.g. a cover candidate)."""
    return Panel(
        body,
        title=title,
        title_align="left",
        border_style=style,
        box=box.ROUNDED,
        padding=(0, 1),
    )


class ProgressBar:
    """Thin handle over one rich Progress task (hides the task id)."""

    def __init__(self, prog: Progress, task_id) -> None:
        self._prog = prog
        self._task = task_id

    def advance(self, n: int = 1) -> None:
        """Advance the task by *n* steps."""
        self._prog.advance(self._task, n)

    def describe(self, text: str) -> None:
        """Replace the task's description line."""
        self._prog.update(self._task, description=text)


@contextmanager
def progress(description: str, total: int | None = None):
    """Yield a :class:`ProgressBar` handle for one task.

    ``total=None`` renders a spinner; a number renders a determinate bar with an
    M/N count. The progress is disabled off-tty so tests / pipes render no frames.
    """
    columns = [SpinnerColumn(), TextColumn("[progress.description]{task.description}")]
    if total is not None:
        columns += [BarColumn(), MofNCompleteColumn(), TimeRemainingColumn()]
    prog = Progress(*columns, console=console, disable=not console.is_terminal)
    with prog:
        task = prog.add_task(description, total=total)
        yield ProgressBar(prog, task)


class StepProgress:
    """Handle for a nested display: an overall status line + a per-book bar.

    The top line is a spinner + status text describing the whole run (all books);
    below it a determinate bar tracks the *current* book's clips, reset per book
    via :meth:`book`.
    """

    def __init__(self, prog: Progress, task_id, spinner: Spinner) -> None:
        self._prog = prog
        self._task = task_id
        self._spinner = spinner

    def status(self, text: str) -> None:
        """Rewrite the overall status line (all books)."""
        self._spinner.update(text=text)

    def book(self, description: str, total: int | None = None) -> None:
        """Start the per-book bar for a new book with *total* clips.

        Resets the bar's completed count to zero; pass ``total=None`` for a
        pulsing/indeterminate bar (e.g. while fetching annotations).
        """
        self._prog.reset(self._task, total=total, description=description)

    def describe(self, text: str) -> None:
        """Change the per-book bar's label without resetting its progress."""
        self._prog.update(self._task, description=text)

    def advance(self, n: int = 1) -> None:
        """Advance the current book's clip bar by *n*."""
        self._prog.advance(self._task, n)


class _NoopStep:
    """No-op stand-in used off-tty so callers need no branching."""

    def status(self, text: str) -> None:
        pass

    def book(self, description: str, total: int | None = None) -> None:
        pass

    def describe(self, text: str) -> None:
        pass

    def advance(self, n: int = 1) -> None:
        pass


@contextmanager
def nested_progress(status: str):
    """Yield a :class:`StepProgress`: an overall status line above a per-book bar.

    The top line is a spinner + *status* text describing the whole run; the bar
    below it tracks the current book's clips (reset per book via
    :meth:`StepProgress.book`). Off-tty (tests/pipes) a :class:`_NoopStep` is
    yielded and nothing renders.
    """
    if not console.is_terminal:
        yield _NoopStep()
        return
    spinner = Spinner("dots", text=status)
    bar = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
        auto_refresh=False,
    )
    task = bar.add_task("", total=None)
    with Live(Group(spinner, bar), console=console, refresh_per_second=12):
        yield StepProgress(bar, task, spinner)


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
