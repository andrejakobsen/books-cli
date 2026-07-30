"""Flat vault layout: folder names, cover width, hub stubs."""

from __future__ import annotations

from pathlib import Path

from books.core.naming import safe_filename
from books.renderers.obsidian.format import wikilink

# --- Vault layout -----------------------------------------------------------

# Book notes live flat in vault/Books/ and are the single indexed file per book:
# frontmatter + a cover embed + inline highlights (+ an optional review). Covers
# live flat in vault/Data/Covers/ (tool-managed data; the embed still resolves,
# and the user hides Data/ in Obsidian). Author hub stubs live in vault/Authors/.
BOOKS_DIRNAME = "Books"
COVERS_DIRNAME = "Data/Covers"
AUTHORS_DIRNAME = "Authors"

# Width (in px) for the cover embed at the top of a book note.
COVER_WIDTH = 150


def cover_link(stem: str) -> str:
    """The ``cover:`` frontmatter wikilink to a book's materialized cover image."""
    return f"[[{COVERS_DIRNAME}/{stem}.jpg]]"


def cover_embed(stem: str) -> str:
    """The top-of-body cover embed line for a book note (sized to COVER_WIDTH)."""
    return f"![[{COVERS_DIRNAME}/{stem}.jpg|{COVER_WIDTH}]]"


# --- Filesystem helpers -----------------------------------------------------


def write_if_absent(path: Path, content: str) -> bool:
    """Write only if the file does not exist yet. Returns True if written."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def write_stub(hub_dir: Path, name: str, note_type: str) -> None:
    """Create a stub hub note (author/genre) if it does not already exist."""
    safe = safe_filename(wikilink(name)[2:-2])
    write_if_absent(hub_dir / f"{safe}.md", f"---\ntype: {note_type}\n---\n")
