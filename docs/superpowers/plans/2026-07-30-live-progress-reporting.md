# Live Progress Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `audible` an overall (matched-books) progress bar plus a live per-book status line that ticks through download and each clip transcription, and make the `calibre`/`render` bars advance correctly and name what they're processing.

**Architecture:** Add a `ProgressBar` handle (hides the rich task id) to `books/core/ui.py` and a `nested_progress` context manager that renders a rich `Live` wrapping a `Group(overall Progress bar, Spinner)`. Callers use the handle's `advance()`/`describe()` instead of the confusing `prog.advance(0)`. `audible.run()` does a local pre-pass to count matched books (the bar total), then drives per-book/per-clip status through the nested handle.

**Tech Stack:** Python 3.11+, `rich` (Progress/Live/Group/Spinner), `typer`, `pytest`, `ruff`.

---

## File Structure

- `books/core/ui.py` — **Modify.** Add `ProgressBar`, refactor `progress()` to yield it (+ `MofNCompleteColumn`), add `StepProgress`/`_NoopStep` and `nested_progress()`.
- `books/commands/audible/command.py` — **Modify.** Split `run()` into a dry-run helper + a real-run path with a matched-books pre-pass and per-clip status via `nested_progress`.
- `books/commands/calibre.py` — **Modify.** Use the `ProgressBar` handle (`describe`/`advance`).
- `books/renderers/obsidian/note.py` — **Modify.** Use the `ProgressBar` handle in `render()`.
- `tests/core/test_ui.py` — **Create.** Unit tests for `ProgressBar` and the no-op step.
- `tests/commands/test_audible_obsidian.py` — **Modify.** Add a per-clip progress test.

---

## Task 1: `ProgressBar` handle + richer `progress()`

**Files:**
- Modify: `books/core/ui.py`
- Test: `tests/core/test_ui.py`

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_ui.py`:

```python
from rich.progress import Progress

from books.core.ui import ProgressBar


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_ui.py::test_progressbar_advance_and_describe -v`
Expected: FAIL with `ImportError: cannot import name 'ProgressBar'`.

- [ ] **Step 3: Add `ProgressBar` and use it in `progress()`**

In `books/core/ui.py`, add `MofNCompleteColumn` to the existing rich import:

```python
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
)
```

Add the handle class above the `progress` function:

```python
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
```

Replace the body of `progress()` so a determinate bar gets a count column and it
yields a `ProgressBar`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_ui.py::test_progressbar_advance_and_describe -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add books/core/ui.py tests/core/test_ui.py
git commit -m "feat(ui): ProgressBar handle + M/N count column"
```

---

## Task 2: `nested_progress` (overall bar + live status line)

**Files:**
- Modify: `books/core/ui.py`
- Test: `tests/core/test_ui.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/core/test_ui.py`:

```python
from books.core import ui


def test_nested_progress_offtty_is_noop():
    # In the pytest process the console is not a terminal, so nested_progress
    # yields a no-op handle whose methods are safely callable.
    with ui.nested_progress("Importing", total=2) as prog:
        prog.status("Book A - downloading")
        prog.advance()
        prog.advance(1)
    # no exception, nothing rendered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/core/test_ui.py::test_nested_progress_offtty_is_noop -v`
Expected: FAIL with `AttributeError: module 'books.core.ui' has no attribute 'nested_progress'`.

- [ ] **Step 3: Implement `StepProgress`, `_NoopStep`, `nested_progress`**

In `books/core/ui.py` add these imports near the top:

```python
from rich.console import Group
from rich.live import Live
from rich.spinner import Spinner
```

Add the classes and context manager (place after `progress()`):

```python
class StepProgress:
    """Handle for a nested display: an overall bar + a live status line."""

    def __init__(self, prog: Progress, task_id, spinner: Spinner) -> None:
        self._prog = prog
        self._task = task_id
        self._spinner = spinner

    def advance(self, n: int = 1) -> None:
        """Advance the overall (outer) bar by *n*."""
        self._prog.advance(self._task, n)

    def status(self, text: str) -> None:
        """Rewrite the per-item status line."""
        self._spinner.update(text=text)


class _NoopStep:
    """No-op stand-in used off-tty so callers need no branching."""

    def advance(self, n: int = 1) -> None:
        pass

    def status(self, text: str) -> None:
        pass


@contextmanager
def nested_progress(description: str, total: int | None):
    """Yield a :class:`StepProgress`: an overall bar plus a live status line.

    Off-tty (tests/pipes) a :class:`_NoopStep` is yielded and nothing renders.
    """
    if not console.is_terminal:
        yield _NoopStep()
        return
    overall = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
        auto_refresh=False,
    )
    task = overall.add_task(description, total=total)
    spinner = Spinner("dots", text="")
    with Live(Group(overall, spinner), console=console, refresh_per_second=12):
        yield StepProgress(overall, task, spinner)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/core/test_ui.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add books/core/ui.py tests/core/test_ui.py
git commit -m "feat(ui): nested_progress (overall bar + live status line)"
```

