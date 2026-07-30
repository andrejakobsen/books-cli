# Audible Clips Importer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `books audible` command that imports Audible bookmarks & clips into existing Obsidian book notes, transcribing each clip's audio into text, mirroring how `kobo`/`highlighted` enrich notes.

**Architecture:** A new capability split into three files: `books/audible_obsidian.py` (pure domain logic + orchestration + CLI, stdlib+Typer only, all heavy I/O injected — the covers.py pattern), `books/audible_client.py` (the Audible cloud adapter: auth, library, annotations, chapters, download+voucher-decrypt — lazily imports the `audible` package), and `books/audible_transcribe.py` (ffmpeg clip-cutting + pluggable transcriber factory — lazily imports `faster-whisper`/`openai`/`SpeechRecognition`). Transcriptions are cached in `<vault>/.imports/audible/cache.json` so re-runs are free and only books with new clips are downloaded. It is a highlight importer: it matches existing notes (by ASIN as `amazon`, then title/author) and never creates them.

**Tech Stack:** Python 3.11+, Typer, `audible` (cloud API + `audible.aescipher` voucher decryption), optional `cryptography` (accelerates decryption), system `ffmpeg` (decrypt+cut AAXC via `-audible_key`/`-audible_iv`), pluggable transcriber (`faster-whisper` local / OpenAI API / Google via `SpeechRecognition`+`pydub`). All declared as an optional `[audible]` extra; base `books` stays stdlib+Typer.

**Reference spec:** `docs/superpowers/specs/2026-07-27-audible-clips-design.md`

---

## Notes for the implementer

- Run `uv run pytest -q` before every commit. Commit directly to `main` (see CLAUDE.md — no branches/PRs).
- The pure logic in `audible_obsidian.py` and the helpers in `audible_transcribe.py` are covered by unit tests with **injected fakes** (no network, no ffmpeg, no models) — exactly like `tests/test_covers.py` injects `fetch_json`/`fetch_bytes`.
- `books/audible_client.py` is the **integration seam**: its networked methods talk to Audible's live API and cannot be unit-tested without a real account. Only its pure helpers (`default_auth_path`, the missing-dependency error) get unit tests. Task 12 is a manual verification pass against a real account; adjust live API field names there if Audible's responses differ from the documented shapes.
- Study these existing files before starting: `books/kobo_export.py` (row→Highlight mapping, `render_marked_section`, `VaultIndex.find`, `write_stub`), `books/covers.py` (injected-I/O + `run()` + Typer command pattern), `books/highlights.py` (the `Highlight` model, `render_highlights`, `parse_markers`), `books/config.py` (`resolve_vault`, `resolve_imports`, `config_path`).

---

## Task 1: Scaffold the module and register the command

**Files:**
- Create: `books/audible_obsidian.py`
- Modify: `books/cli.py:16-35`
- Test: `tests/test_audible_obsidian.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audible_obsidian.py`:

```python
"""Tests for the Audible clips importer."""

from pathlib import Path

from typer.testing import CliRunner

from books import audible_obsidian as ao
from books.cli import app

runner = CliRunner()


def test_command_is_registered():
    result = runner.invoke(app, ["audible", "--help"])
    assert result.exit_code == 0, result.output
    assert "audible" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audible_obsidian.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'books.audible_obsidian'`

- [ ] **Step 3: Create the module skeleton**

Create `books/audible_obsidian.py`:

```python
#!/usr/bin/env python3
"""Import Audible bookmarks & clips into existing Obsidian book notes.

Audible bookmarks/clips live in your Audible cloud account. This importer
authenticates (via the optional `audible` package), fetches your library and each
book's annotations, downloads the audiobook, and uses ffmpeg to decrypt + cut each
clip's audio, which is transcribed into text and embedded under a marker-wrapped
"## Highlights" heading of the *matching* book note. Like kobo/highlighted, it only
enriches notes created by calibre/goodreads -- it never creates book notes; a book
with no matching note is skipped and counted. Books match by ASIN (the `amazon`
frontmatter id), then by standardized title/author.

Transcriptions are cached in <vault>/.imports/audible/cache.json (keyed by
ASIN + annotation id), so re-runs re-render for free and only download a book that
has new clips; downloaded audio is written to a temp dir and deleted after cutting.

This is the one capability that needs third-party packages and system ffmpeg (the
documented exception to the stdlib-only rule). Heavy dependencies are imported
lazily so the rest of the CLI never touches them. Downloading/decrypting owned
audiobooks is for personal archival use only.
"""

from __future__ import annotations

import typer


def audible_command() -> None:
    """Import Audible bookmarks & clips into existing Obsidian book notes."""
    typer.echo("not implemented yet")


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("audible")(audible_command)


def main() -> None:
    """Standalone entry point so the shim script keeps working on its own."""
    typer.run(audible_command)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Register in the CLI hub**

In `books/cli.py`, add `audible_obsidian` to the import block and to `CAPABILITIES` (keep alphabetical-ish ordering used there):

```python
from books import (
    audible_obsidian,
    calibre_obsidian,
    covers,
    goodreads_obsidian,
    highlighted_obsidian,
    kobo_export,
    readwise_obsidian,
    sync,
)

# Modules that expose a register(app) function. Add new capabilities here.
CAPABILITIES = (
    audible_obsidian,
    calibre_obsidian,
    covers,
    goodreads_obsidian,
    highlighted_obsidian,
    kobo_export,
    readwise_obsidian,
    sync,
)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_audible_obsidian.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add books/audible_obsidian.py books/cli.py tests/test_audible_obsidian.py
git commit -m "feat(audible): scaffold audible command + register capability

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Support a bare timestamp locator in the shared renderer

The audio locator is a timestamp (`3:24:15`) with no `p.`/`loc.` unit. Let an explicitly-empty `location_label` suppress the prefix. `None` keeps the current `p.` default, so existing callers are unaffected.

**Files:**
- Modify: `books/highlights.py:207-216` (the `_label` function)
- Test: `tests/test_highlights.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_highlights.py`:

```python
def test_empty_location_label_renders_bare_timestamp():
    from books.highlights import Highlight, render_highlights

    h = Highlight(text="A passage.", page="3:24:15", location_label="")
    out = render_highlights([h])
    assert "> [!quote]+ 3:24:15" in out
    assert "p. 3:24:15" not in out


def test_none_location_label_still_defaults_to_p():
    from books.highlights import Highlight, render_highlights

    h = Highlight(text="A passage.", page="42")
    out = render_highlights([h])
    assert "> [!quote]+ p. 42" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_highlights.py -k location_label -q`
Expected: FAIL — the empty-label case renders `p. 3:24:15`.

- [ ] **Step 3: Update `_label`**

In `books/highlights.py`, replace the `if h.page:` block inside `_label`:

```python
def _label(h: Highlight, chapter_prefix: str = "ch.") -> str:
    parts: list[str] = []
    if h.chapter_index is not None:
        parts.append(f"{chapter_prefix} {h.chapter_index}")
    if h.page:
        label = h.page.replace("-", "–")
        # location_label is "p." by default; an explicit "" suppresses the prefix
        # (used for audio timestamps like "3:24:15" that carry no unit).
        prefix = h.location_label if h.location_label is not None else "p."
        parts.append(f"{prefix} {label}" if prefix else label)
    if h.progress is not None:
        parts.append(f"{round(h.progress * 100)}%")
    return " · ".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_highlights.py -q`
