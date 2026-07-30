import io

from rich.panel import Panel
from rich.progress import Progress
from rich.table import Table

from books.core import ui
from books.core.ui import ProgressBar


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


def test_success_preserves_literal_brackets():
    out = _cap(ui.success, "The Book [Deluxe]")
    assert "The Book [Deluxe]" in out


def test_error_with_bracket_text_does_not_crash():
    buf = io.StringIO()
    old = ui.err_console.file
    ui.err_console.file = buf
    try:
        ui.error("boom [/] danger")
    finally:
        ui.err_console.file = old
    assert "boom [/] danger" in buf.getvalue()


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
    with ui.progress("working", total=3) as bar:
        assert bar._prog.disable is True


def test_progressbar_advance_and_describe():
    prog = Progress()
    task = prog.add_task("init", total=5)
    bar = ProgressBar(prog, task)

    bar.advance()
    bar.advance(2)
    bar.describe("now working")

    t = prog.tasks[0]
    assert t.completed == 3
    assert t.description == "now working"


def test_confirm_reads_from_injected_stream():
    assert ui.confirm("ok?", default=False, stream=io.StringIO("y\n")) is True


def test_prompt_choice_validates_and_returns():
    got = ui.prompt_choice("pick", choices=["y", "n"], default="y", stream=io.StringIO("n\n"))
    assert got == "n"


def test_nested_progress_offtty_is_noop():
    # In the pytest process the console is not a terminal, so nested_progress
    # yields a no-op handle whose methods are safely callable.
    with ui.nested_progress("Importing", total=2) as prog:
        prog.status("Book A - downloading")
        prog.advance()
        prog.advance(1)
    # no exception, nothing rendered
