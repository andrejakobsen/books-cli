# books CLI Reorganization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the flat `books/` package into a modular `core/ · renderers/ · commands/` layout, split the two oversized modules (`obsidian.py`, `covers.py`), delete the redundant `scripts/` folder — with zero behavior change.

**Architecture:** One-way dependency direction `commands → renderers → core`. `core/` is format-agnostic (paths, config, CSV store, highlight model + marker parsing). `renderers/obsidian/` owns all Obsidian/markdown-specific code. `commands/` holds the CLI capabilities, each exposing `register(app)`. `cli.py` stays the Typer hub.

**Tech Stack:** Python 3.11+, Typer, pydantic, python-frontmatter, ruamel.yaml; `uv` for env/test; `pytest`.

---

## Conventions for this plan (read first)

This is a **behavior-preserving refactor**, not new feature work. The existing test suite (`uv run pytest -q`, currently green) IS the safety net — there is no new "write a failing test" cycle. Each task's discipline is:

1. Move / split code **verbatim** — cut function and class bodies unchanged. Do **not** rewrite logic. The only edits to a moved symbol are its own `import` lines.
2. Update every reference across **both** `books/` and `tests/` in the same task (grep the whole repo).
3. Run the full suite + `books --help`; both must be green before committing.

**Verbatim-cut instruction:** where a step says "move symbols X, Y, Z to `dest.py`", copy those definitions exactly as they appear in the source file (same order, same bodies, same docstrings/comments), then delete them from the source. Add only the `import` header shown for the destination file.

**Global verification (run after every task):**

```bash
uv run pytest -q
uv run books --help
```
Expected: all tests pass; `--help` lists `calibre goodreads highlighted kobo readwise render sync covers audible`.

---

## Task 1: Scaffold the new package tree, delete `scripts/`, add `__main__`

**Files:**
- Create: `books/core/__init__.py`, `books/renderers/__init__.py`, `books/renderers/obsidian/__init__.py`, `books/commands/__init__.py`, `books/commands/covers/__init__.py`, `books/commands/audible/__init__.py`
- Create: `books/__main__.py`
- Create: `tests/core/__init__.py` is NOT needed (pytest uses rootdir discovery); instead create empty dirs by placing the first test there in later tasks.
- Delete: `scripts/` (whole directory)

- [ ] **Step 1: Create the package directories with empty `__init__.py` files**

```bash
cd /Users/andrejakobsen/GitHub/books-cli
mkdir -p books/core books/renderers/obsidian books/commands/covers books/commands/audible
printf '"""Format-agnostic core: paths, config, CSV store, highlight model."""\n' > books/core/__init__.py
printf '"""Output renderers. Each subpackage turns the store into one output format."""\n' > books/renderers/__init__.py
printf '"""Obsidian renderer: vault layout, frontmatter, sections, highlight rendering."""\n' > books/renderers/obsidian/__init__.py
printf '"""CLI capability commands. Each module/package exposes register(app)."""\n' > books/commands/__init__.py
: > books/commands/covers/__init__.py
: > books/commands/audible/__init__.py
```

- [ ] **Step 2: Add `books/__main__.py` so `python -m books` works**

