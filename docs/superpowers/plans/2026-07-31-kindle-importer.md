
# Kindle Importer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`-
[ ]`) syntax for tracking.

**Goal:** Add a `kindle` importer that ingests `My Clippings.txt`, deduplicates adjusted highlights (keeping the latest), attaches notes to highlights, and writes the results to the per-book CSV
highlights store.

**Architecture:** A new `books/commands/kindle/` package with three focused modules — `parser.py` (tokenize the log into `Entry` records), `dedup.py` (collapse overlapping highlight events +
attach notes, the novel logic), and `command.py` (book grouping, catalog resolution, store write, device detection, Typer wiring). It is a Phase-B highlights importer like
kobo/highlighted/readwise: a pure store writer that never creates notes. It joins the default sync-set and is selectable via `books import --kindle`.

**Tech Stack:** Python 3.11+, Typer, pydantic (store models), pytest, ruff. Standard library only for the new modules (`re`, `dataclasses`, `datetime`, `glob`).

**Reference reading before starting:**

- `docs/superpowers/specs/2026-07-31-kindle-importer-design.md` — the approved spec.
- `books/commands/readwise.py` and `books/commands/highlighted.py` — sibling importers to mirror.
- `books/core/highlights.py` — the `Highlight` dataclass (mutable; fields: `text`, `note`, `page`, `location_label`, `date`, `tags`, `links`, `source`, …).
- `books/core/store.py` — `import_highlights(vault, source, groups)` and `skipped_note(count)`.
- `books/core/matching.py` — `norm_title(str) -> str`, `author_key(str) -> tuple[str, str]`, `BookRef`.
- `books/core/config.py` — per-importer config dataclasses + `_parse_sections`.
- `books/commands/import_cmd.py` — `Step`, `build_steps`, `_all_steps`, `_CONSUMERS`, flags.

**Conventions:** After every code change run `uv run ruff check --fix` + `uv run ruff format`, then `uv run pytest -q`. Commit directly to `main` (this repo's rule — no feature branches).

---

## File Structure

- **Create** `books/commands/kindle/__init__.py` — re-export `register`, `run_import`, `convert`, `default_clippings_path`.
- **Create** `books/commands/kindle/parser.py` — `Entry` dataclass + `parse_clippings(text) -> list[Entry]`.
- **Create** `books/commands/kindle/dedup.py` — `to_highlights(entries) -> list[Highlight]` plus `_overlap`, `_dedup`.
- **Create** `books/commands/kindle/command.py` — `convert`, `run_import`, `default_clippings_path`, the `kindle` Typer command, `register`.
- **Create** `tests/commands/test_kindle_parser.py`, `tests/commands/test_kindle_dedup.py`, `tests/commands/test_kindle.py`.
- **Modify** `books/core/config.py` — add `KindleConfig`, `"kindle"` to `VALID_IMPORTERS` + `DEFAULT_IMPORTERS`, parse `[kindle]`, extend default-file templates.
- **Modify** `books/commands/import_cmd.py` — import the module, `_CONSUMERS`, `_detect_kindle`/`_run_kindle`, `Step`, phase tuple, `--kindle` flag.
- **Modify** `CLAUDE.md` — document the new importer.

---

## Task 1: Parser — `Entry` model and record parsing  ✅ DONE (committed)

**Files:**

- Create: `books/commands/kindle/__init__.py`
- Create: `books/commands/kindle/parser.py`
- Test: `tests/commands/test_kindle_parser.py`

- [x] **Step 1: Create the empty package init**
- [x] **Step 2: Write the failing parser tests** (9 tests: location/page/page+location parsing, BOM strip, note/bookmark kinds, multi-record, unparseable date → None, malformed record skipped)
- [x] **Step 3: Run tests to verify they fail** — ImportError, as expected.
- [x] **Step 4: Implement the parser** (`Entry` dataclass; `parse_clippings`; `_range_ints`; `_parse_date` with a fixed English month map; `_parse_record` with per-record BOM strip and locator
regexes; location preferred over page for the numeric range).
- [x] **Step 5: Run tests to verify they pass** — 9 passed.
- [x] **Step 6: Lint, format, commit** — committed as `feat(kindle): parse My Clippings.txt into Entry records`.

---

## Task 2: Dedup + note attachment → Highlights  ✅ DONE (committed)

**Files:**

- Create: `books/commands/kindle/dedup.py`
- Test: `tests/commands/test_kindle_dedup.py`

- [x] **Step 1: Write the failing dedup tests** (11 tests: same-start/same-end/contained merge; non-overlapping kept separate; timestamp tie → file order; location label + ISO date + source;
page-based default label; note attached to overlapping highlight; standalone note → text-less highlight; note dedup; bookmarks dropped).
- [x] **Step 2: Run tests to verify they fail** — ModuleNotFoundError, as expected.
- [x] **Step 3: Implement dedup + note attachment** (`_overlap`; `_pick_latest` with `(added is not None, added or datetime.min, idx)` key; `_dedup` interval-merge cluster; `_to_highlight`;
`_match_note_index`; `to_highlights`).
- [x] **Step 4: Run tests to verify they pass** — 11 passed.
- [x] **Step 5: Lint, format, commit** — committed as `feat(kindle): dedup adjusted highlights and attach notes`.

---

## Task 3: Command — grouping, resolution, store write, device detection  ⛔ BLOCKED at Step 3 (pipelock hook)

**Files:**

- Create: `books/commands/kindle/command.py`
- Modify: `books/commands/kindle/__init__.py`
- Test: `tests/commands/test_kindle.py`

- [x] **Step 1: Write the failing command/integration tests** (`tests/commands/test_kindle.py` — dedups+writes store, skips unmatched book, override path). *Already written.*
- [x] **Step 2: Run tests to verify they fail** — ImportError (`command` not found), as expected.
- [ ] **Step 3: Implement the command module** — Create `books/commands/kindle/command.py`:

```python
#!/usr/bin/env python3
"""Add Kindle ``My Clippings.txt`` highlights to the CSV highlights store.

Parses the clipping log, deduplicates adjusted highlights + attaches notes (see
``parser``/``dedup``), groups entries by book (title + author only -- Kindle
carries no ISBN/Amazon id), resolves each book to a ``book_id`` against the merged
catalog, and writes its highlights to ``Data/Highlights/<book_id>.csv`` (source
"kindle"). A book with no catalog match is skipped and counted, so run
``merge``/``import`` first. This importer never creates book notes; ``export``
turns the store into notes. Standard library only.
"""

