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

New key **`[export].highlights_template`** in `~/.config/books/config.toml`:

- A path to a template file (`.md` / `.jinja`), resolved via
  `resolve_path` (absolute / `~` as-is; relative against cwd).
- Unset / empty → the built-in default template.
- Parsed like the other export keys: added to `ExportConfig`
  (`highlights_template: str = ""`) and read in `_parse_sections` with the
  same tolerant string handling. The commented default file gains a line
  documenting the key.

`export_command` already loads `cfg`; it passes
`cfg.export.highlights_template` into the renderer alongside `timezone`.

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

## Built-in default template

Shipped as a packaged file: `books/renderers/obsidian/templates/callout.md.jinja`,
loaded at runtime (via `importlib.resources` / package path). It doubles as a
copy-paste starting point a user can point `highlights_template` at.

**Hard requirement:** the default template's output equals the current
`_callout` output **byte-for-byte**. The existing tests pin exact strings, so
the default is authored to match them. The default template body:

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
falls back to the default). A missing file, a Jinja compile error, or a render
error → `ui.warn(...)` naming the problem, then fall back to the built-in
default template. A broken custom template never aborts the export.

Template compilation/resolution happens once per `render_highlights` call, so a
bad template warns once, not per highlight.

## Testing

1. **Default parity:** the default template's output equals the current
   `_callout` output across the existing highlight fixtures (byte-for-byte),
   including notes, tags, links, date lines, and suppressed-time cases.
2. **Custom override:** a custom template file changes the callout shape while
   grouping/headers/anchors (owned by Python) stay intact.
3. **Fallback:** a missing file and an invalid template each warn and fall back
   to the default (export still succeeds).
4. **Filters:** `quote` (default and custom prefix, blank-line handling) and
   `tag` behave as specified.
5. **Config:** `[export].highlights_template` parses (set / unset / non-string)
   and reaches the renderer.

## Dependencies touched

- `pyproject.toml` — add `jinja2` to runtime deps.
- `books/core/config.py` — `ExportConfig.highlights_template`, parsing, default
  file comment.
- `books/commands/export.py` — thread the template path into the renderer.
- `books/renderers/obsidian/highlights.py` — template loading + rendering,
  filters, `render_highlights` signature.
- `books/renderers/obsidian/note.py` — thread the template through.
- `books/renderers/obsidian/templates/callout.md.jinja` — new default template.
```
