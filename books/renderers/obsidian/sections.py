"""Idempotent note-body sections: marker-wrapped blocks, write-once, top embed."""

from __future__ import annotations

import re

from books.renderers.obsidian.frontmatter import split_frontmatter


def _marker_pair(marker: str) -> tuple[str, str]:
    """Return the (start, end) HTML-comment markers for a generated block."""
    return f"%% books:{marker}:start %%", f"%% books:{marker}:end %%"


def render_marked_section(note_text: str, heading: str, marker: str, content: str) -> str:
    """Insert-or-replace a '## <heading>' section whose body is marker-delimited.

    The generated body lives between ``%% books:<marker>:start %%`` and
    ``%% books:<marker>:end %%`` comment markers. On a re-run only the text
    between the markers is replaced — the heading and everything outside the
    markers (a hand-written ``## Review`` section, note body, etc.) is left
    untouched. When the markers are absent the whole ``## heading`` section is
    appended. Idempotent for a given *content*.
    """
    start, end = _marker_pair(marker)
    block = f"{start}\n{content.rstrip(chr(10))}\n{end}"
    pattern = re.compile(rf"{re.escape(start)}.*?{re.escape(end)}", re.DOTALL)
    if pattern.search(note_text):
        return pattern.sub(lambda _m: block, note_text)
    sep = "" if note_text.endswith("\n") else "\n"
    return f"{note_text}{sep}\n## {heading}\n{block}\n"


def ensure_section(note_text: str, heading: str, content: str) -> str:
    """Append a '## <heading>' section with inline *content* iff heading absent.

    Write-once: if the note already has a ``## <heading>`` the note is returned
    unchanged (used for the imported review, which must never be clobbered).
    """
    if re.search(rf"(?m)^##\s+{re.escape(heading)}\s*$", note_text):
        return note_text
    sep = "" if note_text.endswith("\n") else "\n"
    return f"{note_text}{sep}\n## {heading}\n{content.rstrip(chr(10))}\n"


def ensure_top_embed(note_text: str, embed: str) -> str:
    """Insert *embed* at the top of the note body iff not already present.

    *embed* is a full embed line (e.g. ``![[Covers/<stem>.jpg|150]]``). The line
    is placed immediately after the frontmatter block, above any existing body.
    A no-op when the exact embed already appears anywhere in the note.
    """
    if embed in note_text:
        return note_text
    if not note_text.startswith("---"):
        body = note_text.lstrip("\n")
        return f"{embed}\n\n{body}" if body else f"{embed}\n"
    fm_lines, body = split_frontmatter(note_text)
    front = "---\n" + "\n".join(fm_lines) + "\n---\n"
    body = body.lstrip("\n")
    return f"{front}\n{embed}\n\n{body}" if body else f"{front}\n{embed}\n"
