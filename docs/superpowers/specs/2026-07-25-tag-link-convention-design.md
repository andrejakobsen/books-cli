# `#tag` / `@link` convention in highlight notes

Date: 2026-07-25
Status: Approved

## Problem

Every highlight source (Kobo inline `#hashtags`, and the *Tags* columns from the
Highlighted and Readwise CSV exports) currently funnels annotations into
`Highlight.tags`, which render as `#tag` inline tags on a trailing line under the
quote callout.

We want a second, distinct kind of annotation: a **link**. Where the author means
an Obsidian graph link rather than a tag, they write `@link`. So the vault ends up
with two conventions that must be parsed apart:

- `#tag`  → an Obsidian inline tag (`#tag`), as today
- `@link` → an Obsidian wikilink (`[[link]]`), matching how authors/genres render

## Convention

`@` and `#` behave identically as markers. Each marker captures everything from the
marker character until the **next `@` or `#` marker, or a newline** (the "end of
line" convention). Markers live at the end of a line; there is **no** mid-prose
linking and no multi-word boundary guessing.

Example note text:

```
Great chapter. @One Two #history #russia
```

parses to: clean note `Great chapter.`, links `["One Two"]`, tags `["history", "russia"]`.

## Design

### 1. Model — `booktools/highlights.py`

- Add `links: list[str] = field(default_factory=list)` to the `Highlight`
  dataclass, alongside `tags`.
- Add `sanitize_link(raw)`: strip surrounding whitespace, drop a single leading
  `@`, collapse internal whitespace runs to a single space, and **keep case**
  (links are wikilink display names, not slugs). Return `None` when empty.
  - Contrast with `sanitize_tag`, which lowercases and replaces whitespace with `-`.
- In `render_highlights`, the trailing line under a quote combines both kinds:
  links first (rendered via the existing `obsidian.wikilink()` helper), then tags:

  ```
  [[Link One]] [[Link Two]] #tag1 #tag2
  ```

  The line is emitted when either `h.links` or `h.tags` is non-empty.

### 2. Shared marker parser — `booktools/highlights.py`

- `parse_markers(text) -> tuple[str | None, list[str], list[str]]` returning
  `(clean_text, links, tags)`:
  - Scan for `@` and `#` markers; each captures text up to the next marker or newline.
  - `@…` → link via `sanitize_link`; `#…` → tag via `sanitize_tag`.
  - Remove the marker spans from `clean_text`; collapse whitespace; `None` if empty.
  - De-duplicate each list in first-seen order.
- This replaces Kobo's `_HASHTAG_RE` + `extract_tags`.

### 3. Sources

- **Kobo** (`kobo_export.py`): call `parse_markers` on the note; pass `links=`/`tags=`
  into `Highlight`; keep the cleaned note text as the note body.
- **Highlighted** (`highlighted_obsidian.py`) and **Readwise** (`readwise_obsidian.py`):
  their comma-separated *Tags* column now splits by prefix — an entry starting with
  `@` becomes a link (`sanitize_link`), otherwise a tag (`sanitize_tag`). Populate
  both `links` and `tags`.
  - Readwise's separate *Document tags* column → `shelves` frontmatter is unchanged.

### 4. Tests & docs

- Unit tests for `parse_markers` (multi-word links, mixed markers on a line, dedupe,
  empty input), the rendered links line in `render_highlights`, and the `@`-prefix
  CSV split for the Highlighted and Readwise importers.
- Update the CLAUDE.md capability blurbs for `kobo`, `highlighted`, and `readwise`
  to mention the `#tag` / `@link` convention.

## Decisions

- **Links first, then tags** on the rendered trailing line.
- **No inline-prose linking**; markers use the end-of-line capture rule.
- Links preserve case and spaces; tags remain lowercased and dash-slugged.
