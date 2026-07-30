# `--refresh` flag for `render` and `sync` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--refresh` flag to `render` and `sync` that deletes `Books/` and `Authors/` before rendering, while caching and restoring user-owned frontmatter (`topics`, `aliases`, `cssclasses`) for books that still exist in the catalog.

**Architecture:** The Obsidian renderer owns the layout knowledge (which folders to delete, which keys are user-owned). `render(vault, *, refresh=False)` caches the user-owned properties from every existing `Books/*.md` (keyed by `book_id` = note stem), deletes the two folders, then renders — seeding each note's cached properties back via a new `preserved=` override on `render_note`. The flag is threaded through the `Renderer` protocol and both CLI commands.

**Tech Stack:** Python 3.11+, Typer, pytest, python-frontmatter, ruamel.yaml.

---

## File Structure

- `books/renderers/obsidian/note.py` — add `_collect_preserved`, `_clear_note_dirs`, `preserved=` param on `render_note`, `refresh=` on `render` + `ObsidianRenderer.render`.
- `books/renderers/base.py` — add `refresh` to the `Renderer.render` protocol.
- `books/commands/render.py` — add `--refresh` CLI option.
- `books/commands/sync.py` — add `--refresh` CLI option, thread through `run_sync` → `_steps` → `_run_render`.
- `tests/commands/test_render.py` — unit tests for caching, deletion, restore.
- `tests/commands/test_sync.py` — update `_stub_runs`, add refresh-forwarding test.

Reference facts (already in the codebase):
- `BOOKS_DIRNAME = "Books"`, `AUTHORS_DIRNAME = "Authors"` (`books/renderers/obsidian/layout.py`).
- `PRESERVED_EXTRA_KEYS = ("aliases", "cssclasses")` (`books/renderers/obsidian/frontmatter.py`), already imported into `note.py`.
- The note stem equals `row.book_id`. `load_note(path)` returns `({}, "")` for a missing file.
- `shutil` is already imported in `note.py`.

---

## Task 1: Cache user-owned properties + `preserved=` override on `render_note`

**Files:**
- Modify: `books/renderers/obsidian/note.py`
- Test: `tests/commands/test_render.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/commands/test_render.py`:

```python
def test_collect_preserved_extracts_user_owned_keys(tmp_path):
    vault = tmp_path / "vault"
    books = vault / "Books"
    books.mkdir(parents=True)
    (books / "X - A.md").write_text(
        '---\ntype: book\ntitle: X\ntopics:\n- "[[History]]"\n'
        "aliases:\n- Alt\ncssclasses:\n- book\n---\n\nManual.\n",
        encoding="utf-8",
    )
    (books / "Plain - B.md").write_text(
        "---\ntype: book\ntitle: Plain\ntopics: []\n---\n\n", encoding="utf-8"
    )
    cache = R._collect_preserved(vault)
    assert cache["X - A"] == {
        "topics": ["[[History]]"],
        "aliases": ["Alt"],
        "cssclasses": ["book"],
    }
    # empty topics list is falsy-but-present: kept as-is
    assert cache["Plain - B"] == {"topics": []}


def test_collect_preserved_empty_when_no_books_dir(tmp_path):
    assert R._collect_preserved(tmp_path / "vault") == {}


def test_render_note_uses_preserved_override(tmp_path):
    # No note on disk; the preserved override seeds topics/aliases as if an
    # existing note carried them.
    vault = tmp_path / "vault"
    row = store.BookRow(book_id="X - A", title="X", authors=["A"], format="ebook")
    path = R.render_note(vault, row, [], preserved={"topics": ["[[History]]"], "aliases": ["Alt"]})
    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    assert post["topics"] == ["[[History]]"]
    assert post["aliases"] == ["Alt"]
    assert post["format"] == "ebook"  # still authoritative from the row
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/commands/test_render.py -k "collect_preserved or preserved_override" -v`
Expected: FAIL (`AttributeError: module ... has no attribute '_collect_preserved'`, and `render_note() got an unexpected keyword argument 'preserved'`).

- [ ] **Step 3: Implement `_collect_preserved` and the `preserved=` override**

In `books/renderers/obsidian/note.py`, add after the imports (near the top, below the existing `compose_review`/helpers is fine — place it above `render_note`):

