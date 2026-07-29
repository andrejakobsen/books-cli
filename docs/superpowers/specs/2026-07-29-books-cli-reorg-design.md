# books CLI reorganization — design

**Date:** 2026-07-29
**Status:** Approved
**Goal:** Reorganize the flat `books/` package into a modular, maintainable, renderer-aware
layout following common Python CLI best practices, and delete the redundant `scripts/`
shim folder. No behavior changes — the `books` CLI and every command keep working
identically; the test suite stays green.

## Motivation

The package is currently a flat pile of ~17 top-level modules in `books/`, with
capability files named inconsistently (`calibre_obsidian.py`, `kobo_export.py`,
`render_obsidian.py`) alongside shared modules (`obsidian.py`, `highlights.py`,
`store.py`, `config.py`). Two modules have grown oversized (`obsidian.py` 623 lines,
`covers.py` 742 lines). A parallel `scripts/` folder holds 12-line shims that duplicate
what the installed `books <command>` CLI already does.

A second driver: **Obsidian is currently the center of gravity, but it should be one
renderer among future ones.** The newer CSV-store architecture (`store.py`) is a
format-agnostic data layer; the `render` command turns that store into Obsidian notes.
The layout should make "add another renderer" a sibling package, not a rewrite.

## Target structure

```
books/
├── __init__.py                 # package marker only
├── __main__.py                 # `python -m books` → cli.main()
├── cli.py                      # Typer hub + CAPABILITIES registry (unchanged role)
├── core/                       # format-AGNOSTIC — no Obsidian/markdown knowledge
│   ├── __init__.py
│   ├── paths.py                # resolve_path (moved out of books/__init__.py)
│   ├── config.py               # unchanged logic
│   ├── store.py                # CSV catalog + per-book highlights (canonical data model)
│   └── highlights.py           # Highlight dataclass, marker parsing (#tag/@link),
│                               #   split_tag_column, sort_key — DATA + parsing half only
├── renderers/                  # output targets — add new ones beside obsidian/
│   ├── __init__.py             # room for a Renderer protocol later
│   └── obsidian/               # renderer #1: everything Obsidian/markdown-specific
│       ├── __init__.py         # re-exports the public API (stable import surface)
│       ├── layout.py           # folder constants, cover_path/cover_refs, flat filenames
│       ├── frontmatter.py      # BOOK_PROPERTY_ORDER, update_frontmatter, yaml_quote, readers
│       ├── sections.py         # render_marked_section, ensure_section
│       ├── matching.py         # norm_title, norm_isbn, author_key, fold
│       ├── format.py           # wikilink, link_list, html_to_markdown
│       ├── highlights.py       # render_highlights → [!quote] callouts, chapter headers
│       └── vault_index.py      # VaultIndex, BookNote
└── commands/                   # CLI capabilities, each exposing register(app)
    ├── __init__.py
    ├── calibre.py              # was calibre_obsidian.py
    ├── goodreads.py            # was goodreads_obsidian.py
    ├── kobo.py                 # was kobo_export.py
    ├── highlighted.py          # was highlighted_obsidian.py
    ├── readwise.py             # was readwise_obsidian.py
    ├── render.py               # was render_obsidian.py — store → obsidian renderer (the seam)
    ├── sync.py                 # orchestrator
    ├── covers/                 # split of covers.py (742 lines)
    │   ├── __init__.py         # register(app) + command entrypoint
    │   ├── command.py          # scan/select/write orchestration
    │   ├── sources.py          # apple, google, open library, amazon lookups
    │   └── images.py           # image_dimensions, validation, fetch_with_retry, normalize_author
    └── audible/                # groups the 3 audible files
        ├── __init__.py         # register(app)
        ├── command.py          # was audible_obsidian.py (register + convert)
        ├── models.py           # Annotation, Chapter, DownloadedAudio, LibraryBook dataclasses
        ├── client.py           # was audible_client.py
        └── transcribe.py       # was audible_transcribe.py
```

`scripts/` is **deleted entirely.** The standalone-run ability it provided is dropped;
`books <command>` covers every case.

## Design decisions

### Three top-level groupings encode the layering
- **`core/`** — format-agnostic building blocks. Depends on nothing else in the package
  (except itself). Holds the data model (`store`), config, path handling, and the
  highlight *data + marker parsing*.
- **`renderers/`** — output targets. `renderers/obsidian/` owns 100% of the
  Obsidian/markdown-specific code. A future `renderers/web/` or `renderers/json/` slots
  in beside it. Renderers may depend on `core/`, never on `commands/`.
