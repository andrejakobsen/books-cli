# Export highlight dates to Obsidian — design

Date: 2026-07-31

## Problem

Every highlight already carries a timestamp: source importers populate
`Highlight.date`, `store.write_highlights` normalizes it to ISO 8601 UTC, and
`row_to_highlight` loads it back into `Highlight.date` at export time. But the
Obsidian renderer never emits it — `render_highlights` / `_callout` drop the
field on the floor. We want to surface each highlight's date (and, where known,
time) in the exported note.

## Output format

The date renders as the **last line of the callout body**, after the tags line
and before the `^anchor`:

```
> [!quote]+ ch. 2 · 42% · [[Trotsky]]
> The highlighted text here.
>
>> My note about it.
>
> #tag1 #tag2
> [[2024-03-15]] · 15:30
^ch2-42
```

- A **daily-note wikilink** (`[[YYYY-MM-DD]]`) followed by a middot and a
  minute-precision **local time** (`· HH:MM`).
- Date and time are in the **configured timezone**, converted from the stored
  UTC value. A late-evening UTC highlight can therefore shift onto the next
  local day (the wikilink date is the local date).
- A highlight with **no date** emits no line at all (the date line is simply
  omitted; the rest of the callout is unchanged).

### Date-only vs. real midnight (per-source rule)

The store normalizes date-only sources to `...T00:00:00Z`, so a date-only
highlight is indistinguishable from one taken exactly at midnight UTC when
looking at a single row. **The store format is left unchanged.** Instead the
renderer decides per **source group**:

- For each source group in the book's highlights, compute `all_midnight` = every
  *dated* highlight in that group is at `00:00:00Z` (checked in **UTC**).
- `all_midnight` group → the source is date-only → render **link only**
  (`> [[2024-03-15]]`, no time). The wikilink uses the stored UTC date part
  directly (no timezone shift, since there is no meaningful time).
- Otherwise → render the time (`> [[2024-03-15]] · 15:30`), **including** any
  genuine `00:00:00Z` in that group (a lone midnight among varied times is real).
- Undated highlights are ignored by the `all_midnight` computation.

Scope: the check runs over the highlights available at render time, which is one
book at a time, so the decision is **per source, per book**. This matches how
`render_highlights` already groups highlights by `source`. The only lost case is
a source whose *entire* set for a book happens to sit at midnight — an accepted,
rare edge.

## Configuration

New `[export]` section in `~/.config/books/config.toml`:

```toml
[export]
timezone = "Europe/Oslo"
```

- Add `ExportConfig(timezone="Europe/Oslo")` to the `Config` dataclass and wire
  it into `_parse_sections` using the existing `_nonempty_str_or` helper, keyed
  off the `[export]` table.
- Add a commented `[export]` block to the auto-generated default config file
  (`_DEFAULT_FILE`) and the fully-uncommented `_DEFAULT_FILE_PARSEABLE` used by
  tests.
- Default timezone: `Europe/Oslo`.
- **Invalid / unknown zone** (typo, unrecognized name): fall back to
  `Europe/Oslo` with a `ui.warn`, validated at **render time** via
  `zoneinfo.ZoneInfo`. Keeping the `zoneinfo` import in the renderer keeps
  `config.py` dependency-free. `zoneinfo` is stdlib (Python 3.11+) — no new
  dependency.

## Code changes

Dependency direction preserved: `commands → renderers → core`.

### `books/core/highlights.py` (format-agnostic)

Add a helper that converts a stored ISO-UTC string into an aware local datetime:

```python
def local_datetime(iso: str | None, tz: ZoneInfo) -> datetime | None:
    """Parse a stored ISO-8601 timestamp and convert it to *tz*.

    Naive input is assumed UTC. Returns None for empty/None/unparseable input.
    """
```

Also add a small predicate (or reuse `local_datetime` + UTC parse) to test
whether a stored value is at `00:00:00Z` in UTC, for the `all_midnight` check.
Keep the UTC-midnight test independent of the display timezone.

`normalize_date` is **unchanged**.

### `books/renderers/obsidian/highlights.py`

- `render_highlights` gains a `timezone: str` parameter. It resolves/validates
  the zone once (`ZoneInfo`, warn + fall back to `Europe/Oslo` on failure).
- Per source group, compute the `all_midnight` flag from that group's dated
  highlights.
- `_callout` gains the information it needs (the resolved `ZoneInfo` and the
  group's `suppress_time` flag) and emits the trailing date line:
  - no date → no line;
  - `suppress_time` (all-midnight group) → `> [[<utc-date>]]`;
  - otherwise → `> [[<local-date>]] · <local HH:MM>`.
- The Obsidian-specific wikilink/middot formatting lives here; the UTC→local
  conversion lives in `core`.

### `books/renderers/obsidian/note.py`

Thread `timezone` through `render` → `build_body` / `render_note` →
`render_highlights`.

### `books/commands/export.py`

Read `config.load_config()`, pass `cfg.export.timezone` into
`renderer.render(...)`. The `Renderer.render` protocol signature gains a
`timezone` argument.

## Testing

- `local_datetime`: UTC→Oslo conversion (standard and DST offsets), day-shift on
  a late-UTC time, naive-assumed-UTC, `00:00:00Z` handling, unparseable → None,
  empty/None → None.
- Invalid timezone string → falls back to `Europe/Oslo` with a warning.
- Callout rendering:
  - timed highlight → `> [[date]] · HH:MM` on the trailing line;
  - all-midnight source group → `> [[date]]` (link only);
  - a genuine `00:00:00Z` within a group that has other non-midnight times →
    time shown;
  - undated highlight → no date line;
  - day-shift case renders the shifted local date in the wikilink.
- Per-source scope: a book mixing an all-midnight source and a timed source
  renders link-only for the former and times for the latter.
- Config: `[export].timezone` parses; missing section / missing key / non-string
  value fall back to `Europe/Oslo`.

## Docs

Update `CLAUDE.md`:
- The highlights-rendering section (the `#tag`/`@link` convention paragraph and
  the callout anatomy) to document the trailing date line and the per-source
  midnight rule.
- The configuration section to document `[export].timezone`.

## Out of scope

- Changing the store's date format / `normalize_date` behavior.
- Frontmatter-level highlight date aggregation (e.g. a "last highlighted" note
  property).
- Per-source global (whole-store) midnight detection.
