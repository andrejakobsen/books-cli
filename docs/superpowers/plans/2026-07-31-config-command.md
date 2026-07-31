# `books config` Command Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `books config` command group whose first subcommand, `books config export`, is a prompt_toolkit TUI that shows the highlight templates with a live side-by-side markdown preview and saves the chosen one into `config.toml`.

**Architecture:** A new capability module (`books/commands/config_cmd.py`) builds a `config` Typer sub-app attached via `app.add_typer(...)`. All data/rendering logic is pure and lives in a sibling `books/commands/config_preview.py` (sample highlights, template discovery, preview rendering). Config writes are a comment-preserving tomlkit helper in `books/core/config.py`. The full-screen prompt_toolkit app is a thin shell over the pure helpers, with a numbered off-tty fallback.

**Tech Stack:** Python 3.11+, Typer, Jinja2 (existing renderer), `prompt_toolkit` (new core dep, the TUI engine), `tomlkit` (new core dep, comment-preserving TOML writes), rich (existing `ui`), pytest.

---

## File Structure

- Modify `pyproject.toml` — add `prompt_toolkit` + `tomlkit` to core `dependencies`.
- Modify `books/core/config.py` — add `set_highlights_template()` (tomlkit writer).
- Create `books/commands/config_preview.py` — pure helpers: `sample_highlights()`, `list_obsidian_templates()`, `template_label()`, `render_preview()`.
- Create `books/commands/config_cmd.py` — the `config` Typer sub-app, `export` command, the prompt_toolkit app shell, and the off-tty fallback. Exposes `register(app)`.
- Modify `books/cli.py` — import `config_cmd` and add it to `CAPABILITIES`.
- Create `tests/core/test_config_set.py` — tests for `set_highlights_template`.
- Create `tests/commands/test_config_preview.py` — tests for the pure helpers.
- Create `tests/commands/test_config_cmd.py` — CLI registration + off-tty selection tests.
- Modify `tests/commands/test_cli.py` — assert `config` is registered.
- Modify `CLAUDE.md` and `books/core/config.py` default-file comment — docs.

---

### Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the two runtime deps**

In `pyproject.toml`, the `[project].dependencies` list currently ends:

```toml
    "rich>=13",
    "jinja2>=3.1",
]
```

Change it to:

```toml
    "rich>=13",
    "jinja2>=3.1",
    "prompt_toolkit>=3.0",
    "tomlkit>=0.12",
]
```

- [ ] **Step 2: Sync the environment**

Run: `uv sync`
Expected: resolves and installs `prompt_toolkit` and `tomlkit` with no errors.

- [ ] **Step 3: Verify imports work**

Run: `uv run python -c "import prompt_toolkit, tomlkit; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add prompt_toolkit + tomlkit as core deps for books config"
```

---

### Task 2: `set_highlights_template` config writer

**Files:**
- Modify: `books/core/config.py`
- Test: `tests/core/test_config_set.py`

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_config_set.py`:

```python
"""Tests for config.set_highlights_template (comment-preserving TOML write)."""

from books.core import config


def test_set_creates_file_and_key_when_absent(tmp_path):
    cfg_file = tmp_path / "books" / "config.toml"
    config.set_highlights_template("~/t/callout.md.jinja", cfg_file)
    assert cfg_file.is_file()
    cfg = config.load_config(cfg_file)
    assert cfg.export.obsidian.highlights_template == "~/t/callout.md.jinja"


def test_set_preserves_existing_content_and_comments(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        "# my header comment\n"
        'obsidian_path = "~/Vaults"\n'
        'vault = "Reading"  # inline comment\n'
        "\n"
        "[export]\n"
        'timezone = "America/New_York"\n'
    )
    config.set_highlights_template("~/t/blockquote.md.jinja", cfg_file)
    text = cfg_file.read_text()
    assert "# my header comment" in text
    assert "# inline comment" in text
    assert 'timezone = "America/New_York"' in text
    cfg = config.load_config(cfg_file)
    assert cfg.vault == "Reading"
    assert cfg.export.timezone == "America/New_York"
    assert cfg.export.obsidian.highlights_template == "~/t/blockquote.md.jinja"


