"""Interactive selection of which Audible books to transcribe.

Owns the arrow-key checkbox picker (via the optional ``questionary`` dependency,
imported lazily so no other command loads it) and its pure, testable helpers: the
per-row label and the pre-check predicate. A book is pre-checked only when it is
already in the catalog AND has at least one clip; audiobook-only ("new") books and
zero-clip books start unchecked so a bulk run never transcribes them by accident.
"""

from __future__ import annotations

from books.commands.audible.models import Candidate


def candidate_label(cand: Candidate) -> str:
    """One picker row: ``<title> — <authors>  [status] · <n> clip(s)[ (cached)]``."""
    authors = ", ".join(cand.book.authors) or "?"
    status = "✓ in library" if cand.in_library else "+ new"
    label = f"{cand.book.title} — {authors}  [{status}] · {cand.clip_count} clip(s)"
    if cand.cached:
        label += " (cached)"
    return label


def should_precheck(cand: Candidate) -> bool:
    """Pre-check a row only if the book is in the catalog and has ≥1 clip."""
    return cand.in_library and cand.clip_count > 0


def select_books(candidates: list[Candidate]) -> list[Candidate]:
    """Show the checkbox picker and return the chosen candidates (never None).

    ``questionary`` is imported here so the dependency loads only when a real
    interactive selection is requested.
    """
    import questionary

    choices = [
        questionary.Choice(title=candidate_label(cand), value=cand, checked=should_precheck(cand))
        for cand in candidates
    ]
    result = questionary.checkbox("Select audiobooks to transcribe", choices=choices).ask()
    return result or []
