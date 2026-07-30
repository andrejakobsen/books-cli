# Audible interactive book selection + audiobook-only caching

**Date:** 2026-07-30
**Status:** Design approved

## Problem

The `audible` command silently skips any Audible library book that does not match
the merged catalog (`Data/books.csv`, built from calibre/goodreads). Only matched
books are transcribed and written. This means:

- You cannot transcribe an audiobook you own on Audible but have not imported from
  calibre/goodreads.
- There is no way to choose *which* books to process — it is all-matched-or-nothing.
- Unattended runs can transcribe the entire matched library with no confirmation.

## Goals

1. Let the user **check off** which Audible books to transcribe (interactive), with
   an easy "all" option.
2. Transcribe **audiobook-only** books (no calibre/goodreads match), caching them and
   writing enough to the store that a future `merge` + `render` folds them in.
3. Indicate in the picker whether each book is already **in the library** (catalog
   match) or **new** (audiobook-only).
4. Only show the OpenAI **cost estimate** when the `openai` transcriber backend is
   selected (local/google are free).
5. **Never pre-check** a book that has zero clips (it may still appear in the list,
   unchecked, so the user can consciously opt in).

Non-goals: running `merge`/`render` from the audible command (separation of phases
is preserved).

Note: to satisfy goal 5 below (never pre-check a book with zero clips) we DO fetch
each book's annotations before showing the picker — a network `annotations()` call
per library book, shown behind a progress spinner. The fetched annotations are
reused by `run()` so no book is fetched twice.

## Design

### 1. Selection picker — `books/commands/audible/select.py` (new)

A small module owning the interactive selection, keeping `questionary` out of the
rest of the code.

- `questionary` is added to the optional `[audible]` extra in `pyproject.toml` and
  imported **lazily** inside `select.py` (consistent with the existing rule that
  audible's heavy deps never load for other commands).
- A pure `candidate_label(cand) -> str` builds each row's display text:
  `"<title> — <authors>  [✓ in library] · <n> clip(s)"` when `book_id` is set, else
  `"[+ new]"`; append `" (cached)"` when a cache file already exists for the ASIN.
  This is unit-testable without `questionary`.
- `select_books(candidates) -> list[Candidate]` renders a `questionary.checkbox`
  prompt. A book starts **checked** iff it is already in the catalog **and** has at
  least one clip. Audiobook-only ("new") books and zero-clip books start
  **unchecked**. Space toggles a row, `a` toggles all, enter confirms. Returns the
  selected candidates (empty list if the user confirms with nothing selected).

`Candidate` is a lightweight dataclass carrying `(book, book_id, annotations,
cached)`; `clip_count` is `len(annotations)` and `in_library` is `book_id is not
None`. The `default`/pre-check predicate (`in_library and clip_count > 0`) is a pure
function, unit-testable without `questionary`.

### 2. CLI — `audible_command`

- Add `--all` flag: skip the picker and select every library book.
- `--asin` (existing): target exactly one book; no picker.
- Resolution order:
  1. `--asin` → that single book only.
  2. `--all` → every library book.
  3. tty, neither flag → show the picker.
  4. off-tty, neither flag → clean error (`typer.BadParameter` / non-zero exit)
     telling the user to pass `--all` or `--asin`. No surprise bulk runs.
- Thread the transcriber kind into `run` so the cost estimate can be gated.

### 3. `run()` — process unmatched books

- Build one candidate list of **all** library books (respecting `--asin`). For each,
  fetch `client.annotations(asin)` up front (behind a spinner), resolve its `book_id`
  (or `None`) via `store.Catalog.find`, and set `cached`
  (`book_cache_path(...).exists()`). Store the fetched annotations on the candidate
  so `run()` does not re-fetch.
- Apply selection: `--all` selects all; picker returns the chosen subset; off-tty
  path is gated in the CLI before `run`.
- A selected book with **zero** annotations is a no-op (nothing to transcribe); it is
  skipped without a layer row.
- For each **selected** book, download / cut / transcribe / cache exactly as today
  (respecting the per-book cache so re-runs are free).
- **Matched book** (`book_id` set): write highlights (`store.write_highlights`) and
  the audible layer row — unchanged behavior.
- **Unmatched book** (`book_id is None`): write the audible layer row only
  (`title`/`authors`/`amazon`, `format: audiobook`) so a later `merge` creates the
  catalog entry and `render` makes the note. Highlights are **not** written this run
  (no `book_id` exists yet); they land on the next audible run, when the book matches
  by ASIN and is served from cache for free. Increment a new `new` stat counter.
- The audible layer is still written once at the end (`store.write_layer`), merging
  the existing rows with rows for every processed book (matched and unmatched),
  preserving other audiobooks' rows across partial runs.

### 4. Cost estimate gated to openai

- `run` / `_run_dry` receive the transcriber kind (or a `show_cost: bool`).
- The `~$…` figure and the `@ $/sec` note render **only** when
  `transcriber == "openai"`. `local` / `google` show estimated **minutes** only.
- Dry-run continues to list **all** books with their status (`in library` / `new`)
  and new-clip counts; it never invokes the picker (it writes nothing).

### 5. Stats & final report

- Add `new` to the stats dict (audiobook-only books whose layer row was written but
  whose highlights await a future sync).
- Final message notes matched books written, `new` audiobook-only books staged for a
  future `merge`/`render`, clips, downloaded, transcribed, and failures.

## Testing

- `candidate_label`: status labels (`in library` / `new`), clip count, the
  `(cached)` suffix.
- pre-check predicate: checked iff `in_library and clip_count > 0`; new books,
  zero-clip matched books, and zero-clip new books all start unchecked.
- `build_candidates` (or equivalent): correct `book_id`/`cached`/annotations tagging,
  `--asin` filtering.
- `run()` with a fake client:
  - matched-only: highlights + layer written (unchanged).
  - unmatched-only: layer row written, **no** highlights file; `new` counted.
  - mixed selection.
  - `--all` selects everything without a picker.
  - off-tty without `--all`/`--asin` → clean error, nothing written.
- Cost estimate: present for `openai`, absent for `local`/`google`.

`questionary` itself is not exercised in tests — selection logic is tested through
the pure helpers, and `run()` is driven with an explicit selected list / `--all`.

## Migration / compatibility

- No cache format change; existing per-book `<asin>.json` caches are reused.
- Existing matched-book behavior is unchanged when `--all` is passed.
- The audible capability remains outside `sync` and is run manually after `merge`.
