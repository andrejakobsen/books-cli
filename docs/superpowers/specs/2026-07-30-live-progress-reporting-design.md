# Live, granular progress reporting

**Date:** 2026-07-30
**Status:** Approved (design)

## Problem

The `audible` progress bar appears stuck at `0:00:00`, and the other bars
(`calibre`, `render`) "show no progress" too.

### Root cause

`books/core/ui.py` exposes a `progress(description, total)` context manager that
yields a started rich `Progress` with one task. Every caller then calls
`prog.advance(0)`. Because rich's signature is `advance(task_id, advance=1)`,
`advance(0)` means *"advance task #0 by the default 1"* — so it **does** advance,
but only **once per top-level item, at the start of the iteration**.

- `calibre` / `render`: each item (one `metadata.opf`, one note) is fast, so the
  bar moves but carries no description of *what* it is working on — it barely
  registers and gives no context.
- `audible`: a top-level item is an **entire audiobook** — download the whole
  file, then transcribe every clip — which takes minutes. The bar freezes on one
  book the whole time, and `TimeRemainingColumn` reads `0:00:00` because it
  estimated remaining time from "1 step completed in ~0 elapsed seconds". There is
  zero feedback about download vs. transcription or which clip of how many.

The bar mechanics are fine; the granularity is wrong for long-running work.

## Goals

- Audible shows an **overall bar** (matched books) plus a **live per-book status
  line** that ticks through the download step and each clip
  (`transcribing clip 7/12`). This is the primary ask.
- `calibre` and `render` bars advance correctly per item and name what they are
  processing, so they read as live progress.
- Existing behavior and the injected-I/O test surface of `audible.run()` are
  preserved.

## Non-goals (YAGNI)

- Adding progress bars to commands that don't have one today (`merge`, `covers`,
  `goodreads`, `kobo`, `highlighted`, `readwise`).
- An inner *clip bar* for audible — the chosen display is a text status line, not
  a second bar.
- Changing the transcriber/downloader/cutter interfaces.

## Design

### 1. `books/core/ui.py` — cleaner + richer progress API

**`progress(description, total)`** keeps its contract but yields a small
`ProgressBar` handle instead of the raw rich `Progress`, hiding the task id:

```python
class ProgressBar:
    def advance(self, n: int = 1) -> None: ...   # advance the task by n
    def describe(self, text: str) -> None: ...   # update the task description
```

Determinate bars (`total is not None`) gain a `MofNCompleteColumn` so the bar
shows an `M/N` count (e.g. `2/9`) alongside the existing bar + time-remaining. As
today, the progress is disabled off-tty (tests/pipes render no frames), and the
handle's methods are safe no-ops in that case.

**New `nested_progress(description, total)`** for the audible use case, yielding a
handle:

```python
class StepProgress:
    def advance(self, n: int = 1) -> None: ...   # overall (books) bar +n
    def status(self, text: str) -> None: ...     # rewrite the per-item status line
```

Rendered as a rich `Live` wrapping a `Group` of:
1. an overall `Progress` (description + bar + `M/N` + time-remaining), and
2. a `Spinner("dots", text=...)` whose text is the current per-book status.

The `Live` drives both renderables (the `Progress` is used as a plain renderable —
its own auto-refresh is off so the outer `Live` owns the frame loop). Off-tty,
`nested_progress` yields a no-op `StepProgress`, so tests and pipes render nothing.

Rendered shape:

```
Importing audiobooks  ━━━╸━━━━━  2/9  0:01:40
⠹ The Deluge — Adam Tooze · transcribing clip 7/12
```

### 2. `books/commands/audible/command.py` — matched-only bar + per-clip status

- **Pre-pass** (local, no network): iterate the library once, resolve each book
  via `catalog.find`, and split into matched / skipped. Apply `--limit` to the
  matched list. The overall bar's `total` is the matched count.
- Drive `nested_progress("Importing audiobooks", total=len(matched))`:
  - `.status(f"{title} — {authors} · downloading")` before `downloader.download(...)`.
  - loop clips with `.status(f"{title} — {authors} · transcribing clip {i}/{n}")`
    before each `transcriber(...)` call.
  - `.advance()` after each book completes.
- Skipped books are still counted; `[skip]` and warning lines print above the live
  region via the shared console.
- `dry_run` is unchanged (plain echoed lines, no bar).
- `run()`'s public signature is unchanged, so all existing audible tests pass
  untouched. The per-book/per-clip driving happens inside `run()` against the
  `nested_progress` handle (a no-op off-tty).

### 3. `calibre.py` + `render` (`books/renderers/obsidian/note.py`)

Use the new handle: `.describe(f"Scanning {title}")` /
`.describe(f"Rendering {stem}")` at the top of each iteration and `.advance()` at
the end, replacing `prog.advance(0)`. The bar now both moves and names the current
file/book.

## Testing

- `ProgressBar.advance/describe` update the underlying task's `completed` /
  `description`.
- `nested_progress` off-tty yields a working no-op handle (methods callable, no
  output); on-tty it builds the `Live`/`Group` without error.
- Audible: assert the pre-pass sets the overall total to the matched count, and
  that a status update fires per clip and an advance fires per book (spy via an
  injected/fake handle or by asserting call counts). Existing `run()` tests remain
  green.
- Full suite (`uv run pytest -q`) stays green; `ruff check --fix` + `ruff format`
  clean.
