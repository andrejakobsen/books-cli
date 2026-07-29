#!/usr/bin/env python3
"""Import Audible bookmarks & clips into existing Obsidian book notes.

Audible bookmarks/clips live in your Audible cloud account. This importer
authenticates (via the optional `audible` package), fetches your library and each
book's annotations, downloads the audiobook, and uses ffmpeg to decrypt + cut each
clip's audio, which is transcribed into text and embedded under a marker-wrapped
"## Highlights" heading of the *matching* book note. Like kobo/highlighted, it only
enriches notes created by calibre/goodreads -- it never creates book notes; a book
with no matching note is skipped and counted. Books match by ASIN (the `amazon`
frontmatter id), then by standardized title/author.

Transcriptions are cached in <vault>/.imports/audible/cache.json (keyed by
ASIN + annotation id), so re-runs re-render for free and only download a book that
has new clips; downloaded audio is written to a temp dir and deleted after cutting.

This is the one capability that needs third-party packages and system ffmpeg (the
documented exception to the stdlib-only rule). Heavy dependencies are imported
lazily so the rest of the CLI never touches them. Downloading/decrypting owned
audiobooks is for personal archival use only.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import typer

from books.core import config
from books.highlights import Highlight, parse_markers, render_highlights
from books.obsidian import (
    AUTHORS_DIRNAME,
    BookRef,
    VaultIndex,
    link_list,
    render_marked_section,
    update_frontmatter,
    write_stub,
    yaml_quote,
)


@dataclass
class LibraryBook:
    """A book in the Audible library."""
    asin: str
    title: str
    authors: list[str] = field(default_factory=list)


@dataclass
class Annotation:
    """A single Audible bookmark, clip, or note.

    `end_ms` is None for a point bookmark (the plain "bookmark" button has no
    duration); a clip carries both start and end. `note` is the user's typed text
    (may be None).
    """
    id: str
    start_ms: int
    end_ms: int | None = None
    note: str | None = None
    date: str | None = None


@dataclass
class Chapter:
    """A chapter with its position range (end exclusive), in reading order."""
    index: int
    title: str
    start_ms: int
    end_ms: int


@dataclass
class DownloadedAudio:
    """A downloaded (still-encrypted) audiobook plus its AAXC decryption key/iv.

    `key`/`iv` are None for a non-DRM source; when set, ffmpeg decrypts on the fly
    via -audible_key/-audible_iv while cutting each clip.
    """
    path: "Path"
    key: str | None = None
    iv: str | None = None


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


def annotation_to_record(ann: Annotation, text: str,
                         chapters: list[Chapter]) -> dict:
    """Build the cache record for a transcribed annotation."""
    ch = chapter_for(ann.start_ms, chapters)
    return {
        "text": (text or "").strip(),
        "start_ms": int(ann.start_ms),
        "end_ms": None if ann.end_ms is None else int(ann.end_ms),
        "note": ann.note,
        "date": ann.date,
        "chapter": ch.title if ch else None,
        "chapter_index": ch.index if ch else None,
    }


def record_to_highlight(rec: dict) -> Highlight:
    """Build a source-agnostic Highlight from a cache record.

    The transcription is the highlight text; the user's typed note becomes the
    nested blockquote (with its #tag/@link markers parsed out, same convention as
    Kobo). When there is no transcription, the note text is used as the body so a
    bookmark that carries only a note still comes through. The locator is a bare
    timestamp (empty location_label); the zero-padded ms position goes in `block`
    so highlights sort in exact listening order.
    """
    note, links, tags = parse_markers((rec.get("note") or "").strip() or None)
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


def load_cache(path: Path) -> dict:
    """Load the transcription cache, or {} when missing/corrupt."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(path: Path, data: dict) -> None:
    """Write the transcription cache as pretty JSON (parents created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                    encoding="utf-8")


def uncached(annotations: list[Annotation], clips: dict) -> list[Annotation]:
    """Return the annotations whose id is not already in the cached clips."""
    return [a for a in annotations if a.id not in clips]


def render_note(note_path: Path, book: LibraryBook, clips: dict) -> int:
    """Enrich an existing book note with a book's cached clips.

    Fills provenance frontmatter -- including `format: audiobook` -- (never
    overwriting existing values, except the `highlighted` flag which flips to
    true) and replaces the marked "## Highlights" section. Empty-text records are
    dropped. Returns the number of highlights written.
    """
    highlights = [record_to_highlight(rec) for rec in clips.values()]
    highlights = [h for h in highlights if h.text]
    if not highlights:
        # Nothing transcribed (and no note text): don't flip `highlighted` or
        # write an empty section — leave the note untouched.
        return 0

    updates = {
        "title": yaml_quote(book.title),
        "authors": link_list(book.authors) if book.authors else "",
        "amazon": yaml_quote(book.asin) if book.asin else "",
        "source": "audible",
        "format": "audiobook",
        "highlighted": "true",
    }
    base = note_path.read_text(encoding="utf-8")
    note_path.write_text(update_frontmatter(base, updates), encoding="utf-8")

    text = note_path.read_text(encoding="utf-8")
    text = render_marked_section(
        text, "Highlights", "highlights",
        render_highlights(highlights, chapter_label="Audible ch."))
    note_path.write_text(text, encoding="utf-8")
    return len(highlights)


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


def run(vault, *, client, downloader, cutter, transcriber, cache_path,
        clip_window, limit=None, asin=None, dry_run=False,
        echo=lambda *_: None) -> dict:
    """Import Audible clips into matching notes. All heavy I/O is injected.

    Returns a stats dict: books/entries/skipped/downloaded/transcribed. In
    *dry_run* mode nothing is downloaded, transcribed, cached, or written; the plan
    is emitted via *echo*.
    """
    vault.mkdir(parents=True, exist_ok=True)
    index = VaultIndex(vault)
    authors_dir = vault / AUTHORS_DIRNAME
    cache = load_cache(cache_path)
    stats = {"books": 0, "entries": 0, "skipped": 0,
             "downloaded": 0, "transcribed": 0, "failed": 0,
             "est_seconds": 0.0}

    library = client.library()
    if asin:
        library = [b for b in library if b.asin == asin]

    matched = 0
    for book in library:
        # Isolate each book: a single failure (an unpublished/undownloadable
        # title, a license/voucher error, a network hiccup, a bad transcribe)
        # is counted and skipped so it never aborts the whole run.
        try:
            ref = BookRef(title=book.title, authors=book.authors,
                          amazon=book.asin)
            dest = index.find(ref)
            if dest is None:
                stats["skipped"] += 1
                if dry_run:
                    authors = ", ".join(book.authors) or "?"
                    anns = client.annotations(book.asin)
                    secs = _clip_seconds(anns, clip_window)
                    stats["est_seconds"] += secs
                    echo(f"[dry-run] SKIP (no note): {book.title} — {authors} "
                         f"[asin {book.asin}] — {len(anns)} clip(s), "
                         f"~{secs/60:.1f} min, ~${secs * COST_PER_SECOND:.2f}")
                continue
            if limit is not None and matched >= limit:
                break
            matched += 1

            annotations = client.annotations(book.asin)
            if not annotations:
                continue

            book_cache = cache.setdefault(book.asin,
                                          {"title": book.title, "clips": {}})
            clips = book_cache.setdefault("clips", {})
            new = uncached(annotations, clips)

            if dry_run:
                secs = _clip_seconds(new, clip_window)
                stats["est_seconds"] += secs
                echo(f"[dry-run] {book.title}: {len(annotations)} annotations, "
                     f"{len(new)} new to transcribe — ~{secs/60:.1f} min, "
                     f"~${secs * COST_PER_SECOND:.2f}")
                continue

            if new:
                chapters = client.chapters(book.asin)
                with tempfile.TemporaryDirectory() as td:
                    tmp = Path(td)
                    audio = downloader.download(book.asin, tmp)
                    stats["downloaded"] += 1
                    for ann in new:
                        start, end = _clip_bounds(ann, clip_window)
                        clip_path = cutter.cut(audio, start, end,
                                               tmp / f"{ann.id}.wav")
                        text = transcriber(clip_path)
                        clips[ann.id] = annotation_to_record(
                            ann, text, chapters)
                        stats["transcribed"] += 1
                save_cache(cache_path, cache)

            n = render_note(dest.note_path, book, clips)
            if n == 0:
                # No renderable highlights for this book — note left untouched.
                continue
            for author in book.authors:
                write_stub(authors_dir, author, "author")
            stats["books"] += 1
            stats["entries"] += n
        except Exception as exc:  # noqa: BLE001 — continue-on-error per book
            stats["failed"] += 1
            echo(f"[skip] {book.title} [asin {book.asin}]: {exc}")
            continue

    return stats


def _build_client(quality: str = "normal"):
    """Construct the live Audible client (auto-login on first run)."""
    from books.audible_client import AudibleClient, default_auth_path
    return AudibleClient.load_or_login(default_auth_path(), quality=quality)


def _build_transcriber(kind: str, model: str):
    from books.audible_transcribe import make_transcriber
    return make_transcriber(kind, model)


def _build_cutter():
    from books.audible_transcribe import check_ffmpeg, cut_clip

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
        "local", "--transcriber", "-t",
        help="Speech-to-text backend: 'local' (faster-whisper, no key, offline), "
             "'openai' (needs OPENAI_API_KEY), or 'google' (free, lower quality)."),
    model: str = typer.Option(
        "small", "--model",
        help="Whisper model size for the local/openai backends."),
    clip_window: int = typer.Option(
        30, "--clip-window",
        help="Seconds of audio to transcribe for a point bookmark that has no end "
             "position (the window ends at the mark). Clips use their own length."),
    quality: str = typer.Option(
        "normal", "--quality",
        help="Audiobook download quality: 'normal' (smallest/fastest, ample for "
             "transcription), 'high', or 'best'. Only affects download size — clips "
             "are transcribed to text either way."),
    limit: int | None = typer.Option(
        None, "--limit", help="Process at most this many matched books."),
    asin: str | None = typer.Option(
        None, "--asin", help="Only process the book with this Audible ASIN."),
    output: Path | None = typer.Option(
        None, "--output", "-o",
        help="Output Obsidian vault. Defaults to the vault from your config file "
             "(~/.config/books/config.toml)."),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Show which books match and how many clips would be transcribed "
             "(still logs in to read your library), without downloading audio, "
             "transcribing, or writing."),
) -> None:
    """Import Audible bookmarks & clips into existing Obsidian book notes.

    Authenticates to your Audible account (prompting on first run and caching the
    auth), then for each library book that matches an existing note (by ASIN, then
    title/author) fetches its bookmarks/clips, downloads the audiobook, and cuts +
    transcribes each new clip into a marker-wrapped '## Highlights' section. A book
    with no matching note is skipped and counted (run calibre/goodreads first).
    Transcriptions are cached, so re-runs only download books with new clips.
    """
    from books.audible_client import AudibleClient
    if quality not in AudibleClient.QUALITY_CHOICES:
        raise typer.BadParameter(
            f"--quality must be one of {', '.join(AudibleClient.QUALITY_CHOICES)}")

    vault = config.resolve_vault(output)
    cache_path = config.resolve_imports("audible", output) / "cache.json"

    client = _build_client(quality)
    if dry_run:
        downloader = cutter = transcribe_fn = None
    else:
        transcribe_fn = _build_transcriber(transcriber, model)
        cutter = _build_cutter()
        downloader = _build_downloader(client)

    stats = run(
        vault, client=client, downloader=downloader, cutter=cutter,
        transcriber=transcribe_fn, cache_path=cache_path,
        clip_window=clip_window, limit=limit, asin=asin, dry_run=dry_run,
        echo=typer.echo,
    )

    if dry_run:
        secs = stats["est_seconds"]
        typer.echo(
            f"Dry run: {stats['skipped']} book(s) skipped — no note. "
            f"Estimated transcription: ~{secs/60:.1f} min "
            f"(~${secs * COST_PER_SECOND:.2f} @ ${COST_PER_SECOND:.5f}/sec) "
            f"across all listed clips.")
        return
    books_word = "book" if stats["books"] == 1 else "books"
    skip = (f" ({stats['skipped']} skipped — no note)"
            if stats["skipped"] else "")
    fail = f", {stats['failed']} failed" if stats.get("failed") else ""
    typer.echo(
        f"Done. {stats['books']} {books_word}{skip}, {stats['entries']} clips, "
        f"{stats['downloaded']} downloaded, {stats['transcribed']} transcribed"
        f"{fail}.\n"
        f"Output: {vault}")


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("audible")(audible_command)


def main() -> None:
    """Standalone entry point so the shim script keeps working on its own."""
    typer.run(audible_command)


if __name__ == "__main__":
    main()