---

## Task 3: Use the handle in `calibre` and `render`

**Files:**
- Modify: `books/commands/calibre.py:220-222`
- Modify: `books/renderers/obsidian/note.py:211-213`
- Test: `tests/commands/test_calibre.py`, `tests/commands/test_render.py` (existing, must stay green)

- [ ] **Step 1: Update calibre's loop**

In `books/commands/calibre.py`, replace:

```python
    with ui.progress("Scanning Calibre library", total=len(opf_paths)) as prog:
        for opf_path in opf_paths:
            prog.advance(0)
            rel_parts = opf_path.relative_to(library).parts
```

with:

```python
    with ui.progress("Scanning Calibre library", total=len(opf_paths)) as prog:
        for opf_path in opf_paths:
            prog.describe(f"Scanning {opf_path.parent.name}")
            rel_parts = opf_path.relative_to(library).parts
```

and add `prog.advance()` as the **last statement inside the `for` loop body** (after
`stats["authors"].update(meta.authors)` on line ~244), at the same indentation as
the other loop-body statements:

```python
            rows.append(_to_row(meta, cover_rel))
            stats["books"] += 1
            stats["authors"].update(meta.authors)
            prog.advance()
```

Note: the `continue` branches above still advance because... they do NOT — so also
add `prog.advance()` immediately before each `continue` in that loop. There are
three: after the `ET.ParseError` warn (`stats["skipped"] += 1; continue`), after the
empty-title `stats["skipped"] += 1; continue`. Update both to:

```python
                stats["skipped"] += 1
                prog.advance()
                continue
```

- [ ] **Step 2: Update render's loop**

In `books/renderers/obsidian/note.py`, replace:

```python
    with ui.progress("Rendering notes", total=len(rows)) as prog:
        for row in rows:
            prog.advance(0)
            if not row.book_id:
                continue
```

with:

```python
    with ui.progress("Rendering notes", total=len(rows)) as prog:
        for row in rows:
            prog.describe(f"Rendering {row.book_id or row.title}")
            if not row.book_id:
                prog.advance()
                continue
```

and add `prog.advance()` as the last statement of the `for` loop body (after the
`for author in row.authors:` block completes). The `except ... continue` branch and
the normal path both need it, so put a single `prog.advance()` at the end of the
loop body — but the `except: continue` returns early, so also add `prog.advance()`
right before that `continue`:

```python
            except Exception as exc:  # continue-on-error per book
                stats["failed"] += 1
                ui.warn(f"{row.book_id}: {exc}")
                prog.advance()
                continue
            stats["notes"] += 1
            stats["highlights"] += len(highlights)
            if compose_review(row.review, row.private_notes):
                stats["reviews"] += 1
            for author in row.authors:
                if author and author not in seen_authors:
                    write_stub(authors_dir, author, "author")
                    seen_authors.add(author)
            prog.advance()
```

- [ ] **Step 3: Run the affected suites**

Run: `uv run pytest tests/commands/test_calibre.py tests/commands/test_render.py -q`
Expected: PASS (behavior unchanged; progress is disabled off-tty).

- [ ] **Step 4: Commit**

```bash
git add books/commands/calibre.py books/renderers/obsidian/note.py
git commit -m "refactor(progress): calibre/render advance per item + describe current book"
```

---

## Task 4: Audible — matched-books bar + per-clip status

**Files:**
- Modify: `books/commands/audible/command.py:192-313`
- Test: `tests/commands/test_audible_obsidian.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/commands/test_audible_obsidian.py` (near the other `run` tests):

