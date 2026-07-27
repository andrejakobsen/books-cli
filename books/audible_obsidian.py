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

from dataclasses import dataclass, field
from pathlib import Path

import typer

from books.highlights import Highlight, parse_markers, render_highlights


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


def audible_command() -> None:
    """Import Audible bookmarks & clips into existing Obsidian book notes."""
    typer.echo("not implemented yet")


def register(app: typer.Typer) -> None:
    """Register this capability's command(s) on the shared Typer app."""
    app.command("audible")(audible_command)


def main() -> None:
    """Standalone entry point so the shim script keeps working on its own."""
    typer.run(audible_command)


if __name__ == "__main__":
    main()