Expected: PASS (new tests + all existing highlights tests still green)

- [ ] **Step 5: Commit**

```bash
git add books/highlights.py tests/test_highlights.py
git commit -m "feat(highlights): let empty location_label render a bare locator

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Domain dataclasses + timestamp formatting + chapter lookup

**Files:**
- Modify: `books/audible_obsidian.py`
- Test: `tests/test_audible_obsidian.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audible_obsidian.py`:

```python
def test_format_timestamp_always_has_hours():
    assert ao.format_timestamp(0) == "0:00:00"
    assert ao.format_timestamp(754_000) == "0:12:34"
    assert ao.format_timestamp(3_600_000) == "1:00:00"
    assert ao.format_timestamp(12_305_000) == "3:25:05"
    assert ao.format_timestamp(-5) == "0:00:00"  # clamps negatives


def test_chapter_for_finds_containing_chapter():
    chapters = [
        ao.Chapter(index=1, title="Intro", start_ms=0, end_ms=60_000),
        ao.Chapter(index=2, title="Rise", start_ms=60_000, end_ms=120_000),
    ]
    assert ao.chapter_for(0, chapters).title == "Intro"
    assert ao.chapter_for(59_999, chapters).title == "Intro"
    assert ao.chapter_for(60_000, chapters).title == "Rise"
    assert ao.chapter_for(999_999, chapters) is None
    assert ao.chapter_for(0, []) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audible_obsidian.py -k "timestamp or chapter_for" -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'format_timestamp'`

- [ ] **Step 3: Implement the dataclasses and helpers**

In `books/audible_obsidian.py`, add after the imports (add `from dataclasses import dataclass, field`):

```python
from dataclasses import dataclass, field


@dataclass
class LibraryBook:
    """A book in the Audible library."""

    asin: str
    title: str
    authors: list[str] = field(default_factory=list)


@dataclass
class Annotation:
    """A single Audible bookmark, clip, or note.

    `end_ms` is None for a point bookmark (the plain "bookmark" button has no
    duration); a clip carries both start and end. `note` is the user's typed text
    (may be None).
    """

    id: str
    start_ms: int
    end_ms: int | None = None
    note: str | None = None
    date: str | None = None


@dataclass
class Chapter:
    """A chapter with its position range (end exclusive), in reading order."""

    index: int
    title: str
    start_ms: int
    end_ms: int


@dataclass
class DownloadedAudio:
    """A downloaded (still-encrypted) audiobook plus its AAXC decryption key/iv.

    `key`/`iv` are None for a non-DRM source; when set, ffmpeg decrypts on the fly
    via -audible_key/-audible_iv while cutting each clip.
    """

    path: "Path"
    key: str | None = None
    iv: str | None = None


def format_timestamp(ms: int) -> str:
    """Format a millisecond offset as ``H:MM:SS`` (hours always present).

    Hours are always the leading component, so the string's leading integer equals
    the hour count -- keeping reading order correct under Highlight.sort_key, which
    reads the first integer of the locator. Negative inputs clamp to zero.
    """
    total = max(0, int(ms)) // 1000
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def chapter_for(start_ms: int, chapters: list[Chapter]) -> Chapter | None:
    """Return the chapter whose [start, end) range contains *start_ms*, else None."""
    for ch in chapters:
        if ch.start_ms <= start_ms < ch.end_ms:
            return ch
    return None
```

Also add `from pathlib import Path` to the imports (used in the type hints above and later tasks).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audible_obsidian.py -k "timestamp or chapter_for" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add books/audible_obsidian.py tests/test_audible_obsidian.py
git commit -m "feat(audible): add domain dataclasses, timestamp + chapter helpers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Annotation → cache-record → Highlight mapping

The cache record is the single intermediate: a new clip becomes a record (stored in `cache.json`), and every render builds `Highlight`s from records. This keeps the DRY rule (transcription time and re-render time share one mapping).

**Files:**
- Modify: `books/audible_obsidian.py`
- Test: `tests/test_audible_obsidian.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audible_obsidian.py`:

```python
def _chapters():
    return [ao.Chapter(index=2, title="The Rise", start_ms=60_000, end_ms=600_000)]


def test_annotation_to_record_maps_clip_with_chapter():
    ann = ao.Annotation(
        id="a1", start_ms=120_000, end_ms=150_000, note="Key idea #power @stalin", date="2026-07-01"
    )
    rec = ao.annotation_to_record(ann, "This is the clip text.", _chapters())
    assert rec["text"] == "This is the clip text."
    assert rec["start_ms"] == 120_000
    assert rec["end_ms"] == 150_000
    assert rec["note"] == "Key idea #power @stalin"
    assert rec["chapter"] == "The Rise"
    assert rec["chapter_index"] == 2


def test_record_to_highlight_renders_bare_timestamp_and_markers():
    rec = {
        "text": "This is the clip text.",
        "start_ms": 120_000,
        "end_ms": 150_000,
        "note": "Key idea #power @stalin",
        "date": "2026-07-01",
        "chapter": "The Rise",
        "chapter_index": 2,
    }
    h = ao.record_to_highlight(rec)
    assert h.text == "This is the clip text."
    assert h.note == "Key idea"  # markers stripped from note
    assert h.tags == ["power"]
    assert h.links == ["Stalin"]
    assert h.chapter_index == 2
    assert h.chapter_title == "The Rise"
    assert h.page == "2:00:00"  # 120_000 ms
    assert h.location_label == ""  # bare timestamp
    assert h.block == "000000120000"  # zero-padded ms for exact ordering


def test_record_to_highlight_falls_back_to_note_when_no_text():
    rec = {
        "text": "",
        "start_ms": 0,
        "end_ms": None,
        "note": "Just my note",
        "date": None,
        "chapter": None,
        "chapter_index": None,
    }
    h = ao.record_to_highlight(rec)
    assert h.text == "Just my note"  # note used as body
    assert h.note is None  # not duplicated
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audible_obsidian.py -k "record" -q`
Expected: FAIL — `AttributeError: ... 'annotation_to_record'`

- [ ] **Step 3: Implement the mapping**

Add to `books/audible_obsidian.py` (add `from books.highlights import Highlight, parse_markers, render_highlights` to imports):

```python
from books.highlights import Highlight, parse_markers, render_highlights


def annotation_to_record(ann: Annotation, text: str, chapters: list[Chapter]) -> dict:
    """Build the cache record for a transcribed annotation."""
    ch = chapter_for(ann.start_ms, chapters)
    return {
        "text": (text or "").strip(),
        "start_ms": int(ann.start_ms),
        "end_ms": None if ann.end_ms is None else int(ann.end_ms),
        "note": ann.note,
        "date": ann.date,
        "chapter": ch.title if ch else None,
        "chapter_index": ch.index if ch else None,
    }


