# Export Highlight Dates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render each highlight's date (and local time, where known) as a trailing daily-note wikilink line inside the Obsidian `[!quote]` callout.

**Architecture:** The store already keeps `Highlight.date` as ISO 8601 UTC. Add a format-agnostic UTC→local converter in `core`, a `[export].timezone` config setting, and a trailing date line in the Obsidian callout renderer. The renderer decides per source group whether the source is date-only (all timestamps at UTC midnight → link only) or timed (show the local time). The timezone is threaded from `export.py` down through the renderer.

**Tech Stack:** Python 3.11+, stdlib `zoneinfo` / `datetime`, Typer CLI, pytest.

---

## File Structure

- `books/core/highlights.py` — add `local_datetime(iso, tz)` and `is_utc_midnight(iso)` (format-agnostic; `normalize_date` unchanged).
- `books/core/config.py` — add `ExportConfig`, wire `[export].timezone` into `Config` + `_parse_sections`, add to default config files.
- `books/renderers/obsidian/highlights.py` — `render_highlights` gains a `timezone` param; per-source `all_midnight`; `_callout` emits the date line.
- `books/renderers/obsidian/note.py` — thread `timezone` through `render` → `render_body` → `render_note` and `ObsidianRenderer.render`.
- `books/renderers/base.py` — `Renderer.render` protocol gains `timezone`.
- `books/commands/export.py` — read config, pass `cfg.export.timezone` to `renderer.render`.
- `CLAUDE.md` — document the trailing date line and `[export].timezone`.

Tests:
- `tests/core/test_highlights.py` — `local_datetime`, `is_utc_midnight`.
- `tests/core/test_config.py` — `[export].timezone` parsing + fallbacks.
- `tests/renderers/obsidian/test_highlights_render.py` — date line rendering + per-source midnight rule.

---

## Task 1: Core UTC→local helpers

**Files:**
- Modify: `books/core/highlights.py`
- Test: `tests/core/test_highlights.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/core/test_highlights.py` (import at top of the new tests if not present: `from zoneinfo import ZoneInfo` and ensure `from books.core.highlights import ...` includes the new names):

```python
from zoneinfo import ZoneInfo

from books.core.highlights import is_utc_midnight, local_datetime


def test_local_datetime_converts_utc_to_oslo_winter():
    dt = local_datetime("2024-01-15T12:30:00Z", ZoneInfo("Europe/Oslo"))
    assert (dt.year, dt.month, dt.day, dt.hour, dt.minute) == (2024, 1, 15, 13, 30)


def test_local_datetime_converts_utc_to_oslo_dst():
    # July -> Oslo is UTC+2
    dt = local_datetime("2024-07-15T12:30:00Z", ZoneInfo("Europe/Oslo"))
    assert (dt.hour, dt.minute) == (14, 30)


def test_local_datetime_day_shift_across_midnight():
    # 23:30Z on the 15th -> 00:30 local on the 16th (UTC+1)
    dt = local_datetime("2024-01-15T23:30:00Z", ZoneInfo("Europe/Oslo"))
    assert (dt.day, dt.hour, dt.minute) == (16, 0, 30)


def test_local_datetime_naive_is_assumed_utc():
    dt = local_datetime("2024-01-15T12:30:00", ZoneInfo("Europe/Oslo"))
    assert (dt.hour, dt.minute) == (13, 30)


def test_local_datetime_none_and_empty_and_unparseable():
    tz = ZoneInfo("Europe/Oslo")
    assert local_datetime(None, tz) is None
    assert local_datetime("   ", tz) is None
    assert local_datetime("not a date", tz) is None


def test_is_utc_midnight():
    assert is_utc_midnight("2024-03-15T00:00:00Z") is True
    assert is_utc_midnight("2024-03-15T12:00:00Z") is False
    assert is_utc_midnight(None) is False
    assert is_utc_midnight("garbage") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_highlights.py -k "local_datetime or is_utc_midnight" -v`
Expected: FAIL with `ImportError`/`cannot import name 'local_datetime'`.

- [ ] **Step 3: Implement the helpers**

In `books/core/highlights.py`, add `from zoneinfo import ZoneInfo` to the imports (near `from datetime import UTC, datetime`), then add these functions after `normalize_date`:

