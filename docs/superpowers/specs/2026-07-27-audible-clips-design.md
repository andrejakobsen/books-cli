# Audible clips importer — design

**Date:** 2026-07-27
**Command:** `books audible`
**Module:** `books/audible_obsidian.py` (added to `CAPABILITIES`; shim `scripts/audible.py`)
**Status:** Approved (brainstorming) — pending implementation plan

## Summary

A new capability that imports **Audible bookmarks and clips** into existing Obsidian
book notes, transcribing the audio of each clip into text. It is a *highlight
importer* in the same family as `kobo`, `highlighted`, and `readwise`: it **enriches
existing notes only** and never creates them. Inspiration was drawn from
`gostak-dd/audible-bookmark-extractor` and `jaredgth/audible-bookmark-transcriber`,
adapted to this project's shared Obsidian layer, never-overwrite merge, marked
sections, and idempotent re-run philosophy.

Unlike every other capability, this one requires third-party packages and system
`ffmpeg`; it is the documented exception to the "stdlib + Typer only" rule.

## Data model recap (Audible annotations)

The Audible cloud API returns per-book annotations in two relevant shapes:

- **Clip** — carries both `startPosition` and `endPosition` (a real duration). We
  transcribe exactly `start → end`, whatever length the user recorded.
- **Bookmark** — a single `startPosition`, **no end**. There is no duration in the
  data, so we transcribe a fallback window (see `--clip-window`).

Both may carry a user-typed `note` (free text) and a `creationTime`. The library
listing supplies ASIN, title, authors, and chapter metadata (chapter title +
position ranges).

## Decisions (from brainstorming)

1. **Data source:** full pipeline built into `books` — authenticate to Audible,
   fetch annotations, download the audiobook, decrypt + cut clips with `ffmpeg`,
   transcribe, enrich notes.
2. **Transcriber:** pluggable via `--transcriber local|openai|google`, all behind
   one interface. **Default `local`** (faster-whisper, `small` model): no API key,
   offline, free.
3. **Caching:** cache transcripts, drop audio. Transcriptions persist in a JSON
   cache keyed by ASIN + annotation id; downloaded audio goes to a temp dir and is
   deleted after cutting/transcribing. Re-runs re-render from cache for free and
   only download a book that has genuinely new clips.
4. **Note creation:** **enrich-only** — match via `VaultIndex.find` (ASIN as the
   `amazon` id, then standardized title/author); a book with no matching note is
   skipped and counted. Consistent with the other three highlight importers.
5. **Auth flow:** **auto-prompt on first run**. No cached auth → interactive login,
   then continue; later runs are silent.
6. **Sync:** **standalone** — not added to the `sync` orchestrator (audible is
   heavy/networked and may cost money on paid transcribers).

## Dependencies & the stdlib-only exception

- Add an optional extra to `pyproject.toml`:
  ```toml
  [project.optional-dependencies]
  audible = ["audible", "faster-whisper", "openai", "SpeechRecognition", "pydub"]
  ```
  Base `books` stays stdlib + Typer.
- **Lazy imports** inside `audible_obsidian.py`, each guarded with a clear message:
  *"audible support needs extra deps — install with `uv tool install '.[audible]'`"*.
  No other command imports these.
- System **ffmpeg** is required for decrypt + cut; checked at runtime with a friendly
  error if absent.
- CLAUDE.md documents this as the explicit exception to the stdlib-only rule, plus a
  personal-use / DRM note (mirroring the reference repos).

## Authentication

- `books audible` with no cached auth drops into the `audible` library's interactive
  login: email, password, marketplace prompt, OTP / CAPTCHA callback.
- Auth is saved to `~/.config/books/audible-auth.json` (mode `0600`); marketplace
  defaults to a config key (default `us`, prompt-overridable). Later runs load the
  cached auth silently and refresh as the library supports.

## Pipeline (per run)

