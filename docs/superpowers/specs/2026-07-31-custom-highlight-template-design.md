# Custom highlight callout template

**Date:** 2026-07-31
**Status:** Approved (design)

## Goal

Let a user provide their own template controlling how an individual highlight's
`> [!quote]` callout is rendered in exported Obsidian notes — the same idea as
[Readwise's Obsidian export templates](https://docs.readwise.io/readwise/docs/exporting-highlights/obsidian),
but scoped to a single highlight block.

## Scope

The template renders **exactly one highlight's `> [!quote]` block** — the string
`_callout()` produces today in `books/renderers/obsidian/highlights.py`.

Everything else stays in Python and is unchanged:

- reading-order sort (`sort_key`)
- source grouping and the `### <Source>` headers
- chapter grouping and the `### <Chapter>` headers
- unique block-anchor computation (`build_anchors`)
- per-source group time-suppression decision (`suppress_time`)
- stitching rendered blocks/headers together with blank lines

Out of scope (untouched): frontmatter schema, cover embed, write-once `## Review`,
and the `## Highlights` idempotency markers. No loops, headers, or grouping live
in the template.

## Configuration

New key **`highlights_template`** under a new **`[export.obsidian]`** table in
`~/.config/books/config.toml` (nested so it reads clearly as an Obsidian-specific
setting; future formats get their own `[export.<format>]` table):

- A path to a template file (`.md` / `.jinja`), resolved via
  `resolve_path` (absolute / `~` as-is; relative against cwd).
- Unset / empty → the built-in default template.
- Modeled as a nested dataclass: `ExportConfig` gains
  `obsidian: ObsidianExportConfig = field(default_factory=ObsidianExportConfig)`,
  where `ObsidianExportConfig` has `highlights_template: str = ""`. `timezone`
  stays directly on `[export]` (unchanged). `_parse_sections` reads the
  `[export.obsidian]` sub-table with the same tolerant string handling.
- The commented default config file documents it as an Obsidian template and
  points at `~/.config/books/templates/obsidian/`.

`export_command` already loads `cfg`; it passes
`cfg.export.obsidian.highlights_template` into the renderer alongside `timezone`.

## Example templates in the config dir

The packaged example templates are copied into
**`~/.config/books/templates/obsidian/`** (respecting `$XDG_CONFIG_HOME`, next to
`config.toml`) automatically — no command needed. Templates are namespaced by
format under `templates/<format>/` so a future renderer (Notion, etc.) gets its
own `templates/notion/` without collision. This is a **create-missing-only**
scaffold: a user's edited file is never overwritten; only absent files are
written (so the set self-heals if a file is deleted, but hand edits survive).
This gives users a browsable, tweakable starting set.

**Layering.** The example templates are Obsidian-specific, so the scaffold lives
in the **renderer** layer (a new `books/renderers/obsidian/templates.py`), not in
`core/config.py` — `core` must never import a renderer (`commands → renderers →
core`). `core/config.py` owns only the format-agnostic path helper
`templates_dir()` (returns `config_path().parent / "templates"`); the renderer
appends the `obsidian` subfolder. The scaffold runs at the start of
`ObsidianRenderer.render` (the first `export`), which is create-missing-only and
idempotent, so the files "just appear" without a command. Failures are swallowed
like the config auto-create (`OSError` → skip), so a read-only config dir never
crashes a command.

**Where the templates live vs. where the backup lives.** All templates —
including the default `callout.md.jinja` — live in `~/.config/books/templates/`
and are the files actually read at render time. The packaged copies inside the
`books` package are a **backup only**: they seed the scaffold (create-missing)
and are the last-resort fallback when the corresponding `.config` file is
missing or fails to load. Normal operation reads from `.config`; the package is
never the primary source.

The five shipped examples (all consume the same `h` context + `quote`/`tag`
filters; Python still owns grouping/headers/anchors regardless of choice):

1. **`callout.md.jinja`** — the default `> [!quote]+` callout, byte-for-byte
   identical to current output (locator + links on the title line, note nested
   as `>>`, tags line, date line, anchor). This is also the packaged renderer
   default.
2. **`callout-plain-note.md.jinja`** — the same `[!quote]` callout for the
   quote, but the author's note rendered as plain *italic* text right below the
   callout instead of nested inside it.
3. **`blockquote.md.jinja`** — a plain Markdown `>` blockquote (no `[!quote]`
   type / fold), note as plain text below, minimal metadata.
4. **`plain.md.jinja`** — the highlight as plain text (no blockquote), a small
   `— label · [[date]]` attribution line under it, note in italics.
5. **`minimal.md.jinja`** — only the highlight text and the `^anchor`; no
   locator, date, tags, or note. The barest option.

## Engine and dependency

**Jinja2**, added as a runtime dependency in `pyproject.toml` (matches the
engine Readwise's template system uses). Templates are rendered with an
autoescape-off environment (this is Markdown, not HTML).

## Template context

Each callout render receives a single variable `h` (a plain mapping / small
object) with **computed display fields** — ready to print, mirroring what
`_callout` assembles today:

| Field    | Type        | Value                                                              |
|----------|-------------|-------------------------------------------------------------------|
| `text`   | str         | the highlight text (may contain newlines)                         |
| `note`   | str         | the author's note, `""` when absent                              |
| `tags`   | list[str]   | tag slugs (no `#`), `[]` when none                                |
| `links`  | list[str]   | already-formatted `[[Wikilink]]` strings, `[]` when none         |
| `label`  | str         | the locator string, e.g. `ch. 2 · 42%`, `""` when none          |
| `date`   | str         | `YYYY-MM-DD` for the daily-note link, `""` when no date          |
| `time`   | str         | `HH:MM` local time, `""` when suppressed or no date              |
| `anchor` | str         | the unique block id (without the leading `^`)                    |

Two Jinja **filters** are registered on the environment:

- `quote(prefix='>')` — prefixes every line of a string for a callout body;
  a blank line becomes the bare marker (`>`). This exposes the existing
  `_quote_lines` helper. Example: `{{ h.text | quote }}`,
  `{{ h.note | quote('>>') }}`.
- `tag` — renders a slug as `#slug`. Example: `{{ h.tags | map('tag') | join(' ') }}`.

The template output is used verbatim as one block (trailing whitespace
trimmed) and slotted where `_callout`'s return value goes today.

## Template resolution order

When the renderer needs a template it resolves in this order:

1. **`[export.obsidian].highlights_template`** if set — the explicit user path.
2. **`~/.config/books/templates/obsidian/callout.md.jinja`** — the scaffolded
   default, the normal source.
3. **Packaged backup** `books/renderers/obsidian/templates/callout.md.jinja` —
   last resort, used only when the `.config` file is missing or fails to load.

At each step a load/compile failure warns (`ui.warn`) and falls through to the
next step, so a broken custom template falls back to the scaffolded default,
and a deleted/broken scaffolded default falls back to the packaged backup. The
packaged backup is authored to always compile.

## Default template body

**Hard requirement:** the default template's output equals the current
`_callout` output **byte-for-byte**. The existing tests pin exact strings, so
the default is authored to match them. The default template body (shipped both
as the scaffolded `callout.md.jinja` and the packaged backup):

```jinja
> [!quote]+{% if h.label or h.links %} {{ [h.label, h.links | join(', ')] | select | join(' · ') }}{% endif %}
{{ h.text | quote }}
{%- if h.note %}
>
{{ h.note | quote('>>') }}
{%- endif %}
{%- if h.tags %}
>
> {{ h.tags | map('tag') | join(' ') }}
{%- endif %}
{%- if h.date %}
> [[{{ h.date }}]]{% if h.time %} · {{ h.time }}{% endif %}
{%- endif %}
^{{ h.anchor }}
```

(Exact whitespace/`{%- -%}` trimming to be finalized against the fixtures so
the byte-for-byte test passes; the template is the source of truth once tests
are green.)

## Rendering flow (changes in `highlights.py`)

`render_highlights` gains a `template` parameter (the resolved template source
string, or `None`/`""` → built-in default). It:

1. Compiles the template once per call (default or custom).
2. For each highlight, builds the `h` context dict from the existing computed
   values (`_label`, `wikilink`-formatted links, `tags`, the `_date_line`
   date/time split, and the anchor) and renders the template instead of
   calling `_callout`.

`_callout` is either removed or reduced to building the context dict; the
markdown assembly moves into the default template. `note.py`'s `render_body`
and `render_note`/`render`/`ObsidianRenderer.render` thread the template string
through (parallel to the existing `timezone` threading).

## Error handling

Mirrors the existing timezone fallback (`_resolve_zone`: unknown zone warns and
falls back to the default). At each step of the resolution order above, a
missing file, a Jinja compile error, or a render error → `ui.warn(...)` naming
the problem, then fall through to the next step. The packaged backup is the
terminal fallback and is authored to always compile, so the export never
aborts on a template problem.

Template compilation/resolution happens once per `render_highlights` call, so a
bad template warns once, not per highlight.

## Testing

1. **Default parity:** the default template's output equals the current
   `_callout` output across the existing highlight fixtures (byte-for-byte),
   including notes, tags, links, date lines, and suppressed-time cases.
2. **Custom override:** a custom template file changes the callout shape while
   grouping/headers/anchors (owned by Python) stay intact.
3. **Resolution order + fallback:** explicit path wins; unset falls to the
   scaffolded `.config` default; a missing/broken `.config` default falls to the
   packaged backup; a broken explicit path warns and falls through. Each step
   warns and export still succeeds.
4. **Filters:** `quote` (default and custom prefix, blank-line handling) and
   `tag` behave as specified.
5. **Config:** `[export.obsidian].highlights_template` parses (set / unset /
   non-string / missing sub-table) and reaches the renderer; `timezone` still
   parses on `[export]`.
6. **Scaffolding:** the scaffold creates `~/.config/books/templates/obsidian/`
   with the five examples; a hand-edited file is not overwritten; a deleted file
   is re-created; a read-only config dir is tolerated (no crash).
7. **Example templates compile:** every packaged example compiles and renders
   against a sample highlight without error.

## Dependencies touched

- `pyproject.toml` — add `jinja2` to runtime deps.
- `books/core/config.py` — `ObsidianExportConfig.highlights_template` nested
  under `ExportConfig.obsidian`, parsing of `[export.obsidian]`, the default
  config-file comment, and the format-agnostic `templates_dir()` path helper.
- `books/renderers/obsidian/templates.py` — new module: `scaffold_templates()`
  (create-missing copy of packaged examples into `templates/obsidian/`) and
  `resolve_template()` (config path → `.config` default → packaged backup).
- `books/commands/export.py` — thread `cfg.export.obsidian.highlights_template`
  into the renderer.
- `books/renderers/obsidian/highlights.py` — the `quote`/`tag` Jinja filters,
  the callout context builder, and the `render_highlights` `template` param.
- `books/renderers/obsidian/note.py` — thread the template through
  `render`/`render_note`/`render_body`; `ObsidianRenderer.render` runs the
  scaffold + resolves the template once.
- `books/renderers/obsidian/templates/*.md.jinja` — the five packaged example
  templates (backup + scaffold source), incl. the default `callout.md.jinja`.
```
