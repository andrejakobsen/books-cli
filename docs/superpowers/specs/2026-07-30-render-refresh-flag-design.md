# `--refresh` flag for `render` and `sync`

**Date:** 2026-07-30
**Status:** Approved

## Problem

`render` is idempotent per book but only ever *adds/updates* notes. It never
removes files, so stale artifacts accumulate in the vault:

- notes for books that were removed from the catalog,
- notes left behind when a book's `book_id`/stem changes (e.g. a disambiguated
  rename), and
- orphaned author stubs.

A plain re-render can't clean these up. We want a `--refresh` mode that does a
clean rebuild of the note folders while preserving the user-owned frontmatter
properties that only live in the notes.

## Behavior

`--refresh` (on both `render` and `sync`):

1. **Cache** the user-owned, store-unbacked frontmatter properties from every
   existing `Books/*.md`, keyed by `book_id` (the note stem):
   - `topics` (100% user-owned)
   - `aliases`, `cssclasses` (`PRESERVED_EXTRA_KEYS`)
2. **Delete** `Books/` and `Authors/` (guarded — no error when absent).
3. **Render** the store as usual. Each book's note is seeded with its cached
   properties, so a surviving book's note is byte-identical to a normal render.

Because the cache is keyed by `book_id` and only consulted when that book is
re-rendered, cached properties are **re-added only for books that still exist**
in the catalog after the refresh. Cached props for a deleted book are simply
discarded along with its note.

Without `--refresh` the commands behave exactly as today (default `False`).

## What is NOT preserved (accepted trade-offs)

- **Manual free-text in a book note body** (outside the managed cover / `## Review`
  / `## Highlights` regions) is lost. Per the vault architecture, personal notes
  belong elsewhere in the vault, so this is acceptable.
- **Author notes** are recreated as bare `type: author` stubs. Hand-written
  content in an `Authors/*.md` note is lost on refresh. Author notes are treated
  as regenerable stubs by design.
- Everything reconstructable from the CSV store (`title`, `authors`, `## Review`
  from the `review`/`private_notes` columns, `## Highlights`, cover embed,
  canonical frontmatter) is rebuilt automatically.

## Implementation

The layout knowledge (which folders to delete, which keys are user-owned) stays
in the Obsidian renderer; the flag is threaded through the renderer seam.

1. **`books/renderers/obsidian/note.py`**
   - `render(vault, *, refresh: bool = False)`. When `refresh`:
     - build `cache: dict[str, dict]` via a new helper that scans `Books/*.md`
       and extracts `topics` + `PRESERVED_EXTRA_KEYS` per stem (via `load_note`);
     - `shutil.rmtree` `Books/` and `Authors/` when they exist;
     - render, passing `cache.get(row.book_id)` to each `render_note`.
   - `render_note(vault, row, highlights, *, preserved: dict | None = None)`:
     when `preserved` is not `None`, use it as the `existing` frontmatter for
     `book_frontmatter` (the on-disk read returns `({}, "")` after deletion).
     `existing_body` remains whatever `load_note` returns (empty after refresh).
2. **`books/renderers/base.py`** — `Renderer.render(self, vault, *, refresh: bool = False)`.
3. **`books/renderers/obsidian/note.py` `ObsidianRenderer.render`** — forward `refresh`.
4. **`books/commands/render.py`** — add `--refresh` option; call
   `renderer.render(vault, refresh=refresh)`.
5. **`books/commands/sync.py`** — add `--refresh` option; thread through
   `run_sync(vault, *, dry_run, refresh)` to the render step's runner
   (`_run_render(vault, refresh)`), preserving the existing monkeypatch-friendly
   global-lookup pattern. `--refresh` is a no-op under `--dry-run` (nothing is
   written or deleted); the dry-run plan is unchanged.

## Testing

- `render(..., refresh=True)` deletes stale notes/author stubs not backed by the
  current store.
- Cached `topics`/`aliases`/`cssclasses` are restored for surviving books and
  **not** for deleted books.
- `render(..., refresh=False)` is unchanged (default path).
- `refresh` on a vault with no `Books/`/`Authors/` folders does not error.
- Idempotence: `render(refresh=True)` twice yields identical bytes.
- `sync --refresh` forwards the flag to the render step; `sync --refresh --dry-run`
  writes/deletes nothing.
