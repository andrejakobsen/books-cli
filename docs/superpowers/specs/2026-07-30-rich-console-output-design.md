# Rich console output for `books`

**Date:** 2026-07-30
**Status:** Approved — ready for implementation planning

## Goal

Replace the scattered, ad-hoc console output (~35 call sites using `typer.secho`,
`typer.echo`, and bare `print()`) with a single Rich-based presentation layer so the
CLI reads as one coherent, colored, well-structured tool: report tables, panels,
progress bars for long loops, and validated interactive prompts.

## Decisions (from brainstorming)

1. **Full adoption.** A shared console module plus conversion of *all* output call
   sites, and structured output (sync report, run summaries) upgraded to Rich tables /
   panels — not just colored lines.
2. **Live progress.** Rich progress bars for long loops (calibre scan, covers fetch,
   render write, audible download/transcribe); a spinner for network / ffmpeg waits.
3. **Rich prompts.** Interactive input in `covers` and `audible` moves to
   `rich.prompt.Prompt`/`Confirm` (styled, choice-validated, re-asks on bad input).

## Architecture

### New module: `books/core/ui.py`

The single home for all CLI presentation. Lives in `core` because both `commands/` and
`renderers/` print, and the dependency direction is `commands → renderers → core`. It
carries no markdown/Obsidian knowledge — only console presentation.

Public surface:

- **`console`** — a module-level `rich.console.Console()` created with **no explicit
  `file`** argument, so its `file` property resolves `sys.stdout` dynamically at write
  time. This is what makes Typer's `CliRunner` output redirection and non-tty color
  suppression both work without extra wiring.
  - Width: when `console.is_terminal` is false (tests, pipes), the console is
    configured with a **generous fixed width (200)** so Rich does not wrap lines and
    break existing substring assertions. When attached to a real terminal, width is
    auto-detected.
- **`err_console`** — a second `Console(stderr=True)` for warnings/errors, keeping
  stdout clean. Replaces the current `err=True` echoes.
- **Semantic helpers** (call sites never hand-write Rich markup):
  - `info(msg)` — plain line to stdout.
  - `success(msg)` — green `✓` prefix, stdout.
  - `warn(msg)` — yellow `⊘` prefix, stderr.
  - `error(msg)` — red `✗` prefix, stderr.
  - `dim(msg)` — dimmed line.
  - `summary_table(title, subtitle=None) -> rich.table.Table` — pre-styled `Table`
    factory (glyph / label / result columns) for report tables.
  - `panel(body, title=None, style="blue") -> rich.panel.Panel` — pre-styled panel.
  - `progress(description, total=None)` — context manager yielding a Rich `Progress`.
    `total=None` → spinner; a number → determinate bar. The progress is created with
    `disable=not console.is_terminal` so tests and pipes render no live frames.
  - `prompt_choice(question, choices, default) -> str` — wrapper over
    `rich.prompt.Prompt.ask(..., choices=..., default=...)` bound to `console`.
  - `confirm(question, default=False) -> bool` — wrapper over `Confirm.ask`.

### Testing seam

- **Output.** `CliRunner` swaps `sys.stdout`; because `console` has no bound `file` it
  follows that swap automatically. Non-tty width is generous, so existing substring
  assertions (`"2 highlights"`, `"0 books"`, `"missing"`, `"books.csv"`, `"1 skipped"`,
  etc.) remain valid.
- **Input.** Rich prompts read from `console`, not `sys.stdin`, so the covers input-feed
  tests need a shim. Add `set_streams(stdin=None)` (or a `stream=` parameter on the
  prompt wrappers) that repoints Rich's read stream at the runner's stdin for the
  duration of a test. The prompt wrappers accept an optional `stream` so this is
  injectable without global mutation where practical.
- **Progress.** Disabled in non-tty, so no live-frame output pollutes captured stdout.

## Call-site conversion (all ~35 sites)

- **`books/commands/sync.py`** — the per-step report (`_step_*` / summary helpers,
  lines ~270–306) becomes a `summary_table`: `✓`/`⊘`/`✗` glyph column, cyan step name,
  result text. The footer tally (`N ok · N skipped · N failed`) uses the semantic
  helpers. `--dry-run` plan renders via the same table.
- **`books/commands/covers/command.py`** — candidate display (`_terminal_prompt`,
  lines ~85–90) → `panel`; approval → `prompt_choice(["y","n","s","q"], default="y")`;
  per-book results (`✓`, `no cover`, `[dry-run]`, `Quit.`) → `success`/`warn`/`dim`;
  the final run summary (lines ~244–254) → a `summary_table`.
- **`books/commands/calibre.py`** — the per-book scan loop wrapped in
  `progress(total=len(books))`; `WARN: could not parse …` (line ~226) → `warn(...)`;
  final summary (line ~289) → `info`.
- **`books/commands/render.py`** — the per-book render loop wrapped in a `progress`
  bar; final summary (line ~69) → `info`.
- **`books/renderers/obsidian/note.py`** — the corrupt-note line (line ~220,
  `typer.secho(... YELLOW)`) → `warn(...)` imported from `books.core.ui`
  (renderer → core is allowed).
- **`books/commands/audible/command.py`** — download/transcribe loop → `progress`
  (spinner during network / ffmpeg); the injected `echo=typer.echo` sink (line ~427)
  switches to the ui helpers; summaries (lines ~432, ~442) → `info`/`success`.
- **`books/commands/goodreads.py`** (line ~209), **`merge.py`** (line ~38),
  **`kobo.py`** (lines ~248–255), **`readwise.py`** (line ~158),
  **`highlighted.py`** (lines ~145–155) — one-line summaries → `info`/`success`;
  `highlighted`'s stderr skip line (line ~145, `err=True`) → `warn`.

## Dependency

Add `rich>=13` as an explicit entry in `[project].dependencies` in `pyproject.toml`
(currently only present transitively via Typer). Keep the rest of the lean-deps policy
unchanged.

## Out of scope

- No change to Typer's own help / usage / error rendering.
- No Rich markup written into notes or CSV data — presentation only.
- No reflow of the highlight / markdown renderers; the `out`-string assertions in
  `tests/renderers/` are file content and are untouched.
- No new configuration knobs (no `--no-color` flag) in this pass; Rich already respects
  `NO_COLOR` / non-tty automatically.

## Success criteria

- `uv run pytest -q` passes with no changes to existing command-output assertions.
- `uv run ruff check` and `uv run ruff format` are clean.
- Every former `typer.secho` / `typer.echo` / `print()` in `books/` routes through
  `books/core/ui.py`.
- `sync`, `covers`, and the long-loop commands show tables / panels / progress when run
  in a real terminal, and produce clean, assertion-compatible plain output when piped.