1. Load auth → fetch **library** (ASIN, title, authors, chapter metadata).
2. **Match before download:** resolve each library book via `VaultIndex.find` (ASIN
   → `amazon`, then title/author). No note → skip + count *before any download*.
   This is the primary cost-saver.
3. For matched books, fetch **annotations**. Diff against the cache; a clip is "new"
   only if its annotation id is absent from the cache.
4. If a book has new clips: download the AAXC to a temp dir, `ffmpeg`-decrypt + cut
   each new clip (clips → `start → end`; point bookmarks → `--clip-window` seconds
   ending at the mark), transcribe with the selected backend, write results into
   `cache.json`, then **delete the audio**.
5. Build `Highlight`s from the **cache** (all clips for the book, new and cached):
   - `text` = transcription (falls back to the user's typed note if audio /
     transcription is unavailable).
   - `note` = user's typed note (rendered as the nested `>>` blockquote).
   - timestamp (`ms → H:MM:SS`) as the locator; chapter title mapped from position →
     enables the existing chapter grouping.
   - tags / links parsed from the note via the `#tag` / `@link` convention
     (`parse_markers`, same as Kobo).
   - `date` = `creationTime`.
6. Render into the marked `## Highlights` section (`render_marked_section` →
   idempotent), set frontmatter `source: audible`, `amazon: <ASIN>` (never-overwrite),
   `highlighted: true`.

## Cache

`<vault>/.imports/audible/cache.json`:

```json
{
  "<ASIN>": {
    "title": "...",
    "clips": {
      "<annotationId>": {
        "text": "transcription",
        "start_ms": 12345,
        "end_ms": 20345,
        "note": "user note or null",
        "date": "creationTime",
        "chapter": "Chapter title or null"
      }
    }
  }
}
```

Re-runs re-render from cache for free; the network is touched only for books with new
clips.

## CLI options

| Option | Default | Notes |
|---|---|---|
| `--transcriber local\|openai\|google` | `local` | one interface, three backends |
| `--model` | `small` | whisper model size (local/openai) |
| `--clip-window SECONDS` | `30` | **point bookmarks only** (no end position) |
| `--limit N` | none | cap number of books processed |
| `--asin ASIN` | none | target a single book |
| `--output` / `-o` | config vault | standard vault override |
| `--dry-run` | off | print the plan (matched books, what would download/transcribe); no writes, no downloads |

## Shared-layer change

One tiny, backward-compatible tweak to `books/highlights.py`: an explicitly-empty
`location_label` (`""`) suppresses the `p.` prefix so audio timestamps render bare
(`ch. 3 · 3:24:15`). Current callers pass `None` → still `p.`. The ms position is
stuffed into the `block` sort field so reading order stays correct. All other
rendering reuses the existing `Highlight` / `render_highlights` machinery unchanged.

## Testing

Follow the `covers.py` pattern — **inject all network / heavy I/O** (audible client,
downloader, `ffmpeg` runner, transcriber) so the suite runs offline and fast. Cover:

- annotation → `Highlight` mapping (clip vs point bookmark; note-only fallback)
- `ms → H:MM:SS` timestamp formatting
- cache read / write + skip-cached (no re-download / re-transcribe)
- match / skip (ASIN, then title/author; unmatched skipped + counted)
- `--dry-run` plan output (no writes, no downloads)
- marked-section idempotency across re-runs
- frontmatter never-overwrite merge (`amazon`, `source`, `highlighted`)
- empty-`location_label` rendering + `block`-based timestamp ordering

## Docs to update

- CLAUDE.md: add the `audible` capability entry; bump the capability count; note the
  `.imports/audible` folder; document the stdlib-only exception and DRM/personal-use
  caveat; note that `audible` is a highlight importer (enrich-only) and is **not** in
  `sync`.
- `scripts/audible.py` shim kept in sync with the module.

## Legal / personal-use note

Downloading and decrypting owned audiobooks is for personal archival use only, as with
the reference tools. This is documented in the module docstring and CLAUDE.md; the tool
never distributes DRM-free files.