def test_set_overwrites_previous_value(tmp_path):
    cfg_file = tmp_path / "config.toml"
    config.set_highlights_template("~/t/a.md.jinja", cfg_file)
    config.set_highlights_template("~/t/b.md.jinja", cfg_file)
    cfg = config.load_config(cfg_file)
    assert cfg.export.obsidian.highlights_template == "~/t/b.md.jinja"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_config_set.py -v`
Expected: FAIL with `AttributeError: module 'books.core.config' has no attribute 'set_highlights_template'`.

- [ ] **Step 3: Implement the writer**

In `books/core/config.py`, add `import tomlkit` near the top imports (after `import tomllib`):

```python
import tomlkit
```

Then add this function after `load_config` (near the other module-level helpers):

```python
def set_highlights_template(path: str, config_file: Path | None = None) -> None:
    """Set ``[export.obsidian].highlights_template`` in the config file.

    Round-trips the TOML with tomlkit so comments and unrelated keys survive.
    Creates the file from defaults first when absent, then ensures the
    ``[export]`` and ``[export.obsidian]`` tables exist and sets the key.
    """
    config_file = config_file or config_path()
    if not config_file.exists():
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(_DEFAULT_FILE)
    doc = tomlkit.parse(config_file.read_text())
    export = doc.get("export")
    if not isinstance(export, dict):
        export = tomlkit.table()
        doc["export"] = export
    obsidian = export.get("obsidian")
    if not isinstance(obsidian, dict):
        obsidian = tomlkit.table()
        export["obsidian"] = obsidian
    obsidian["highlights_template"] = path
    config_file.write_text(tomlkit.dumps(doc))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_config_set.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add books/core/config.py tests/core/test_config_set.py
git commit -m "feat(config): add set_highlights_template tomlkit writer"
```

---

### Task 3: Preview helpers (sample data, discovery, rendering)

**Files:**
- Create: `books/commands/config_preview.py`
- Test: `tests/commands/test_config_preview.py`

- [ ] **Step 1: Write the failing test**

Create `tests/commands/test_config_preview.py`:

```python
"""Tests for the config-export preview helpers (pure, no TUI)."""

from books.commands import config_preview as P
from books.core import config


def test_sample_highlights_exercises_features():
    hls = P.sample_highlights()
    assert len(hls) >= 2
    assert any(h.note for h in hls)
    assert any(h.tags for h in hls)
    assert any(h.links for h in hls)
    assert any(h.chapter_title for h in hls)
    assert any(h.date for h in hls)


def test_template_label_strips_suffix(tmp_path):
    assert P.template_label(tmp_path / "callout.md.jinja") == "callout"


def test_list_obsidian_templates_scaffolds_examples(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "templates_dir", lambda: tmp_path / "templates")
    templates = P.list_obsidian_templates()
    labels = {P.template_label(p) for p in templates}
    assert {"callout", "blockquote", "plain", "minimal"} <= labels


def test_list_obsidian_templates_includes_custom(monkeypatch, tmp_path):
    tdir = tmp_path / "templates" / "obsidian"
    tdir.mkdir(parents=True)
    (tdir / "custom.md.jinja").write_text("{{ h.text }} ^{{ h.anchor }}")
    monkeypatch.setattr(config, "templates_dir", lambda: tmp_path / "templates")
    labels = {P.template_label(p) for p in P.list_obsidian_templates()}
    assert "custom" in labels


def test_render_preview_produces_markdown(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "templates_dir", lambda: tmp_path / "templates")
    templates = P.list_obsidian_templates()
    callout = next(p for p in templates if P.template_label(p) == "callout")
    out = P.render_preview(callout)
    assert out.strip()
    assert "^" in out  # every template emits a block anchor
    assert "[!quote]" in out  # the callout template's marker
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/commands/test_config_preview.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'books.commands.config_preview'`.

- [ ] **Step 3: Implement the helpers**

Create `books/commands/config_preview.py`:

```python
"""Pure helpers for `books config export`: sample data, discovery, preview.

No TUI/prompt_toolkit here — these functions are the testable core the config
command's shell delegates to. `render_preview` reuses the real Obsidian renderer
so a preview is byte-accurate to a real export.
"""

from __future__ import annotations

from pathlib import Path

from books.core import config
from books.core.highlights import Highlight
from books.renderers.obsidian import render_highlights
from books.renderers.obsidian.templates import resolve_template, scaffold_templates

_SUFFIX = ".md.jinja"