```python
class RecordingStep:
    def __init__(self):
        self.statuses = []
        self.advances = 0
        self.total = None

    def status(self, text):
        self.statuses.append(text)

    def advance(self, n=1):
        self.advances += n


def test_run_reports_per_clip_progress(monkeypatch, tmp_path):
    from contextlib import contextmanager

    out, book, anns = _catalog_and_library(tmp_path)
    rec = RecordingStep()

    @contextmanager
    def fake_nested(description, total):
        rec.total = total
        yield rec

    monkeypatch.setattr(ao.ui, "nested_progress", fake_nested)

    ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=FakeDownloader(),
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_path=out / "c.json",
        clip_window=30,
    )

    assert rec.total == 1  # one matched book
    assert rec.advances == 1  # advanced once for the book
    assert any("downloading" in s for s in rec.statuses)
    assert any("transcribing clip 1/1" in s for s in rec.statuses)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/commands/test_audible_obsidian.py::test_run_reports_per_clip_progress -v`
Expected: FAIL (no `downloading`/`transcribing clip 1/1` statuses recorded — the old
`run()` never calls `nested_progress`).

- [ ] **Step 3: Restructure `run()`**

In `books/commands/audible/command.py`, replace the whole `run(...)` function body
(lines ~192-313, from `def run(` through `return stats`) with:

```python
def run(
    vault,
    *,
    client,
    downloader,
    cutter,
    transcriber,
    cache_path,
    clip_window,
    limit=None,
    asin=None,
    dry_run=False,
    echo=lambda *_: None,
) -> dict:
    """Import Audible clips into the CSV store. All heavy I/O is injected.

    Resolves each library book to a book_id via the merged catalog
    (Data/books.csv); an unmatched book is skipped and counted. For a matched book
    with transcribed clips, writes per-book highlights (source ``audible``) and an
    ``audible`` metadata layer row (``format: audiobook``). ``merge`` + ``render``
    later surface them. In *dry_run* mode nothing is written.
    """
    vault.mkdir(parents=True, exist_ok=True)
    catalog = store.Catalog(vault)
    cache = load_cache(cache_path)
    stats = {
        "books": 0,
        "entries": 0,
        "skipped": 0,
        "downloaded": 0,
        "transcribed": 0,
        "failed": 0,
        "est_seconds": 0.0,
    }

    library = client.library()
    if asin:
        library = [b for b in library if b.asin == asin]

    if dry_run:
        return _run_dry(library, catalog, cache, stats, client, clip_window, limit, echo)

    # Preserve other audiobooks' layer rows across partial (--asin/--limit) runs.
    layer = {r.amazon: r for r in store.read_layer(vault, "audible") if r.amazon}

    # Pre-pass: resolve matches locally (no network) so the bar counts matched books.
    matched: list = []
    for book in library:
        ref = BookRef(title=book.title, authors=book.authors, amazon=book.asin)
        book_id = catalog.find(ref)
        if book_id is None:
            stats["skipped"] += 1
            continue
        matched.append((book, book_id))
    if limit is not None:
        matched = matched[:limit]

    with ui.nested_progress("Importing audiobooks", total=len(matched)) as prog:
        for book, book_id in matched:
            authors = ", ".join(book.authors) or "?"
            # Isolate each book: a single failure (an unpublished/undownloadable
            # title, a license/voucher error, a network hiccup, a bad transcribe)
            # is counted and skipped so it never aborts the whole run.
            try:
                prog.status(f"{book.title} — {authors}")
                annotations = client.annotations(book.asin)
                if not annotations:
                    continue

                book_cache = cache.setdefault(book.asin, {"title": book.title, "clips": {}})
                clips = book_cache.setdefault("clips", {})
                new = uncached(annotations, clips)

                if new:
                    chapters = client.chapters(book.asin)
                    with tempfile.TemporaryDirectory() as td:
                        tmp = Path(td)
                        prog.status(f"{book.title} — {authors} · downloading")
                        audio = downloader.download(book.asin, tmp)
                        stats["downloaded"] += 1
                        for i, ann in enumerate(new, start=1):
                            prog.status(
                                f"{book.title} — {authors} · transcribing clip {i}/{len(new)}"
                            )
                            start, end = _clip_bounds(ann, clip_window)
                            clip_path = cutter.cut(audio, start, end, tmp / f"{ann.id}.wav")
                            text = transcriber(clip_path)
                            clips[ann.id] = annotation_to_record(ann, text, chapters)
                            stats["transcribed"] += 1
                    save_cache(cache_path, cache)

                rows = book_highlight_rows(clips)
                if not rows:
                    continue
                store.write_highlights(vault, book_id, "audible", rows)
                layer[book.asin] = store.BookRow(
                    title=book.title,
                    authors=list(book.authors),
                    amazon=book.asin,
                    format="audiobook",
                )
                stats["books"] += 1
                stats["entries"] += len(rows)
            except Exception as exc:  # noqa: BLE001 — continue-on-error per book
                stats["failed"] += 1
                echo(f"[skip] {book.title} [asin {book.asin}]: {exc}")
            finally:
                prog.advance()

    store.write_layer(vault, "audible", list(layer.values()))
    return stats


def _run_dry(library, catalog, cache, stats, client, clip_window, limit, echo) -> dict:
    """Dry-run path: log matches + estimated transcription, write nothing."""
    matched = 0
    for book in library:
        ref = BookRef(title=book.title, authors=book.authors, amazon=book.asin)
        book_id = catalog.find(ref)
        if book_id is None:
            stats["skipped"] += 1
            authors = ", ".join(book.authors) or "?"
            anns = client.annotations(book.asin)
            secs = _clip_seconds(anns, clip_window)
            stats["est_seconds"] += secs
            echo(
                f"[dry-run] SKIP (no book): {book.title} — {authors} "
                f"[asin {book.asin}] — {len(anns)} clip(s), "
                f"~{secs / 60:.1f} min, ~${secs * COST_PER_SECOND:.2f}"
            )
            continue
        if limit is not None and matched >= limit:
            break
        matched += 1
        annotations = client.annotations(book.asin)
        if not annotations:
            continue
        book_cache = cache.setdefault(book.asin, {"title": book.title, "clips": {}})
        clips = book_cache.setdefault("clips", {})
        new = uncached(annotations, clips)
        secs = _clip_seconds(new, clip_window)
        stats["est_seconds"] += secs
        echo(
            f"[dry-run] {book.title}: {len(annotations)} annotations, "
            f"{len(new)} new to transcribe — ~{secs / 60:.1f} min, "
            f"~${secs * COST_PER_SECOND:.2f}"
        )
    return stats
```