```python
# User-owned frontmatter keys that live only in the note (never in the store).
# Cached before a --refresh delete and restored for books still in the catalog.
_PRESERVED_KEYS = ("topics", *PRESERVED_EXTRA_KEYS)


def _collect_preserved(vault: Path) -> dict[str, dict]:
    """Map each existing book note's stem -> its user-owned frontmatter keys.

    Reads every ``Books/*.md`` and keeps only :data:`_PRESERVED_KEYS` that are
    present (``topics`` + the preserved extras). Used before a ``--refresh``
    delete so surviving books get their hand-curated properties restored. A note
    with unreadable frontmatter is skipped.
    """
    books_dir = vault / BOOKS_DIRNAME
    cache: dict[str, dict] = {}
    if not books_dir.is_dir():
        return cache
    for note_path in sorted(books_dir.glob("*.md")):
        try:
            meta, _ = load_note(note_path)
        except Exception:  # skip a note whose frontmatter cannot be parsed
            continue
        kept = {k: meta[k] for k in _PRESERVED_KEYS if k in meta}
        if kept:
            cache[note_path.stem] = kept
    return cache
```

Then change `render_note`'s signature and its existing-frontmatter read. Replace:

```python
def render_note(vault: Path, row: BookRow, highlights: list) -> Path:
```

with:

```python
def render_note(
    vault: Path, row: BookRow, highlights: list, *, preserved: dict | None = None
) -> Path:
```

and replace the line:

```python
    existing_meta, existing_body = load_note(note_path)
```

with:

```python
    disk_meta, existing_body = load_note(note_path)
    existing_meta = preserved if preserved is not None else disk_meta
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/commands/test_render.py -k "collect_preserved or preserved_override" -v`
Expected: PASS.

- [ ] **Step 5: Run the full render test file to confirm no regressions**

Run: `uv run pytest tests/commands/test_render.py -q`
Expected: PASS (existing `render_note` calls use the default `preserved=None`).

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix && uv run ruff format
git add books/renderers/obsidian/note.py tests/commands/test_render.py
git commit -m "feat(render): cache user-owned props + preserved= override on render_note

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `render(vault, *, refresh=True)` deletes folders + restores props

**Files:**
- Modify: `books/renderers/obsidian/note.py`
- Test: `tests/commands/test_render.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/commands/test_render.py`:

```python
def test_render_refresh_deletes_stale_notes_and_author_stubs(tmp_path):
    vault = tmp_path / "vault"
    store.write_books_csv(
        vault, [store.BookRow(book_id="X - A", title="X", authors=["Ada Lovelace"])]
    )
    # Pre-existing stale files not backed by the current catalog.
    (vault / "Books").mkdir(parents=True)
    (vault / "Books" / "Gone - Z.md").write_text(
        "---\ntype: book\ntitle: Gone\n---\n", encoding="utf-8"
    )
    (vault / "Authors").mkdir(parents=True)
    (vault / "Authors" / "Old Author.md").write_text("---\ntype: author\n---\n", encoding="utf-8")
    R.render(vault, refresh=True)
    assert not (vault / "Books" / "Gone - Z.md").exists()  # stale note removed
    assert not (vault / "Authors" / "Old Author.md").exists()  # stale stub removed
    assert (vault / "Books" / "X - A.md").is_file()  # catalog book rebuilt
    assert (vault / "Authors" / "Ada Lovelace.md").is_file()  # its author rebuilt


def test_render_refresh_restores_props_for_surviving_books(tmp_path):
    vault = tmp_path / "vault"
    store.write_books_csv(
        vault, [store.BookRow(book_id="X - A", title="X", authors=["A"], format="ebook")]
    )
    note = vault / "Books" / "X - A.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        '---\ntype: book\ntitle: X\ntopics:\n- "[[History]]"\n'
        "aliases:\n- Alt\n---\n\nManual paragraph.\n",
        encoding="utf-8",
    )
    R.render(vault, refresh=True)
    post = frontmatter.loads(note.read_text(encoding="utf-8"))
    assert post["topics"] == ["[[History]]"]  # cached + restored
    assert post["aliases"] == ["Alt"]
    assert post["format"] == "ebook"  # authoritative from the row
    assert "Manual paragraph." not in post.content  # body is NOT preserved on refresh


def test_render_refresh_drops_props_for_deleted_books(tmp_path):
    # A note whose book is no longer in the catalog is gone and its cached props
    # are never restored (nothing to restore them onto).
    vault = tmp_path / "vault"
    store.write_books_csv(vault, [store.BookRow(book_id="X - A", title="X", authors=["A"])])
    gone = vault / "Books" / "Gone - Z.md"
    gone.parent.mkdir(parents=True)
    gone.write_text('---\ntype: book\ntitle: Gone\ntopics:\n- "[[Kept]]"\n---\n', encoding="utf-8")
    R.render(vault, refresh=True)
    assert not gone.exists()
    assert not any(p.name == "Gone - Z.md" for p in (vault / "Books").glob("*.md"))


def test_render_refresh_noop_when_dirs_absent(tmp_path):
    vault = tmp_path / "vault"
    store.write_books_csv(vault, [store.BookRow(book_id="X - A", title="X", authors=["A"])])
    # No Books/ or Authors/ exist yet; refresh must not raise.
    R.render(vault, refresh=True)
    assert (vault / "Books" / "X - A.md").is_file()


def test_render_refresh_idempotent(tmp_path):
    vault = tmp_path / "vault"
    store.write_books_csv(
        vault, [store.BookRow(book_id="X - A", title="X", authors=["A"], format="ebook")]
    )
    R.render(vault, refresh=True)
    before = {p: p.read_text(encoding="utf-8") for p in vault.rglob("*.md")}
    R.render(vault, refresh=True)
    after = {p: p.read_text(encoding="utf-8") for p in vault.rglob("*.md")}
    assert before == after
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/commands/test_render.py -k "refresh" -v`
Expected: FAIL (`render() got an unexpected keyword argument 'refresh'`).