def sample_highlights() -> list[Highlight]:
    """A small, representative highlight set that exercises every template field.

    Covers a chapter title (so chapter subheaders render), an author note, tags,
    links, a percent locator, a page locator, and dated highlights. A single
    (unset) source keeps the preview free of source headers.
    """
    return [
        Highlight(
            text="The quick brown fox jumps over the lazy dog.",
            note="A marginal note from the reader.",
            chapter_index=1,
            chapter_title="On Foxes",
            progress=0.42,
            date="2024-03-15T14:30:00Z",
            tags=["history", "nature"],
            links=["Charles Darwin"],
        ),
        Highlight(
            text="A second highlight a little later in the same chapter.",
            chapter_index=1,
            chapter_title="On Foxes",
            progress=0.58,
            page="42",
            date="2024-03-15T15:10:00Z",
        ),
        Highlight(
            text="A highlight in the next chapter, with no note or tags.",
            chapter_index=2,
            chapter_title="On Dogs",
            progress=0.10,
            date="2024-03-16T09:00:00Z",
        ),
    ]


def template_label(path: Path) -> str:
    """Human label for a template file (``callout.md.jinja`` -> ``callout``)."""
    return path.name[: -len(_SUFFIX)] if path.name.endswith(_SUFFIX) else path.stem


def list_obsidian_templates() -> list[Path]:
    """Scaffold the packaged examples, then return all ``*.md.jinja``, sorted."""
    scaffold_templates()
    obsidian_dir = config.templates_dir() / "obsidian"
    if not obsidian_dir.is_dir():
        return []
    return sorted(obsidian_dir.glob(f"*{_SUFFIX}"))


def render_preview(path: Path) -> str:
    """Render the sample highlights through the template at *path*.

    Uses ``resolve_template`` (explicit path wins) and the real
    ``render_highlights`` so the output matches a real export exactly.
    """
    template = resolve_template(str(path))
    return render_highlights(sample_highlights(), template=template)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/commands/test_config_preview.py -v`
Expected: PASS (all five tests).

- [ ] **Step 5: Commit**

```bash
git add books/commands/config_preview.py tests/commands/test_config_preview.py
git commit -m "feat(config): add preview helpers (sample data, discovery, render)"
```

---

### Task 4: The `config` command (sub-app, off-tty fallback, TUI shell)

**Files:**
- Create: `books/commands/config_cmd.py`
- Test: `tests/commands/test_config_cmd.py`

- [ ] **Step 1: Write the failing test**

Create `tests/commands/test_config_cmd.py`:

```python
"""Tests for the `books config export` command (registration + off-tty flow)."""

from typer.testing import CliRunner

from books.cli import app
from books.core import config

runner = CliRunner()


def test_config_group_registered():
    result = runner.invoke(app, ["config", "--help"])
    assert result.exit_code == 0
    assert "export" in result.output


def test_export_help():
    result = runner.invoke(app, ["config", "export", "--help"])
    assert result.exit_code == 0


def test_offtty_selection_writes_config(monkeypatch, tmp_path):
    # Point config + templates at a temp dir via XDG_CONFIG_HOME.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # CliRunner is non-tty, so the command takes the numbered fallback path.
    result = runner.invoke(app, ["config", "export"], input="blockquote\n")
    assert result.exit_code == 0
    cfg = config.load_config(config.config_path())
    assert cfg.export.obsidian.highlights_template.endswith("blockquote.md.jinja")