from __future__ import annotations

import glob
from pathlib import Path

import typer

from books.commands.kindle.dedup import to_highlights
from books.commands.kindle.parser import parse_clippings
from books.core import config, store, ui
from books.core.highlights import Highlight
from books.core.matching import BookRef, author_key, norm_title
from books.core.paths import resolve_path

CLIPPINGS_NAME = "My Clippings.txt"
# Mounted Kindle exposes documents/My Clippings.txt; the volume name varies.
DEVICE_GLOB = "/Volumes/*/documents/My Clippings.txt"


def default_clippings_path(vault: Path, override: str = "") -> Path:
    """Resolve which ``My Clippings.txt`` to read.

    Priority: an explicit *override* (flag/config) wins; otherwise a mounted
    Kindle (first ``DEVICE_GLOB`` match) is used; otherwise the canonical
    ``Data/Imports/kindle/My Clippings.txt`` inside the vault. The returned path
    may not exist (callers check ``is_file``).
    """
    if override:
        return resolve_path(Path(override), Path.home())
    matches = sorted(glob.glob(DEVICE_GLOB))
    if matches:
        return Path(matches[0])
    return config.resolve_imports("kindle", vault) / CLIPPINGS_NAME


def convert(clippings_path: Path, output: Path) -> dict:
    """Parse *clippings_path*, dedup per book, and write the per-book store.

    Books are grouped by ``(norm_title, author_key)`` and resolved to a book_id
    via ``store.Catalog``; a book with no match is skipped and counted. Returns
    ``{"books": int, "entries": int, "skipped": int}``.
    """
    output.mkdir(parents=True, exist_ok=True)
    text = clippings_path.read_text(encoding="utf-8-sig")
    entries = parse_clippings(text)

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

    resolved: list[tuple[BookRef, list[Highlight]]] = []
    for key in order:
        group = groups[key]
        highlights = to_highlights(group)
        if not highlights:
            continue
        first = group[0]
        ref = BookRef(
            title=first.title,
            authors=[first.author] if first.author else [],
        )
        resolved.append((ref, highlights))

    return store.import_highlights(output, "kindle", resolved)


