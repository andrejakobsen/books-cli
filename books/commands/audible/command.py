#!/usr/bin/env python3
"""Import Audible bookmarks & clips into the CSV store.

Audible bookmarks/clips live in your Audible cloud account. This importer
authenticates (via the optional `audible` package), fetches your library and each
book's annotations, downloads the audiobook, and uses ffmpeg to decrypt + cut each
clip's audio, which is transcribed into text. Each library book is resolved to a
book_id against the merged catalog (``Data/books.csv``); a matched book's
transcribed clips are written as per-book highlights (source ``audible``) via
``store.write_highlights`` and an ``audible`` metadata layer row carrying
``format: audiobook``. A book with no catalog match is skipped and counted, so run
the metadata importers + ``merge`` first to build ``Data/books.csv``; run ``merge``
+ ``render`` afterward to fold in the layer and surface the highlights in the actual
notes. Books match by ASIN (the `amazon` id), then by standardized title/author.

Transcriptions are cached one JSON file per book at
<vault>/Data/Imports/audible/cache/<asin>.json (keyed by annotation id within the
file), so re-runs re-render for free and only download a book that has new clips;
downloaded audio is written to a temp dir and deleted after cutting. A legacy
monolithic cache.json is split into per-book files on the first run (then removed).

This is the one capability that needs third-party packages and system ffmpeg (the
documented exception to the stdlib-only rule). Heavy dependencies are imported
lazily so the rest of the CLI never touches them. Downloading/decrypting owned
audiobooks is for personal archival use only.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import typer

from books.commands.audible.models import Annotation, Chapter
from books.core import config, store, ui
from books.core.highlights import Highlight, parse_markers
from books.core.matching import BookRef


def format_timestamp(ms: int) -> str:
    """Format a millisecond offset as ``H:MM:SS`` (hours always present).

    Hours are always the leading component, so the string's leading integer equals
    the hour count -- keeping reading order correct under Highlight.sort_key, which
    reads the first integer of the locator. Negative inputs clamp to zero.
    """
    total = max(0, int(ms)) // 1000
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def chapter_for(start_ms: int, chapters: list[Chapter]) -> Chapter | None:
    """Return the chapter whose [start, end) range contains *start_ms*, else None."""
    for ch in chapters:
        if ch.start_ms <= start_ms < ch.end_ms:
            return ch
    return None


def annotation_to_record(ann: Annotation, text: str, chapters: list[Chapter]) -> dict:
    """Build the cache record for a transcribed annotation."""
    ch = chapter_for(ann.start_ms, chapters)
    return {
        "text": (text or "").strip(),
        "start_ms": int(ann.start_ms),
        "end_ms": None if ann.end_ms is None else int(ann.end_ms),
        "title": ann.title,
        "note": ann.note,
        "date": ann.date,
        "chapter": ch.title if ch else None,
        "chapter_index": ch.index if ch else None,
    }


def _merge_markers(*parts: str | None) -> tuple[str | None, list[str], list[str]]:
    """Parse #tag/@link markers out of each part and merge the results.

    Each part is marker-parsed independently (same convention as Kobo); the
    cleaned texts are joined with newlines in order (blank/missing parts dropped),
    and the links/tags are pooled in first-seen order (de-duplicated). Returns
    ``(merged_text, links, tags)`` with merged_text None when nothing remains.
    """
    texts: list[str] = []
    links: list[str] = []
    tags: list[str] = []
    for part in parts:
        clean, part_links, part_tags = parse_markers((part or "").strip() or None)
        if clean:
            texts.append(clean)
        for link in part_links:
            if link not in links:
                links.append(link)
        for tag in part_tags:
            if tag not in tags:
                tags.append(tag)
    return ("\n".join(texts) or None), links, tags


def record_to_highlight(rec: dict) -> Highlight:
    """Build a source-agnostic Highlight from a cache record.

    The transcription is the highlight text; the clip's title and note are merged
    into the nested blockquote (title first, then body on a new line), with their
    #tag/@link markers parsed out and pooled (same convention as Kobo). When there
    is no transcription, the merged title+note is used as the body so a clip that
    carries only text still comes through. The locator is a bare timestamp (empty
    location_label); the zero-padded ms position goes in `block` so highlights sort
    in exact listening order.
    """
    note, links, tags = _merge_markers(rec.get("title"), rec.get("note"))
    body = (rec.get("text") or "").strip()
    if not body:
        body = note or ""
        note = None
    start = int(rec.get("start_ms") or 0)
    idx = rec.get("chapter_index")
    return Highlight(
        text=body,
        note=note,
        chapter_index=idx if isinstance(idx, int) else None,
        chapter_title=(rec.get("chapter") or None),
        page=format_timestamp(start),
        location_label="",
        block=f"{max(0, start):012d}",
        date=rec.get("date"),
        tags=tags,
        links=links,
    )


def book_cache_path(cache_dir: Path, asin: str) -> Path:
    """The cache file for one book: ``<cache_dir>/<asin>.json``.

    The ASIN is the book's stable key throughout this importer, so it is the
    natural per-book filename (unique, filesystem-safe, no lookup needed).
    """
    return cache_dir / f"{asin}.json"


def load_book_cache(cache_dir: Path, asin: str) -> dict:
    """Load one book's cache record ``{title, clips}``, or {} when missing/corrupt."""
    try:
        return json.loads(book_cache_path(cache_dir, asin).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_book_cache(cache_dir: Path, asin: str, data: dict) -> None:
    """Write one book's cache record as pretty JSON (parents created)."""
    path = book_cache_path(cache_dir, asin)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_legacy_cache(cache_dir: Path) -> dict:
    """Load the pre-split monolithic ``cache.json`` (sibling of *cache_dir*), or {}."""
    try:
        data = json.loads(cache_dir.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def migrate_legacy_cache(cache_dir: Path) -> None:
    """Split a legacy monolithic ``cache.json`` into per-book ``<asin>.json`` files.

    One-time upgrade: each ASIN keyed in the old ``<...>/audible/cache.json`` is
    written to its own ``<cache_dir>/<asin>.json`` (an existing per-book file is
    never overwritten), then the legacy file is removed. A no-op when it is absent,
    so re-runs cost nothing.
    """
    legacy_path = cache_dir.with_suffix(".json")
    if not legacy_path.exists():
        return
    for asin, rec in load_legacy_cache(cache_dir).items():
        if isinstance(rec, dict) and not book_cache_path(cache_dir, asin).exists():
            save_book_cache(cache_dir, asin, rec)
    legacy_path.unlink(missing_ok=True)


def uncached(annotations: list[Annotation], clips: dict) -> list[Annotation]:
    """Return the annotations whose id is not already in the cached clips."""
    return [a for a in annotations if a.id not in clips]


def book_highlight_rows(clips: dict, valid_ids: set | None = None) -> list[store.HighlightRow]:
    """Map a book's cached clips into audible-source HighlightRows.

    Each clip record becomes a Highlight (:func:`record_to_highlight`); empty-text
    records are dropped. The cache key (the Audible annotation id) is the stable
    ``annotation_id`` so re-runs replace cleanly.

    ``valid_ids`` (the current run's annotation ids) prunes stale cache entries: a
    ``cache.json`` written before the twin-bookmark/duplicate-note dedup still holds
    transcriptions for ids that are no longer annotations, and emitting them would
    resurface the very duplicates the dedup removes. When ``valid_ids`` is None all
    cached records are emitted (used where the caller has no annotation list).
    """
    rows: list[store.HighlightRow] = []
    for ann_id, rec in clips.items():
        if valid_ids is not None and ann_id not in valid_ids:
            continue
        h = record_to_highlight(rec)
        if h.text:
            rows.append(store.highlight_to_row(h, "audible", ann_id))
    return rows


def _is_text_only(ann: Annotation) -> bool:
    """True for a standalone note: it has an explicit zero-length range (end == start).

    Such an annotation carries user text but no chosen audio span, so it is rendered
    from its text alone — never downloaded, cut, or transcribed. A clip (end > start)
    and a legacy point bookmark (end is None) are both False.
    """
    return ann.end_ms is not None and ann.end_ms <= ann.start_ms


def _clip_bounds(ann: Annotation, clip_window: int) -> tuple[int, int]:
    """Resolve the (start_ms, end_ms) audio range to cut for an annotation.

    A clip uses its own recorded start/end. A point bookmark (no end position) has
    no duration, so a *clip_window*-second window ending at the mark is used
    (people bookmark just after hearing something)."""
    if ann.end_ms is not None:
        return int(ann.start_ms), int(ann.end_ms)
    end = int(ann.start_ms)
    return max(0, end - clip_window * 1000), end


def _clip_seconds(anns, clip_window: int) -> float:
    """Total audio seconds that *anns* would be cut/transcribed to."""
    total_ms = 0
    for ann in anns:
        start, end = _clip_bounds(ann, clip_window)
        total_ms += max(0, end - start)
    return total_ms / 1000.0


# Transcription price estimate (dry-run only): OpenAI-style per-audio-second.
COST_PER_SECOND = 0.00028


def run(
    vault,
    *,
    client,
    downloader,
    cutter,
    transcriber,
    cache_dir,
    clip_window,
    limit=None,
    asin=None,
    dry_run=False,
    echo=lambda *_: None,
) -> dict:
    """Import Audible clips into the CSV store. All heavy I/O is injected.

    Resolves each library book to a book_id via the merged catalog
    (Data/books.csv); an unmatched book is skipped and counted. For a matched book
    with transcribed clips, writes per-book highlights (source ``audible``) and an
    ``audible`` metadata layer row (``format: audiobook``). ``merge`` + ``render``
    later surface them. In *dry_run* mode nothing is written.
    """
    vault.mkdir(parents=True, exist_ok=True)
    catalog = store.Catalog(vault)
    stats = {
        "books": 0,
        "entries": 0,
        "skipped": 0,
        "downloaded": 0,
        "transcribed": 0,
        "failed": 0,
        "est_seconds": 0.0,
    }

    library = client.library()
    if asin:
        library = [b for b in library if b.asin == asin]

    if dry_run:
        return _run_dry(library, catalog, cache_dir, stats, client, clip_window, limit, echo)

    # One-time upgrade of an old monolithic cache.json into per-book files.
    migrate_legacy_cache(cache_dir)

    # Preserve other audiobooks' layer rows across partial (--asin/--limit) runs.
    layer = {r.amazon: r for r in store.read_layer(vault, "audible") if r.amazon}

    # Pre-pass: resolve matches locally (no network) so the bar counts matched books.
    matched: list = []
    for book in library:
        ref = BookRef(title=book.title, authors=book.authors, amazon=book.asin)
        book_id = catalog.find(ref)
        if book_id is None:
            stats["skipped"] += 1
            continue
        matched.append((book, book_id))
    if limit is not None:
        matched = matched[:limit]

    with ui.nested_progress("Importing audiobooks", total=len(matched)) as prog:
        for book, book_id in matched:
            authors = ", ".join(book.authors) or "?"
            # Isolate each book: a single failure (an unpublished/undownloadable
            # title, a license/voucher error, a network hiccup, a bad transcribe)
            # is counted and skipped so it never aborts the whole run.
            try:
                prog.status(f"{book.title} — {authors}")
                annotations = client.annotations(book.asin)
                if not annotations:
                    continue

                book_cache = load_book_cache(cache_dir, book.asin)
                book_cache.setdefault("title", book.title)
                clips = book_cache.setdefault("clips", {})
                new = uncached(annotations, clips)

                if new:
                    chapters = client.chapters(book.asin)
                    # Text-only notes (end == start) have no audio range: their text
                    # IS the highlight, so they need no download/cut/transcribe.
                    needs_audio = any(not _is_text_only(a) for a in new)
                    with tempfile.TemporaryDirectory() as td:
                        tmp = Path(td)
                        audio = None
                        if needs_audio:
                            prog.status(f"{book.title} — {authors} · downloading")
                            audio = downloader.download(book.asin, tmp)
                            stats["downloaded"] += 1
                        for i, ann in enumerate(new, start=1):
                            if _is_text_only(ann):
                                text = ""  # note text becomes the body in record_to_highlight
                            else:
                                prog.status(
                                    f"{book.title} — {authors} · transcribing clip {i}/{len(new)}"
                                )
                                start, end = _clip_bounds(ann, clip_window)
                                clip_path = cutter.cut(audio, start, end, tmp / f"{ann.id}.wav")
                                text = transcriber(clip_path)
                                stats["transcribed"] += 1
                            clips[ann.id] = annotation_to_record(ann, text, chapters)
                    save_book_cache(cache_dir, book.asin, book_cache)

                rows = book_highlight_rows(clips, valid_ids={a.id for a in annotations})
                if not rows:
                    continue
                store.write_highlights(vault, book_id, "audible", rows)
                layer[book.asin] = store.BookRow(
                    title=book.title,
                    authors=list(book.authors),
                    amazon=book.asin,
                    format="audiobook",
                )
                stats["books"] += 1
                stats["entries"] += len(rows)
            except Exception as exc:  # noqa: BLE001 — continue-on-error per book
                stats["failed"] += 1
                echo(f"[skip] {book.title} [asin {book.asin}]: {exc}")
            finally:
                prog.advance()

    store.write_layer(vault, "audible", list(layer.values()))
    return stats


def _run_dry(library, catalog, cache_dir, stats, client, clip_window, limit, echo) -> dict:
    """Dry-run path: log matches + estimated transcription, write nothing.

    Reads per-book caches (falling back to a not-yet-migrated legacy ``cache.json``)
    to estimate only the *new* clips, but never writes or migrates on disk.
    """
    legacy = load_legacy_cache(cache_dir)
    matched = 0
    for book in library:
        ref = BookRef(title=book.title, authors=book.authors, amazon=book.asin)
        book_id = catalog.find(ref)
        if book_id is None:
            stats["skipped"] += 1
            authors = ", ".join(book.authors) or "?"
            anns = client.annotations(book.asin)
            secs = _clip_seconds(anns, clip_window)
            stats["est_seconds"] += secs
            echo(
                f"[dry-run] SKIP (no book): {book.title} — {authors} "
                f"[asin {book.asin}] — {len(anns)} clip(s), "
                f"~{secs / 60:.1f} min, ~${secs * COST_PER_SECOND:.2f}"
            )
            continue
        if limit is not None and matched >= limit:
            break
        matched += 1
        annotations = client.annotations(book.asin)
        if not annotations:
            continue
        book_cache = load_book_cache(cache_dir, book.asin) or legacy.get(book.asin, {})
        clips = book_cache.get("clips", {})
        new = uncached(annotations, clips)
        secs = _clip_seconds(new, clip_window)
        stats["est_seconds"] += secs
        echo(
            f"[dry-run] {book.title}: {len(annotations)} annotations, "
            f"{len(new)} new to transcribe — ~{secs / 60:.1f} min, "
            f"~${secs * COST_PER_SECOND:.2f}"
        )
    return stats


def _build_client(quality: str = "normal"):
    """Construct the live Audible client (auto-login on first run)."""
    from books.commands.audible.client import AudibleClient, default_auth_path

    return AudibleClient.load_or_login(default_auth_path(), quality=quality)


def _build_transcriber(kind: str, model: str):
    from books.commands.audible.transcribe import make_transcriber

    return make_transcriber(kind, model)


def _build_cutter():
    from books.commands.audible.transcribe import check_ffmpeg, cut_clip

    class _FfmpegCutter:
        def cut(self, audio, start_ms, end_ms, dest):
            return cut_clip(audio, start_ms, end_ms, dest)

    check_ffmpeg()
    return _FfmpegCutter()


def _build_downloader(client):
    class _AudibleDownloader:
        def download(self, asin, dest_dir):
            return client.download(asin, dest_dir)

    return _AudibleDownloader()


def audible_command(
    transcriber: str = typer.Option(
        "local",
        "--transcriber",
        "-t",
        help="Speech-to-text backend: 'local' (faster-whisper, no key, offline), "
        "'openai' (needs OPENAI_API_KEY), or 'google' (free, lower quality).",
    ),
    model: str = typer.Option(
        "small", "--model", help="Whisper model size for the local/openai backends."
    ),
    clip_window: int = typer.Option(
        30,
        "--clip-window",
        help="Seconds of audio to transcribe for a point bookmark that has no end "
        "position (the window ends at the mark). Clips use their own length.",
    ),
    quality: str = typer.Option(
        "normal",
        "--quality",
        help="Audiobook download quality: 'normal' (smallest/fastest, ample for "
        "transcription), 'high', or 'best'. Only affects download size — clips "
        "are transcribed to text either way.",
    ),
    limit: int | None = typer.Option(
        None, "--limit", help="Process at most this many matched books."
    ),
    asin: str | None = typer.Option(
        None, "--asin", help="Only process the book with this Audible ASIN."
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
        "(~/.config/books/config.toml).",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show which books match and how many clips would be transcribed "
        "(still logs in to read your library), without downloading audio, "
        "transcribing, or writing.",
    ),
) -> None:
    """Import Audible bookmarks & clips into the CSV store.

    Authenticates to your Audible account (prompting on first run and caching the
    auth), then for each library book that matches the merged catalog (by ASIN,
    then title/author) fetches its bookmarks/clips, downloads the audiobook, and
    cuts + transcribes each new clip. Matched books' clips are written as per-book
    highlights (source 'audible') and an 'audible' metadata layer with
    'format: audiobook'; run 'merge' + 'render' afterward to surface them in the
    notes. A book with no catalog match is skipped and counted (run
    calibre/goodreads/merge first). Transcriptions are cached, so re-runs only
    download books with new clips.
    """
    from books.commands.audible.client import AudibleClient

    if quality not in AudibleClient.QUALITY_CHOICES:
        raise typer.BadParameter(
            f"--quality must be one of {', '.join(AudibleClient.QUALITY_CHOICES)}"
        )

    vault = config.resolve_vault(output)
    cache_dir = config.resolve_imports("audible", output) / "cache"

    client = _build_client(quality)
    if dry_run:
        downloader = cutter = transcribe_fn = None
    else:
        transcribe_fn = _build_transcriber(transcriber, model)
        cutter = _build_cutter()
        downloader = _build_downloader(client)

    stats = run(
        vault,
        client=client,
        downloader=downloader,
        cutter=cutter,
        transcriber=transcribe_fn,
        cache_dir=cache_dir,
        clip_window=clip_window,
        limit=limit,
        asin=asin,
        dry_run=dry_run,
        echo=ui.info,
    )

    if dry_run:
        secs = stats["est_seconds"]
        ui.info(
            f"Dry run: {stats['skipped']} book(s) skipped — no book match. "
            f"Estimated transcription: ~{secs / 60:.1f} min "
            f"(~${secs * COST_PER_SECOND:.2f} @ ${COST_PER_SECOND:.5f}/sec) "
            f"across all listed clips."
        )
        return
    books_word = "book" if stats["books"] == 1 else "books"
    skip = store.skipped_note(stats["skipped"])
    fail = f", {stats['failed']} failed" if stats.get("failed") else ""
    ui.info(
        f"Done. {stats['books']} {books_word}{skip}, {stats['entries']} clips, "
        f"{stats['downloaded']} downloaded, {stats['transcribed']} transcribed"
        f"{fail}.\n"
        f"Output: {vault}"
    )


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("audible")(audible_command)