def record_to_highlight(rec: dict) -> Highlight:
    """Build a source-agnostic Highlight from a cache record.

    The transcription is the highlight text; the user's typed note becomes the
    nested blockquote (with its #tag/@link markers parsed out, same convention as
    Kobo). When there is no transcription, the note text is used as the body so a
    bookmark that carries only a note still comes through. The locator is a bare
    timestamp (empty location_label); the zero-padded ms position goes in `block`
    so highlights sort in exact listening order.
    """
    note, links, tags = parse_markers((rec.get("note") or "").strip() or None)
    body = (rec.get("text") or "").strip()
    if not body:
        body = note or ""
        note = None
    start = int(rec.get("start_ms") or 0)
    idx = rec.get("chapter_index")
    return Highlight(
        text=body,
        note=note,
        chapter_index=idx if isinstance(idx, int) else None,
        chapter_title=(rec.get("chapter") or None),
        page=format_timestamp(start),
        location_label="",
        block=f"{max(0, start):012d}",
        date=rec.get("date"),
        tags=tags,
        links=links,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audible_obsidian.py -k "record" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add books/audible_obsidian.py tests/test_audible_obsidian.py
git commit -m "feat(audible): map annotations to cache records and highlights

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Transcription cache read/write + new-clip diff

**Files:**
- Modify: `books/audible_obsidian.py`
- Test: `tests/test_audible_obsidian.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audible_obsidian.py`:

```python
def test_cache_roundtrip_and_missing(tmp_path):
    path = tmp_path / "sub" / "cache.json"
    assert ao.load_cache(path) == {}  # missing file -> {}
    data = {"B01": {"title": "Stalin", "clips": {"a1": {"text": "hi"}}}}
    ao.save_cache(path, data)
    assert ao.load_cache(path) == data


def test_load_cache_tolerates_corrupt_file(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("{not json", encoding="utf-8")
    assert ao.load_cache(path) == {}


def test_uncached_returns_only_new_annotations():
    anns = [ao.Annotation(id="a1", start_ms=0), ao.Annotation(id="a2", start_ms=10)]
    clips = {"a1": {"text": "already"}}
    new = ao.uncached(anns, clips)
    assert [a.id for a in new] == ["a2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audible_obsidian.py -k "cache or uncached" -q`
Expected: FAIL — `AttributeError: ... 'load_cache'`

- [ ] **Step 3: Implement the cache helpers**

Add to `books/audible_obsidian.py` (add `import json` to imports):

```python
import json


def load_cache(path: Path) -> dict:
    """Load the transcription cache, or {} when missing/corrupt."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(path: Path, data: dict) -> None:
    """Write the transcription cache as pretty JSON (parents created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def uncached(annotations: list[Annotation], clips: dict) -> list[Annotation]:
    """Return the annotations whose id is not already in the cached clips."""
    return [a for a in annotations if a.id not in clips]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audible_obsidian.py -k "cache or uncached" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add books/audible_obsidian.py tests/test_audible_obsidian.py
git commit -m "feat(audible): add transcription cache and new-clip diff

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Render a book's clips into its note

**Files:**
- Modify: `books/audible_obsidian.py`
- Test: `tests/test_audible_obsidian.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audible_obsidian.py`:

```python
def _seed_note(out, stem, frontmatter):
    books = out / "Books"
    books.mkdir(parents=True, exist_ok=True)
    note = books / f"{stem}.md"
    note.write_text(frontmatter, encoding="utf-8")
    return note


def test_render_note_writes_frontmatter_and_marked_section(tmp_path):
    out = tmp_path / "V"
    note = _seed_note(
        out,
        "Stalin - Stephen Kotkin",
        '---\ntype: book\ntitle: "Stalin"\n'
        'authors: ["[[Stephen Kotkin]]"]\namazon: ""\nsource: ""\n'
        'highlighted: false\ncover: ""\n---\n\nMy body.\n',
    )
    book = ao.LibraryBook(asin="B0ASIN", title="Stalin", authors=["Stephen Kotkin"])
    clips = {
        "a1": {
            "text": "First clip.",
            "start_ms": 120_000,
            "end_ms": 150_000,
            "note": None,
            "date": None,
            "chapter": "The Rise",
            "chapter_index": 2,
        },
    }
    n = ao.render_note(note, book, clips)
    assert n == 1
    text = note.read_text(encoding="utf-8")
    assert "My body." in text  # body preserved
    assert "amazon: B0ASIN" in text  # ASIN backfilled
    assert "source: audible" in text
    assert "highlighted: true" in text
    assert "## Highlights" in text
    assert "%% books:highlights:start %%" in text
    assert "### The Rise" in text  # chapter grouping header
    assert "Audible ch. 2 · 0:02:00" in text  # chapter_label + bare timestamp (120_000 ms)
    assert "First clip." in text


def test_render_note_skips_empty_text_highlights(tmp_path):
    out = tmp_path / "V"
    note = _seed_note(out, "Stalin - Stephen Kotkin", '---\ntype: book\ntitle: "Stalin"\n---\n')
    book = ao.LibraryBook(asin="B0ASIN", title="Stalin")
    clips = {
        "a1": {
            "text": "",
            "start_ms": 0,
            "end_ms": None,
            "note": None,
            "date": None,
            "chapter": None,
            "chapter_index": None,
        }
    }
    assert ao.render_note(note, book, clips) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audible_obsidian.py -k "render_note" -q`
Expected: FAIL — `AttributeError: ... 'render_note'`

- [ ] **Step 3: Implement `render_note`**

Add to `books/audible_obsidian.py` (add the obsidian imports):

```python
from books.obsidian import (
    AUTHORS_DIRNAME,
    BookRef,
    VaultIndex,
    link_list,
    render_marked_section,
    update_frontmatter,
    write_stub,
    yaml_quote,
)


def render_note(note_path: Path, book: LibraryBook, clips: dict) -> int:
    """Enrich an existing book note with a book's cached clips.

    Fills provenance frontmatter (never overwriting existing values, except the
    `highlighted` flag which flips to true) and replaces the marked
    "## Highlights" section. Empty-text records are dropped. Returns the number of
    highlights written.
    """
    highlights = [record_to_highlight(rec) for rec in clips.values()]
    highlights = [h for h in highlights if h.text]

    updates = {
        "title": yaml_quote(book.title),
        "authors": link_list(book.authors) if book.authors else "",
        "amazon": yaml_quote(book.asin) if book.asin else "",
        "source": "audible",
        "highlighted": "true",
    }
    base = note_path.read_text(encoding="utf-8")
    note_path.write_text(update_frontmatter(base, updates), encoding="utf-8")

    text = note_path.read_text(encoding="utf-8")
    text = render_marked_section(
        text, "Highlights", "highlights", render_highlights(highlights, chapter_label="Audible ch.")
    )
    note_path.write_text(text, encoding="utf-8")
    return len(highlights)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audible_obsidian.py -k "render_note" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add books/audible_obsidian.py tests/test_audible_obsidian.py
git commit -m "feat(audible): render a book's cached clips into its note

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: The `run()` orchestrator (with injected I/O)

This is the heart: match books, download-only-when-new, cut+transcribe new clips, cache, render. All heavy I/O (`client`, `downloader`, `cutter`, `transcriber`) is injected so tests run offline — the `covers.run(...)` pattern.

**Files:**
- Modify: `books/audible_obsidian.py`
- Test: `tests/test_audible_obsidian.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audible_obsidian.py` (fakes + tests):

```python
class FakeClient:
    def __init__(self, library, annotations, chapters=None):
        self._library = library
        self._annotations = annotations  # {asin: [Annotation]}
        self._chapters = chapters or {}  # {asin: [Chapter]}
        self.annotation_calls = []

    def library(self):
        return list(self._library)

    def annotations(self, asin):
        self.annotation_calls.append(asin)
        return list(self._annotations.get(asin, []))

    def chapters(self, asin):
        return list(self._chapters.get(asin, []))


class FakeDownloader:
    def __init__(self):
        self.calls = []

    def download(self, asin, dest_dir):
        self.calls.append(asin)
        p = Path(dest_dir) / f"{asin}.aaxc"
        p.write_bytes(b"fake-audio")
        return ao.DownloadedAudio(path=p, key=None, iv=None)


class FakeCutter:
    def __init__(self):
        self.calls = []

    def cut(self, audio, start_ms, end_ms, dest):
        self.calls.append((audio.path.name, start_ms, end_ms))
        Path(dest).write_bytes(b"clip")
        return Path(dest)


def _fake_transcriber(path):
    return "transcribed text"


def _library_and_notes(tmp_path):
    out = tmp_path / "V"
    _seed_note(
        out,
        "Stalin - Stephen Kotkin",
        '---\ntype: book\ntitle: "Stalin"\nauthors: ["[[Stephen Kotkin]]"]\namazon: ""\n---\n',
    )
    book = ao.LibraryBook(asin="B0STALIN", title="Stalin", authors=["Stephen Kotkin"])
    anns = {"B0STALIN": [ao.Annotation(id="a1", start_ms=120_000, end_ms=150_000, note="Nice")]}
    return out, book, anns


def test_run_enriches_matched_and_writes_cache(tmp_path):
    out, book, anns = _library_and_notes(tmp_path)
    client = FakeClient([book], anns)
    cache_path = out / ".imports" / "audible" / "cache.json"
    down, cut = FakeDownloader(), FakeCutter()
    stats = ao.run(
        out,
        client=client,
        downloader=down,
        cutter=cut,
        transcriber=_fake_transcriber,
        cache_path=cache_path,
        clip_window=30,
    )
    assert stats["books"] == 1 and stats["entries"] == 1
    assert stats["downloaded"] == 1 and stats["transcribed"] == 1
    note = out / "Books" / "Stalin - Stephen Kotkin.md"
    assert "transcribed text" in note.read_text()
    cache = ao.load_cache(cache_path)
    assert cache["B0STALIN"]["clips"]["a1"]["text"] == "transcribed text"


def test_run_skips_unmatched_without_download(tmp_path):
    out = tmp_path / "V"
    (out / "Books").mkdir(parents=True)  # no matching note
    book = ao.LibraryBook(asin="B0X", title="Unknown", authors=["Nobody"])
    client = FakeClient([book], {"B0X": [ao.Annotation(id="a1", start_ms=0, end_ms=10)]})
    down = FakeDownloader()
    stats = ao.run(
        out,
        client=client,
        downloader=down,
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_path=out / "c.json",
        clip_window=30,
    )
    assert stats["skipped"] == 1 and stats["books"] == 0
    assert down.calls == []  # never downloaded


def test_run_idempotent_uses_cache_no_redownload(tmp_path):
    out, book, anns = _library_and_notes(tmp_path)
    cache_path = out / ".imports" / "audible" / "cache.json"
    down1 = FakeDownloader()
    ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=down1,
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_path=cache_path,
        clip_window=30,
    )
    before = (out / "Books" / "Stalin - Stephen Kotkin.md").read_text()
    down2 = FakeDownloader()
    ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=down2,
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_path=cache_path,
        clip_window=30,
    )
    after = (out / "Books" / "Stalin - Stephen Kotkin.md").read_text()
    assert down2.calls == []  # no new clips -> no download
    assert before == after  # note unchanged


def test_run_point_bookmark_uses_window_before_mark(tmp_path):
    out = tmp_path / "V"
    _seed_note(
        out,
        "Stalin - Stephen Kotkin",
        '---\ntype: book\ntitle: "Stalin"\nauthors: ["[[Stephen Kotkin]]"]\n---\n',
    )
    book = ao.LibraryBook(asin="B0STALIN", title="Stalin", authors=["Stephen Kotkin"])
    anns = {"B0STALIN": [ao.Annotation(id="a1", start_ms=90_000, end_ms=None)]}
    cut = FakeCutter()
    ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=FakeDownloader(),
        cutter=cut,
        transcriber=_fake_transcriber,
        cache_path=out / "c.json",
        clip_window=30,
    )
    # point bookmark: window ends at the mark, starts clip_window seconds earlier
    assert cut.calls == [("B0STALIN.aaxc", 60_000, 90_000)]


def test_run_dry_run_writes_nothing(tmp_path):
    out, book, anns = _library_and_notes(tmp_path)
    note = out / "Books" / "Stalin - Stephen Kotkin.md"
    before = note.read_text()
    down = FakeDownloader()
    stats = ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=down,
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_path=out / "c.json",
        clip_window=30,
        dry_run=True,
    )
    assert down.calls == []
    assert note.read_text() == before
    assert not (out / "c.json").exists()
    assert stats["books"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audible_obsidian.py -k "run_" -q`
Expected: FAIL — `AttributeError: ... 'run'`

- [ ] **Step 3: Implement `run()`**

Add to `books/audible_obsidian.py` (add `import tempfile` to imports):

```python
import tempfile


def _clip_bounds(ann: Annotation, clip_window: int) -> tuple[int, int]:
    """Resolve the (start_ms, end_ms) audio range to cut for an annotation.

    A clip uses its own recorded start/end. A point bookmark (no end position) has
    no duration, so a *clip_window*-second window ending at the mark is used
    (people bookmark just after hearing something)."""
    if ann.end_ms is not None:
        return int(ann.start_ms), int(ann.end_ms)
    end = int(ann.start_ms)
    return max(0, end - clip_window * 1000), end


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
    """Import Audible clips into matching notes. All heavy I/O is injected.

    Returns a stats dict: books/entries/skipped/downloaded/transcribed. In
    *dry_run* mode nothing is downloaded, transcribed, cached, or written; the plan
    is emitted via *echo*.
    """
    vault.mkdir(parents=True, exist_ok=True)
    index = VaultIndex(vault)
    authors_dir = vault / AUTHORS_DIRNAME
    cache = load_cache(cache_path)
    stats = {"books": 0, "entries": 0, "skipped": 0, "downloaded": 0, "transcribed": 0}

    library = client.library()
    if asin:
        library = [b for b in library if b.asin == asin]

    matched = 0
    for book in library:
        ref = BookRef(title=book.title, authors=book.authors, amazon=book.asin)
        dest = index.find(ref)
        if dest is None:
            stats["skipped"] += 1
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

        if dry_run:
            echo(
                f"[dry-run] {book.title}: {len(annotations)} annotations, "
                f"{len(new)} new to transcribe"
            )
            continue

        if new:
            chapters = client.chapters(book.asin)
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                audio = downloader.download(book.asin, tmp)
                stats["downloaded"] += 1
                for ann in new:
                    start, end = _clip_bounds(ann, clip_window)
                    clip_path = cutter.cut(audio, start, end, tmp / f"{ann.id}.wav")
                    text = transcriber(clip_path)
                    clips[ann.id] = annotation_to_record(ann, text, chapters)
                    stats["transcribed"] += 1
            save_cache(cache_path, cache)

        n = render_note(dest.note_path, book, clips)
        for author in book.authors:
            write_stub(authors_dir, author, "author")
        stats["books"] += 1
        stats["entries"] += n

    return stats
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audible_obsidian.py -k "run_" -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add books/audible_obsidian.py tests/test_audible_obsidian.py
git commit -m "feat(audible): add run() orchestrator with injected I/O

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 8: ffmpeg cutter + pluggable transcriber factory

**Files:**
- Create: `books/audible_transcribe.py`
- Test: `tests/test_audible_transcribe.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audible_transcribe.py`:

```python
"""Tests for the Audible ffmpeg cutter + transcriber factory."""

import subprocess

import pytest

from books import audible_obsidian as ao
from books import audible_transcribe as at


def test_check_ffmpeg_raises_when_missing(monkeypatch):
    monkeypatch.setattr(at.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        at.check_ffmpeg()


def test_check_ffmpeg_ok_when_present(monkeypatch):
    monkeypatch.setattr(at.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    at.check_ffmpeg()  # no raise


def test_cut_clip_builds_plain_ffmpeg_command(monkeypatch, tmp_path):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(at.subprocess, "run", fake_run)
    audio = ao.DownloadedAudio(path=tmp_path / "b.aaxc", key=None, iv=None)
    dest = tmp_path / "clip.wav"
    assert at.cut_clip(audio, 60_000, 90_000, dest) == dest
    cmd = calls["cmd"]
    assert cmd[0] == "ffmpeg"
    assert "-ss" in cmd and "60.000" in cmd
    assert "-to" in cmd and "90.000" in cmd
    assert "-audible_key" not in cmd  # no DRM key -> no decrypt flags
    assert str(dest) in cmd


def test_cut_clip_passes_audible_key_iv_when_present(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(at.subprocess, "run", lambda cmd, **k: calls.setdefault("cmd", cmd))
    audio = ao.DownloadedAudio(path=tmp_path / "b.aaxc", key="KEY", iv="IV")
    at.cut_clip(audio, 0, 5_000, tmp_path / "c.wav")
    cmd = calls["cmd"]
    assert "-audible_key" in cmd and "KEY" in cmd
    assert "-audible_iv" in cmd and "IV" in cmd
    # decrypt flags must precede -i so ffmpeg applies them to the input
    assert cmd.index("-audible_key") < cmd.index("-i")


def test_make_transcriber_rejects_unknown_backend():
    with pytest.raises(ValueError, match="unknown transcriber"):
        at.make_transcriber("bogus")


def test_make_transcriber_dispatches(monkeypatch):
    monkeypatch.setattr(at, "_local_transcriber", lambda model: "LOCAL")
    monkeypatch.setattr(at, "_openai_transcriber", lambda model: "OPENAI")
    monkeypatch.setattr(at, "_google_transcriber", lambda: "GOOGLE")
    assert at.make_transcriber("local") == "LOCAL"
    assert at.make_transcriber("openai") == "OPENAI"
    assert at.make_transcriber("google") == "GOOGLE"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audible_transcribe.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'books.audible_transcribe'`

- [ ] **Step 3: Implement the module**

Create `books/audible_transcribe.py`:

```python
"""ffmpeg clip-cutting + a pluggable speech-to-text transcriber factory.

ffmpeg decrypts (AAXC via -audible_key/-audible_iv) and cuts each clip in one
pass. The transcriber is chosen at runtime: `local` (faster-whisper, no key,
offline), `openai` (OpenAI audio API, needs OPENAI_API_KEY), or `google`
(SpeechRecognition's free recognizer). Every backend's heavy import is lazy so the
rest of the CLI never loads them; a missing dependency raises a clear install hint.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from books.audible_obsidian import DownloadedAudio

_MISSING = (
    "Audible support needs extra dependencies. Install them with:\n"
    "  uv tool install '.[audible]'    (or: pip install 'books[audible]')"
)


def check_ffmpeg() -> None:
    """Raise RuntimeError with an install hint if ffmpeg is not on PATH."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found on PATH — install it (e.g. `brew install ffmpeg`) "
            "to cut and decrypt Audible clips."
        )


def cut_clip(audio: DownloadedAudio, start_ms: int, end_ms: int, dest: Path) -> Path:
    """Cut [start_ms, end_ms) of *audio* into a 16 kHz mono WAV at *dest*.

    When the source is DRM-protected AAXC, the voucher key/iv are passed as input
    options (before -i) so ffmpeg decrypts on the fly. Returns *dest*.
    """
    cmd = ["ffmpeg", "-nostdin", "-y"]
    if audio.key and audio.iv:
        cmd += ["-audible_key", audio.key, "-audible_iv", audio.iv]
    cmd += [
        "-i",
        str(audio.path),
        "-ss",
        f"{start_ms / 1000:.3f}",
        "-to",
        f"{end_ms / 1000:.3f}",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return dest


def make_transcriber(kind: str, model: str = "small"):
    """Return a ``transcribe(clip_path) -> str`` callable for the chosen backend."""
    if kind == "local":
        return _local_transcriber(model)
    if kind == "openai":
        return _openai_transcriber(model)
    if kind == "google":
        return _google_transcriber()
    raise ValueError(f"unknown transcriber: {kind!r} (expected 'local', 'openai', or 'google')")


def _local_transcriber(model: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError(_MISSING) from exc
    whisper = WhisperModel(model)

    def transcribe(path: Path) -> str:
        segments, _ = whisper.transcribe(str(path))
        return " ".join(seg.text.strip() for seg in segments).strip()

    return transcribe


def _openai_transcriber(model: str):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(_MISSING) from exc
    client = OpenAI()

    def transcribe(path: Path) -> str:
        with open(path, "rb") as fh:
            result = client.audio.transcriptions.create(model="whisper-1", file=fh)
        return (result.text or "").strip()

    return transcribe


def _google_transcriber():
    try:
        import speech_recognition as sr
        from pydub import AudioSegment
    except ImportError as exc:
        raise RuntimeError(_MISSING) from exc
    recognizer = sr.Recognizer()

    def transcribe(path: Path) -> str:
        wav = Path(path).with_suffix(".google.wav")
        AudioSegment.from_file(path).export(wav, format="wav")
        with sr.AudioFile(str(wav)) as source:
            audio = recognizer.record(source)
        try:
            return recognizer.recognize_google(audio).strip()
        except sr.UnknownValueError:
            return ""

    return transcribe
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audible_transcribe.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add books/audible_transcribe.py tests/test_audible_transcribe.py
git commit -m "feat(audible): ffmpeg cutter + pluggable transcriber factory

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 9: Audible cloud adapter (auth path + integration seam)

The networked methods require a live account and are verified manually (Task 12). Only the pure helpers are unit-tested here.

**Files:**
- Create: `books/audible_client.py`
- Test: `tests/test_audible_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_audible_client.py`:

```python
"""Tests for the Audible cloud adapter's pure helpers."""

from books import audible_client as ac


def test_default_auth_path_is_in_config_dir(monkeypatch, tmp_path):
    from books import config

    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "books" / "config.toml")
    assert ac.default_auth_path() == tmp_path / "books" / "audible-auth.json"


def test_chapters_from_metadata_parses_ranges():
    meta = {
        "content_metadata": {
            "chapter_info": {
                "chapters": [
                    {"title": "Intro", "start_offset_ms": 0, "length_ms": 60_000},
                    {"title": "Rise", "start_offset_ms": 60_000, "length_ms": 90_000},
                ]
            }
        }
    }
    chapters = ac.chapters_from_metadata(meta)
    assert [c.index for c in chapters] == [1, 2]
    assert chapters[0].title == "Intro"
    assert chapters[0].start_ms == 0 and chapters[0].end_ms == 60_000
    assert chapters[1].start_ms == 60_000 and chapters[1].end_ms == 150_000


def test_annotations_from_sidecar_maps_clips_and_bookmarks():
    payload = {
        "payload": {
            "records": [
                {
                    "annotationId": "c1",
                    "type": "audible.Clip",
                    "startPosition": "10000",
                    "endPosition": "20000",
                    "creationTime": "2026-07-01",
                    "text": "my note",
                },
                {
                    "annotationId": "b1",
                    "type": "audible.Bookmark",
                    "startPosition": "30000",
                    "creationTime": "2026-07-02",
                },
            ]
        }
    }
    anns = ac.annotations_from_sidecar(payload)
    assert anns[0].id == "c1" and anns[0].start_ms == 10000
    assert anns[0].end_ms == 20000 and anns[0].note == "my note"
    assert anns[1].id == "b1" and anns[1].start_ms == 30000
    assert anns[1].end_ms is None  # bookmark has no duration
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audible_client.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'books.audible_client'`

- [ ] **Step 3: Implement the adapter**

Create `books/audible_client.py`. The pure parsers (`chapters_from_metadata`, `annotations_from_sidecar`, `default_auth_path`) are tested; the networked `AudibleClient` methods are the integration seam (verified in Task 12).

```python
"""Audible cloud adapter: auth, library, annotations, chapters, download.

Wraps the maintained `audible` + `audible-cli` packages (imported lazily so the rest
of the CLI never needs them) rather than reimplementing auth, the license/voucher
flow, download, or annotations. Exposes the small interface `run()` consumes:
`library()`, `annotations(asin)`, `chapters(asin)`, `download(asin, dest_dir)`.

Download flow: use `audible_cli.models.LibraryItem.get_aaxc_url(quality)` to obtain
the AAXC download URL + voucher (which yields the key/iv), download the AAXC, and
hand the key/iv to ffmpeg (`-audible_key`/`-audible_iv`) at cut time — no separate
whole-file decrypt. `cryptography` (optional) accelerates the voucher decryption.
Chapters come from `LibraryItem.get_content_metadata(quality, chapter_type=...)`.
Bookmarks/clips come from the CDE sidecar endpoint (no audible-cli helper exists, so
this one call is made directly and parsed by `annotations_from_sidecar`).

The networked methods require a live Audible account and are verified manually; the
pure parsers below are unit-tested.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.request import urlopen

from books import config
from books.audible_obsidian import Annotation, Chapter, DownloadedAudio, LibraryBook

_MISSING = (
    "Audible support needs the `audible` package. Install the extra with:\n"
    "  uv tool install '.[audible]'    (or: pip install 'books[audible]')"
)

SIDECAR_URL = "https://cde-ta-g7g.amazon.com/FionaCDEServiceEngine/sidecar?type=AUDI&key={asin}"


def default_auth_path() -> Path:
    """Where the cached Audible auth file lives (beside the CLI config)."""
    return config.config_path().parent / "audible-auth.json"


def _to_ms(value) -> int:
    """Parse a position that Audible may send as int or numeric string."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def chapters_from_metadata(meta: dict) -> list[Chapter]:
    """Parse content-metadata JSON into ordered Chapters (end = start + length)."""
    raw = (((meta or {}).get("content_metadata") or {}).get("chapter_info") or {}).get(
        "chapters"
    ) or []
    chapters: list[Chapter] = []
    for i, ch in enumerate(raw, start=1):
        start = _to_ms(ch.get("start_offset_ms"))
        length = _to_ms(ch.get("length_ms"))
        chapters.append(
            Chapter(
                index=i,
                title=(ch.get("title") or f"Chapter {i}").strip(),
                start_ms=start,
                end_ms=start + length,
            )
        )
    return chapters


def annotations_from_sidecar(payload: dict) -> list[Annotation]:
    """Parse the CDE sidecar payload into Annotations (clips + bookmarks + notes).

    A record with an endPosition is a clip (has duration); one without is a point
    bookmark. `text` carries the user's typed note when present.
    """
    records = ((payload or {}).get("payload") or {}).get("records") or []
    out: list[Annotation] = []
    for rec in records:
        ann_id = rec.get("annotationId") or rec.get("id")
        if not ann_id or rec.get("startPosition") is None:
            continue
        end = rec.get("endPosition")
        out.append(
            Annotation(
                id=str(ann_id),
                start_ms=_to_ms(rec.get("startPosition")),
                end_ms=None if end is None else _to_ms(end),
                note=(rec.get("text") or "").strip() or None,
                date=(rec.get("creationTime") or "").strip() or None,
            )
        )
    return out


class AudibleClient:
    """Thin wrapper over the `audible` package (integration seam)."""

    def __init__(self, auth, client) -> None:
        self._auth = auth
        self._client = client

    # ---- construction -----------------------------------------------------

    @classmethod
    def load_or_login(cls, auth_path: Path, marketplace: str = "us"):
        """Load a cached auth file, or run the interactive login and cache it."""
        try:
            import audible
        except ImportError as exc:
            raise RuntimeError(_MISSING) from exc
        if auth_path.is_file():
            auth = audible.Authenticator.from_file(str(auth_path))
        else:
            typer_prompt = __import__("typer")
            username = typer_prompt.prompt("Audible email")
            password = typer_prompt.prompt("Audible password", hide_input=True)
            country = typer_prompt.prompt(
                "Audible marketplace (us, uk, de, ...)", default=marketplace
            )
            auth = audible.Authenticator.from_login(
                username, password, locale=country, with_username=False
            )
            auth_path.parent.mkdir(parents=True, exist_ok=True)
            auth.to_file(str(auth_path))
            auth_path.chmod(0o600)
        return cls(auth, audible.Client(auth))

    # ---- reads ------------------------------------------------------------

    def _library_items(self):
        """Fetch the library as audible-cli LibraryItem models (keyed by asin)."""
        from audible_cli.models import Library

        library = Library.from_api(
            self._client, response_groups="product_desc,contributors,relationships"
        )
        return {item.asin: item for item in library}

    def library(self) -> list[LibraryBook]:
        out: list[LibraryBook] = []
        for asin, item in self._library_items().items():
            authors = [
                a.get("name", "").strip()
                for a in (getattr(item, "authors", None) or [])
                if a.get("name")
            ]
            out.append(
                LibraryBook(
                    asin=asin,
                    title=(getattr(item, "title", "") or "").strip(),
                    authors=authors,
                )
            )
        return out

    def chapters(self, asin: str) -> list[Chapter]:
        item = self._library_items()[asin]
        meta = item.get_content_metadata(quality="High")
        return chapters_from_metadata(meta)

    def annotations(self, asin: str) -> list[Annotation]:
        """Fetch bookmarks/clips from the CDE sidecar (no audible-cli helper)."""
        with urlopen(self._signed(SIDECAR_URL.format(asin=asin))) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return annotations_from_sidecar(payload)

    def _signed(self, url: str):
        """Build a urllib Request signed with the Audible auth."""
        from urllib.request import Request

        req = Request(url)
        # The Authenticator produces the Authorization headers for a bare GET.
        headers = self._auth.sign_request(method="GET", path=url, body=b"")
        for key, value in headers.items():
            req.add_header(key, value)
        return req

    def download(self, asin: str, dest_dir: Path) -> DownloadedAudio:
        """Download the AAXC via audible-cli and return it plus its key/iv."""
        item = self._library_items()[asin]
        url, codec, voucher = item.get_aaxc_url("High")
        dest = Path(dest_dir) / f"{asin}.aaxc"
        with urlopen(url) as resp, open(dest, "wb") as fh:
            fh.write(resp.read())
        return DownloadedAudio(path=dest, key=voucher["key"], iv=voucher["iv"])
```

> Integration note: the exact `audible_cli.models` import path and the shapes of
> `get_aaxc_url` (URL, codec, voucher key/iv), `get_content_metadata`, the library
> item attributes, and the sidecar records are Audible/audible-cli's live shapes —
> verify and adjust in Task 12. The pure parsers above pin down the shapes the tests
> assert; the `LibraryItem` calls are the thin adapter over audible-cli.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audible_client.py -q`
Expected: PASS (only the pure helpers are exercised)

- [ ] **Step 5: Commit**

```bash
git add books/audible_client.py tests/test_audible_client.py
git commit -m "feat(audible): add cloud adapter (auth, library, sidecar, download)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 10: Wire the Typer command (options, defaults, auto-login, summary)

**Files:**
- Modify: `books/audible_obsidian.py`
- Test: `tests/test_audible_obsidian.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audible_obsidian.py`:

```python
def test_cli_enriches_note_end_to_end(monkeypatch, tmp_path):
    from books import config

    out, book, anns = _library_and_notes(tmp_path)
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: out)
    monkeypatch.setattr(
        config, "resolve_imports", lambda name, output=None: out / ".imports" / name
    )
    monkeypatch.setattr(ao, "_build_client", lambda: FakeClient([book], anns))
    monkeypatch.setattr(ao, "_build_transcriber", lambda kind, model: _fake_transcriber)
    monkeypatch.setattr(ao, "_build_cutter", lambda: FakeCutter())
    monkeypatch.setattr(ao, "_build_downloader", lambda client: FakeDownloader())

    result = runner.invoke(app, ["audible"])
    assert result.exit_code == 0, result.output
    note = out / "Books" / "Stalin - Stephen Kotkin.md"
    assert "transcribed text" in note.read_text()
    assert "1 book" in result.output


def test_cli_dry_run_builds_no_heavy_adapters(monkeypatch, tmp_path):
    from books import config

    out, book, anns = _library_and_notes(tmp_path)
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: out)
    monkeypatch.setattr(
        config, "resolve_imports", lambda name, output=None: out / ".imports" / name
    )
    monkeypatch.setattr(ao, "_build_client", lambda: FakeClient([book], anns))

    def _boom(*a, **k):
        raise AssertionError("heavy adapter built during dry-run")

    monkeypatch.setattr(ao, "_build_transcriber", _boom)
    monkeypatch.setattr(ao, "_build_cutter", _boom)
    monkeypatch.setattr(ao, "_build_downloader", _boom)

    result = runner.invoke(app, ["audible", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "[dry-run]" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audible_obsidian.py -k "cli_" -q`
Expected: FAIL — the placeholder `audible_command` prints "not implemented yet"; `_build_client` doesn't exist.

- [ ] **Step 3: Implement the builders and the command**

In `books/audible_obsidian.py`, add `from books import config` to imports, then add the builder seams and replace `audible_command`:

```python
def _build_client():
    """Construct the live Audible client (auto-login on first run)."""
    from books.audible_client import AudibleClient, default_auth_path

    return AudibleClient.load_or_login(default_auth_path())


def _build_transcriber(kind: str, model: str):
    from books.audible_transcribe import make_transcriber

    return make_transcriber(kind, model)


def _build_cutter():
    from books.audible_transcribe import check_ffmpeg, cut_clip

    class _FfmpegCutter:
        def cut(self, audio, start_ms, end_ms, dest):
            return cut_clip(audio, start_ms, end_ms, dest)

    check_ffmpeg()
    return _FfmpegCutter()


def _build_downloader(client):
    class _AudibleDownloader:
        def download(self, asin, dest_dir):
            return client.download(asin, dest_dir)

    return _AudibleDownloader()


def audible_command(
    transcriber: str = typer.Option(
        "local",
        "--transcriber",
        "-t",
        help="Speech-to-text backend: 'local' (faster-whisper, no key, offline), "
        "'openai' (needs OPENAI_API_KEY), or 'google' (free, lower quality).",
    ),
    model: str = typer.Option(
        "small", "--model", help="Whisper model size for the local/openai backends."
    ),
    clip_window: int = typer.Option(
        30,
        "--clip-window",
        help="Seconds of audio to transcribe for a point bookmark that has no end "
        "position (the window ends at the mark). Clips use their own length.",
    ),
    limit: int | None = typer.Option(
        None, "--limit", help="Process at most this many matched books."
    ),
    asin: str | None = typer.Option(
        None, "--asin", help="Only process the book with this Audible ASIN."
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show which books match and how many clips would be transcribed, "
        "without logging in for audio, downloading, or writing.",
    ),
) -> None:
    """Import Audible bookmarks & clips into existing Obsidian book notes.

    Authenticates to your Audible account (prompting on first run and caching the
    auth), then for each library book that matches an existing note (by ASIN, then
    title/author) fetches its bookmarks/clips, downloads the audiobook, and cuts +
    transcribes each new clip into a marker-wrapped '## Highlights' section. A book
    with no matching note is skipped and counted (run calibre/goodreads first).
    Transcriptions are cached, so re-runs only download books with new clips.
    """
    vault = config.resolve_vault(output)
    cache_path = config.resolve_imports("audible", output) / "cache.json"

    client = _build_client()
    if dry_run:
        downloader = cutter = transcribe_fn = None
    else:
        transcribe_fn = _build_transcriber(transcriber, model)
        cutter = _build_cutter()
        downloader = _build_downloader(client)

    stats = run(
        vault,
        client=client,
        downloader=downloader,
        cutter=cutter,
        transcriber=transcribe_fn,
        cache_path=cache_path,
        clip_window=clip_window,
        limit=limit,
        asin=asin,
        dry_run=dry_run,
        echo=typer.echo,
    )

    if dry_run:
        typer.echo(f"Dry run: {stats['skipped']} book(s) skipped — no note.")
        return
    books_word = "book" if stats["books"] == 1 else "books"
    skip = f" ({stats['skipped']} skipped — no note)" if stats["skipped"] else ""
    typer.echo(
        f"Done. {stats['books']} {books_word}{skip}, {stats['entries']} clips, "
        f"{stats['downloaded']} downloaded, {stats['transcribed']} transcribed.\n"
        f"Output: {vault}"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_audible_obsidian.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add books/audible_obsidian.py tests/test_audible_obsidian.py
git commit -m "feat(audible): wire Typer command with options, auto-login, summary

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 11: Optional dependency extra + standalone shim

**Files:**
- Modify: `pyproject.toml:6-9`
- Create: `scripts/audible_obsidian.py`

- [ ] **Step 1: Add the optional extra to pyproject**

In `pyproject.toml`, after the `dependencies` array, add:

```toml
[project.optional-dependencies]
# Heavy, third-party deps for the `audible` capability only (the documented
# exception to the stdlib-only rule). We depend on the maintained `audible` +
# `audible-cli` packages rather than reimplementing auth, the license/voucher
# flow, download, or annotations ourselves. `cryptography` is
# optional-but-recommended: it accelerates the `audible` package's voucher
# decryption / activation bytes.
audible = [
    "audible>=0.10",
    "audible-cli>=0.3",
    "cryptography>=42",
    "faster-whisper>=1.0",
    "openai>=1.0",
    "SpeechRecognition>=3.10",
    "pydub>=0.25",
]
```

> **Why both `audible` and `audible-cli`:** `audible` gives us the authenticator +
> low-level client; `audible-cli` (imported as the `audible_cli` library) gives us
> the higher-level `models.LibraryItem` with `get_aaxc_url()`,
> `get_content_metadata()`, and its download helpers — so `audible_client.py` adapts
> those instead of hand-rolling the licenserequest/voucher/sidecar HTTP. Keep our
> code to thin adapters + the pure parsers.

- [ ] **Step 2: Verify the base install still resolves**

Run: `uv sync`
Expected: succeeds; base deps unchanged (the extra is not installed by default).

- [ ] **Step 3: Create the standalone shim**

Create `scripts/audible_obsidian.py`:

```python
#!/usr/bin/env python3
"""Standalone shim: `python audible_obsidian.py --dry-run`.

The real implementation lives in ``books.audible_obsidian``. This keeps the script
runnable on its own while there is a single source of truth. For the full CLI with
all capabilities, use ``books`` (see pyproject.toml).
"""

from books.audible_obsidian import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Verify the shim imports**

Run: `uv run python -c "import scripts.audible_obsidian"` (or `uv run python scripts/audible_obsidian.py --help`)
Expected: prints the command help (exit 0).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (all tests green)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml scripts/audible_obsidian.py
git commit -m "build(audible): add optional [audible] extra + standalone shim

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 12: Manual verification against a live Audible account

This exercises the integration seam (`books/audible_client.py`) that unit tests cannot cover. Do it once with a real account and fix any live-API field-name mismatches.

**Files:**
- Modify (if the live API differs): `books/audible_client.py`

- [ ] **Step 1: Install the extra + ffmpeg**

Run: `uv tool install '.[audible]' --reinstall` and ensure `ffmpeg` is on PATH (`brew install ffmpeg`).

- [ ] **Step 2: Dry run to confirm auth + matching**

Run: `books audible --dry-run`
Expected: prompts for Audible email/password/marketplace on first run, caches `~/.config/books/audible-auth.json` (mode 600), then prints per-book `[dry-run]` lines and the skipped count. No downloads, no writes.

- [ ] **Step 3: Real run on a single book**

Run: `books audible --asin <ASIN-of-a-book-you-have-a-note-for> --limit 1`
Expected: downloads the AAXC, cuts + transcribes its clips, writes a `## Highlights` section into the matching note, and populates `<vault>/.imports/audible/cache.json`. If a field name differs (library authors, sidecar records, voucher `key`/`iv`, or the auth request-signing call), fix it in `books/audible_client.py` and re-run.

- [ ] **Step 4: Confirm idempotency**

Run the same command again.
Expected: no re-download (no new clips), the note is unchanged, and the run is fast.

- [ ] **Step 5: Commit any live-API fixes**

```bash
git add books/audible_client.py
git commit -m "fix(audible): align cloud adapter with live Audible API

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 13: Documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the capability count and list**

In `CLAUDE.md`, update the architecture overview: the three highlight importers become **four** (`kobo`, `highlighted`, `readwise`, `audible`), and there are now **eight** capabilities besides `sync`. Add a bullet for `audible` in the capability list:

```markdown
- `books/audible_obsidian.py` → `audible` — imports **Audible bookmarks & clips** into
  existing Obsidian book notes (enrich-only via `VaultIndex.find`, matched by ASIN as
  `amazon` then title/author; unmatched books skipped and counted). Authenticates to
  the Audible cloud (auto-prompt on first run, auth cached at
  `~/.config/books/audible-auth.json`), fetches each book's annotations, downloads the
  audiobook, and uses **ffmpeg** to decrypt (AAXC via `-audible_key`/`-audible_iv`) and
  cut each clip, then transcribes it with a pluggable backend (`--transcriber
  local|openai|google`, default `local`). Clips use their own start→end; a point
  bookmark (no end) uses `--clip-window` seconds ending at the mark. Transcriptions are
  cached in `<vault>/.imports/audible/cache.json` (keyed by ASIN + annotation id), so
  re-runs re-render for free and only download books with new clips; downloaded audio
  is written to a temp dir and deleted. Not part of `sync`.
```

- [ ] **Step 2: Document the stdlib-only exception**

Add a note near the "stdlib-only" statement at the end of the Obsidian-layer section:

```markdown
> **Exception to stdlib-only:** the `audible` capability needs third-party packages
> (`audible`, transcriber backends) and system `ffmpeg`. They are an optional
> `[audible]` extra in `pyproject.toml`, imported lazily inside
> `books/audible_obsidian.py` / `audible_client.py` / `audible_transcribe.py` so no
> other command loads them. `cryptography` is an optional-but-recommended accelerator
> for the `audible` package's decryption. Downloading/decrypting owned audiobooks is
> for personal archival use only.
```

- [ ] **Step 3: Note the imports subfolder**

In the Configuration section's list of canonical import subfolders, add `.imports/audible` (holds `cache.json`, not raw CSVs).

- [ ] **Step 4: Run the full suite once more**

Run: `uv run pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document the audible capability + stdlib-only exception

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Done criteria

- `books audible --help` lists the command and all options.
- Full suite green: `uv run pytest -q`.
- `tests/test_audible_obsidian.py`, `tests/test_audible_transcribe.py`,
  `tests/test_audible_client.py` cover: timestamp formatting, chapter lookup,
  annotation→record→Highlight mapping (clip/bookmark/note-fallback), cache
  roundtrip + new-clip diff, note rendering + chapter grouping, `run()`
  (enrich/skip/idempotent/point-bookmark-window/dry-run), ffmpeg command building
  (plain + AAXC key/iv), transcriber dispatch, and the sidecar/metadata parsers.
- Base `books` install unaffected; `audible` deps live behind the `[audible]` extra
  and are imported lazily.
- Manual verification (Task 12) confirms the live pipeline end-to-end and idempotent
  re-runs.
- `CLAUDE.md` updated.
```
