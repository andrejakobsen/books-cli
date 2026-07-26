# `sync` — master command design

Date: 2026-07-26

## Goal

A single `books sync` command that runs every importer in the correct
dependency order using each command's default options, so a user can refresh
their whole vault in one shot. Note-creating importers (`calibre`, `goodreads`)
run first to establish book identity; the highlight enrichers
(`kobo`, `highlighted`, `readwise`) run afterward and only fill existing notes.

Covers are **out of scope** — `covers` stays a separate manual command.

## Behavior

### Order & detection

`sync` runs these steps in order, skipping any step whose source is absent:

| # | Step | Runs when |
|---|------|-----------|
| 1 | calibre | the resolved Calibre library dir exists (default `~/Calibre Library`) |
| 2 | goodreads | `.imports/goodreads` has a top-level `*.csv` |
| 3 | kobo | a Kobo device is mounted (`KOBO_DEVICE_DB`) **or** `.imports/kobo` has a `*.sqlite` |
| 4 | highlighted | `.imports/highlighted` has any top-level `*.csv` |
| 5 | readwise | `.imports/readwise` has a top-level `*.csv` |

Detection is best-effort and never writes. Import subfolders resolve via
`config.resolve_imports(<name>, output)`; the Calibre library default mirrors the
`calibre` command (`~/Calibre Library`).

### Flags

- `--output, -o PATH` — vault override, threaded to every step (same semantics
  as the other commands; resolved once via `config.resolve_vault`).
- `--dry-run` — print the detection plan (which steps *would* run and from which
  source) without writing anything. The underlying importers have no dry-run, so
  this reports detection only, not per-note changes.

### Error handling

Continue-on-error. Each step is wrapped in `try/except`; a failure is logged and
the remaining steps still run. A final summary tallies ran / skipped / failed.

## Implementation

New capability module `booktools/sync.py` exposing `register(app)` that attaches
the `sync` command, added to `CAPABILITIES` in `booktools/cli.py` (same pattern
as every other capability). Also add a `scripts/sync.py` shim for parity with the
other standalone shims.

### Structure

Each step is described by a small record with three parts:

- `name` — display label (`"calibre"`, `"goodreads"`, …).
- `detect(vault) -> str | None` — returns a short source description when the
  step should run (e.g. `"~/Calibre Library"`, `".imports/goodreads"`,
  `"Kobo device"`), or `None` to skip.
- `run(vault) -> dict` — performs the import by calling the module's **existing
  core function directly** (no shelling out), returning its stats dict:
  - calibre → `calibre_obsidian.convert(library, vault)`
  - goodreads → `goodreads_obsidian.convert(newest_csv, vault)`
  - kobo → `kobo_export.export_obsidian(db_path, vault)` (db resolved via the
    module's `_default_kobo_db`, which snapshots a mounted device safely)
  - highlighted → `highlighted_obsidian.convert` over each CSV in the folder
    (reusing `resolve_csv_paths`), tallying stats
  - readwise → `readwise_obsidian.convert(newest_csv, vault)`

`sync` resolves the vault once via `config.resolve_vault(output)`, ensures it
exists, then for each step: run `detect`; if it returns a source, print the
header and either (dry-run) note it would run, or call `run` inside try/except
and record a `StepResult`.

A `StepResult` captures: `name`, `status` (`ran` / `skipped` / `failed`),
`summary` (a one-line human string built from the stats dict, or the skip
reason), and `error` (message when failed).

### Detection helpers

- `_has_csv(folder) -> bool` — folder exists and has a top-level `*.csv`.
- `_kobo_source(vault) -> str | None` — `"Kobo device"` if mounted, else the
  imports folder when it holds a `*.sqlite`, else `None`.

Each step formats its own summary from its stats dict (e.g. calibre:
`"12 books, 8 covers, 3 authors"`; readwise: `"5 books, 214 highlights (2 skipped)"`).

### Colored, readable output

Via `typer.secho` / `typer.style`:

- Cyan bold header per step as it starts: `▶ calibre`
- Green `  ✓ 12 books, 8 covers` on success
- Dim/yellow `  ⊘ skipped — no source in .imports/readwise` when skipped
- Red `  ✗ failed — <error>` on failure
- A final aligned summary block: counts of ran / skipped / failed, one line per
  step with its status glyph and summary.

Colors go through Typer's styling (which respects `NO_COLOR` / non-tty), so no
new dependency is introduced.

## Testing

`tests/test_sync.py`:

- **Detection predicates** — temp folders with and without each source; verify
  `detect` returns the right source string or `None`, including the kobo
  device-vs-folder branches.
- **Continue-on-error** — monkeypatch step `run` functions so one raises; assert
  the others still run and the final summary reports one failure with its
  message.
- **Dry-run** — with sources present, assert no `run` is called and no files are
  written, and the plan lists the detected steps.
- **Ordering** — assert steps execute calibre → goodreads → kobo → highlighted →
  readwise (record call order via monkeypatched runs).

Step `run` functions are monkeypatched in tests so no real Calibre/Kobo data is
needed.
