# Custom Highlight Callout Template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users supply their own Jinja2 template controlling how a single highlight's `> [!quote]` callout renders in exported Obsidian notes, with five packaged example templates scaffolded into `~/.config/books/templates/obsidian/`.

**Architecture:** The template renders exactly one highlight block; Python keeps all sorting, source/chapter grouping + headers, anchor computation, and per-source time-suppression, then stitches rendered blocks. A new `books/renderers/obsidian/templates.py` owns the Jinja environment (with `quote`/`tag` filters), template resolution (config path → `~/.config/books/templates/obsidian/callout.md.jinja` → packaged backup), and the create-missing scaffold. `render_highlights` builds a per-highlight context dict and renders it through the resolved template. The packaged default template reproduces today's output byte-for-byte.

**Tech Stack:** Python 3.11+, Jinja2 (new runtime dep), Typer, pytest, ruff.

**Reference spec:** `docs/superpowers/specs/2026-07-31-custom-highlight-template-design.md`

---

## File structure

- **Create** `books/renderers/obsidian/templates.py` — Jinja env + `quote`/`tag` filters, `resolve_template()`, `scaffold_templates()`.
- **Create** `books/renderers/obsidian/templates/callout.md.jinja` — packaged default (byte-for-byte parity).
- **Create** `books/renderers/obsidian/templates/callout-plain-note.md.jinja`
- **Create** `books/renderers/obsidian/templates/blockquote.md.jinja`
- **Create** `books/renderers/obsidian/templates/plain.md.jinja`
- **Create** `books/renderers/obsidian/templates/minimal.md.jinja`
- **Modify** `books/renderers/obsidian/highlights.py` — remove `_callout`/`_date_line`/`_quote_lines`; add `_callout_context`; render via template; `render_highlights(..., template=None)`.
- **Modify** `books/renderers/obsidian/note.py` — thread `template` through `render`/`render_note`/`render_body`; `ObsidianRenderer.render` runs the scaffold + resolves the template; add `highlights_template` param.
- **Modify** `books/renderers/obsidian/__init__.py` — export `resolve_template`, `scaffold_templates`.
- **Modify** `books/renderers/base.py` — add `highlights_template: str = ""` to the `Renderer.render` protocol.
- **Modify** `books/commands/export.py` — pass `cfg.export.obsidian.highlights_template`.
- **Modify** `books/core/config.py` — `ObsidianExportConfig` nested under `ExportConfig.obsidian`, `[export.obsidian]` parsing, `templates_dir()`, default-file comment + parseable copy.
- **Modify** `pyproject.toml` — add `jinja2` runtime dep.
- **Test** `tests/renderers/obsidian/test_templates.py` (new), `tests/renderers/obsidian/test_highlights_render.py`, `tests/core/test_config.py`.
- **Docs** `CLAUDE.md`, `README.md`.

---

## Task 1: Add the Jinja2 dependency

**Files:**
- Modify: `pyproject.toml:7-15`

- [ ] **Step 1: Add jinja2 to runtime deps**

In `pyproject.toml`, add `"jinja2>=3.1"` to the `dependencies` list (after `"rich>=13",`):

```toml
dependencies = [
    "typer>=0.12",
    "pydantic>=2.6",
    "isbnlib>=3.10",
    "rapidfuzz>=3.6",
    "python-frontmatter>=1.1",
    "ruamel.yaml>=0.18",
    "rich>=13",
    "jinja2>=3.1",
]
```

- [ ] **Step 2: Sync the environment**

Run: `uv sync`
Expected: resolves and installs `jinja2` (and `markupsafe`) with no errors.

- [ ] **Step 3: Verify import works**