- [ ] **Step 4: Run the new test and the full audible suite**

Run: `uv run pytest tests/commands/test_audible_obsidian.py -q`
Expected: PASS (new `test_run_reports_per_clip_progress` plus all existing tests).

- [ ] **Step 5: Commit**

```bash
git add books/commands/audible/command.py tests/commands/test_audible_obsidian.py
git commit -m "feat(audible): matched-books bar + live per-clip status"
```

---

## Task 5: Full verification + lint

**Files:** none (verification only)

- [ ] **Step 1: Lint & format**

Run: `uv run ruff check --fix && uv run ruff format`
Expected: no remaining errors.

- [ ] **Step 2: Full test suite**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 3: Manual smoke (optional, needs a real vault + Audible)**

Run: `uv run books audible --limit 1`
Expected: an "Importing audiobooks" bar showing `1/1` and a status line cycling
through `… · downloading` then `… · transcribing clip i/n`.

- [ ] **Step 4: Commit any lint/format fixups**

```bash
git add -A
git commit -m "chore: lint/format for progress reporting" || echo "nothing to commit"
```

---

## Self-Review

- **Spec coverage:**
  - Spec §1 (ui API: `ProgressBar` + `M/N` column; `nested_progress` + no-op off-tty) → Tasks 1 & 2.
  - Spec §2 (audible matched-only total, per-book/per-clip status, dry-run unchanged, `run()` signature unchanged) → Task 4.
  - Spec §3 (calibre/render describe + advance) → Task 3.
  - Spec Testing (handle unit tests, off-tty no-op, per-clip spy, suite green) → Tasks 1, 2, 4, 5.
- **Placeholder scan:** none — every code step shows full code.
- **Type consistency:** `ProgressBar(prog, task_id)` with `.advance(n=1)`/`.describe(text)`; `StepProgress(prog, task_id, spinner)` and `_NoopStep` both expose `.advance(n=1)`/`.status(text)`; `nested_progress(description, total)` yields one of them; `run()` keeps its exact existing signature and `_run_dry(library, catalog, cache, stats, client, clip_window, limit, echo)` mirrors the prior dry-run behavior.
