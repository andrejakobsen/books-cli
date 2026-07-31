"""`books config` — configure the CLI. First subcommand: `config export`.

`books config export` lets you browse the highlight callout templates with a
live rendered-markdown preview and saves the chosen one into
``[export.obsidian].highlights_template``. Interactive terminals get a
full-screen prompt_toolkit app (exporter list -> template list + live preview);
off-tty callers get a numbered fallback so tests/pipes still work.
"""

from __future__ import annotations

from pathlib import Path

import typer

from books.commands.config_preview import (
    list_obsidian_templates,
    render_preview,
    template_label,
)
from books.core import config, ui

config_app = typer.Typer(no_args_is_help=True, help="Configure the books CLI.")

# Output formats offered by `config export`. Only obsidian exists today; a future
# renderer adds a row here and its own template list.
FORMATS = ("obsidian",)


def _display_path(path: Path) -> str:
    """Render *path* with a leading ``~`` when under the home dir (portable config)."""
    home = Path.home()
    try:
        return "~/" + str(path.relative_to(home))
    except ValueError:
        return str(path)


def _current_label() -> str | None:
    """Label of the currently-configured template, if any."""
    raw = config.load_config().export.obsidian.highlights_template
    return template_label(Path(raw)) if raw else None


def _select_offtty(templates: list[Path]) -> Path | None:
    """Numbered fallback: print each preview, then ask by label."""
    labels = [template_label(p) for p in templates]
    for p, label in zip(templates, labels, strict=True):
        ui.info(f"--- {label} ---")
        ui.info(render_preview(p))
    choice = ui.prompt_choice("Template", labels, default=labels[0])
    return templates[labels.index(choice)]


def export_config_command() -> None:
    """Pick a highlight template (with live preview) and save it to config."""
    templates = list_obsidian_templates()
    if not templates:
        ui.error("No highlight templates found.")
        raise typer.Exit(1)

    if ui.console.is_terminal:
        selected = _run_tui(templates, _current_label())
    else:
        ui.info("Configuring exporter: obsidian")
        selected = _select_offtty(templates)

    if selected is None:
        ui.info("No changes made.")
        return
    config.set_highlights_template(_display_path(selected))
    ui.success(f"Set obsidian highlights_template to {selected.name}")


def _run_tui(templates: list[Path], current: str | None) -> Path | None:
    """Full-screen picker: exporter list -> template list with live preview.

    Returns the chosen template path, or None if the user quit/cancelled.
    """
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.layout.dimension import D

    labels = [template_label(p) for p in templates]
    preview_cache: dict[int, str] = {}

    state = {
        "screen": "format",  # "format" | "template"
        "f_idx": 0,
        "t_idx": labels.index(current) if current in labels else 0,
        "result": None,
    }

    def _preview(idx: int) -> str:
        if idx not in preview_cache:
            preview_cache[idx] = render_preview(templates[idx])
        return preview_cache[idx]

    def _list_text() -> list[tuple[str, str]]:
        if state["screen"] == "format":
            items, cur = list(FORMATS), state["f_idx"]
        else:
            items, cur = labels, state["t_idx"]
        out: list[tuple[str, str]] = []
        for i, name in enumerate(items):
            if i == cur:
                out.append(("class:selected", f" > {name}\n"))
            else:
                out.append(("", f"   {name}\n"))
        return out

    def _right_text() -> str:
        if state["screen"] == "format":
            return "Select an exporter to configure, then press Enter."
        return _preview(state["t_idx"])

    def _title_text() -> str:
        if state["screen"] == "format":
            return "Exporters"
        return f"Template   (preview: {labels[state['t_idx']]})"

    kb = KeyBindings()

    @kb.add("up")
    def _(event):
        key = "f_idx" if state["screen"] == "format" else "t_idx"
        state[key] = max(0, state[key] - 1)

    @kb.add("down")
    def _(event):
        n = len(FORMATS) if state["screen"] == "format" else len(labels)
        key = "f_idx" if state["screen"] == "format" else "t_idx"
        state[key] = min(n - 1, state[key] + 1)

    @kb.add("enter")
    def _(event):
        if state["screen"] == "format":
            state["screen"] = "template"
        else:
            state["result"] = templates[state["t_idx"]]
            event.app.exit()

    @kb.add("left")
    @kb.add("escape")
    def _(event):
        if state["screen"] == "template":
            state["screen"] = "format"
        else:
            event.app.exit()

    @kb.add("q")
    @kb.add("c-c")
    def _(event):
        event.app.exit()

    left = Window(FormattedTextControl(_list_text), width=D(preferred=28))
    right = Window(FormattedTextControl(_right_text), wrap_lines=True)
    header = Window(FormattedTextControl(_title_text), height=1)
    footer = Window(
        FormattedTextControl("  ↑↓ move · ↵ select · ← back · q quit"), height=1
    )
    body = VSplit([left, Window(width=1, char="│"), right])
    layout = Layout(HSplit([header, body, footer]))

    app = Application(layout=layout, key_bindings=kb, full_screen=True)
    app.run()
    return state["result"]


def register(app: typer.Typer) -> None:
    """Register the `config` sub-app on the shared Typer app."""
    config_app.command("export")(export_config_command)
    app.add_typer(config_app, name="config")


def main() -> None:
    typer.run(export_config_command)


if __name__ == "__main__":
    main()