```python
"""Enable `python -m books` → the Typer CLI."""

from books.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Delete the redundant `scripts/` folder**

First confirm nothing outside `scripts/` references it:

```bash
grep -rn "scripts/" books/ tests/ pyproject.toml || echo "no references — safe to delete"
git rm -r scripts/
```
Expected: the grep prints "no references — safe to delete" (pyproject's `[project.scripts]` is a TOML table, not the folder — do not touch it).

- [ ] **Step 4: Verify**

Run the global verification. Nothing imports the new empty packages yet, so the suite stays green; `books --help` still lists all 9 commands.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: scaffold core/renderers/commands packages; drop scripts/ shims

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Move `resolve_path` and `config` into `core/`

**Files:**
- Modify: `books/__init__.py` (remove `resolve_path`, leave a bare package docstring)
- Create: `books/core/paths.py`
- Move: `books/config.py` → `books/core/config.py`
- Modify: every importer of `config` / `resolve_path`
- Move: `tests/test_config.py` → `tests/core/test_config.py`

- [ ] **Step 1: Create `books/core/paths.py` with the moved `resolve_path`**

Move the `resolve_path` function verbatim out of `books/__init__.py` into a new `books/core/paths.py` (keep the module docstring/imports it needs: `from pathlib import Path`).

- [ ] **Step 2: Reduce `books/__init__.py` to a bare marker**

`books/__init__.py` becomes:

```python
"""books package."""
```

- [ ] **Step 3: Move config with `git mv` and fix its internal import**

```bash
git mv books/config.py books/core/config.py
```
In `books/core/config.py`, change `from books import resolve_path` → `from books.core.paths import resolve_path`.

- [ ] **Step 4: Update every reference across the repo**

Find them:
```bash
grep -rn "from books import resolve_path\|from books import config\|from books import config, resolve_path\|resolve_path" books/ tests/
```
Apply these replacements (in `books/` source files and `tests/`):
- `from books import config` → `from books.core import config`
- `from books import resolve_path` → `from books.core.paths import resolve_path`
- `from books import config, resolve_path` → split into two lines:
  ```python
  from books.core import config
  from books.core.paths import resolve_path
  ```
- `from books import config` used with an alias, and `from books import store`/others on a shared line: split the line so only the `config` import moves.

Modules that import `config` and/or `resolve_path` (per current grep): `calibre_obsidian.py`, `goodreads_obsidian.py`, `kobo_export.py`, `highlighted_obsidian.py`, `readwise_obsidian.py`, `render_obsidian.py`, `audible_obsidian.py`, `audible_client.py`, `covers.py`, `sync.py`, and the test `test_config.py`.

- [ ] **Step 5: Move the config test**

```bash
mkdir -p tests/core
git mv tests/test_config.py tests/core/test_config.py
```
In `tests/core/test_config.py`, update `from books import config` → `from books.core import config` (and any `resolve_path` import per Step 4).

- [ ] **Step 6: Verify** — run the global verification.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: move resolve_path and config into books.core

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Split `obsidian.py` into the `renderers/obsidian/` package

The 623-line `books/obsidian.py` splits into six submodules. Cut each group **verbatim** (line ranges are from the current file for reference). No cycles: dependency order is `frontmatter, matching → format → layout → sections → vault_index`.

**Files:**
- Create: `books/renderers/obsidian/frontmatter.py`
- Create: `books/renderers/obsidian/matching.py`
- Create: `books/renderers/obsidian/format.py`
- Create: `books/renderers/obsidian/layout.py`
- Create: `books/renderers/obsidian/sections.py`
- Create: `books/renderers/obsidian/vault_index.py`
- Rewrite: `books/renderers/obsidian/__init__.py` (re-export the public API)
- Delete: `books/obsidian.py`
- Move: `tests/test_obsidian.py` → `tests/renderers/obsidian/test_obsidian.py`, `tests/test_compose_layout.py` → `tests/renderers/obsidian/test_compose_layout.py`

- [ ] **Step 1: `frontmatter.py`** — schema + frontmatter read/merge (self-contained).

Header:
```python
"""Book-note frontmatter: canonical schema, reading, and the never-overwrite merge."""

from __future__ import annotations

import re
```
Move verbatim: `BOOK_PROPERTY_ORDER` (L24), `OVERWRITE_KEYS` (L57), `BOOK_FLAG_DEFAULTS` (L60), `_split_frontmatter` (L264), `_key_of` (L278), `_is_blank_value` (L287), `frontmatter_values` (L292), `unquote` (L302), `extract_wikilinks` (L310), `update_frontmatter` (L317).

- [ ] **Step 2: `matching.py`** — normalization (self-contained).

Header:
```python
"""Title/ISBN/author normalization used to match a book to an existing note."""

from __future__ import annotations

import re
import unicodedata
```
Move verbatim: `fold` (L581), `norm_title` (L587), `norm_isbn` (L592), `norm_amazon` (L599), `author_key` (L606).

- [ ] **Step 3: `format.py`** — YAML/link/HTML formatting (self-contained).

Header:
```python
"""YAML scalar, wikilink, and HTML→Markdown formatting helpers."""

from __future__ import annotations

from html.parser import HTMLParser
```
Move verbatim: `yaml_quote` (L82), `format_rating` (L88), `wikilink` (L101), `link_list` (L108), `plain_list` (L113), `_HTMLToMarkdown` (L493), `html_to_markdown` (L571).

- [ ] **Step 4: `layout.py`** — folder constants, filenames, cover refs, stubs.

Header:
```python
"""Flat vault layout: folder names, safe filenames, cover paths, hub stubs."""

from __future__ import annotations

import re
from pathlib import Path

from books.renderers.obsidian.format import wikilink, yaml_quote
```
Move verbatim: `BOOKS_DIRNAME`, `COVERS_DIRNAME`, `NOTES_DIRNAME`, `AUTHORS_DIRNAME`, `TOPICS_DIRNAME` (L70-74), `COVER_WIDTH` (L77), `_ILLEGAL_FS` (L120), `sanitize_folder_name` (L123), `safe_filename` (L128), `strip_subtitle` (L136), `next_free_stem` (L146), `write_if_absent` (L172), `write_stub` (L181), `cover_path` (L242), `cover_refs` (L252).

- [ ] **Step 5: `sections.py`** — body section helpers.

Header:
```python
"""Idempotent note-body sections: marker-wrapped blocks, write-once, top embed."""

from __future__ import annotations

import re

