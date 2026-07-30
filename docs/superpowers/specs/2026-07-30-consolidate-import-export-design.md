# Consolidate importers into `books import`; rename `render` → `export`

**Date:** 2026-07-30
**Status:** Approved design (pending written-spec review)

## Goal

Collapse the eight separate importer/merge commands into a single `books import`
command whose flags select a subset of importers (no flag = run the default
"sync-set"), and rename the `render` command to `export`. `merge` becomes an
internal step. Per-importer settings move from CLI flags into the user config
file. The result is a three-command CLI: `import`, `export`, `reset`.

## Motivation

Today the CLI exposes eleven commands (`calibre`, `goodreads`, `merge`, `kobo`,
`highlighted`, `readwise`, `audible`, `covers`, `render`, `reset`, `sync`). The
importers are all variations on "ingest a source into the CSV store", and `sync`
already orchestrates most of them. Users must remember the phase ordering and the
`merge`/`render` boundaries. Consolidating to `import` + `export` gives one
obvious ingest command and one obvious output command, with the phase ordering
handled internally.

## Command surface (after)

| Command | Purpose |
|---|---|
| `books import [selection flags] [--output] [--dry-run]` | Ingest raw sources into the CSV store. |
| `books export [--obsidian] [--refresh] [--output]` | Turn the store into notes (renamed `render`). |
| `books reset [--dry-run] [--yes] [--output]` | Unchanged — wipe the derived store. |

Removed as commands (kept as internal modules): `calibre`, `goodreads`, `merge`,
`kobo`, `highlighted`, `readwise`, `audible`, `covers`, `render`, `sync`.

### `books import`

Selection flags (one per importer): `--calibre`, `--goodreads`, `--kobo`,
`--highlighted`, `--readwise`, `--audible`, `--covers`.

Semantics:

- **No selection flag** → run the *configured default set*. Out of the box this
  is the sync-set: `calibre`, `goodreads`, `kobo`, `highlighted`, `readwise`
  (same set `sync` runs today; `audible`/`covers` excluded because they need
  cloud auth / network and interactive selection). The default set is
  configurable via `[import].default` in `config.toml`, so a user who wants
  covers or audible in every no-flag run can add them there.
- **One or more flags** → run exactly those importers, nothing else. E.g.
  `books import --calibre --kobo` runs just those two; `books import --audible`
  runs just audible.
- `audible` and `covers` are opt-in: they run **only** when their flag is passed
  (never in the no-flag run).
- Each selected importer still **detects its source** and is skipped (reported,
  not an error) when the source is absent — the existing `sync` detection logic.
- Only shared options exist on `import`: `--output/-o`, `--dry-run`. There are
  **no** per-importer CLI options (see Config below) and **no** one-off targeting
  flags (dropped: `--asin`, `--book`, `--limit`, `--all`, `--interactive`,
  `--csv`, `--db`, `--library`, `--transcriber`).

Merge (automatic):

- `merge` is never a user-facing flag. `import` injects it into the run whenever
  the selected importers make it necessary:
  - A **metadata/enrichment** importer (`calibre`, `goodreads`, `audible`,
    `covers`) writes a `Data/Sources/<name>.csv` layer → schedule a `merge`
    **after** those importers so the layer folds into `Data/books.csv`.
  - A **highlight** importer (`kobo`, `highlighted`, `readwise`) resolves against
    `Data/books.csv` → schedule a `merge` **before** them (re-clustering existing
    layers is idempotent and cheap; guarantees the catalog is current).
  - When the selection spans both (the no-flag sync-set), merge sits at the phase
    boundary exactly as `sync` runs it today: `calibre → goodreads → merge →
    kobo → highlighted → readwise`.
  - `covers`/`audible` (layer writers that also *resolve* against the catalog)
    get a merge **before** (ensure catalog) and **after** (fold their layer).

Behavior preserved from `sync`:

- Continue-on-error: a failed step is reported but never stops the others.
- `--dry-run` prints the detection plan (each step + its source location) without
  writing.
- A colored per-step + summary report via the existing `books.core.ui` helpers.

### `books export`

A straight rename of `render` (module, command name, help text). Options
unchanged: `--output/-o`, `--obsidian` (default/only format today), `--refresh`
(clean rebuild of `Books/` + `Authors/`). All behavior identical to today's
`render`.

### `books reset`

Unchanged. Its help/recovery text updates to reference `import`/`export` instead
of `sync`/`render`.

## Configuration

Per-importer settings move into `~/.config/books/config.toml` as typed sections.
The top-level keys (`obsidian_path`, `vault`, `imports`) are unchanged.

```toml
obsidian_path = "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian"
vault = "History"
imports = "Data/Imports"

[import]
# Importers that run when `books import` is given no flags.
# Defaults to the sync-set; add "covers"/"audible" to include them by default.
default = ["calibre", "goodreads", "kobo", "highlighted", "readwise"]

[calibre]
library = "~/Calibre Library"

[kobo]
# db = "/custom/KoboReader.sqlite"   # optional; mounted device / canonical folder auto-detected

[audible]
transcriber = "local"   # local | openai | google
select = "interactive"  # interactive | all  (off-tty falls back to "all")

[covers]
interactive = false
limit = 0               # 0 = no limit
```

Design of the config layer:

- `config.py` gains one small dataclass per importer section (`CalibreConfig`,
  `KoboConfig`, `AudibleConfig`, `CoversConfig`) plus an `ImportConfig` holding
  the `[import].default` list, each with built-in defaults matching today's CLI
  defaults. `ImportConfig.default` falls back to the sync-set and drops any
  unknown importer name.
