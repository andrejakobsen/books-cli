"""Flat vault layout: folder names, safe filenames, cover paths, hub stubs."""

from __future__ import annotations

import re
from pathlib import Path

from books.renderers.obsidian.format import wikilink, yaml_quote

# --- Vault layout -----------------------------------------------------------

# Book notes live flat in vault/Books/ and are the single indexed file per book:
# frontmatter + a cover embed + inline highlights (+ an optional review). Covers
# live flat in vault/Covers/ (a visible folder, so the embed renders; the user
# hides it in Obsidian). Personal notes are hand-made in vault/Notes/ and never
# touched by the tooling — the book note only links to them.
BOOKS_DIRNAME = "Books"
COVERS_DIRNAME = "Covers"
NOTES_DIRNAME = "Notes"
AUTHORS_DIRNAME = "Authors"
TOPICS_DIRNAME = "Topics"

# Width (in px) for the cover embed at the top of a book note.
COVER_WIDTH = 150


# --- Filesystem helpers -----------------------------------------------------

_ILLEGAL_FS = re.compile(r'[/\\:*?"<>|\x00-\x1f]')


def sanitize_folder_name(name: str) -> str:
    """Strip a trailing Calibre ' (NN)' id suffix from a book folder name."""
    return re.sub(r"\s*\(\d+\)$", "", name).strip()


def safe_filename(name: str) -> str:
    """Make *name* safe to use as a single path segment."""
    cleaned = _ILLEGAL_FS.sub("_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(". ")
    return cleaned or "Untitled"


def strip_subtitle(title: str) -> str:
    """Drop everything after the first ':' (the subtitle), for tidy filenames.

    ``"The Deluge: The Great War..."`` -> ``"The Deluge"``. Falls back to the
    full (stripped) title when nothing precedes the colon.
    """
    head = (title or "").split(":", 1)[0].strip()
    return head or (title or "").strip()


def next_free_stem(title: str, author: str, used_lower: set[str]) -> str:
    """Return a unique note stem for (title, author) given already-used stems.

    Ladder: clean stem (subtitle dropped) -> restore subtitle (':' -> ',')
    -> numeric '(n)' suffix. *used_lower* holds already-taken stems lowercased;
    membership is tested case-insensitively (matching case-insensitive
    filesystems). The chosen stem is NOT added to used_lower -- the caller does
    that so it can also map the stem to a path/id.
    """
    def stem_for(t: str) -> str:
        return safe_filename(f"{t} - {author}" if author else t)

    short = stem_for(strip_subtitle(title))
    if short.lower() not in used_lower:
        return short

    full = stem_for(title.replace(":", ","))
    if full.lower() not in used_lower:
        return full

    n = 2
    while f"{full} ({n})".lower() in used_lower:
        n += 1
    return safe_filename(f"{full} ({n})")


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


def cover_path(note_path: Path) -> Path:
    """The flat cover-image path for a book note: ``vault/Covers/<stem>.jpg``.

    Keyed to the note's own filename stem (which VaultIndex already keeps unique),
    so the cover file matches its note one-to-one.
    """
    vault = note_path.parents[1]
    return vault / COVERS_DIRNAME / f"{note_path.stem}.jpg"


def cover_refs(note_path: Path) -> tuple[str, str]:
    """Return (frontmatter_value, body_embed) wikilinks for a book's cover.

    The frontmatter value is a plain quoted wikilink (for gallery/Bases views);
    the body embed carries the fixed display width (``|150``).
    """
    target = cover_path(note_path).relative_to(note_path.parents[1]).as_posix()
    return yaml_quote(f"[[{target}]]"), f"![[{target}|{COVER_WIDTH}]]"
