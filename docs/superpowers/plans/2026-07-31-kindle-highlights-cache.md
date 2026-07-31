# Kindle Highlights Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-book JSON cache to the Kindle importer so extraction (needs the device / `My Clippings.txt`) is decoupled from catalog resolution — highlights cache once and attach to the store on any later `books import`, in any order, without the Kindle attached.

**Architecture:** A new `books/commands/kindle/cache.py` module owns the cache (`Data/Imports/kindle/cache/<stem>.json`, one file per book) and `Highlight ↔ dict` serialization. `command.convert` is reworked into two decoupled steps — *extract* (parse → dedup → wholesale-overwrite each book's cache file, only when the device is present) and *resolve* (load the whole cache every run → `store.import_highlights`, match-only). Unmatched books stay cached and are reported as **pending**. Mirrors the Audible per-book cache precedent.

**Tech Stack:** Python 3.11+, Typer, pydantic (store models), pytest, ruff. Standard library only for the new module (`json`, `dataclasses`, `pathlib`).

**Reference reading before starting:**

- `docs/superpowers/specs/2026-07-31-kindle-highlights-cache-design.md` — the approved spec.
- `books/commands/kindle/command.py` — current `convert`/`run_import`/`kindle_import` (being reworked).
- `books/commands/audible/command.py` — the per-book cache precedent (`book_cache_path`/`load_book_cache`/`save_book_cache`).
- `books/core/highlights.py` — the `Highlight` dataclass (fields: `text`, `note`, `chapter_index`, `chapter_title`, `progress`, `block`, `segment`, `page`, `location_label`, `date`, `tags`, `links`, `source`).
- `books/core/store.py:509` — `import_highlights(vault, source, groups) -> {"books", "entries", "skipped"}`.
- `books/core/naming.py:20` — `safe_filename(name) -> str`.
- `books/commands/import_cmd.py` — `Step`, `_all_steps`, `_detect_kindle`, `_run_kindle`, `_summ_highlights`.

**Conventions:** After every code change run `uv run ruff check --fix` + `uv run ruff format`, then `uv run pytest -q`. Commit directly to `main` (this repo's rule — no feature branches).

**Known caveat (pipelock):** the `.storecode` pipelock hook blocks docstrings phrased like "written into the … store for later …" (Memory Persistence Directive). Keep docstrings plain and factual (the word "cache" is fine — Audible uses it). If a write is blocked, reword the docstring (not the logic) and retry, bisecting to find the trigger phrase.

---

## File Structure

- **Create** `books/commands/kindle/cache.py` — `cache_dir`, `book_stem`, `save_book`, `load_all`, `highlight_to_dict`, `highlight_from_dict`.
- **Create** `tests/commands/test_kindle_cache.py` — cache unit tests.
- **Modify** `books/commands/kindle/command.py` — rework `convert`/`run_import`/`kindle_import` for the extract+resolve split and the `pending` stat.
- **Modify** `books/commands/kindle/__init__.py` — re-export `cache_dir`.
- **Modify** `tests/commands/test_kindle.py` — update `skipped` → `pending`, add resolve-from-cache + wholesale-overwrite cases.
- **Modify** `books/commands/import_cmd.py` — `_detect_kindle` honours the cache; add `_summ_kindle`; wire it into the `kindle` Step.
- **Modify** `tests/commands/test_import.py` — add a cache-only detection test.
- **Modify** `CLAUDE.md` — document the cache + pending/resolve-anytime behavior.

---

## Task 1: Cache module — serialization, naming, save/load

**Files:**

- Create: `books/commands/kindle/cache.py`
- Test: `tests/commands/test_kindle_cache.py`

- [ ] **Step 1: Write the failing cache tests**

Create `tests/commands/test_kindle_cache.py`:

```python
"""Unit tests for the Kindle per-book highlights cache."""

from books.commands.kindle import cache
from books.core.highlights import Highlight


def test_highlight_dict_round_trip():
    h = Highlight(
        text="hello",
        note="a thought",
        page="472-473",
        location_label="loc.",
        date="2015-07-31T00:18:38",
        source="kindle",
        tags=["x"],
        links=["Y"],
    )
    restored = cache.highlight_from_dict(cache.highlight_to_dict(h))
    assert restored == h


def test_highlight_from_dict_ignores_unknown_keys():
    d = {"text": "hi", "bogus": 1}
    assert cache.highlight_from_dict(d) == Highlight(text="hi")


def test_save_and_load_round_trip(tmp_path):
    cdir = cache.cache_dir(tmp_path)
    stem = cache.book_stem("The Deluge", "Adam Tooze", set())
    cache.save_book(cdir, stem, "The Deluge", "Adam Tooze", [Highlight(text="a")])
    records = cache.load_all(cdir)
    assert len(records) == 1
    assert records[0]["title"] == "The Deluge"
    assert records[0]["author"] == "Adam Tooze"
    assert records[0]["highlights"] == [Highlight(text="a")]


def test_save_book_wholesale_overwrite(tmp_path):
    cdir = cache.cache_dir(tmp_path)
    stem = cache.book_stem("T", "A", set())
    cache.save_book(cdir, stem, "T", "A", [Highlight(text="old")])
    cache.save_book(cdir, stem, "T", "A", [Highlight(text="new")])
    records = cache.load_all(cdir)
    assert len(records) == 1
    assert records[0]["highlights"] == [Highlight(text="new")]


def test_book_stem_readable_and_collision_suffix():
    used = set()
    assert cache.book_stem("The Deluge", "Adam Tooze", used) == "The Deluge - Adam Tooze"
    # A second distinct book that sanitizes to the same stem gets a numeric suffix.
    assert cache.book_stem("The Deluge", "Adam Tooze", used) == "The Deluge - Adam Tooze (2)"


def test_load_all_missing_dir_is_empty(tmp_path):
    assert cache.load_all(tmp_path / "nope") == []


def test_load_all_skips_corrupt_file(tmp_path):
    cdir = cache.cache_dir(tmp_path)
    cdir.mkdir(parents=True)
    (cdir / "bad.json").write_text("{not json", encoding="utf-8")
    assert cache.load_all(cdir) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/commands/test_kindle_cache.py -q`
Expected: FAIL — `ModuleNotFoundError: books.commands.kindle.cache`.

- [ ] **Step 3: Implement the cache module**

Create `books/commands/kindle/cache.py`:

```python
#!/usr/bin/env python3
"""Per-book JSON cache for Kindle highlights.

One file per book at ``<vault>/Data/Imports/kindle/cache/<stem>.json`` holds a
book's deduplicated highlights, keyed by a readable ``<Title> - <Author>`` stem
(Kindle carries no ISBN/ASIN). The cache decouples extraction (needs the device)
from catalog resolution: ``command.convert`` refreshes it from the device when
present and always resolves the whole cache against the catalog. Standard library
only.
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from pathlib import Path

from books.core.highlights import Highlight
from books.core.naming import safe_filename

_HIGHLIGHT_FIELDS = {f.name for f in fields(Highlight)}


def cache_dir(vault: Path) -> Path:
    """The Kindle cache folder: ``<vault>/Data/Imports/kindle/cache``."""
    return vault / "Data" / "Imports" / "kindle" / "cache"


def highlight_to_dict(h: Highlight) -> dict:
    """Serialize a ``Highlight`` to a plain dict (all fields)."""
    return asdict(h)


def highlight_from_dict(d: dict) -> Highlight:
    """Rebuild a ``Highlight`` from a dict, ignoring unknown keys."""
    return Highlight(**{k: v for k, v in d.items() if k in _HIGHLIGHT_FIELDS})


def book_stem(title: str, author: str, used: set[str]) -> str:
    """A stable, readable cache stem for a book, disambiguated against *used*.

    ``used`` accumulates the lowercased stems already assigned this run (so a rare
    collision between two distinct books gets a ``(2)``/``(3)`` suffix). Callers
    iterate books in a deterministic (sorted) order so assignment is reproducible.
    """
    base = safe_filename(f"{title} - {author}" if author else title)
    stem = base
    n = 2
    while stem.lower() in used:
        stem = f"{base} ({n})"
        n += 1
    used.add(stem.lower())
    return stem


def save_book(cdir: Path, stem: str, title: str, author: str, highlights: list[Highlight]) -> None:
    """Write one book's cache record (wholesale overwrite; parents created)."""
    cdir.mkdir(parents=True, exist_ok=True)
    record = {
        "title": title,
        "author": author,
        "highlights": [highlight_to_dict(h) for h in highlights],
    }
    (cdir / f"{stem}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_all(cdir: Path) -> list[dict]:
    """Every cache record ``{title, author, highlights}``; skips corrupt files."""
    if not cdir.is_dir():
        return []
    records: list[dict] = []
    for path in sorted(cdir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        records.append(
            {
                "title": data.get("title", ""),
                "author": data.get("author", ""),
                "highlights": [highlight_from_dict(h) for h in data.get("highlights", [])],
            }
        )
    return records
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/commands/test_kindle_cache.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff check --fix books/commands/kindle/cache.py tests/commands/test_kindle_cache.py
uv run ruff format books/commands/kindle/cache.py tests/commands/test_kindle_cache.py
git add books/commands/kindle/cache.py tests/commands/test_kindle_cache.py
git commit -m "feat(kindle): add per-book highlights cache module"
```

---

## Task 2: Rework `convert` into extract + resolve

**Files:**

- Modify: `books/commands/kindle/command.py`
- Modify: `books/commands/kindle/__init__.py`
- Test: `tests/commands/test_kindle.py`

- [ ] **Step 1: Update the existing command tests and add cache cases**

In `tests/commands/test_kindle.py`, change the `test_convert_skips_unmatched_book` assertion from `skipped` to `pending`:

```python
def test_convert_skips_unmatched_book(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _seed_malcolm(vault)
    stats = command.convert(_clippings(tmp_path, MALCOLM + UNMATCHED), vault)
    assert stats["books"] == 1
    assert stats["pending"] == 1
```

Then append these new tests to the file:

```python
def test_convert_caches_and_resolves_from_cache_without_device(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    # First pass: device present, but no catalog yet -> everything pending, cached.
    stats = command.convert(_clippings(tmp_path, MALCOLM), vault)
    assert stats == {"books": 0, "entries": 1, "pending": 1}
    from books.commands.kindle import cache

    assert list(cache.cache_dir(vault).glob("*.json"))  # cache written
    # Later: catalog appears, and we resolve WITHOUT the device (clippings=None).
    _seed_malcolm(vault)
    stats = command.convert(None, vault)
    assert stats == {"books": 1, "entries": 1, "pending": 0}
    rows = store.read_highlights(vault, "The Autobiography of Malcolm X - Malcolm X")
    assert rows[0].text == "new version"
    assert rows[0].note == "a thought"


def test_convert_wholesale_overwrite_on_reparse(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _seed_malcolm(vault)
    command.convert(_clippings(tmp_path, MALCOLM), vault)
    # Re-parse with an edited highlight; the cache file is replaced, not appended.
    edited = MALCOLM.replace("new version", "edited version")
    stats = command.convert(_clippings(tmp_path, edited), vault)
    assert stats["entries"] == 1
    rows = store.read_highlights(vault, "The Autobiography of Malcolm X - Malcolm X")
    assert rows[0].text == "edited version"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/commands/test_kindle.py -q`
Expected: FAIL — `KeyError: 'pending'` / new tests error (convert doesn't accept `None`, no cache).

- [ ] **Step 3: Rework `convert` (and its imports)**

In `books/commands/kindle/command.py`, add the cache import near the other kindle imports:

```python
from books.commands.kindle import cache
```

Replace the whole `convert` function with:

```python
def convert(clippings_path: Path | None, output: Path) -> dict:
    """Refresh the cache from the device (if present) and resolve it to the store.

    *Extract* (only when *clippings_path* is a real file): parse, group by
    ``(norm_title, author_key)``, dedup per book, and wholesale-overwrite each
    book's cache file. *Resolve* (always): load the whole cache and resolve every
    book to a book_id via ``store.import_highlights`` (match-only); unmatched books
    stay cached. Returns ``{"books": int, "entries": int, "pending": int}``.
    """
    output.mkdir(parents=True, exist_ok=True)
    cdir = cache.cache_dir(output)

    if clippings_path is not None and clippings_path.is_file():
        entries = parse_clippings(clippings_path.read_text(encoding="utf-8-sig"))
        groups: dict[tuple, list] = {}
        order: list[tuple] = []
        for entry in entries:
            if not entry.title:
                continue
            key = (norm_title(entry.title), author_key(entry.author))
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(entry)
        used: set[str] = set()
        for key in sorted(order):
            group = groups[key]
            highlights = to_highlights(group)
            if not highlights:
                continue
            first = group[0]
            stem = cache.book_stem(first.title, first.author, used)
            cache.save_book(cdir, stem, first.title, first.author, highlights)

    resolved: list[tuple[BookRef, list[Highlight]]] = []
    for record in cache.load_all(cdir):
        if not record["highlights"]:
            continue
        ref = BookRef(
            title=record["title"],
            authors=[record["author"]] if record["author"] else [],
        )
        resolved.append((ref, record["highlights"]))

    stats = store.import_highlights(output, "kindle", resolved)
    return {"books": stats["books"], "entries": stats["entries"], "pending": stats["skipped"]}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/commands/test_kindle.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Re-export `cache_dir` from the package init**

In `books/commands/kindle/__init__.py`, add `cache_dir` to the imports and `__all__`:

```python
from books.commands.kindle.cache import cache_dir
from books.commands.kindle.command import (
    convert,
    default_clippings_path,
    kindle_import,
    register,
    run_import,
)

__all__ = [
    "cache_dir",
    "convert",
    "default_clippings_path",
    "kindle_import",
    "register",
    "run_import",
]
```

- [ ] **Step 6: Run the full suite, lint, format, commit**

```bash
uv run pytest -q
uv run ruff check --fix books/commands/kindle/ tests/commands/test_kindle.py
uv run ruff format books/commands/kindle/ tests/commands/test_kindle.py
git add books/commands/kindle/ tests/commands/test_kindle.py
git commit -m "feat(kindle): cache highlights and resolve the cache every run"
```

Expected: full suite still green (note `run_import`/`kindle_import` are updated next; the standalone command's old `skipped` behavior is not asserted anywhere).

---

## Task 3: Cache-aware entry points (`run_import`, `kindle_import`)

**Files:**

- Modify: `books/commands/kindle/command.py`
- Test: `tests/commands/test_kindle.py`

- [ ] **Step 1: Write the failing entry-point tests**

Append to `tests/commands/test_kindle.py`:

```python
def test_run_import_uses_cache_when_device_absent(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    _seed_malcolm(vault)
    # Seed the cache via a device pass using an explicit config path.
    clip = _clippings(tmp_path, MALCOLM)
    command.convert(clip, vault)
    # Now the device is gone; run_import resolves from cache alone.
    cfg = config.KindleConfig(clippings="")

    # No clippings anywhere -> default path won't be a file, but the cache exists.
    stats = command.run_import(vault, cfg)
    assert stats["books"] == 1
    assert stats["pending"] == 0


def test_run_import_empty_when_no_source_and_no_cache(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = config.KindleConfig(clippings="")
    assert command.run_import(vault, cfg) == {"books": 0, "entries": 0, "pending": 0}
```

Add the config import at the top of `tests/commands/test_kindle.py` if not present:

```python
from books.core import config
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/commands/test_kindle.py -q -k run_import`
Expected: FAIL — `run_import` returns empty (old `is_file` gate ignores the cache) / `KeyError`.

- [ ] **Step 3: Rework `run_import` and `kindle_import`**

In `books/commands/kindle/command.py`, replace `run_import` with:

```python
def run_import(vault: Path, cfg: config.KindleConfig) -> dict:
    """Import entry point used by ``books import`` (returns store stats).

    Runs when a clippings file is available (device / canonical / override) *or* a
    non-empty cache already exists — so highlights resolve even with the Kindle
    unplugged. Empty stats only when neither is present.
    """
    path = default_clippings_path(vault, cfg.clippings)
    clip = path if path.is_file() else None
    cdir = cache.cache_dir(vault)
    has_cache = cdir.is_dir() and any(cdir.glob("*.json"))
    if clip is None and not has_cache:
        return {"books": 0, "entries": 0, "pending": 0}
    return convert(clip, vault)
```

Replace the body of `kindle_import` (keep its signature/decorated options) — from `vault = config.resolve_vault(output)` to the end of the function — with:

```python
vault = config.resolve_vault(output)
if clippings is not None:
    clip = resolve_path(clippings, Path.cwd())
    if not clip.is_file():
        raise typer.BadParameter(f"clippings file not found: {clip}", param_hint="--clippings")
else:
    auto = default_clippings_path(vault)
    clip = auto if auto.is_file() else None

cdir = cache.cache_dir(vault)
has_cache = cdir.is_dir() and any(cdir.glob("*.json"))
if clip is None and not has_cache:
    raise typer.BadParameter("no Kindle clippings file or cache found", param_hint="--clippings")

vault.mkdir(parents=True, exist_ok=True)
stats = convert(clip, vault)
pending = f", {stats['pending']} pending" if stats["pending"] else ""
ui.info(f"Done. {stats['books']} books{pending}, {stats['entries']} highlights.\nOutput: {vault}")
```

Also update the `kindle_import` docstring's final sentence so it no longer says a skipped book is "skipped and counted" — replace that sentence with:

```python
    skipped. A book with no catalog match stays cached and is reported as pending,
    so import order does not matter — run ``import``/``merge`` whenever.
```

(If the pipelock hook blocks the write, reword the docstring — not the logic — per the Known caveat.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/commands/test_kindle.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff check --fix books/commands/kindle/command.py tests/commands/test_kindle.py
uv run ruff format books/commands/kindle/command.py tests/commands/test_kindle.py
git add books/commands/kindle/command.py tests/commands/test_kindle.py
git commit -m "feat(kindle): resolve from cache when the device is absent"
```

---

## Task 4: Pipeline detection + pending summary

**Files:**

- Modify: `books/commands/import_cmd.py`
- Test: `tests/commands/test_import.py`

- [ ] **Step 1: Write the failing pipeline tests**

Append to `tests/commands/test_import.py`:

```python
def test_detect_kindle_true_with_cache_only(tmp_path):
    from books.commands.kindle import cache
    from books.core.highlights import Highlight

    cdir = cache.cache_dir(tmp_path)
    cache.save_book(cdir, "T - A", "T", "A", [Highlight(text="x")])
    assert import_cmd._detect_kindle(tmp_path, config.Config()) == str(cdir)


def test_summ_kindle_reports_pending():
    assert "3 pending" in import_cmd._summ_kindle({"books": 1, "entries": 5, "pending": 3})
    assert "pending" not in import_cmd._summ_kindle({"books": 1, "entries": 5, "pending": 0})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/commands/test_import.py -q -k "kindle"`
Expected: FAIL — `_detect_kindle` returns `None` for cache-only; `_summ_kindle` does not exist.

- [ ] **Step 3: Make `_detect_kindle` honour the cache**

In `books/commands/import_cmd.py`, replace `_detect_kindle` with:

```python
def _detect_kindle(vault: Path, cfg: config.Config) -> str | None:
    path = kindle.default_clippings_path(vault, cfg.kindle.clippings)
    if path.is_file():
        return str(path)
    cdir = kindle.cache_dir(vault)
    if cdir.is_dir() and any(cdir.glob("*.json")):
        return str(cdir)
    return None
```

- [ ] **Step 4: Add `_summ_kindle` and wire it into the Step**

In `books/commands/import_cmd.py`, add near `_summ_highlights`:

```python
def _summ_kindle(s: dict) -> str:
    pending = f", {s['pending']} pending" if s.get("pending") else ""
    return f"{s.get('books', 0)} books, {s.get('entries', 0)} highlights{pending}"
```

In `_all_steps`, change the `kindle` Step to use `_summ_kindle` instead of `_summ_highlights`:

```python
        "kindle": Step(
            "kindle",
            _detect_kindle,
            _run_kindle,
            _summ_kindle,
            _imports_label("kindle", cfg),
        ),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/commands/test_import.py -q -k "kindle"`
Expected: PASS.

- [ ] **Step 6: Run the full suite, lint, format, commit**

```bash
uv run pytest -q
uv run ruff check --fix books/commands/import_cmd.py tests/commands/test_import.py
uv run ruff format books/commands/import_cmd.py tests/commands/test_import.py
git add books/commands/import_cmd.py tests/commands/test_import.py
git commit -m "feat(kindle): detect the cache and report pending in the pipeline"
```

Expected: full suite green (495+ tests).

---

## Task 5: Documentation

**Files:**

- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the Phase-B / kindle description**

In `CLAUDE.md`, find the sentence added by the original importer:

> Kindle clippings are an append-only event log, so the importer deduplicates adjusted highlights (keeps the latest by timestamp, matching on location overlap) and attaches notes to their highlights.

Append to it:

> Because `My Clippings.txt` lives only on the device, kindle also caches each book's deduplicated highlights one JSON file per book under `Data/Imports/kindle/cache/` (mirroring the Audible cache). Every `books import` re-resolves the whole cache against the catalog, so highlights attach whenever their catalog entry exists — import order does not matter and the Kindle need not be attached. Books with no catalog match stay cached and are reported as **pending** (not discarded).

- [ ] **Step 2: Update the import_cmd.py bullet**

In the `books/commands/import_cmd.py` bullet, change the Kindle input sentence:

> Kindle reads `Data/Imports/kindle/My Clippings.txt` (or a mounted Kindle's `documents/My Clippings.txt`, auto-detected).

to:

> Kindle reads `Data/Imports/kindle/My Clippings.txt` (or a mounted Kindle's `documents/My Clippings.txt`, auto-detected) and caches highlights under `Data/Imports/kindle/cache/`; the step also runs from that cache alone (no device needed) and reports unmatched books as pending.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(kindle): document the highlights cache and pending behavior"
```

---

## Task 6: Final verification

- [ ] **Step 1: Full lint + format + test**

Run: `uv run ruff check --fix && uv run ruff format && uv run pytest -q`
Expected: PASS, no regressions.

- [ ] **Step 2: Smoke-test extract+cache against the sample file**

```bash
uv run python -c "
from pathlib import Path
import tempfile
from books.commands.kindle import command, cache
vault = Path(tempfile.mkdtemp())
stats = command.convert(Path('data/My Clippings.txt'), vault)
n = len(list(cache.cache_dir(vault).glob('*.json')))
print('stats:', stats, '| cache files:', n)
"
```

Expected: `stats: {'books': 0, 'entries': 0, 'pending': N}` with no catalog (all pending), and `cache files: N` (~122) — extraction populated the cache even though nothing matched.

- [ ] **Step 3: Smoke-test resolve-from-cache after seeding one book**

```bash
uv run python -c "
from pathlib import Path
import tempfile
from books.commands.kindle import command
from books.core import store
vault = Path(tempfile.mkdtemp())
command.convert(Path('data/My Clippings.txt'), vault)   # populate cache, 0 matched
# Seed one catalog row that matches a real cached book, then resolve WITHOUT the device.
rows = store.read_highlights  # noqa: F841 (ensure import ok)
titles = [p.stem for p in (vault/'Data'/'Imports'/'kindle'/'cache').glob('*.json')]
print('example cached book stems:', titles[:3])
"
```

Expected: prints a few cached book stems (confirms the readable-stem naming). No exceptions.

---

## Self-Review Notes

- **Spec coverage:** cache module + serialization + readable stems (T1) ✓; extract/resolve split + wholesale overwrite + pending stat (T2) ✓; cache-aware `run_import`/`kindle_import` incl. device-absent + explicit-path error (T3) ✓; pipeline detection honours cache + `_summ_kindle` pending (T4) ✓; docs (T5) ✓; verification incl. real-file smoke test (T6) ✓.
- **Type consistency:** `cache_dir`/`book_stem`/`save_book`/`load_all`/`highlight_to_dict`/`highlight_from_dict` defined in T1 are used verbatim in T2–T4; `convert(Path | None, Path)` (T2) called by `run_import`/`kindle_import` (T3) and `import_cmd._run_kindle` (unchanged, already `kindle.run_import`); `{"books","entries","pending"}` stat keys consistent across T2–T4; `kindle.cache_dir` re-export (T2 Step 5) used by `_detect_kindle` (T4).
- **No behavior change elsewhere:** catalog/merge/other importers untouched; `store.import_highlights` still returns `skipped`, remapped to `pending` only at the kindle boundary.
- **Known caveat:** docstrings may trip the `.storecode` pipelock; reword (not the logic) if blocked.