```python
def local_datetime(iso: str | None, tz: ZoneInfo) -> datetime | None:
    """Parse a stored ISO-8601 timestamp and convert it to *tz*.

    Naive input is assumed UTC; aware input is converted. Returns None for
    empty/None/unparseable input. ``normalize_date`` guarantees stored values
    are ISO-8601-parseable, so failures here mean legacy/hand-edited data.
    """
    if iso is None:
        return None
    text = iso.strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz)


def is_utc_midnight(iso: str | None) -> bool:
    """True when *iso* is exactly 00:00:00 in UTC (a date-only stored value)."""
    dt = local_datetime(iso, ZoneInfo("UTC"))
    if dt is None:
        return False
    return dt.hour == 0 and dt.minute == 0 and dt.second == 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_highlights.py -k "local_datetime or is_utc_midnight" -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff check --fix && uv run ruff format
git add books/core/highlights.py tests/core/test_highlights.py
git commit -m "feat(highlights): add local_datetime + is_utc_midnight helpers

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `[export].timezone` config

**Files:**
- Modify: `books/core/config.py`
- Test: `tests/core/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/core/test_config.py`:

```python
def test_load_config_reads_export_timezone(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[export]\ntimezone = "America/New_York"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.export.timezone == "America/New_York"


def test_load_config_defaults_export_timezone_when_absent(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('vault = "History"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.export.timezone == "Europe/Oslo"


def test_load_config_defaults_export_timezone_on_non_string(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[export]\ntimezone = 5\n")
    cfg = config.load_config(cfg_file)
    assert cfg.export.timezone == "Europe/Oslo"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_config.py -k export_timezone -v`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'export'`.

- [ ] **Step 3: Implement config wiring**

In `books/core/config.py`:

1. Add a default constant near `DEFAULT_IMPORTS` (line ~19):

```python
DEFAULT_TIMEZONE = "Europe/Oslo"
```

2. Add the dataclass (near the other section dataclasses, e.g. after `KindleConfig`):

```python
@dataclass
class ExportConfig:
    timezone: str = DEFAULT_TIMEZONE
```

3. Add the field to `Config` (after `kindle`):

```python
    export: ExportConfig = field(default_factory=ExportConfig)
```

4. In `_parse_sections`, add the table read and the entry:

```python
    exp = _table(data, "export")
```

and in the returned dict:

```python
        "export": ExportConfig(timezone=_nonempty_str_or(exp, "timezone", DEFAULT_TIMEZONE)),
```

5. Add a commented `[export]` block to `_DEFAULT_FILE` (after the `[kindle]` block):

```python
"# [export]\n"

f'# timezone = "{DEFAULT_TIMEZONE}"  # IANA zone for highlight date/time rendering\n'
```

6. Add the parseable equivalent to `_DEFAULT_FILE_PARSEABLE` (after the `[kindle]` block):

```python
"[export]\n"

f'timezone = "{DEFAULT_TIMEZONE}"\n'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_config.py -v`
Expected: PASS (all config tests, including the 3 new ones).

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff check --fix && uv run ruff format
git add books/core/config.py tests/core/test_config.py
git commit -m "feat(config): add [export].timezone setting

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Render the date line in callouts

**Files:**
- Modify: `books/renderers/obsidian/highlights.py`
- Test: `tests/renderers/obsidian/test_highlights_render.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/renderers/obsidian/test_highlights_render.py`:

```python
def test_render_date_line_shows_local_time():
    hs = [Highlight(text="A", chapter_index=1, progress=0.1, date="2024-07-15T12:30:00Z")]
    out = render_highlights(hs, timezone="Europe/Oslo")
    # July -> Oslo UTC+2 -> 14:30
    assert "> [[2024-07-15]] · 14:30" in out


def test_render_date_line_day_shift():
    hs = [Highlight(text="A", chapter_index=1, progress=0.1, date="2024-01-15T23:30:00Z")]
    out = render_highlights(hs, timezone="Europe/Oslo")
    assert "> [[2024-01-16]] · 00:30" in out


def test_render_no_date_emits_no_line():
    hs = [Highlight(text="A", chapter_index=1, progress=0.1)]
    out = render_highlights(hs)
    assert "[[" not in out


def test_render_all_midnight_source_is_link_only():
    hs = [
        Highlight(text="A", page="10", date="2024-03-15T00:00:00Z", source="kindle"),
        Highlight(text="B", page="20", date="2024-03-16T00:00:00Z", source="kindle"),
    ]
    out = render_highlights(hs, timezone="Europe/Oslo")
    assert "> [[2024-03-15]]" in out
    assert "> [[2024-03-16]]" in out
    assert "·" not in out.split("[[2024-03-15]]")[1].split("\n")[0]  # no time on that line


def test_render_real_midnight_shown_when_group_has_other_times():
    hs = [
        Highlight(text="A", page="10", date="2024-03-15T00:00:00Z", source="readwise"),
        Highlight(text="B", page="20", date="2024-03-15T12:00:00Z", source="readwise"),
    ]
    out = render_highlights(hs, timezone="Europe/Oslo")
    # midnight UTC -> Oslo 01:00 (winter, UTC+1); real time is shown
    assert "> [[2024-03-15]] · 01:00" in out
    assert "> [[2024-03-15]] · 13:00" in out


def test_render_invalid_timezone_falls_back(capsys):
    hs = [Highlight(text="A", chapter_index=1, progress=0.1, date="2024-07-15T12:30:00Z")]
    out = render_highlights(hs, timezone="Not/AZone")
    # falls back to Europe/Oslo -> 14:30
    assert "> [[2024-07-15]] · 14:30" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/renderers/obsidian/test_highlights_render.py -k "date_line or midnight or no_date or invalid_timezone" -v`
Expected: FAIL (`render_highlights` has no `timezone` kwarg / no date line emitted).

- [ ] **Step 3: Implement the date line**

In `books/renderers/obsidian/highlights.py`:

1. Update imports at the top:

```python
from zoneinfo import ZoneInfo

from books.core import ui
from books.core.highlights import Highlight, is_utc_midnight, local_datetime, sort_key
from books.renderers.obsidian.format import wikilink
```

2. Add a module constant and a zone resolver near the top:

```python
_DEFAULT_TZ = "Europe/Oslo"


def _resolve_zone(timezone: str) -> ZoneInfo:
    """Resolve an IANA timezone name, warning + falling back to Europe/Oslo."""
    try:
        return ZoneInfo(timezone)
    except Exception:
        ui.warn(f"unknown timezone {timezone!r}; using {_DEFAULT_TZ}")
        return ZoneInfo(_DEFAULT_TZ)
```

3. Add a date-line helper:

```python
def _date_line(h: Highlight, zone: ZoneInfo, suppress_time: bool) -> str | None:
    """Trailing callout line: ``[[date]] · HH:MM`` (local), or ``[[date]]`` when
    the source is date-only (all-midnight group). None when the highlight has no
    parseable date."""
    if not h.date:
        return None
    if suppress_time:
        dt = local_datetime(h.date, ZoneInfo("UTC"))
        return f"> [[{dt:%Y-%m-%d}]]" if dt else None
    dt = local_datetime(h.date, zone)
    return f"> [[{dt:%Y-%m-%d}]] · {dt:%H:%M}" if dt else None
```

4. Change `_callout` to accept the zone + flag and emit the line before the anchor:

```python
def _callout(
    h: Highlight, anchor: str, chapter_prefix: str, zone: ZoneInfo, suppress_time: bool
) -> str:
    """Render one highlight as a single expanded ``[!quote]+`` callout block."""
    title_parts = [p for p in (_label(h, chapter_prefix),) if p]
    if h.links:
        title_parts.append(", ".join(wikilink(name) for name in h.links))
    title = " · ".join(title_parts)
    lines = ["> [!quote]+" + (f" {title}" if title else "")]
    lines += _quote_lines(h.text, ">")
    if h.note and h.note.strip():
        lines.append(">")
        lines += _quote_lines(h.note, ">>")
    if h.tags:
        lines.append(">")
        lines.append("> " + " ".join(f"#{t}" for t in h.tags))
    date_line = _date_line(h, zone, suppress_time)
    if date_line:
        lines.append(date_line)
    lines.append(f"^{anchor}")
    return "\n".join(lines)
```

5. Update `render_highlights` signature and the group loop:

```python
def render_highlights(
    highlights: list[Highlight],
    chapter_label: str | None = None,
    timezone: str = _DEFAULT_TZ,
) -> str:
```

Add (keep the existing docstring, extend it to mention the trailing date line and the per-source date-only rule) and resolve the zone once after `chapter_prefix = chapter_label or "ch."`:

```python
    zone = _resolve_zone(timezone)
```

Then in the `for src, group in ordered_groups:` loop, compute the flag per group and pass it into `_callout`:

```python
    for src, group in ordered_groups:
        if src is not None:
            blocks.append(f"### {src.title()}")
        dated = [h for h in group if h.date]
        suppress_time = bool(dated) and all(is_utc_midnight(h.date) for h in dated)
        grouped = any(h.chapter_title for h in group)
        prev_key = None
        for h in group:
            if grouped:
                key = _chapter_key(h)
                if key != prev_key:
                    header = _chapter_header(h)
                    if header:
                        blocks.append(header)
                    prev_key = key
            blocks.append(_callout(h, anchor_by_id[id(h)], chapter_prefix, zone, suppress_time))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/renderers/obsidian/test_highlights_render.py -v`
Expected: PASS (existing tests + the 6 new ones).

- [ ] **Step 5: Lint, format, commit**

```bash
uv run ruff check --fix && uv run ruff format
git add books/renderers/obsidian/highlights.py tests/renderers/obsidian/test_highlights_render.py
git commit -m "feat(obsidian): render highlight date line in callouts

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Thread the timezone from export through the renderer

**Files:**
- Modify: `books/renderers/obsidian/note.py`
- Modify: `books/renderers/base.py`
- Modify: `books/commands/export.py`
- Test: `tests/renderers/obsidian/test_obsidian.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/renderers/obsidian/test_obsidian.py`. The real store API is
`store.write_books_csv(vault, rows)` and
`store.write_highlights(vault, book_id, source, rows)`; `HighlightRow` uses
`location` + `location_kind` (not `page`) and its own `source` field:

```python
def test_render_passes_timezone_into_note(tmp_path):
    from books.core import store
    from books.core.store import BookRow, HighlightRow
    from books.renderers.obsidian.note import render

    vault = tmp_path / "vault"
    (vault / "Data").mkdir(parents=True)
    row = BookRow(book_id="Book - Author", title="Book", authors=["Author"])
    store.write_books_csv(vault, [row])
    store.write_highlights(
        vault,
        "Book - Author",
        "readwise",
        [
            HighlightRow(
                source="readwise",
                text="A",
                location="10",
                location_kind="page",
                date="2024-07-15T12:30:00Z",
            )
        ],
    )

    render(vault, timezone="Europe/Oslo")

    note = (vault / "Books" / "Book - Author.md").read_text()
    assert "[[2024-07-15]] · 14:30" in note
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/renderers/obsidian/test_obsidian.py::test_render_passes_timezone_into_note -v`
Expected: FAIL with `render() got an unexpected keyword argument 'timezone'`.

- [ ] **Step 3: Thread the parameter**

In `books/renderers/obsidian/note.py`:

1. `render_body` — add the param and pass it on (line ~137/152):

```python
def render_body(
    existing_body: str,
    row: BookRow,
    note_path: Path,
    highlights: list,
    timezone: str = "Europe/Oslo",
) -> str:
```

and the call:

```python
rendered = render_highlights([row_to_highlight(h) for h in highlights], timezone=timezone)
```

2. `render_note` — add the keyword-only param and pass to `render_body` (line ~215/231):

```python
def render_note(
    vault: Path,
    row: BookRow,
    highlights: list,
    *,
    preserved: dict | None = None,
    timezone: str = "Europe/Oslo",
) -> Path:
```

and:

```python
    body = render_body(existing_body, row, note_path, highlights, timezone=timezone).strip("\n")
```

3. `render` — add the keyword-only param and pass to `render_note` (line ~239/269):

```python
def render(vault: Path, *, refresh: bool = False, timezone: str = "Europe/Oslo") -> dict:
```

and:

```python
render_note(
    vault,
    row,
    highlights,
    preserved=cache.get(row.book_id),
    timezone=timezone,
)
```

4. `ObsidianRenderer.render` — pass it through (line ~293):

```python
    def render(self, vault: Path, *, refresh: bool = False, timezone: str = "Europe/Oslo") -> dict:
        return render(vault, refresh=refresh, timezone=timezone)
```

In `books/renderers/base.py`, update the protocol (line ~26):

```python
    def render(self, vault: Path, *, refresh: bool = False, timezone: str = "Europe/Oslo") -> dict: ...
```

In `books/commands/export.py`, read config and pass the timezone. Replace the `stats = renderer.render(vault, refresh=refresh)` line (line ~74) with:

```python
    cfg = config.load_config()
    stats = renderer.render(vault, refresh=refresh, timezone=cfg.export.timezone)
```

(`config` is already imported at the top of `export.py`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/renderers/obsidian/test_obsidian.py -v`
Expected: PASS (existing tests + the new one).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (no regressions).

- [ ] **Step 6: Lint, format, commit**

```bash
uv run ruff check --fix && uv run ruff format
git add books/renderers/obsidian/note.py books/renderers/base.py books/commands/export.py tests/renderers/obsidian/test_obsidian.py
git commit -m "feat(export): pass configured timezone into the renderer

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Documentation

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the highlights-rendering docs**

In `CLAUDE.md`, in the **book note anatomy** / highlights-rendering area (the `#tag`/`@link` convention and the `## Highlights` description), add a sentence documenting the trailing date line, e.g.:

> Each callout ends with a trailing date line: a daily-note wikilink plus the local time (`[[2024-03-15]] · 15:30`), converted from the highlight's stored UTC timestamp to the `[export].timezone` (default `Europe/Oslo`). A source whose highlights are all at UTC midnight (date-only sources) renders the link alone (`[[2024-03-15]]`, no time); this date-only vs. real-midnight decision is made per source, per book. Undated highlights emit no date line.

- [ ] **Step 2: Update the configuration docs**

In the **Configuration** section, document the new setting alongside the other `[...]` sections:

> `[export].timezone` (default `Europe/Oslo`, IANA name) sets the zone used to render highlight dates/times in exported notes; an unknown zone warns and falls back to `Europe/Oslo`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document highlight date line + [export].timezone

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification

- [ ] Run the whole suite: `uv run pytest -q` — all green.
- [ ] `uv run ruff check` — no errors.
- [ ] Manual smoke (optional): `uv run books export --help` runs without import errors.