- [ ] **Step 3: Implement folder deletion + cache/restore in `render`**

In `books/renderers/obsidian/note.py`, add this helper above `render`:

```python
def _clear_note_dirs(vault: Path) -> None:
    """Delete the ``Books/`` and ``Authors/`` folders (no-op when absent)."""
    for name in (BOOKS_DIRNAME, AUTHORS_DIRNAME):
        target = vault / name
        if target.is_dir():
            shutil.rmtree(target)
```

Then change `render`'s signature from:

```python
def render(vault: Path) -> dict:
```

to:

```python
def render(vault: Path, *, refresh: bool = False) -> dict:
```

and, immediately after the `stats = {...}` line at the top of `render`, insert:

```python
    cache = _collect_preserved(vault) if refresh else {}
    if refresh:
        _clear_note_dirs(vault)
```

Finally, in `render`'s loop, change the `render_note` call from:

```python
                    render_note(vault, row, highlights)
```

to:

```python
                    render_note(vault, row, highlights, preserved=cache.get(row.book_id))
```

(When not refreshing, `cache` is empty so `cache.get(...)` is `None` and `render_note` reads the on-disk note exactly as before.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/commands/test_render.py -k "refresh" -v`
Expected: PASS.

- [ ] **Step 5: Run the full render test file**

Run: `uv run pytest tests/commands/test_render.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix && uv run ruff format
git add books/renderers/obsidian/note.py tests/commands/test_render.py
git commit -m "feat(render): refresh mode deletes Books/Authors and restores props

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Thread `refresh` through the renderer seam

**Files:**
- Modify: `books/renderers/base.py`
- Modify: `books/renderers/obsidian/note.py` (`ObsidianRenderer.render`)
- Test: `tests/commands/test_render.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/commands/test_render.py`:

```python
def test_obsidian_renderer_forwards_refresh(tmp_path):
    from books.renderers import get_renderer

    vault = tmp_path / "vault"
    store.write_books_csv(vault, [store.BookRow(book_id="X - A", title="X", authors=["A"])])
    (vault / "Books").mkdir(parents=True)
    (vault / "Books" / "Gone - Z.md").write_text(
        "---\ntype: book\ntitle: Gone\n---\n", encoding="utf-8"
    )
    get_renderer("obsidian").render(vault, refresh=True)
    assert not (vault / "Books" / "Gone - Z.md").exists()  # refresh took effect
    assert (vault / "Books" / "X - A.md").is_file()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/commands/test_render.py::test_obsidian_renderer_forwards_refresh -v`
Expected: FAIL (`render() got an unexpected keyword argument 'refresh'` from `ObsidianRenderer.render`).

- [ ] **Step 3: Update the protocol and the Obsidian renderer**

In `books/renderers/base.py`, change:

```python
    def render(self, vault: Path) -> dict: ...
```

to:

```python
    def render(self, vault: Path, *, refresh: bool = False) -> dict: ...
```

In `books/renderers/obsidian/note.py`, change `ObsidianRenderer.render`:

```python
    def render(self, vault: Path) -> dict:
        return render(vault)
```

to:

```python
    def render(self, vault: Path, *, refresh: bool = False) -> dict:
        return render(vault, refresh=refresh)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/commands/test_render.py::test_obsidian_renderer_forwards_refresh -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix && uv run ruff format
git add books/renderers/base.py books/renderers/obsidian/note.py tests/commands/test_render.py
git commit -m "feat(render): add refresh to the Renderer protocol

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: `render --refresh` CLI option

**Files:**
- Modify: `books/commands/render.py`
- Test: `tests/commands/test_render.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/commands/test_render.py`:

```python
def test_render_command_refresh_deletes_stale_note(tmp_path):
    vault = tmp_path / "vault"
    store.write_layer(vault, "calibre", [store.BookRow(title="X", authors=["A"], format="ebook")])
    store.merge(vault)
    stale = vault / "Books" / "Gone - Z.md"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("---\ntype: book\ntitle: Gone\n---\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["render", "--refresh", "--output", str(vault)])
    assert result.exit_code == 0, result.output
    assert not stale.exists()
    assert (vault / "Books" / "X - A.md").is_file()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/commands/test_render.py::test_render_command_refresh_deletes_stale_note -v`
Expected: FAIL (`No such option: --refresh`, non-zero exit).

- [ ] **Step 3: Add the `--refresh` option to `render_command`**

In `books/commands/render.py`, add a new parameter to `render_command` (after the `obsidian` parameter, before the closing `) -> None:`):

```python
refresh: bool = (
    typer.Option(
        False,
        "--refresh",
        help="Delete Books/ and Authors/ before rendering (a clean rebuild that "
        "removes stale notes/stubs). Your topics/aliases/cssclasses are cached and "
        "restored for books still in the catalog.",
    ),
)
```

Then change the render call from:

```python
    stats = renderer.render(vault)
```

to:

```python
    stats = renderer.render(vault, refresh=refresh)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/commands/test_render.py::test_render_command_refresh_deletes_stale_note -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix && uv run ruff format
git add books/commands/render.py tests/commands/test_render.py
git commit -m "feat(render): add --refresh CLI flag

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: `sync --refresh` threading

**Files:**
- Modify: `books/commands/sync.py`
- Test: `tests/commands/test_sync.py`

- [ ] **Step 1: Update the test stub and add the forwarding test**

In `tests/commands/test_sync.py`, make the `_stub_runs` inner runner tolerate the extra `refresh` argument the render runner now receives. Change:

```python
            def run(vault):
                order.append(n)
                if failing == n:
                    raise RuntimeError(f"boom in {n}")
                return {}
```

to:

```python
            def run(vault, *args, **kwargs):
                order.append(n)
                if failing == n:
                    raise RuntimeError(f"boom in {n}")
                return {}
```

Then add this test at the end of the "Orchestration" section:

```python
def test_sync_refresh_forwarded_to_render(tmp_path, monkeypatch):
    vault = tmp_path / "Vault"
    vault.mkdir()
    _seed_all_sources(vault, monkeypatch)
    order = []
    _stub_runs(monkeypatch, order)

    captured = {}

    def render_run(vault, refresh=False):
        order.append("render")
        captured["refresh"] = refresh
        return {}

    monkeypatch.setattr(sync, "_run_render", render_run)
    sync.run_sync(vault, refresh=True)
    assert captured["refresh"] is True


def test_sync_refresh_defaults_false(tmp_path, monkeypatch):
    vault = tmp_path / "Vault"
    vault.mkdir()
    _seed_all_sources(vault, monkeypatch)
    order = []
    _stub_runs(monkeypatch, order)

    captured = {}

    def render_run(vault, refresh=False):
        order.append("render")
        captured["refresh"] = refresh
        return {}

    monkeypatch.setattr(sync, "_run_render", render_run)
    sync.run_sync(vault)
    assert captured["refresh"] is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/commands/test_sync.py -k "refresh" -v`
Expected: FAIL (`run_sync() got an unexpected keyword argument 'refresh'`).

- [ ] **Step 3: Thread `refresh` through sync**

In `books/commands/sync.py`:

(a) Change `_run_render` from:

```python
def _run_render(vault: Path) -> dict:
    return get_renderer("obsidian").render(vault)
```

to:

```python
def _run_render(vault: Path, refresh: bool = False) -> dict:
    return get_renderer("obsidian").render(vault, refresh=refresh)
```

(b) Change `_steps` to accept `refresh` and bind it into the render runner. Change the signature:

```python
def _steps() -> list[Step]:
```

to:

```python
def _steps(refresh: bool = False) -> list[Step]:
```

and change the render `Step` entry from:

```python
(Step("render", _detect_render, _run_render, _summ_render, "Data/books.csv"),)
```

to:

```python
(
    Step(
        "render",
        _detect_render,
        lambda v: _run_render(v, refresh),
        _summ_render,
        "Data/books.csv",
    ),
)
```

(The `lambda` looks up `_run_render` by name at call time, so tests that monkeypatch `sync._run_render` still take effect.)

(c) Change `run_sync` signature from:

```python
def run_sync(vault: Path, *, dry_run: bool = False) -> list[StepResult]:
```

to:

```python
def run_sync(vault: Path, *, dry_run: bool = False, refresh: bool = False) -> list[StepResult]:
```

and change the `for step in _steps():` line to:

```python
    for step in _steps(refresh):
```

(d) Add the `--refresh` option to the `sync` command. Add this parameter after `dry_run` (before the closing `) -> None:`):

```python
refresh: bool = (
    typer.Option(
        False,
        "--refresh",
        help="Delete Books/ and Authors/ before the render step (a clean rebuild). "
        "Your topics/aliases/cssclasses are cached and restored for books still in "
        "the catalog. Ignored under --dry-run.",
    ),
)
```

and change the final call from:

```python
    run_sync(vault, dry_run=dry_run)
```

to:

```python
    run_sync(vault, dry_run=dry_run, refresh=refresh)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/commands/test_sync.py -k "refresh" -v`
Expected: PASS.

- [ ] **Step 5: Run the full sync test file**

Run: `uv run pytest tests/commands/test_sync.py -q`
Expected: PASS (the `_stub_runs` change keeps existing tests green).

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix && uv run ruff format
git add books/commands/sync.py tests/commands/test_sync.py
git commit -m "feat(sync): add --refresh flag forwarded to the render step

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Full verification + docs

**Files:**
- Modify: `CLAUDE.md` (update the `render` and `sync` capability descriptions)

- [ ] **Step 1: Run the entire suite + lint**

Run:
```bash
uv run ruff check --fix && uv run ruff format
uv run pytest -q
```
Expected: all tests PASS, lint clean.

- [ ] **Step 2: Update `CLAUDE.md`**

In the `render` bullet, append a sentence describing `--refresh`:

> `--refresh` does a clean rebuild — it deletes `Books/` and `Authors/` before rendering (removing stale notes/stubs), caching each existing note's user-owned `topics`/`aliases`/`cssclasses` and restoring them for books still in the catalog (a book dropped from the catalog loses its note and cached props; a book note's manual body text is not preserved).

In the `sync` bullet, append:

> `--refresh` is forwarded to the `render` step (clean rebuild of `Books/`/`Authors/`); it is ignored under `--dry-run`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document --refresh on render/sync

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review Notes

- **Spec coverage:** delete `Books/`+`Authors/` (Task 2, 3, 4, 5); cache `topics`/`aliases`/`cssclasses` (Task 1); restore only for surviving books (Task 2 `test_render_refresh_restores_props_for_surviving_books` / `test_render_refresh_drops_props_for_deleted_books`); no-op when dirs absent (Task 2); idempotence (Task 2); `--dry-run` writes/deletes nothing (deletion only runs inside `_run_render`, which dry-run never calls — covered by existing `test_dry_run_does_not_execute`); protocol threading (Task 3); both CLI flags (Task 4, 5).
- **Type consistency:** `render(vault, *, refresh=False)`, `render_note(..., *, preserved=None)`, `Renderer.render(self, vault, *, refresh=False)`, `_run_render(vault, refresh=False)`, `run_sync(vault, *, dry_run=False, refresh=False)`, `_steps(refresh=False)` — consistent across tasks.
- **No placeholders:** every code step shows the exact code.
