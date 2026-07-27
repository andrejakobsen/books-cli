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

import typer


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