Run: `uv run python -c "import jinja2; print(jinja2.__version__)"`
Expected: prints a 3.1.x version string.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add jinja2 runtime dependency for highlight templates"
```

---

## Task 2: Config — `templates_dir()` and `[export.obsidian].highlights_template`

**Files:**
- Modify: `books/core/config.py`
- Test: `tests/core/test_config.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/core/test_config.py`:

```python
def test_templates_dir_is_sibling_of_config(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config.templates_dir() == tmp_path / "xdg" / "books" / "templates"


def test_load_config_reads_obsidian_highlights_template(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[export.obsidian]\nhighlights_template = "~/my.jinja"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.export.obsidian.highlights_template == "~/my.jinja"


def test_load_config_defaults_highlights_template_when_absent(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('vault = "History"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.export.obsidian.highlights_template == ""


def test_load_config_defaults_highlights_template_on_non_string(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[export.obsidian]\nhighlights_template = 5\n")
    cfg = config.load_config(cfg_file)
    assert cfg.export.obsidian.highlights_template == ""


def test_export_timezone_still_parses_alongside_obsidian_table(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[export]\ntimezone = "America/New_York"\n'
        '[export.obsidian]\nhighlights_template = "/t.jinja"\n'
    )
    cfg = config.load_config(cfg_file)
    assert cfg.export.timezone == "America/New_York"
    assert cfg.export.obsidian.highlights_template == "/t.jinja"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_config.py -k "templates_dir or highlights_template or obsidian_table" -v`
Expected: FAIL — `config` has no attribute `templates_dir`; `ExportConfig` has no `obsidian`.

- [ ] **Step 3: Add `ObsidianExportConfig`, nest it on `ExportConfig`, and `templates_dir()`**

In `books/core/config.py`, replace the `ExportConfig` dataclass (currently lines 123-125):

```python
@dataclass
class ObsidianExportConfig:
    highlights_template: str = ""  # path to a custom callout template; "" = default


@dataclass
class ExportConfig:
    timezone: str = DEFAULT_TIMEZONE
    obsidian: ObsidianExportConfig = field(default_factory=ObsidianExportConfig)
```

In `_parse_sections`, replace the `"export": ...` entry (currently line 213) with:

```python
        "export": ExportConfig(
            timezone=_nonempty_str_or(exp, "timezone", DEFAULT_TIMEZONE),
            obsidian=ObsidianExportConfig(
                highlights_template=_str_or(_table(exp, "obsidian"), "highlights_template", ""),
            ),
        ),
```

Add the path helper next to `config_path()` (after line 148):

```python
def templates_dir() -> Path:
    """Directory holding user-editable export templates (sibling of config.toml)."""
    return config_path().parent / "templates"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_config.py -k "templates_dir or highlights_template or obsidian_table or export" -v`
Expected: PASS (including the existing `test_load_config_reads_export_timezone` tests).

- [ ] **Step 5: Commit**

```bash
git add books/core/config.py tests/core/test_config.py
git commit -m "feat(config): add [export.obsidian].highlights_template + templates_dir()"
```

---

## Task 3: Packaged default template + filters + `resolve_template` + render via template

This is the core task: introduce `templates.py`, the default template file, refactor `render_highlights` to render through it, and prove byte-for-byte parity.

**Files:**
- Create: `books/renderers/obsidian/templates.py`
- Create: `books/renderers/obsidian/templates/callout.md.jinja`
- Modify: `books/renderers/obsidian/highlights.py`
- Modify: `books/renderers/obsidian/__init__.py`
- Test: `tests/renderers/obsidian/test_highlights_render.py`

- [ ] **Step 1: Write the failing parity test**

Append to `tests/renderers/obsidian/test_highlights_render.py`:

```python
def test_default_template_full_block_byte_for_byte():
    hs = [
        Highlight(
            text="A line",
            note="my thought",
            chapter_index=2,
            progress=0.42,
            block="17",
            segment="5",
            links=["Trotsky"],
            tags=["Stalin"],
            date="2024-07-15T12:30:00Z",
        )
    ]
    out = render_highlights(hs, timezone="Europe/Oslo")
    expected = (
        "> [!quote]+ ch. 2 · 42% · [[Trotsky]]\n"
        "> A line\n"
        ">\n"
        ">> my thought\n"
        ">\n"
        "> #Stalin\n"
        "> [[2024-07-15]] · 14:30\n"
        "^ch2-42"
    )
    assert expected in out


def test_default_template_multiline_note_prefixes_each_line():
    hs = [Highlight(text="A", note="one\ntwo", chapter_index=1, block="1")]
    out = render_highlights(hs)
    assert ">> one" in out
    assert ">> two" in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/renderers/obsidian/test_highlights_render.py::test_default_template_full_block_byte_for_byte -v`
Expected: FAIL — output still comes from `_callout`; likely passes already, but the run confirms the current baseline. If it PASSES here that is fine (it proves the target string matches today's output); it must still pass after the refactor.

- [ ] **Step 3: Create the packaged default template**

Create `books/renderers/obsidian/templates/callout.md.jinja` with EXACTLY this content (note: `{% if %}` tags sit at line-ends so their newline lives inside the conditional; do not add `{%- -%}` trims):

```jinja
> [!quote]+{% if h.label or h.links %} {{ [h.label, h.links | join(', ')] | select | join(' · ') }}{% endif %}
{{ h.text | quote }}{% if h.note %}
>
{{ h.note | quote('>>') }}{% endif %}{% if h.tags %}
>
> {{ h.tags | map('tag') | join(' ') }}{% endif %}{% if h.date %}
> [[{{ h.date }}]]{% if h.time %} · {{ h.time }}{% endif %}{% endif %}
^{{ h.anchor }}
```

- [ ] **Step 4: Create `templates.py`**

Create `books/renderers/obsidian/templates.py`:

```python
"""Jinja templates for the Obsidian highlight callout: env, filters, resolution, scaffold.

The template controls the shape of a *single* highlight's ``> [!quote]`` block.
Everything else (sort, source/chapter grouping + headers, anchors, time
suppression, block stitching) stays in ``highlights.py``. Resolution order:
the configured path, then ``~/.config/books/templates/obsidian/callout.md.jinja``,
then the packaged backup — each step warns and falls through on failure, so a
broken template never aborts an export.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import jinja2

from books.core import config, ui
from books.core.paths import resolve_path

_PACKAGE = "books.renderers.obsidian.templates"
DEFAULT_TEMPLATE = "callout.md.jinja"

# The packaged example set: seeds the scaffold + the byte-for-byte backup default.
EXAMPLE_TEMPLATES = (
    "callout.md.jinja",
    "callout-plain-note.md.jinja",
    "blockquote.md.jinja",
    "plain.md.jinja",
    "minimal.md.jinja",
)


def _quote_filter(text: str | None, prefix: str = ">") -> str:
    """Prefix each line of *text* for a callout body; blank lines keep the bare marker."""
    lines = (text or "").split("\n")
    return "\n".join(f"{prefix} {ln}" if ln.strip() else prefix.rstrip() for ln in lines)


def _tag_filter(slug: str) -> str:
    """Render a tag slug as an Obsidian inline tag (``history`` -> ``#history``)."""
    return f"#{slug}"


_ENV = jinja2.Environment(autoescape=False, keep_trailing_newline=False)
_ENV.filters["quote"] = _quote_filter
_ENV.filters["tag"] = _tag_filter


def _packaged_source(name: str) -> str:
    """Read a packaged template file's text."""
    return resources.files(_PACKAGE).joinpath(name).read_text(encoding="utf-8")


def resolve_template(explicit_path: str | None) -> jinja2.Template:
    """Compile the highlight callout template, following the resolution order.

    1. *explicit_path* (the configured ``[export.obsidian].highlights_template``)
       when set; 2. the scaffolded ``templates/obsidian/callout.md.jinja``;
    3. the packaged backup. A read/compile failure warns and falls through; the
    packaged backup always compiles.
    """
    if explicit_path:
        path = resolve_path(Path(explicit_path), Path.cwd())
        try:
            return _ENV.from_string(path.read_text(encoding="utf-8"))
        except (OSError, jinja2.TemplateError) as exc:
            ui.warn(f"highlight template {path}: {exc}; falling back to default")
    default_path = config.templates_dir() / "obsidian" / DEFAULT_TEMPLATE
    if default_path.is_file():
        try:
            return _ENV.from_string(default_path.read_text(encoding="utf-8"))
        except (OSError, jinja2.TemplateError) as exc:
            ui.warn(f"highlight template {default_path}: {exc}; using packaged default")
    return _ENV.from_string(_packaged_source(DEFAULT_TEMPLATE))


def scaffold_templates() -> None:
    """Copy the packaged examples into ``templates/obsidian/`` (create-missing only).

    Never overwrites a hand-edited file; re-creates a deleted one. Idempotent.
    Swallows ``OSError`` (e.g. read-only config dir) so it never crashes a command.
    """
    dest_dir = config.templates_dir() / "obsidian"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in EXAMPLE_TEMPLATES:
            dest = dest_dir / name
            if not dest.exists():
                dest.write_text(_packaged_source(name), encoding="utf-8")
    except OSError:
        pass
```

- [ ] **Step 5: Refactor `highlights.py` to render via the template**

In `books/renderers/obsidian/highlights.py`:

Update the imports at the top (replace the existing `from books.renderers.obsidian.format import wikilink` line and keep the others):

```python
from books.renderers.obsidian.format import wikilink
from books.renderers.obsidian.templates import resolve_template
```

Delete `_quote_lines` (lines 92-94), `_date_line` (lines 97-107), and `_callout` (lines 110-130). Replace them with a context builder:

```python
def _callout_context(
    h: Highlight, anchor: str, chapter_prefix: str, zone: ZoneInfo, suppress_time: bool
) -> dict:
    """Build the template context for one highlight (ready-to-print display fields)."""
    note = h.note if (h.note and h.note.strip()) else ""
    date = ""
    time = ""
    if h.date:
        z = ZoneInfo("UTC") if suppress_time else zone
        dt = local_datetime(h.date, z)
        if dt:
            date = f"{dt:%Y-%m-%d}"
            time = "" if suppress_time else f"{dt:%H:%M}"
    return {
        "text": h.text,
        "note": note,
        "tags": list(h.tags),
        "links": [wikilink(name) for name in h.links],
        "label": _label(h, chapter_prefix),
        "date": date,
        "time": time,
        "anchor": anchor,
    }
```

Change the `render_highlights` signature (line 133-135) to accept a template:

```python
def render_highlights(
    highlights: list[Highlight],
    chapter_label: str | None = None,
    timezone: str = DEFAULT_TIMEZONE,
    template=None,
) -> str:
```

Near the top of the body, after `zone = _resolve_zone(timezone)` (line 162), add:

```python
    if template is None:
        template = resolve_template(None)
```

In the render loop, replace the `_callout(...)` call (line 196) with:

```python
                ctx = _callout_context(h, anchor_by_id[id(h)], chapter_prefix, zone, suppress_time)
                blocks.append(template.render(h=ctx).strip("\n"))
```

Update the `render_highlights` docstring's date-line paragraph to note the shape is now template-controlled (append one sentence): `The exact callout markdown is produced by the resolved Jinja template (default reproduces this layout).`

- [ ] **Step 6: Export the new helpers**

In `books/renderers/obsidian/__init__.py`, add after the `highlights` import (line 13):

```python
from books.renderers.obsidian.templates import resolve_template, scaffold_templates
```

Add `"resolve_template",` and `"scaffold_templates",` to `__all__` (keep it sorted).

- [ ] **Step 7: Run the full highlights + parity suite**

Run: `uv run pytest tests/renderers/obsidian/test_highlights_render.py -v`
Expected: PASS — all existing render tests plus the two new parity tests. This proves the default template reproduces the old `_callout` output byte-for-byte.

- [ ] **Step 8: Run the whole suite to catch regressions**

Run: `uv run pytest -q`
Expected: PASS (all existing tests still green).

- [ ] **Step 9: Lint, format, commit**

```bash
uv run ruff check --fix && uv run ruff format
git add books/renderers/obsidian/templates.py books/renderers/obsidian/templates/callout.md.jinja books/renderers/obsidian/highlights.py books/renderers/obsidian/__init__.py tests/renderers/obsidian/test_highlights_render.py
git commit -m "feat(obsidian): render highlights through a Jinja callout template"
```

---

## Task 4: Custom template override + resolution fallback

**Files:**
- Create: `tests/renderers/obsidian/test_templates.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/renderers/obsidian/test_templates.py`:

```python
"""Tests for the Obsidian highlight template env, resolution, and scaffold."""

import jinja2

from books.core.highlights import Highlight
from books.renderers.obsidian import render_highlights
from books.renderers.obsidian import templates as T


def test_quote_filter_prefixes_lines_and_blank():
    assert T._quote_filter("a\n\nb") == "> a\n>\n> b"
    assert T._quote_filter("x", ">>") == ">> x"


def test_tag_filter():
    assert T._tag_filter("history") == "#history"


def test_custom_template_changes_callout_shape():
    tmpl = jinja2.Template("PLAIN: {{ h.text }} ^{{ h.anchor }}")
    out = render_highlights([Highlight(text="hi", page="4")], template=tmpl)
    assert "PLAIN: hi ^p4" in out
    assert "> [!quote]" not in out


def test_custom_template_still_groups_by_source():
    tmpl = jinja2.Template("- {{ h.text }}")
    out = render_highlights(
        [
            Highlight(text="k", progress=0.1, source="kobo"),
            Highlight(text="r", progress=0.2, source="readwise"),
        ],
        template=tmpl,
    )
    # Python still owns the source headers regardless of the template
    assert "### Kobo" in out and "### Readwise" in out


def test_resolve_template_falls_back_to_packaged_when_config_absent(monkeypatch, tmp_path):
    # point templates_dir at an empty tmp dir -> no .config default -> packaged backup
    monkeypatch.setattr(T.config, "templates_dir", lambda: tmp_path)
    tmpl = T.resolve_template(None)
    out = tmpl.render(h={"text": "x", "note": "", "tags": [], "links": [],
                         "label": "", "date": "", "time": "", "anchor": "a1"})
    assert "> [!quote]+" in out
    assert "> x" in out
    assert "^a1" in out


def test_resolve_template_bad_explicit_path_warns_and_falls_back(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(T.config, "templates_dir", lambda: tmp_path)
    tmpl = T.resolve_template(str(tmp_path / "does-not-exist.jinja"))
    # falls back to packaged default (still compiles + renders a callout)
    out = tmpl.render(h={"text": "x", "note": "", "tags": [], "links": [],
                         "label": "", "date": "", "time": "", "anchor": "a1"})
    assert "> [!quote]+" in out


def test_resolve_template_invalid_syntax_warns_and_falls_back(monkeypatch, tmp_path):
    bad = tmp_path / "bad.jinja"
    bad.write_text("{% if %}broken")  # invalid Jinja
    monkeypatch.setattr(T.config, "templates_dir", lambda: tmp_path)
    tmpl = T.resolve_template(str(bad))
    out = tmpl.render(h={"text": "x", "note": "", "tags": [], "links": [],
                         "label": "", "date": "", "time": "", "anchor": "a1"})
    assert "> [!quote]+" in out


def test_resolve_template_uses_config_default_when_present(monkeypatch, tmp_path):
    obs = tmp_path / "obsidian"
    obs.mkdir()
    (obs / "callout.md.jinja").write_text("CFG:{{ h.text }}")
    monkeypatch.setattr(T.config, "templates_dir", lambda: tmp_path)
    tmpl = T.resolve_template(None)
    assert tmpl.render(h={"text": "hi"}) == "CFG:hi"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/renderers/obsidian/test_templates.py -v`
Expected: initially most PASS (the code from Task 3 already supports these). Any FAIL indicates a real gap — fix it in `templates.py`/`highlights.py`. The value here is locking the contract; if all pass, proceed.

- [ ] **Step 3: Make any needed fixes**

If `test_custom_template_changes_callout_shape` fails because `template=` is not honored, verify Task 3 Step 5 passed the compiled template through and that `render_highlights` only calls `resolve_template` when `template is None`. No new code should be required beyond Task 3.

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/renderers/obsidian/test_templates.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/renderers/obsidian/test_templates.py
git commit -m "test(obsidian): custom template override + resolution fallback"
```

---

## Task 5: The four extra example templates + scaffold

**Files:**
- Create: `books/renderers/obsidian/templates/callout-plain-note.md.jinja`
- Create: `books/renderers/obsidian/templates/blockquote.md.jinja`
- Create: `books/renderers/obsidian/templates/plain.md.jinja`
- Create: `books/renderers/obsidian/templates/minimal.md.jinja`
- Test: `tests/renderers/obsidian/test_templates.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/renderers/obsidian/test_templates.py`:

```python
SAMPLE_CTX = {
    "text": "A line\nsecond line",
    "note": "my thought",
    "tags": ["stalin"],
    "links": ["[[Trotsky]]"],
    "label": "ch. 2 · 42%",
    "date": "2024-07-15",
    "time": "14:30",
    "anchor": "ch2-42",
}


def test_all_example_templates_compile_and_render():
    for name in T.EXAMPLE_TEMPLATES:
        source = T._packaged_source(name)
        tmpl = T._ENV.from_string(source)
        out = tmpl.render(h=SAMPLE_CTX)
        assert "A line" in out  # every template prints the text
        assert out.strip()  # non-empty


def test_scaffold_creates_all_examples(monkeypatch, tmp_path):
    monkeypatch.setattr(T.config, "templates_dir", lambda: tmp_path)
    T.scaffold_templates()
    obs = tmp_path / "obsidian"
    for name in T.EXAMPLE_TEMPLATES:
        assert (obs / name).is_file()


def test_scaffold_does_not_overwrite_edits(monkeypatch, tmp_path):
    monkeypatch.setattr(T.config, "templates_dir", lambda: tmp_path)
    obs = tmp_path / "obsidian"
    obs.mkdir()
    edited = obs / "callout.md.jinja"
    edited.write_text("MY EDIT")
    T.scaffold_templates()
    assert edited.read_text() == "MY EDIT"  # untouched
    assert (obs / "minimal.md.jinja").is_file()  # missing one still created


def test_scaffold_recreates_deleted_file(monkeypatch, tmp_path):
    monkeypatch.setattr(T.config, "templates_dir", lambda: tmp_path)
    T.scaffold_templates()
    (tmp_path / "obsidian" / "minimal.md.jinja").unlink()
    T.scaffold_templates()
    assert (tmp_path / "obsidian" / "minimal.md.jinja").is_file()


def test_scaffold_tolerates_readonly(monkeypatch, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("")  # a FILE where a dir is expected -> mkdir raises
    monkeypatch.setattr(T.config, "templates_dir", lambda: blocker)
    T.scaffold_templates()  # must not raise
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/renderers/obsidian/test_templates.py -k "example_templates or scaffold" -v`
Expected: FAIL — the four example files do not exist yet (`_packaged_source` / scaffold error).

- [ ] **Step 3: Create `callout-plain-note.md.jinja`**

```jinja
> [!quote]+{% if h.label or h.links %} {{ [h.label, h.links | join(', ')] | select | join(' · ') }}{% endif %}
{{ h.text | quote }}{% if h.tags %}
>
> {{ h.tags | map('tag') | join(' ') }}{% endif %}{% if h.date %}
> [[{{ h.date }}]]{% if h.time %} · {{ h.time }}{% endif %}{% endif %}
^{{ h.anchor }}
{% if h.note %}
*{{ h.note }}*
{% endif %}
```

- [ ] **Step 4: Create `blockquote.md.jinja`**

```jinja
{{ h.text | quote }}
{% if h.note %}
{{ h.note }}
{% endif %}
{% if h.label %}— {{ h.label }}{% endif %}{% if h.date %} · [[{{ h.date }}]]{% if h.time %} {{ h.time }}{% endif %}{% endif %}
^{{ h.anchor }}
```

- [ ] **Step 5: Create `plain.md.jinja`**

```jinja
{{ h.text }}

{% if h.label or h.date %}— {{ [h.label, h.date and ('[[' ~ h.date ~ ']]')] | select | join(' · ') }}{% endif %}
{% if h.note %}
*{{ h.note }}*
{% endif %}
^{{ h.anchor }}
```

- [ ] **Step 6: Create `minimal.md.jinja`**

```jinja
{{ h.text }}
^{{ h.anchor }}
```

- [ ] **Step 7: Run to verify they pass**

Run: `uv run pytest tests/renderers/obsidian/test_templates.py -k "example_templates or scaffold" -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add books/renderers/obsidian/templates/ tests/renderers/obsidian/test_templates.py
git commit -m "feat(obsidian): ship example callout templates + create-missing scaffold"
```

---

## Task 6: Thread the template through the renderer + `export`

**Files:**
- Modify: `books/renderers/base.py`
- Modify: `books/renderers/obsidian/note.py`
- Modify: `books/commands/export.py`
- Test: `tests/renderers/obsidian/test_templates.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/renderers/obsidian/test_templates.py`:

```python
def _seed_store(vault):
    """Create a minimal books.csv + one highlight so render() has work to do."""
    from books.core import store

    vault.mkdir(parents=True, exist_ok=True)
    row = store.BookRow(book_id="Book - Author", title="Book", authors=["Author"])
    store.write_books_csv(vault, [row])
    h = store.HighlightRow(source="kobo", text="hello world", location="4", location_kind="page")
    # write_highlights(vault, book_id, source, rows)
    store.write_highlights(vault, "Book - Author", "kobo", [h])
    return row


def test_render_uses_custom_template_from_config_path(tmp_path, monkeypatch):
    from books.renderers.obsidian import note

    vault = tmp_path / "V"
    _seed_store(vault)
    custom = tmp_path / "custom.jinja"
    custom.write_text("CUSTOM {{ h.text }} ^{{ h.anchor }}")
    # keep scaffold from touching the real config dir
    monkeypatch.setattr(note, "scaffold_templates", lambda: None)
    note.render(vault, highlights_template=str(custom))
    text = (vault / "Books" / "Book - Author.md").read_text()
    assert "CUSTOM hello world" in text
    assert "> [!quote]" not in text


def test_obsidian_renderer_runs_scaffold(tmp_path, monkeypatch):
    from books.renderers.obsidian import note

    vault = tmp_path / "V"
    _seed_store(vault)
    called = {"n": 0}
    monkeypatch.setattr(note, "scaffold_templates", lambda: called.__setitem__("n", called["n"] + 1))
    note.ObsidianRenderer().render(vault)
    assert called["n"] == 1
```

The `store` API used here is verified against `books/core/store.py`:
`store.write_books_csv(vault, rows)`, `store.write_highlights(vault, book_id, source, rows)`,
`store.BookRow` (has `book_id`, `title`, `authors`), `store.HighlightRow` (uses
`location` + `location_kind`, not `page`). `render()` reads `books.csv` via
`store.read_books_csv` and skips rows without `book_id`, so the seed row sets `book_id`.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/renderers/obsidian/test_templates.py -k "custom_template_from_config or runs_scaffold" -v`
Expected: FAIL — `note.render` / `ObsidianRenderer.render` take no `highlights_template`, no `scaffold_templates` call.

- [ ] **Step 3: Add the param to the `Renderer` protocol**

In `books/renderers/base.py`, replace the `render` signature (lines 28-30):

```python
    def render(
        self,
        vault: Path,
        *,
        refresh: bool = False,
        timezone: str = DEFAULT_TIMEZONE,
        highlights_template: str = "",
    ) -> dict: ...
```

- [ ] **Step 4: Thread the template through `note.py`**

In `books/renderers/obsidian/note.py`:

Add to the imports from the highlights/templates modules (after line 26 `from books.renderers.obsidian.highlights import render_highlights`):

```python
from books.renderers.obsidian.templates import resolve_template, scaffold_templates
```

`render_body` (lines 138-161): add `template=None` param and pass it on. Change the signature and the `render_highlights` call:

```python
def render_body(
    existing_body: str,
    row: BookRow,
    note_path: Path,
    highlights: list,
    timezone: str = DEFAULT_TIMEZONE,
    template=None,
) -> str:
```

and:

```python
        rendered = render_highlights(
            [row_to_highlight(h) for h in highlights], timezone=timezone, template=template
        )
```

`render_note` (lines 222-248): add `template=None` to the keyword-only params and pass into `render_body`:

```python
def render_note(
    vault: Path,
    row: BookRow,
    highlights: list,
    *,
    preserved: dict | None = None,
    timezone: str = DEFAULT_TIMEZONE,
    template=None,
) -> Path:
```

and change the `render_body` call:

```python
    body = render_body(
        existing_body, row, note_path, highlights, timezone=timezone, template=template
    ).strip("\n")
```

`render` (lines 251-299): add `highlights_template: str = ""`, resolve once, pass into `render_note`:

```python
def render(
    vault: Path,
    *,
    refresh: bool = False,
    timezone: str = DEFAULT_TIMEZONE,
    highlights_template: str = "",
) -> dict:
```

After `cache = _collect_preserved(...)` / before the loop, add:

```python
    template = resolve_template(highlights_template)
```

and change the `render_note` call inside the loop:

```python
                    render_note(
                        vault,
                        row,
                        highlights,
                        preserved=cache.get(row.book_id),
                        timezone=timezone,
                        template=template,
                    )
```

`ObsidianRenderer.render` (lines 307-310): run the scaffold, add the param, delegate:

```python
    def render(
        self,
        vault: Path,
        *,
        refresh: bool = False,
        timezone: str = DEFAULT_TIMEZONE,
        highlights_template: str = "",
    ) -> dict:
        scaffold_templates()
        return render(
            vault, refresh=refresh, timezone=timezone, highlights_template=highlights_template
        )
```

- [ ] **Step 5: Pass the config value from `export`**

In `books/commands/export.py`, replace the `renderer.render(...)` call (line 75):

```python
    stats = renderer.render(
        vault,
        refresh=refresh,
        timezone=cfg.export.timezone,
        highlights_template=cfg.export.obsidian.highlights_template,
    )
```

- [ ] **Step 6: Run to verify they pass**

Run: `uv run pytest tests/renderers/obsidian/test_templates.py -k "custom_template_from_config or runs_scaffold" -v`
Expected: PASS.

- [ ] **Step 7: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 8: Lint, format, commit**

```bash
uv run ruff check --fix && uv run ruff format
git add books/renderers/base.py books/renderers/obsidian/note.py books/commands/export.py tests/renderers/obsidian/test_templates.py
git commit -m "feat(export): thread highlights_template through the renderer + scaffold on export"
```

---

## Task 7: Default config file comment + docs

**Files:**
- Modify: `books/core/config.py` (`_DEFAULT_FILE`, `_DEFAULT_FILE_PARSEABLE`)
- Test: `tests/core/test_config.py`
- Docs: `CLAUDE.md`, `README.md`

- [ ] **Step 1: Write the failing tests**

Append to `tests/core/test_config.py`:

```python
def test_default_file_documents_obsidian_template(tmp_path):
    cfg_file = tmp_path / "books" / "config.toml"
    config.load_config(cfg_file)
    text = cfg_file.read_text()
    assert "[export.obsidian]" in text
    assert "highlights_template" in text


def test_default_parseable_has_export_obsidian(tmp_path):
    import tomllib

    data = tomllib.loads(config._DEFAULT_FILE_PARSEABLE)
    assert data["export"]["obsidian"]["highlights_template"] == ""
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/core/test_config.py -k "documents_obsidian_template or parseable_has_export_obsidian" -v`
Expected: FAIL — the strings are not in the default files yet.

- [ ] **Step 3: Update `_DEFAULT_FILE`**

In `books/core/config.py`, replace the `[export]` block at the end of `_DEFAULT_FILE` (lines 63-64):

```python
    "# [export]\n"
    f'# timezone = "{DEFAULT_TIMEZONE}"  # IANA zone for highlight date/time rendering\n'
    "# Obsidian-specific export settings (a custom highlight callout template).\n"
    "# Examples are scaffolded to ~/.config/books/templates/obsidian/ — copy one and\n"
    "# point highlights_template at it, or edit it in place.\n"
    "# [export.obsidian]\n"
    '# highlights_template = "~/.config/books/templates/obsidian/callout.md.jinja"\n'
```

- [ ] **Step 4: Update `_DEFAULT_FILE_PARSEABLE`**

Replace the trailing `[export]` block (lines 86-87):

```python
    "[export]\n"
    f'timezone = "{DEFAULT_TIMEZONE}"\n'
    "[export.obsidian]\n"
    'highlights_template = ""\n'
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/core/test_config.py -k "documents_obsidian_template or parseable_has_export_obsidian or default_file" -v`
Expected: PASS.

- [ ] **Step 6: Update `CLAUDE.md`**

In the **Configuration** section, after the `[export].timezone` paragraph, add:

```markdown
The `[export.obsidian].highlights_template` key (default empty) points at a Jinja2
template that controls how a single highlight's `> [!quote]` callout renders; unset
uses the built-in default. Templates are format-namespaced under
`~/.config/books/templates/<format>/`; the five Obsidian examples
(`callout`, `callout-plain-note`, `blockquote`, `plain`, `minimal`) are scaffolded
into `~/.config/books/templates/obsidian/` on first `export` (create-missing only,
never clobbering edits). Resolution order: the configured path → the scaffolded
`templates/obsidian/callout.md.jinja` → the packaged backup, warning and falling
through on any load/compile error. The template only shapes one callout — Python
still owns sorting, source/chapter headers, anchors, and time-suppression.
```

In **The shared Obsidian layer** section's file list, add a bullet:

```markdown
- **Highlight templates** (`books/renderers/obsidian/templates.py` + the packaged
  `templates/*.md.jinja`): the Jinja env with `quote`/`tag` filters,
  `resolve_template` (config → `.config` default → packaged backup), and the
  create-missing `scaffold_templates`. `render_highlights` builds a per-highlight
  context and renders it through the resolved template.
```

Also update the **Highlight date line** paragraph's opening to note the callout markdown is template-produced: append `The exact callout markdown is produced by a Jinja template (see templates.py); the default reproduces the layout described here.`

- [ ] **Step 7: Update `README.md`**

Add a short subsection under the configuration/export docs describing `[export.obsidian].highlights_template`, the five examples, the scaffold location, and that only the single-callout shape is templated (mirror the CLAUDE.md wording, trimmed for users). Keep the existing README tone/emoji-header style.

- [ ] **Step 8: Final full run + lint**

```bash
uv run ruff check --fix && uv run ruff format
uv run pytest -q
```
Expected: PASS, no lint errors.

- [ ] **Step 9: Commit**

```bash
git add books/core/config.py tests/core/test_config.py CLAUDE.md README.md
git commit -m "docs: document [export.obsidian].highlights_template + example templates"
```

---

## Self-review notes

- **Spec coverage:** config key + `templates_dir` (Task 2), Jinja engine + context + filters + default parity (Task 3), custom override + resolution fallback (Task 4), example set + scaffold create-missing/tolerant (Task 5), threading through renderer + export + scaffold-on-export (Task 6), config-file docs + CLAUDE/README (Task 7), jinja2 dep (Task 1). All spec sections map to a task.
- **Byte-for-byte parity** is enforced both by the existing `test_highlights_render.py` suite (which pins exact strings) and the explicit `test_default_template_full_block_byte_for_byte` added in Task 3.
- **Layering:** `core/config.py` only gains the format-agnostic `templates_dir()`; all Obsidian template knowledge (packaged files, scaffold, resolution) lives in the renderer layer — no `core → renderers` import.
- **Naming consistency:** `resolve_template`, `scaffold_templates`, `EXAMPLE_TEMPLATES`, `DEFAULT_TEMPLATE`, `_callout_context`, `cfg.export.obsidian.highlights_template`, `templates_dir()` are used identically across tasks.
- **Store API:** verified against `books/core/store.py` — `write_books_csv(vault, rows)`, `write_highlights(vault, book_id, source, rows)`, `HighlightRow(location=..., location_kind="page")`.
```