def run_import(vault: Path, cfg: config.KindleConfig) -> dict:
    """Import entry point used by ``books import`` (returns store stats).

    Resolves the clippings path (device / canonical / override); a missing file
    yields empty stats so the pipeline reports "skipped" rather than failing.
    """
    path = default_clippings_path(vault, cfg.clippings)
    if not path.is_file():
        return {"books": 0, "entries": 0, "skipped": 0}
    return convert(path, vault)


def kindle_import(
    clippings: Path | None = typer.Option(
        None,
        "--clippings",
        "-c",
        help="Path to a Kindle 'My Clippings.txt'. Defaults to a mounted Kindle, "
        "then <vault>/Data/Imports/kindle/My Clippings.txt. Relative paths resolve "
        "against the current directory.",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml). Relative paths resolve against the current directory.",
    ),
) -> None:
    """Add Kindle 'My Clippings.txt' highlights to the CSV highlights store.

    Highlights are written into the per-book highlights store for later rendering
    by ``export``; this command never creates book notes itself. Adjusted
    highlights are deduplicated (latest kept) and notes are attached to their
    highlights. Books are resolved to a book_id via the merged catalog
    (Data/books.csv) by a strict Author/Title comparison; a book with no match is
    skipped and counted, so run ``import``/``merge`` first.
    """
    vault = config.resolve_vault(output)
    path = clippings if clippings is not None else default_clippings_path(vault)
    path = resolve_path(path, Path.cwd())
    if not path.is_file():
        raise typer.BadParameter(f"clippings file not found: {path}", param_hint="--clippings")

    vault.mkdir(parents=True, exist_ok=True)
    stats = convert(path, vault)
    no_note = store.skipped_note(stats["skipped"])
    ui.info(
        f"Done. {stats['books']} books{no_note}, {stats['entries']} highlights.\nOutput: {vault}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("kindle")(kindle_import)
```

- [ ] **Step 4: Wire up the package init** — Replace the contents of `books/commands/kindle/__init__.py`:

```python
"""Kindle My Clippings.txt importer package.

Re-exports the public API so call sites use ``from books.commands.kindle import X``.
"""

from __future__ import annotations

from books.commands.kindle.command import (
    convert,
    default_clippings_path,
    kindle_import,
    register,
    run_import,
)

__all__ = [
    "convert",
    "default_clippings_path",
    "kindle_import",
    "register",
    "run_import",
]
```

- [ ] **Step 5: Run tests to verify they pass** — `uv run pytest tests/commands/test_kindle.py -q` → PASS (3 tests).
- [ ] **Step 6: Lint, format, commit** — `git commit -m "feat(kindle): group, resolve, and write clippings to the store"`.

---

## Task 4: Config — register `kindle` as a known importer

**Files:**

- Modify: `books/core/config.py`
- Test: `tests/core/test_config.py` (add cases; create the file if absent)

- [ ] **Step 1: Write failing config tests**

```python
from books.core import config


def test_kindle_in_default_and_valid_importers():
    assert "kindle" in config.DEFAULT_IMPORTERS
    assert "kindle" in config.VALID_IMPORTERS


def test_kindle_config_parsed(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        'obsidian_path = "/tmp/o"\nvault = "V"\n[kindle]\nclippings = "/tmp/My Clippings.txt"\n'
    )
    cfg = config.load_config(cfg_file)
    assert cfg.kindle.clippings == "/tmp/My Clippings.txt"


def test_kindle_config_defaults_empty(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('vault = "V"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.kindle.clippings == ""


def test_parseable_default_file_includes_kindle():
    import tomllib

    data = tomllib.loads(config._DEFAULT_FILE_PARSEABLE)
    assert "kindle" in data
```

- [ ] **Step 2: Run tests to verify they fail** — `uv run pytest tests/core/test_config.py -q`.
- [ ] **Step 3: Add `kindle` to the importer tuples**

```python
DEFAULT_IMPORTERS = ("calibre", "goodreads", "kobo", "highlighted", "readwise", "kindle")
```

```python
VALID_IMPORTERS = (
    "calibre",
    "goodreads",
    "kobo",
    "highlighted",
    "readwise",
    "audible",
    "covers",
    "kindle",
)
```

- [ ] **Step 4: Add the `KindleConfig` dataclass** (after `CoversConfig`):

```python
@dataclass
class KindleConfig:
    clippings: str = ""  # empty = auto-detect (mounted device / canonical folder)
```

Add the field to `Config` (after the `covers` field):

```python
    kindle: KindleConfig = field(default_factory=KindleConfig)
```

- [ ] **Step 5: Parse the `[kindle]` section** — in `_parse_sections`, add:

```python
    kin = _table(data, "kindle")
```

and in the returned dict (after the `"covers": ...` entry):

```python
        "kindle": KindleConfig(clippings=_str_or(kin, "clippings", "")),
```

- [ ] **Step 6: Extend the default-file templates** — in `_DEFAULT_FILE` append before the closing paren:

```python
"# [kindle]\n"

'# clippings = "/path/to/My Clippings.txt"  # default: mounted Kindle / imports folder\n'
```

in `_DEFAULT_FILE_PARSEABLE` append before the closing paren:

```python
"[kindle]\n"

'clippings = ""\n'
```

- [ ] **Step 7: Run tests to verify they pass** — PASS.
- [ ] **Step 8: Lint, format, commit** — `git commit -m "feat(kindle): add kindle to config importers and [kindle] section"`.

---

## Task 5: Wire `kindle` into the `import` pipeline

**Files:**

- Modify: `books/commands/import_cmd.py`
- Test: `tests/commands/test_import.py` (add cases)

- [ ] **Step 1: Write failing pipeline tests**

```python
from books.commands import import_cmd
from books.core import config


def test_kindle_step_registered():
    steps = import_cmd._all_steps(config.Config())
    assert "kindle" in steps


def test_kindle_included_when_selected():
    names = [s.name for s in import_cmd.build_steps({"kindle"}, config.Config())]
    assert "kindle" in names
    assert names.index("merge") < names.index("kindle")  # merge before the consumer


def test_kindle_flag_selects_only_kindle():
    selection = import_cmd._selection_from_flags(
        {"calibre": False, "kindle": True}, default={"calibre"}
    )
    assert selection == {"kindle"}
```

- [ ] **Step 2: Run tests to verify they fail** — `uv run pytest tests/commands/test_import.py -q -k kindle`.
- [ ] **Step 3: Import the module and mark it a consumer** — add `kindle,` to the importer imports block; update:

```python
_CONSUMERS = ("audible", "covers", "kobo", "highlighted", "readwise", "kindle")
```

- [ ] **Step 4: Add detect + run helpers** (near the other `_detect_*`/`_run_*`):

```python
def _detect_kindle(vault: Path, cfg: config.Config) -> str | None:
    path = kindle.default_clippings_path(vault, cfg.kindle.clippings)
    return str(path) if path.is_file() else None


def _run_kindle(vault: Path, cfg: config.Config) -> dict:
    return kindle.run_import(vault, cfg.kindle)
```

- [ ] **Step 5: Register the Step** — in `_all_steps`, after the `"readwise"` entry:

```python
        "kindle": Step(
            "kindle",
            _detect_kindle,
            _run_kindle,
            _summ_highlights,
            _imports_label("kindle", cfg),
        ),
```

- [ ] **Step 6: Add kindle to the highlights phase ordering** — in `build_steps`:

```python
    for name in ("kobo", "highlighted", "readwise", "kindle"):
        if name in selection:
            out.append(steps[name])
```

- [ ] **Step 7: Add the `--kindle` flag** — in `import_command`, after `readwise_`:

```python
kindle_: bool = (
    typer.Option(False, "--kindle", help="Import Kindle My Clippings.txt highlights."),
)
```

and add `"kindle": kindle_,` to the `_selection_from_flags` flags dict.

- [ ] **Step 8: Run tests to verify they pass** — PASS.
- [ ] **Step 9: Run the full suite** — `uv run pytest -q` → PASS (no regressions).
- [ ] **Step 10: Lint, format, commit** — `git commit -m "feat(kindle): wire kindle into the import pipeline and --kindle flag"`.

---

## Task 6: Documentation

**Files:**

- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the architecture docs**
  - "Phase B — highlights → notes": change "The three highlight importers (`kobo`, `highlighted`, `readwise`)" → "The four highlight importers (`kobo`, `highlighted`, `readwise`, `kindle`)".
  - `import_cmd.py` bullet: add `kindle` to the importer-flag list and default-set description; mention `Data/Imports/kindle/My Clippings.txt` + mounted-Kindle detection.
  - Configuration section: add `[kindle].clippings` (default: auto-detect a mounted Kindle / the imports folder) to per-importer settings; add `Data/Imports/kindle` (holds `My Clippings.txt`, not
raw CSVs) to the canonical-subfolder list.
  - Add a sentence: Kindle clippings are an append-only event log, so the importer deduplicates adjusted highlights (keeps the latest by timestamp, matching on location overlap) and attaches
notes to their highlights.
- [ ] **Step 2: Verify docs don't claim `books kindle` is a top-level command** (it is not in `CAPABILITIES`, like its siblings — describe it as an importer run via `books import`).
- [ ] **Step 3: Commit** — `git commit -m "docs(kindle): document the Kindle My Clippings importer"`.

---

## Task 7: Final verification

- [ ] **Step 1: Full lint + format + test** — `uv run ruff check --fix && uv run ruff format && uv run pytest -q` → PASS.
- [ ] **Step 2: Smoke-test the parser against the sample file** (`data/My Clippings.txt`):

```bash
uv run python -c "
from pathlib import Path
from books.commands.kindle import parser
entries = parser.parse_clippings(Path('data/My Clippings.txt').read_text(encoding='utf-8-sig'))
kinds = {}
for e in entries:
    kinds[e.kind] = kinds.get(e.kind, 0) + 1
print('entries:', len(entries), 'kinds:', kinds)
"
```

Expected: a few thousand entries, dominated by `highlight`, with `note`/`bookmark` present.

- [ ] **Step 3: Confirm dedup reduces the count**:

```bash
uv run python -c "
from pathlib import Path
from collections import defaultdict
from books.commands.kindle import parser, dedup
from books.core.matching import norm_title, author_key
entries = parser.parse_clippings(Path('data/My Clippings.txt').read_text(encoding='utf-8-sig'))
groups = defaultdict(list)
for e in entries:
    if e.title:
        groups[(norm_title(e.title), author_key(e.author))].append(e)
raw = sum(1 for e in entries if e.kind == 'highlight')
deduped = sum(len(dedup.to_highlights(g)) for g in groups.values())
print('raw highlights:', raw, '-> after dedup+notes:', deduped)
"
```

Expected: deduped count meaningfully lower than raw (adjusted highlights collapsed).

---

## Self-Review Notes

- **Spec coverage:** parser (T1) ✓; dedup + note attach (T2) ✓; book resolution + store write + device detection (T3) ✓; config/default-set (T4) ✓; import pipeline wiring + `--kindle` (T5) ✓;
docs (T6) ✓. Standalone `books kindle` function exists (T3) but is intentionally not in `CAPABILITIES`, matching readwise/highlighted.
- **Type consistency:** `Entry` fields (T1) used verbatim in T2–T3; `to_highlights` (T2) is the single dedup entry point called by `convert` (T3); `default_clippings_path`/`run_import`/`convert`
signatures match across `command.py`, `__init__.py`, `import_cmd.py`; `KindleConfig.clippings` (T4) read by `run_import`/`_detect_kindle`/`_run_kindle` (T3, T5).
- **Known caveat:** `command.py`'s docstring appears to trip the `.storecode` pipelock "Memory Persistence Directive" rule. If the write is blocked, the docstring wording (not the logic) needs
adjusting, or the rule lifted.