from books.renderers.obsidian.frontmatter import _split_frontmatter
```
Move verbatim: `_marker_pair` (L187), `render_marked_section` (L192), `ensure_section` (L212), `ensure_top_embed` (L224).

- [ ] **Step 6: `vault_index.py`** — book identity + the layout authority.

Header:
```python
"""VaultIndex: match a BookRef to a flat book note (find / find_or_create)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from books.renderers.obsidian.format import link_list, yaml_quote
from books.renderers.obsidian.frontmatter import (
    BOOK_FLAG_DEFAULTS,
    extract_wikilinks,
    frontmatter_values,
    unquote,
    update_frontmatter,
)
from books.renderers.obsidian.layout import BOOKS_DIRNAME, next_free_stem
from books.renderers.obsidian.matching import (
    author_key,
    norm_amazon,
    norm_isbn,
    norm_title,
)
```
Move verbatim: `BookRef` (L361), `BookNote` (L370), `build_index` (L377), `VaultIndex` (L406).

- [ ] **Step 7: Write `books/renderers/obsidian/__init__.py` to re-export the public API**

This keeps every call site working with a single import-path change (`from books.obsidian import X` → `from books.renderers.obsidian import X`).

```python
"""Obsidian renderer: vault layout, frontmatter, sections, matching, formatting."""

from books.renderers.obsidian.format import (
    format_rating,
    html_to_markdown,
    link_list,
    plain_list,
    wikilink,
    yaml_quote,
)
from books.renderers.obsidian.frontmatter import (
    BOOK_FLAG_DEFAULTS,
    BOOK_PROPERTY_ORDER,
    OVERWRITE_KEYS,
    extract_wikilinks,
    frontmatter_values,
    unquote,
    update_frontmatter,
)
from books.renderers.obsidian.layout import (
    AUTHORS_DIRNAME,
    BOOKS_DIRNAME,
    COVER_WIDTH,
    COVERS_DIRNAME,
    NOTES_DIRNAME,
    TOPICS_DIRNAME,
    cover_path,
    cover_refs,
    next_free_stem,
    safe_filename,
    sanitize_folder_name,
    strip_subtitle,
    write_if_absent,
    write_stub,
)
from books.renderers.obsidian.matching import (
    author_key,
    fold,
    norm_amazon,
    norm_isbn,
    norm_title,
)
from books.renderers.obsidian.sections import (
    ensure_section,
    ensure_top_embed,
    render_marked_section,
)
from books.renderers.obsidian.vault_index import (
    BookNote,
    BookRef,
    VaultIndex,
    build_index,
)

__all__ = [
    "AUTHORS_DIRNAME", "BOOKS_DIRNAME", "BOOK_FLAG_DEFAULTS", "BOOK_PROPERTY_ORDER",
    "BookNote", "BookRef", "COVERS_DIRNAME", "COVER_WIDTH", "NOTES_DIRNAME",
    "OVERWRITE_KEYS", "TOPICS_DIRNAME", "VaultIndex", "author_key", "build_index",
    "cover_path", "cover_refs", "ensure_section", "ensure_top_embed",
    "extract_wikilinks", "fold", "format_rating", "frontmatter_values",
    "html_to_markdown", "link_list", "next_free_stem", "norm_amazon", "norm_isbn",
    "norm_title", "plain_list", "render_marked_section", "safe_filename",
    "sanitize_folder_name", "strip_subtitle", "unquote", "update_frontmatter",
    "wikilink", "write_if_absent", "write_stub", "yaml_quote",
]
```

- [ ] **Step 8: Delete the old module**

```bash
git rm books/obsidian.py
```

- [ ] **Step 9: Update every reference across the repo (source + tests)**

```bash
grep -rn "books\.obsidian\|from books import obsidian" books/ tests/
```
Replacements:
- `from books.obsidian import (` → `from books.renderers.obsidian import (`
- `from books.obsidian import X` (single-line) → `from books.renderers.obsidian import X`
- `from books import obsidian as ob` (in `tests/test_obsidian.py`) → `from books.renderers import obsidian as ob`

This touches source: `store.py`, `highlights.py` (its `from books.obsidian import wikilink` → `from books.renderers.obsidian import wikilink`), `calibre_obsidian.py`, `goodreads_obsidian.py`, `kobo_export.py`, `highlighted_obsidian.py`, `readwise_obsidian.py`, `render_obsidian.py`, `audible_obsidian.py`, `covers.py`. And **all** test files that import `books.obsidian` (e.g. `test_covers.py`, `test_calibre_to_obsidian.py`, etc.) — update them in place even though some move to new folders in later tasks.

- [ ] **Step 10: Move the obsidian tests into the mirrored folder**

```bash
mkdir -p tests/renderers/obsidian
git mv tests/test_obsidian.py tests/renderers/obsidian/test_obsidian.py
git mv tests/test_compose_layout.py tests/renderers/obsidian/test_compose_layout.py
```
(Their import fixes were already applied in Step 9.)

- [ ] **Step 11: Verify** — run the global verification.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "refactor: split obsidian.py into books.renderers.obsidian package

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Split highlights into `core/highlights.py` (data/parse) + `renderers/obsidian/highlights.py` (render)

**Files:**
- Create: `books/core/highlights.py` (model + marker parsing + ordering)
- Create: `books/renderers/obsidian/highlights.py` (Obsidian rendering)
- Modify: `books/renderers/obsidian/__init__.py` (add the render re-exports)
- Delete: `books/highlights.py`
- Modify: every importer of `books.highlights`
- Split: `tests/test_highlights.py` → `tests/core/test_highlights.py` (parsing/ordering) + `tests/renderers/obsidian/test_highlights_render.py` (anchors/render)

- [ ] **Step 1: Create `books/core/highlights.py` (format-agnostic half)**

Header:
```python
"""Source-agnostic highlight model, marker parsing (#tag/@link), and ordering."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
```
Move verbatim from `books/highlights.py`: `Highlight` (L20), `sanitize_tag` (L37), `_TITLE_STOPWORDS` (L54), `_title_case` (L60), `sanitize_link` (L76), `_MARKER_RE` (L96), `parse_markers` (L99), `split_tag_column` (L126), `_leading_int` (L148), `sort_key` (L159). **Do not** carry over `from books.obsidian import wikilink` — this half must not import a renderer.

- [ ] **Step 2: Create `books/renderers/obsidian/highlights.py` (Obsidian render half)**

Header:
```python
"""Render highlights as an Obsidian `## Highlights` body (callouts + chapter headers)."""

from __future__ import annotations

import re

from books.core.highlights import Highlight, sort_key
from books.renderers.obsidian.format import wikilink
```
Move verbatim: `build_anchors` (L177), `_label` (L208), `_chapter_key` (L223), `_chapter_header` (L232), `_quote_lines` (L246), `_callout` (L252), `render_highlights` (L270).

- [ ] **Step 3: Re-export the render entry points from the obsidian package**

In `books/renderers/obsidian/__init__.py` add:
```python
from books.renderers.obsidian.highlights import build_anchors, render_highlights
```
and add `"build_anchors"` and `"render_highlights"` to `__all__`.

- [ ] **Step 4: Delete the old module**

```bash
git rm books/highlights.py
```

- [ ] **Step 5: Update every importer (source + tests)**

```bash
grep -rn "books\.highlights\|from books import highlights" books/ tests/
```
Apply, per file:
- `books/core/store.py`: `from books.highlights import Highlight` → `from books.core.highlights import Highlight`
- `books/kobo_export.py` and `books/audible_obsidian.py`: replace
  `from books.highlights import Highlight, parse_markers, render_highlights` with
  ```python
  from books.core.highlights import Highlight, parse_markers
  from books.renderers.obsidian import render_highlights
  ```
- `books/highlighted_obsidian.py` and `books/readwise_obsidian.py`: replace
  `from books.highlights import Highlight, render_highlights, split_tag_column` with
  ```python
  from books.core.highlights import Highlight, split_tag_column
  from books.renderers.obsidian import render_highlights
  ```
- `books/render_obsidian.py`: `from books.highlights import render_highlights` → `from books.renderers.obsidian import render_highlights`
- Tests importing `from books.highlights import Highlight, render_highlights` (test_render, test_readwise, test_highlighted, and the render tests inside test_highlights): replace with
  ```python
  from books.core.highlights import Highlight
  from books.renderers.obsidian import render_highlights
  ```
- `tests/test_highlights.py`: `from books import highlights as hl` — handled by the split in Step 6.

- [ ] **Step 6: Split the highlights test file**

`tests/test_highlights.py` currently imports `from books import highlights as hl` and mixes parsing tests (`sanitize_link`, `split_tag_column`, sort) with render tests (`build_anchors`, `render_highlights`).

Split it:
- `tests/core/test_highlights.py`: the parsing/sanitize/sort tests. Import: `from books.core import highlights as hl` (all those symbols now live in core).
- `tests/renderers/obsidian/test_highlights_render.py`: the `build_anchors` and `render_highlights` tests. Imports:
  ```python
  from books.core.highlights import Highlight
  from books.renderers.obsidian import build_anchors, render_highlights
  ```
  Update call sites that used `hl.build_anchors(...)` → `build_anchors(...)`, `hl.render_highlights(...)` → `render_highlights(...)`, and any `hl.Highlight(...)` → `Highlight(...)`.

```bash
git rm tests/test_highlights.py   # after copying its tests into the two new files
```

- [ ] **Step 7: Verify** — run the global verification.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: split highlight parsing (core) from rendering (renderers.obsidian)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Move `store.py` into `core/`

**Files:**
- Move: `books/store.py` → `books/core/store.py`
- Modify: importers of `store` (`render_obsidian.py`, tests)
- Move: `tests/test_store.py` → `tests/core/test_store.py`

- [ ] **Step 1: Move with git**

```bash
git mv books/store.py books/core/store.py
```
Its internal imports were already updated in Tasks 3–4 (`from books.core.highlights import Highlight`, `from books.renderers.obsidian import (...)`). Verify no stale `from books.obsidian`/`from books.highlights` remain in it:
```bash
grep -n "from books" books/core/store.py
```

- [ ] **Step 2: Update store importers**

```bash
grep -rn "from books import store\|from books.store import\|books\.store" books/ tests/
```
- `books/render_obsidian.py`: `from books import config, store` is already `from books.core import config, store` after Task 2 — confirm; and `from books.store import BookRow, row_to_highlight` → `from books.core.store import BookRow, row_to_highlight`.
- Tests: `from books import store` → `from books.core import store`; `from books.store import ...` → `from books.core.store import ...`.

- [ ] **Step 3: Move the store test**

```bash
git mv tests/test_store.py tests/core/test_store.py
```

- [ ] **Step 4: Verify** — run the global verification.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: move store.py into books.core

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Relocate the five importers + render into `commands/` with clean names

**Files:**
- Move: `calibre_obsidian.py`→`commands/calibre.py`, `goodreads_obsidian.py`→`commands/goodreads.py`, `kobo_export.py`→`commands/kobo.py`, `highlighted_obsidian.py`→`commands/highlighted.py`, `readwise_obsidian.py`→`commands/readwise.py`, `render_obsidian.py`→`commands/render.py`
- Modify: `books/cli.py`, `books/sync.py`
- Move+rename tests to `tests/commands/`

- [ ] **Step 1: Move the six modules**

```bash
git mv books/calibre_obsidian.py     books/commands/calibre.py
git mv books/goodreads_obsidian.py   books/commands/goodreads.py
git mv books/kobo_export.py          books/commands/kobo.py
git mv books/highlighted_obsidian.py books/commands/highlighted.py
git mv books/readwise_obsidian.py    books/commands/readwise.py
git mv books/render_obsidian.py      books/commands/render.py
```
Their shared imports (`core`, `renderers.obsidian`) were fixed in Tasks 2–5. No intra-module import changes needed.

- [ ] **Step 2: Remove now-dead standalone `main()` entry points**

The `scripts/` shims are gone, so any module-level `main()` / `if __name__ == "__main__":` guard that existed only to support them is dead. Check each moved module:
```bash
grep -n "def main\|__main__" books/commands/*.py
```
Remove those `main()` functions and `if __name__ == "__main__":` blocks. **Keep** `register(app)` and the core functions (`convert`, `export_obsidian`, etc.). Do not remove a `main()` if it is referenced anywhere (`grep -rn "\.main(" tests/ books/` — expect none for these).

- [ ] **Step 3: Update `books/cli.py`**

Change the import block and `CAPABILITIES` so these six come from `books.commands`. After this task, `covers`, `audible`, and `sync` still import from their old paths (they move in Tasks 7–9), so `cli.py` temporarily mixes old and new. Target the six now:

```python
from books.commands import (
    calibre,
    goodreads,
    highlighted,
    kobo,
    readwise,
    render,
)
# still-old imports until Tasks 7-9:
from books import audible_obsidian, covers, sync
```
And update `CAPABILITIES` to reference `calibre, goodreads, highlighted, kobo, readwise, render` (plus the still-old `audible_obsidian, covers, sync`). Keep the tuple's 9 members and their `register` behavior identical.

- [ ] **Step 4: Update `books/sync.py` references**

`sync.py` imports the importer modules and calls `calibre_obsidian.convert`, `goodreads_obsidian.convert`, `kobo_export.export_obsidian`, `kobo_export.KOBO_DEVICE_DB`, `kobo_export._default_kobo_db`, `highlighted_obsidian.convert`, `readwise_obsidian.convert`. Replace the import block:

```python
from books.core import config
from books.commands import (
    calibre,
    goodreads,
    highlighted,
    kobo,
    readwise,
)
```
Then rename every reference: `calibre_obsidian.` → `calibre.`, `goodreads_obsidian.` → `goodreads.`, `kobo_export.` → `kobo.`, `highlighted_obsidian.` → `highlighted.`, `readwise_obsidian.` → `readwise.`. (`config.` references are unchanged.)

- [ ] **Step 5: Move + rename the tests**

```bash
mkdir -p tests/commands
git mv tests/test_calibre_to_obsidian.py   tests/commands/test_calibre.py
git mv tests/test_goodreads_obsidian.py    tests/commands/test_goodreads.py
git mv tests/test_kobo_export.py           tests/commands/test_kobo.py
git mv tests/test_highlighted_obsidian.py  tests/commands/test_highlighted.py
git mv tests/test_readwise.py              tests/commands/test_readwise.py
git mv tests/test_render_obsidian.py       tests/commands/test_render.py
```
Update the module-alias imports in each:
- `from books import calibre_obsidian as c2o` → `from books.commands import calibre as c2o`
- `from books import goodreads_obsidian as gr` → `from books.commands import goodreads as gr`
- `from books import kobo_export as ke` → `from books.commands import kobo as ke`
- `from books import highlighted_obsidian as hi` → `from books.commands import highlighted as hi`
- `from books import readwise_obsidian as rw` → `from books.commands import readwise as rw`
- `from books import render_obsidian as R` → `from books.commands import render as R`

- [ ] **Step 6: Verify** — run the global verification. Also smoke-check a subcommand:
```bash
uv run books calibre --help
```
Expected: exit 0, usage text.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: move importer + render commands into books.commands with clean names

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Split `covers.py` into the `commands/covers/` package

The 742-line `books/covers.py` splits into three focused modules plus a re-exporting `__init__`. `command` depends on `sources` and `images`; `sources` and `images` do not depend on `command` (no cycles). `sources` receives its fetchers by injection, so it does not import `images`.

**Files:**
- Create: `books/commands/covers/images.py`, `books/commands/covers/sources.py`, `books/commands/covers/command.py`
- Rewrite: `books/commands/covers/__init__.py` (re-export public API + `register`)
- Delete: `books/covers.py`
- Move: `tests/test_covers.py` → `tests/commands/test_covers.py`

- [ ] **Step 1: `images.py`** — HTTP + image validation (no project imports).

Header:
```python
"""HTTP fetching (retry/backoff) and image-bytes validation for covers."""

from __future__ import annotations

import time
import urllib.request  # keep whatever the original used
```
(Match the original module's actual stdlib imports for HTTP.) Move verbatim: `MIN_IMAGE_BYTES` (L402), `MIN_IMAGE_DIM` (L403), `_JPEG_SOF_MARKERS` (L405), `_jpeg_dimensions` (L413), `image_dimensions` (L435), `is_valid_image` (L452), `USER_AGENT` (L519), `HTTP_TIMEOUT` (L520), `HTTP_RETRIES` (L521), `HTTP_BACKOFF` (L522), `HTTP_MAX_SECONDS` (L523), `RETRYABLE_STATUS` (L528), `fetch_with_retry` (L531), `default_fetch_json` (L566), `default_fetch_bytes` (L575).

- [ ] **Step 2: `sources.py`** — cover-provider lookups + the two data models they produce.

Header:
```python
"""Cover candidate model + per-provider lookups (Apple, Google, Open Library, Amazon)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
```
Move verbatim: `MissingBook` (L57), `Candidate` (L67), `GOOGLE_API` (L119), `_GOOGLE_IMAGE_KEYS` (L122), `_label` (L127), `_AUTHOR_TAILS` (L133), `normalize_author` (L136), `_clean` (L153), `_upgrade_google_url` (L158), `google_books_candidates` (L165), `_google_isbn` (L193), `OL_SEARCH_API`..`OL_WORK_EDITIONS` (L200-204), `_norm_fmt` (L207), `_fmt_rank` (L219), `openlibrary_candidates` (L224), `AMAZON_IMAGE` (L274), `amazon_candidates` (L277), `ITUNES_API`..`ITUNES_ART_SIZE` (L289-292), `_itunes_artwork` (L295), `_itunes_isbn` (L305), `apple_books_candidates` (L322), `_API_SOURCES` (L355), `iter_candidates` (L362), `gather_with_errors` (L382), `gather_candidates` (L397).

(`MissingBook` and `Candidate` live here because that's what the lookups produce and consume; `command.py` imports them.)

- [ ] **Step 3: `command.py`** — vault scanning, selection, apply, CLI wiring.

Header:
```python
"""`covers` command: find blank-cover notes, pick a cover, write it into the note."""

from __future__ import annotations

from pathlib import Path

import typer

from books.core import config
from books.core.paths import resolve_path
from books.renderers.obsidian import (
    BOOKS_DIRNAME,
    VaultIndex,
    cover_path,
    cover_refs,
    ensure_top_embed,
    extract_wikilinks,
    frontmatter_values,
    unquote,
    update_frontmatter,
    yaml_quote,
)
from books.commands.covers.images import (
    default_fetch_bytes,
    default_fetch_json,
    is_valid_image,
)
from books.commands.covers.sources import (
    Candidate,
    MissingBook,
    gather_candidates,
    gather_with_errors,
)
```
Move verbatim: `_cover_is_blank` (L76), `note_to_missing` (L81), `find_missing` (L106), `QuitRequested` (L409), `pick_cover` (L468), `apply_cover` (L498), `_terminal_prompt` (L584), `run` (L592), `covers_command` (L651), `register` (L731). Delete the old `main` (L736) — it was for the removed shim.

(Trim each destination file's imports to only what it actually uses; the headers above are the expected supersets.)

- [ ] **Step 4: Re-export in `books/commands/covers/__init__.py`**

The covers tests call many symbols as `covers.<name>` across all three submodules, so the package must re-export them:

```python
"""covers command package."""

from books.commands.covers.command import (
    apply_cover,
    find_missing,
    note_to_missing,
    pick_cover,
    register,
    run,
)
from books.commands.covers.images import (
    default_fetch_bytes,
    default_fetch_json,
    fetch_with_retry,
    image_dimensions,
    is_valid_image,
)
from books.commands.covers.sources import (
    Candidate,
    MissingBook,
    amazon_candidates,
    apple_books_candidates,
    gather_candidates,
    gather_with_errors,
    google_books_candidates,
    normalize_author,
    openlibrary_candidates,
    _itunes_artwork,
    _itunes_isbn,
)
```
(The two `_itunes_*` names are re-exported because `tests/test_covers.py` calls them directly.)

- [ ] **Step 5: Delete the old module and update `cli.py`**

```bash
git rm books/covers.py
```
In `books/cli.py`, change `from books import ... covers ...` → import `covers` from `books.commands` (i.e. `from books.commands import covers`), keeping it in `CAPABILITIES` unchanged otherwise.

- [ ] **Step 6: Move the covers test**

```bash
git mv tests/test_covers.py tests/commands/test_covers.py
```
Update its imports: `from books import covers` → `from books.commands import covers`; and `from books.obsidian import VaultIndex` (already changed to `from books.renderers.obsidian import VaultIndex` in Task 3 — verify). All `covers.<name>` call sites keep working via the Step 4 re-exports.

- [ ] **Step 7: Verify** — run the global verification + `uv run books covers --help`.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: split covers.py into books.commands.covers package

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: Group audible into the `commands/audible/` package

**Files:**
- Create: `books/commands/audible/models.py` (the 4 shared dataclasses)
- Create: `books/commands/audible/command.py` (rest of `audible_obsidian.py`)
- Move: `books/audible_client.py` → `books/commands/audible/client.py`
- Move: `books/audible_transcribe.py` → `books/commands/audible/transcribe.py`
- Rewrite: `books/commands/audible/__init__.py` (expose `register`)
- Delete: `books/audible_obsidian.py`
- Move: audible tests → `tests/commands/`

- [ ] **Step 1: Extract the shared dataclasses to `models.py`**

Create `books/commands/audible/models.py`. Move verbatim the `Annotation`, `Chapter`, `DownloadedAudio`, `LibraryBook` dataclasses out of `books/audible_obsidian.py`. Header:
```python
"""Shared Audible data models used by the command, client, and transcriber."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
```
(Include whatever imports those dataclasses reference; keep bodies verbatim.)

- [ ] **Step 2: Create `command.py` from the rest of `audible_obsidian.py`**

```bash
git mv books/audible_obsidian.py books/commands/audible/command.py
```
Then, in `command.py`: remove the four dataclasses now in `models.py`, and update imports:
- `from books import config` → `from books.core import config`
- `from books.highlights import Highlight, parse_markers, render_highlights` → 
  ```python
  from books.core.highlights import Highlight, parse_markers
  from books.renderers.obsidian import render_highlights
  ```
- `from books.obsidian import (...)` → `from books.renderers.obsidian import (...)`
- add `from books.commands.audible.models import Annotation, Chapter, DownloadedAudio, LibraryBook`
- update the imports of the sibling helpers: `from books.audible_client import ...` → `from books.commands.audible.client import ...`; `from books.audible_transcribe import ...` → `from books.commands.audible.transcribe import ...`
- remove any dead `main()` / `__main__` guard (shim leftover); keep `register` and `convert`.

- [ ] **Step 3: Move client + transcribe and fix their imports**

```bash
git mv books/audible_client.py     books/commands/audible/client.py
git mv books/audible_transcribe.py books/commands/audible/transcribe.py
```
In `client.py`: `from books import config` → `from books.core import config`; `from books.audible_obsidian import Annotation, Chapter, DownloadedAudio, LibraryBook` → `from books.commands.audible.models import Annotation, Chapter, DownloadedAudio, LibraryBook`.
In `transcribe.py`: `from books.audible_obsidian import DownloadedAudio` → `from books.commands.audible.models import DownloadedAudio`.
Keep the lazy/optional third-party imports (`audible`, whisper, etc.) exactly where they are.

- [ ] **Step 4: Expose `register` in the package `__init__`**

```python
"""audible command package."""

from books.commands.audible.command import register

__all__ = ["register"]
```

- [ ] **Step 5: Update `cli.py`**

`from books import audible_obsidian` → `from books.commands import audible`, and in `CAPABILITIES` replace `audible_obsidian` with `audible`.

- [ ] **Step 6: Move + fix the audible tests**

```bash
git mv tests/test_audible_obsidian.py   tests/commands/test_audible_obsidian.py
git mv tests/test_audible_client.py     tests/commands/test_audible_client.py
git mv tests/test_audible_transcribe.py tests/commands/test_audible_transcribe.py
```
Update imports:
- `from books import audible_obsidian as ao` → `from books.commands.audible import command as ao`
- `from books import audible_client as ac` → `from books.commands.audible import client as ac`
- `from books import audible_transcribe as at` → `from books.commands.audible import transcribe as at`
- If any test references a dataclass via `ao.Annotation` / `ao.DownloadedAudio` etc., point it at the models module: `from books.commands.audible import models` and use `models.Annotation`, or import the names directly. (`command.py` also re-imports them, so `ao.Annotation` may still resolve — verify by running the tests and fix only what fails.)

- [ ] **Step 7: Verify** — run the global verification. If the `[audible]` extra isn't installed, its tests may skip/xfail exactly as they do today; confirm the pass/skip pattern is unchanged from before the refactor.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor: group audible into books.commands.audible package (models/command/client/transcribe)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Move `sync.py` into `commands/` and finalize `cli.py`

**Files:**
- Move: `books/sync.py` → `books/commands/sync.py`
- Modify: `books/cli.py`
- Move: `tests/test_sync.py` → `tests/commands/test_sync.py`
- Move: `tests/test_cli.py` → `tests/commands/test_cli.py`

- [ ] **Step 1: Move sync**

```bash
git mv books/sync.py books/commands/sync.py
```
Its imports were updated in Task 6 (`from books.commands import calibre, ...`). Verify no stale `from books import ...` remain:
```bash
grep -n "from books" books/commands/sync.py
```

- [ ] **Step 2: Finalize `cli.py`**

Now every capability lives under `books.commands`. Make the import block uniform:

```python
from books.commands import (
    audible,
    calibre,
    covers,
    goodreads,
    highlighted,
    kobo,
    readwise,
    render,
    sync,
)

CAPABILITIES = (
    audible,
    calibre,
    covers,
    goodreads,
    highlighted,
    kobo,
    readwise,
    render,
    sync,
)
```
Keep `len(CAPABILITIES) == 9` (asserted by `test_cli.py`).

- [ ] **Step 3: Move the sync + cli tests**

```bash
git mv tests/test_sync.py tests/commands/test_sync.py
git mv tests/test_cli.py  tests/commands/test_cli.py
```
`test_sync.py`: `from books import sync` → `from books.commands import sync`.
`test_cli.py`: `from books.cli import CAPABILITIES, app` is unchanged (still valid). Confirm its assertions about command names (`calibre`, `goodreads`, …, `sync`) still hold — command names are unchanged, so they should.

- [ ] **Step 4: Verify** — run the global verification, and confirm the command list:
```bash
uv run books --help
uv run books sync --help
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: move sync into books.commands; unify cli capability registry

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Update packaging + docs; final verification

**Files:**
- Verify: `pyproject.toml`
- Modify: `CLAUDE.md` (module paths), `README.md` if it references old paths

- [ ] **Step 1: Confirm packaging still ships every subpackage**

`[tool.hatch.build.targets.wheel] packages = ["books"]` includes subpackages automatically, and `[project.scripts] books = "books.cli:main"` is unchanged. Confirm a clean install resolves:
```bash
uv sync
uv run python -c "import books.core.store, books.renderers.obsidian, books.commands.sync; print('ok')"
uv run python -m books --help
```
Expected: `ok`, then the help output. No `pyproject.toml` edit expected — only make one if the import check fails (e.g. add explicit subpackages).

- [ ] **Step 2: Update `CLAUDE.md` module paths**

The Architecture section lists old paths (`books/calibre_obsidian.py`, `books/obsidian.py`, `scripts/*.py`, etc.). Update them to the new layout: `books/commands/calibre.py`, `books/renderers/obsidian/`, `books/core/`, etc. Remove the "Standalone shims" section (scripts/ is gone). Keep the capability descriptions themselves accurate; only the paths and the shims paragraph change.

- [ ] **Step 3: Update `README.md`** if it references `scripts/` or old module paths (grep first):
```bash
grep -n "scripts/\|_obsidian\|kobo_export" README.md || echo "no stale refs"
```
Fix any hits; otherwise skip.

- [ ] **Step 4: Final full verification**

```bash
uv run pytest -q
uv run books --help
uv run ruff check books/
```
Expected: all tests pass; help lists all 9 commands; ruff is clean (fix any new import-order/unused-import lints ruff flags from the moves).

- [ ] **Step 5: Confirm the tree matches the spec**

```bash
find books -name '*.py' | sort
```
Expected shape: `books/{__init__,__main__,cli}.py`, `books/core/{paths,config,store,highlights}.py`, `books/renderers/obsidian/{__init__,layout,frontmatter,sections,matching,format,highlights,vault_index}.py`, `books/commands/{calibre,goodreads,kobo,highlighted,readwise,render,sync}.py`, `books/commands/covers/{__init__,command,sources,images}.py`, `books/commands/audible/{__init__,command,models,client,transcribe}.py`. No files left directly under `books/` except `__init__`, `__main__`, `cli`.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "docs: update CLAUDE.md/README for the core/renderers/commands layout

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-review notes (coverage vs. spec)

- **`scripts/` deleted** → Task 1. Standalone-run dropped; `python -m books` added as a bonus, not a per-capability shim.
- **`resolve_path`/`config`/`store`/`highlights` → `core/`** → Tasks 2, 4, 5. `core/highlights.py` holds only model + parsing (no renderer import) — spec's "one extra split".
- **`obsidian.py` → `renderers/obsidian/` package (6 modules + re-export)** → Task 3.
- **`render_highlights` → `renderers/obsidian/highlights.py`** → Task 4.
- **`covers.py` → `commands/covers/` (command/sources/images + re-export)** → Task 7.
- **audible → `commands/audible/` (models/command/client/transcribe)** → Task 8.
- **Clean command names, `_obsidian`/`_export` dropped** → Task 6.
- **`cli.py` registry unified under `books.commands`** → Task 9.
- **Tests mirror the package (`tests/core`, `tests/renderers/obsidian`, `tests/commands`)** → moves distributed across Tasks 2–9.
- **One-way deps `commands → renderers → core`** enforced by the import headers in Tasks 3–8 (no `core` module imports a renderer; the covers/audible commands import `renderers.obsidian`, never vice versa).
- **Out of scope (unchanged):** importers still write Obsidian notes via `VaultIndex`; no `--renderer` flag; no logic edits beyond import paths.
```