- The main `Config` dataclass gains fields holding those sub-configs.
- `load_config` parses each `[section]` table defensively (same per-key
  fallback used for the top-level keys): a missing section, missing key, or wrong
  type falls back to the built-in default. A malformed config never crashes.
- The auto-created default config file (`_DEFAULT_FILE`) is extended to include
  the new sections as commented examples so first-run users see the knobs.
- The CSV-folder importers (`goodreads`, `highlighted`, `readwise`) keep using
  the existing `imports` mechanism (canonical `Data/Imports/<name>` folders) —
  no new config needed. Custom input for a path-based importer is provided by
  placing the file in its canonical folder (or, for calibre/kobo, via the new
  `[calibre].library` / `[kobo].db` config keys).

The importer **core functions** already accept their inputs as parameters
(`calibre.convert(library, vault)`, `kobo.export_obsidian(db, vault)`,
`readwise.convert(csv, vault)`, etc.). `import` reads config once and passes the
resolved values into each step's runner. Audible/covers `run` entry points gain
parameters for `transcriber`/`select`/`interactive`/`limit` sourced from config
(replacing what were CLI options).

## Architecture

`sync.py` already contains the exact orchestration machinery this needs: a
`Step` dataclass (detect/run/summarize/where), a step registry, continue-on-error
execution, `--dry-run` planning, and a rich summary table. The implementation:

1. **`books/commands/import_cmd.py`** (module name avoids the `import` keyword;
   registered as the `import` command). This is `sync.py` evolved:
   - Reuses/keeps the `Step`, `StepResult`, detection helpers, summaries, and
     rich-output helpers.
   - The step list is built from the **selection flags**: no flags → the
     sync-set; flags → the named subset. `merge` steps are injected around the
     selected importers per the rules in the `import` section above.
   - Runners read per-importer config (calibre library, kobo db, audible/covers
     behavior) instead of using hardcoded defaults.
   - `run_import(vault, *, selection, dry_run)` is the core; the Typer command is
     a thin wrapper resolving the vault and translating flags → selection.

2. **`books/commands/render.py` → `books/commands/export.py`**: rename the file,
   the command name (`app.command("export")`), and the internal function name;
   update help text. No behavior change.

3. **`books/core/config.py`**: add the per-importer sub-dataclasses, extend
   `Config`, extend `load_config` parsing, extend `_DEFAULT_FILE`.

4. **`books/cli.py`**: `CAPABILITIES` becomes `(export_cmd, import_cmd, reset)`.
   The individual importer modules (`calibre`, `goodreads`, `merge`, `kobo`,
   `highlighted`, `readwise`, `audible`, `covers`) are no longer registered — but
   their modules remain importable (their `register` functions are simply not
   called). `sync` module is removed/absorbed.

5. Audible/covers `command.py`: keep the `run(...)` core callable; the CLI
   `register`/command wrappers are removed (they're driven by `import` now). Any
   option previously read from Typer options is now a plain function parameter
   supplied by `import` from config.

## Data flow (unchanged store, new entry points)

```
raw sources ──(books import)──▶ Data/Sources/*.csv ──(auto merge)──▶ Data/books.csv
                             └─▶ Data/Highlights/<book_id>.csv
Data/books.csv + Highlights ──(books export)──▶ Books/*.md, Authors/*.md
```

The two-phase CSV-store pipeline, the store models, matching, and the Obsidian
renderer are all unchanged. Only the CLI entry points change.

## Error handling

- Unchanged continue-on-error semantics from `sync`: a failed importer is
  reported in the summary; other steps still run.
- `import` with a selection flag whose source is absent → that step is skipped
  and reported (not an error), matching `sync`.
- `export` errors cleanly when `Data/books.csv` is missing (unchanged from
  `render`).
- Config parsing never raises — bad/partial config falls back per key.

## Testing

- **Config:** unit tests for each new section (present / absent / malformed /
  wrong-type → correct fallback); `_DEFAULT_FILE` still parses.
- **Import selection:** no-flag → sync-set; single/multiple flags → exact subset;
  `--audible`/`--covers` never in the no-flag run; merge injected in the right
  positions for each selection shape; `--dry-run` plan output.
- **Import behavior:** continue-on-error (a failing step doesn't stop others);
  per-importer config values reach the runners (calibre library, kobo db,
  audible transcriber/select, covers interactive/limit).
- **Export:** the renamed command behaves identically to the old `render` tests
  (adapt/rename existing `render` tests to `export`).
- **CLI wiring:** `books --help` lists exactly `import`, `export`, `reset`; the
  removed command names are gone.
- Reuse and adapt the existing `sync` tests as the `import` test suite.

## Out of scope

- No change to the store format, matching, or the Obsidian renderer internals.
- No new output formats (the `--obsidian`/`get_renderer` seam is untouched).
- No one-off targeting on `import` (`--asin`/`--book`/`--limit` dropped for now;
  can be reconsidered later if missed).
- No backward-compatibility aliases for the removed command names.

## Migration notes

- `CLAUDE.md` needs a substantial rewrite of the capability list and the
  pipeline description (import/export replace the per-source commands + sync +
  render). The historical `docs/superpowers/` specs are left as-is (historical
  record).
- The recovery flow in `reset` help becomes: `reset` → `import` → `export`
  (plus `import --audible` / `import --covers` as needed).