- **`commands/`** — CLI capabilities. May depend on `core/` and `renderers/`. `sync` and
  `render` import sibling command functions directly (intra-`commands/`), which is fine.

The dependency direction is one-way: `commands → renderers → core`.

### `obsidian.py` split into `renderers/obsidian/` package
The 623-line module splits by responsibility into `layout`, `frontmatter`, `sections`,
`matching`, `format`, `highlights` (rendering), and `vault_index`. The package
`__init__.py` re-exports the current public API so existing call sites migrate with a
single path change (`from books.obsidian import X` → `from books.renderers.obsidian
import X`) rather than per-symbol churn. The split is internal.

### `covers.py` split into `commands/covers/` package
The 742-line module splits into `command` (orchestration + `register`), `sources`
(the per-provider lookups: Apple/Google/Open Library/Amazon), and `images` (dimension
parsing, validation, retry/backoff, author/title normalization). The package
`__init__.py` exposes `register(app)`.

### `audible/` grouped as a subpackage
The three existing files become `commands/audible/{command,client,transcribe}.py`, with
the shared dataclasses (`Annotation`, `Chapter`, `DownloadedAudio`, `LibraryBook`)
extracted into `models.py` so `client.py` and `transcribe.py` import models rather than
the command module. The optional `[audible]` deps stay lazily imported inside these
files. `__init__.py` exposes `register(app)`.

### Highlight rendering moves to the renderer
`core/highlights.py` keeps the format-agnostic pieces: the `Highlight` dataclass, marker
parsing (`parse_markers`, `split_tag_column`), and `sort_key`/reading-order logic.
`render_highlights` (which emits Obsidian `[!quote]` callouts, wikilinks, and chapter
subheaders) moves to `renderers/obsidian/highlights.py`. This makes the renderer boundary
real: a future renderer reuses the model + parsing and writes its own output.

### Clean command module names
The `_obsidian` / `_export` suffixes are dropped throughout `commands/`.

### `resolve_path` moves to `core/paths.py`
`books/__init__.py` becomes an empty package marker. All importers update to
`from books.core.paths import resolve_path`.

### `cli.py` and the registry
`cli.py` stays the hub. Its `CAPABILITIES` tuple now imports from `books.commands.*`.
Registration stays explicit (add a module to the tuple to add a command). A new
`books/__main__.py` enables `python -m books`.

## Scope boundaries (out of scope)

- **No data-flow rewrite.** The importers (`calibre`, `goodreads`, `kobo`, `highlighted`,
  `readwise`, `audible`) still write Obsidian notes directly via `VaultIndex`; they stay
  Obsidian-coupled and live in `commands/` importing `renderers/obsidian/`. Routing them
  through the store into any renderer is a separate future project.
- **No `--renderer` flag yet.** `render.py` still targets Obsidian; the structure just
  leaves the seam so a flag can be added later without moving files.
- **No logic changes.** Every move preserves behavior. Any function body edits are limited
  to import-path updates.

## Tests

Tests reorganize to mirror the package:

```
tests/
├── core/          # test_config.py, test_store.py, test_highlights.py, test_paths.py
├── renderers/
│   └── obsidian/  # test_obsidian.py (+ compose-layout), test_highlights_render.py
└── commands/      # test_calibre.py, test_goodreads.py, test_kobo.py, test_highlighted.py,
                   #   test_readwise.py, test_render.py, test_sync.py,
                   #   test_covers.py, test_audible_*.py, test_cli.py
```

Test files are renamed to match new module names and their imports updated. The existing
1:1 mirror discipline is preserved against the new layout. `uv run pytest -q` must pass
at the end.

## Migration approach

- Use `git mv` to preserve history where a file moves whole; split files with `git mv`
  then extract into new siblings.
- Update `pyproject.toml`: `[tool.hatch.build.targets.wheel]` still packages `["books"]`
  (subpackages are included automatically); `[project.scripts]` `books = "books.cli:main"`
  is unchanged.
- Migrate in dependency order (core first, then renderers, then commands) so the suite can
  be run at each step to catch breakage early.
- Keep the `books --help` command list and behavior identical.

## Success criteria

- `scripts/` is gone.
- `books/` follows the `core/ · renderers/ · commands/` layout above.
- `obsidian.py` and `covers.py` are split into focused modules; no module is
  gratuitously large.
- Adding a new renderer is visibly a matter of adding `renderers/<name>/`.
- `uv run pytest -q` passes; `books --help` and every subcommand behave as before.
