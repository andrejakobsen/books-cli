"""Shared Audible data models used by the command, client, and transcriber."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LibraryBook:
    """A book in the Audible library."""

    asin: str
    title: str
    authors: list[str] = field(default_factory=list)


@dataclass
class Candidate:
    """A library book prepared for selection: its catalog match + fetched clips.

    Built once by :func:`books.commands.audible.command.build_candidates` so the
    picker and :func:`run` share a single ``annotations`` fetch. ``book_id`` is the
    resolved catalog id (None for an audiobook-only book with no calibre/goodreads
    match); ``cached`` is True when a per-book transcription cache already exists.
    """

    book: LibraryBook
    annotations: list[Annotation] = field(default_factory=list)
    book_id: str | None = None
    cached: bool = False

    @property
    def in_library(self) -> bool:
        """True when this book matches the merged catalog (has a book_id)."""
        return self.book_id is not None

    @property
    def clip_count(self) -> int:
        """Number of Audible annotations (bookmarks/clips/notes) on this book."""
        return len(self.annotations)


@dataclass
class Annotation:
    """A single Audible bookmark, clip, or note.

    `end_ms` is None for a point bookmark (the plain "bookmark" button has no
    duration); a clip carries both start and end. `title` is the clip's title and
    `note` is its note body -- both user-typed (either may be None).
    """

    id: str
    start_ms: int
    end_ms: int | None = None
    title: str | None = None
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

    path: Path
    key: str | None = None
    iv: str | None = None
