# `books config` command — design

## Goal

Add a `books config` command group. Its first subcommand, `books config export`,
is an interactive TUI for configuring how the store is exported to notes. It lets
the user browse the available highlight callout templates with a **live
side-by-side preview** of the rendered markdown, then saves the chosen template
into the config file. The flow is exporter-first so it extends cleanly to future
renderers.

## User-facing behaviour

`books config export` opens a full-screen prompt_toolkit application:

1. **Screen 1 — pick an exporter/format.** A list of output formats to configure.
   Today it holds a single row, `obsidian`; the list is data-driven so a future
   renderer just adds a row. Selecting a format advances to that format's config
   screen.
2. **Screen 2 — pick a template (obsidian).** A two-pane view:
   - Left: the names of the discovered `*.md.jinja` templates in
     `~/.config/books/templates/obsidian/` (the five scaffolded examples plus any
     custom ones the user added). The currently-configured template is
     pre-highlighted.
   - Right: the **live rendered markdown** for the highlighted template — literally
     the markdown that would land in a note — updating as the selection moves.

Keys: `↑`/`↓` move, `Enter` select, `←`/`Esc` go back (Screen 2 → Screen 1),
`q` quit without saving.

On `Enter` in Screen 2 the chosen template's path (with a `~` prefix, e.g.
`~/.config/books/templates/obsidian/blockquote.md.jinja`) is written into
`[export.obsidian].highlights_template` in `config.toml`, and a confirmation is
printed via `ui.success`. Cancelling writes nothing.

**Off-tty** (tests, pipes, no terminal): the full-screen app is skipped. The
command falls back to `ui.prompt_choice` numbered lists — first for the format
(auto-selected when only one exists), then for the template — and still writes the
selection on choice.

## Architecture

New capability module `books/commands/config_cmd.py` exposing `register(app)`,
added to `CAPABILITIES` in `books/cli.py`. It builds a `config` Typer sub-app and
attaches it via `app.add_typer(config_app, name="config")`, giving
`books config <subcommand>`. First subcommand: `export`.

The command is split so the TUI shell is thin and everything testable is pure:

- **`books/commands/config_cmd.py`** — the Typer wiring + the prompt_toolkit
  Application shell (`export` command). Handles tty detection and the off-tty
  fallback. Delegates all data/rendering to the pure helpers below.
- **Sample data + preview rendering** live next to the command (e.g. a
  `preview.py` sibling, or in `config_cmd.py` if small):
  - `sample_highlights() -> list[Highlight]` — a small, hand-crafted set that
    exercises every template feature: a chapter title, an author note, `#tags`,
    `@links`, a page/percent locator, and a dated highlight. Baked in, so the
    preview works on a fresh vault with an empty store.
  - `list_obsidian_templates() -> list[Path]` — runs `scaffold_templates()` first,
    then discovers `*.md.jinja` in `config.templates_dir()/"obsidian"`, sorted.
  - `render_preview(template_path: Path) -> str` — compiles the template file and
    calls `render_highlights(sample_highlights(), template=<compiled>)`, so the
    preview reuses the real renderer and is byte-accurate (chapter headers,
    callouts, date line included).

## Config writing

`config.toml` is comment-rich and may be hand-edited, so writes must preserve
comments and unrelated keys. Add **`tomlkit`** (lightweight, pure-Python) as a
core dependency and a new helper in `books/core/config.py`:

- `set_highlights_template(path: str, config_file: Path | None = None) -> None` —
  round-trips `config.toml` with tomlkit, ensures the `[export]` and
  `[export.obsidian]` tables exist, sets `highlights_template = <path>`, and writes
  the file back. Creates the file from defaults first if absent (reusing
  `load_config`'s auto-create path).

## Dependencies

Add to core `dependencies` in `pyproject.toml`:

- `prompt_toolkit` — the TUI engine (used directly, not via questionary).
- `tomlkit` — comment-preserving TOML writes.

`questionary` and the audible capability are untouched (questionary stays in the
optional `[audible]` extra).

## Testing

Pure units, tested directly:

- `sample_highlights()` — returns highlights covering every feature.
- `list_obsidian_templates()` — scaffolds then lists the five examples (plus a
  custom one dropped into a temp templates dir).
- `render_preview(path)` — for each packaged template, produces non-empty markdown
  and matches what `render_highlights` yields for the same template.
- `set_highlights_template(path)` — round-trips a temp `config.toml`: the key is
  set under `[export.obsidian]`, and pre-existing comments/keys survive; a
  subsequent `load_config` reads the value back.

The prompt_toolkit Application is a thin shell: tested only for the off-tty
fallback (numbered selection writes the config) and that it wires the pure
functions. The interactive full-screen path itself is not unit-tested.

## Docs

Update `CLAUDE.md` (add `config` to the command list + the `[export.obsidian]`
section) and the config-defaults docs as needed.