def test_offtty_default_selects_first(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    # Empty input -> accept the default (first template alphabetically: blockquote).
    result = runner.invoke(app, ["config", "export"], input="\n")
    assert result.exit_code == 0
    cfg = config.load_config(config.config_path())
    assert cfg.export.obsidian.highlights_template.endswith(".md.jinja")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/commands/test_config_cmd.py -v`
Expected: FAIL — `config` is not a registered command yet (help lacks `config`, exit_code != 0).

- [ ] **Step 3: Implement the command module**

Create `books/commands/config_cmd.py`:

```python
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
        "t_idx": max(labels.index(current), 0) if current in labels else 0,
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
    footer = Window(FormattedTextControl("  ↑↓ move · ↵ select · ← back · q quit"), height=1)
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
```

- [ ] **Step 4: Run test to verify it fails on registration only**

Run: `uv run pytest tests/commands/test_config_cmd.py -v`
Expected: still FAIL — the module exists but `cli.py` has not registered it yet (Task 5). The two `--help` tests fail because `config` is unknown.

- [ ] **Step 5: Commit**

```bash
git add books/commands/config_cmd.py tests/commands/test_config_cmd.py
git commit -m "feat(config): add config export command (TUI + off-tty fallback)"
```

---

### Task 5: Wire the command into the CLI

**Files:**
- Modify: `books/cli.py`
- Modify: `tests/commands/test_cli.py`

- [ ] **Step 1: Update the CLI registration test**

In `tests/commands/test_cli.py`, find `test_all_capabilities_registered` and add `config` to the tuple:

```python
def test_all_capabilities_registered():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("import", "export", "reset", "config"):
        assert command in result.output
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/commands/test_cli.py::test_all_capabilities_registered -v`
Expected: FAIL — `config` not in `--help` output.

- [ ] **Step 3: Register the module**

In `books/cli.py`, update the import block and `CAPABILITIES`:

```python
from books.commands import (
    config_cmd,
    export,
    import_cmd,
    reset,
)

# Modules that expose a register(app) function. Add new capabilities here.
CAPABILITIES = (
    config_cmd,
    export,
    import_cmd,
    reset,
)
```

- [ ] **Step 4: Run the full config + cli suites**

Run: `uv run pytest tests/commands/test_cli.py tests/commands/test_config_cmd.py -v`
Expected: PASS (registration, help, and both off-tty selection tests).

- [ ] **Step 5: Commit**

```bash
git add books/cli.py tests/commands/test_cli.py
git commit -m "feat(cli): register the config command group"
```

---

### Task 6: Manual TUI smoke check + docs

**Files:**
- Modify: `books/core/config.py` (default-file comment)
- Modify: `CLAUDE.md`

- [ ] **Step 1: Manually smoke-test the interactive TUI**

Run: `uv run books config export`
Expected: a full-screen view opens with `obsidian` under "Exporters"; Enter advances to the template list with a live markdown preview on the right that updates as you press ↑/↓; Enter on a template prints `✓ Set obsidian highlights_template to <name>.md.jinja` and exits; `q` exits with `No changes made.`. Verify `~/.config/books/config.toml` now has the key under `[export.obsidian]`.

(If not on an interactive terminal, note this step was skipped and rely on the off-tty tests.)

- [ ] **Step 2: Update the config default-file comment**

In `books/core/config.py`, the `_DEFAULT_FILE` string documents `highlights_template`. Update that comment block to mention the command. Change:

```python
"# Examples are scaffolded to ~/.config/books/templates/obsidian/ — copy one and\n"

"# point highlights_template at it, or edit it in place.\n"
```

to:

```python
"# Examples are scaffolded to ~/.config/books/templates/obsidian/ — copy one and\n"

"# point highlights_template at it, or run `books config export` to pick one\n"
"# interactively with a live preview.\n"
```

- [ ] **Step 3: Update CLAUDE.md**

In `CLAUDE.md`, in the paragraph beginning "Three commands exist today", change it to read "Four commands exist today" and add `**`config`** (interactively configure the exporter — pick a highlight template with a live preview)` to the list. Also, in the `[export.obsidian].highlights_template` configuration paragraph, append a sentence: "Run `books config export` to browse the templates with a live markdown preview and save the choice."

- [ ] **Step 4: Run the full suite + lint**

Run: `uv run ruff check --fix && uv run ruff format && uv run pytest -q`
Expected: lint clean, formatting applied, all tests pass.

- [ ] **Step 5: Commit**

```bash
git add books/core/config.py CLAUDE.md
git commit -m "docs: document books config export command"
```

---

## Self-Review Notes

- **Spec coverage:** command group + `config export` (Tasks 4-5), exporter-first flow (Task 4 `_run_tui` two screens + `FORMATS`), live side-by-side preview (Task 4 right pane + `render_preview`), built-in sample data (Task 3), save-to-config via tomlkit (Task 2), off-tty fallback (Task 4 `_select_offtty` + tests), new deps (Task 1), docs (Task 6). All covered.
- **Type consistency:** `template_label`, `render_preview`, `list_obsidian_templates`, `sample_highlights` (Task 3) are used with identical signatures in Task 4. `set_highlights_template(path, config_file=None)` (Task 2) is called as `set_highlights_template(_display_path(...))` in Task 4. `FORMATS` is a module tuple used by both key handlers and `_list_text`.
- **Note on the interactive TUI:** the full-screen `_run_tui` path is not unit-tested (prompt_toolkit needs a real terminal); it is covered by the manual smoke check (Task 6, Step 1). The pure helpers it calls and the off-tty branch are fully tested.
```
