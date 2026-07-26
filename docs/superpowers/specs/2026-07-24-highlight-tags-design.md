# Tags for Exported Highlights — Design

Date: 2026-07-24

## Goal

Associate tags with individual highlights so they can be cross-referenced in
Obsidian. Tags come from two sources:

- **Highlighted** CSV export: a dedicated `Tags` column (comma-separated).
- **Kobo**: inline `#hashtags` embedded in the note text (e.g.
  `"This is a note from kobo. #Stalin #USSR"`).

Tags render **inside the quote callout**, on their own line below the quoted
text, so they share the quote's block anchor (`^ch3-p45`). This binds each tag to
a specific highlight: searching `#Stalin` in Obsidian surfaces the quote block,
and the quote can be transcluded via `![[Book#^ch3-p45]]`.

## Non-goals

- No frontmatter aggregation of tags onto the canonical book note (per-quote
  only).
- No change to the Kobo CSV/zip export format — tags are an Obsidian-only concern
  (the callout rendering). The CSV path is untouched.

## Changes

### 1. Shared model — `booktools/highlights.py`

- Add `tags: list[str] = field(default_factory=list)` to the `Highlight`
  dataclass.
- Add helper `sanitize_tag(raw: str) -> str | None`:
  - trim surrounding whitespace,
  - strip a single leading `#` if present,
  - replace internal whitespace runs with a single `-` (Obsidian inline tags
    cannot contain spaces),
  - lowercase the result by convention, so `"Cold War"` → `"cold-war"` and
    `"#Stalin"` → `"stalin"`,
  - return `None` for an empty/blank result.

  Because both importers funnel their tags through `sanitize_tag`, tags from
  Kobo and Highlighted are always lowercase.

### 2. Rendering — `render_highlights` (`highlights.py`)

When a highlight has tags, append a line inside the quote callout below the
quoted text:

```
> [!quote]+ ch. 3 · p. 45
> Some highlighted text
>
> #Stalin #USSR
^ch3-p45
```

- Tags line is `> ` + space-joined `#<tag>` values.
- Separated from the quoted text by a blank callout line (`>`).
- When there are no tags, the callout is unchanged (no trailing blank line).
- Note callout and block anchors are unaffected.

### 3. Kobo — `booktools/kobo_export.py`

In `row_to_highlight`, extract inline hashtags from the note text:

- Regex: `#(\w[\w/-]*)` — matches on the `#` boundary regardless of surrounding
  whitespace, so `#tag1#tag2` yields two tags and nesting/hyphens
  (`#history/ussr`, `#cold-war`) are preserved.
- Collect matches in order, de-duplicated (first occurrence wins).
- **Strip** all matched hashtag spans from the note text, then collapse
  whitespace runs and trim; if the result is empty, the note becomes `None`.
- Pass the collected tags (via `sanitize_tag`) into the `Highlight`.

The CSV export path (`export`) is unchanged.

### 4. Highlighted — `booktools/highlighted_obsidian.py`

In `row_to_highlight`, split the `Tags` column on commas, run each through
`sanitize_tag`, and drop `None`/empty results.

## Testing

### `sanitize_tag`
- `"Cold War"` → `"cold-war"` (whitespace→hyphen, lowercased).
- `"#Stalin"` → `"stalin"` (leading `#` stripped, lowercased).
- `"#USSR"` → `"ussr"` (lowercased).
- `"  spaced  "` → `"spaced"`.
- `""` / `"   "` / `"#"` → `None`.

### `render_highlights`
- Highlight with tags → `> #a #b` line appears inside the callout, above the
  `^anchor`, below the quoted text.
- Highlight with no tags → callout output unchanged (regression).
- Tags + note → tags inside quote callout; note callout still rendered after.

### Kobo hashtag extraction (`row_to_highlight`)
All of these yield note `"Note."` and tags `["tag1", "tag2"]`:
- `"Note. #tag1 #tag2"`
- `"Note.#tag1 #tag2"` (no space before first tag)
- `"Note. #tag1#tag2"` (no space between tags)

Plus:
- Note that is only tags (`"#tag1 #tag2"`) → note `None`, tags `["tag1","tag2"]`.
- No tags → note verbatim, tags empty.
- Duplicate tags (`"#tag1 x #tag1"`) → `["tag1"]` (deduped, order preserved).
- Nested/hyphen tags (`"#history/ussr #cold-war"`) preserved verbatim.

### Highlighted comma-split (`row_to_highlight`)
- `"Stalin, USSR"` → `["Stalin", "USSR"]`.
- `"Stalin"` → `["Stalin"]`.
- `""` / missing → `[]`.
- `"Cold War, USSR"` → `["cold-war", "ussr"]` (whitespace sanitized, lowercased).

## Constraints

- Standard library only (Typer remains the sole runtime dependency).
- Keep shared tag logic in `highlights.py`; importers only map their source
  format into the model.
