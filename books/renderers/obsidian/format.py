"""Rating and wikilink formatting helpers."""

from __future__ import annotations


def format_rating(value: float | int | None) -> str:
    """Render a 0-5 rating as star emoji (``3`` -> ``⭐⭐⭐``).

    Fractional ratings (e.g. Calibre's 3.5) round to the nearest whole star.
    A present rating is always at least one star, so an explicit ``0`` (or a
    rating that rounds down to 0) renders as ``⭐``. Only a missing rating
    (``None``) renders as the empty string.
    """
    if value is None:
        return ""
    return "⭐" * max(1, round(value))


def wikilink(name: str) -> str:
    """Wrap *name* in an Obsidian [[wikilink]], sanitizing illegal chars."""
    clean = name.replace("[", "(").replace("]", ")").replace("|", "-")
    clean = clean.replace("#", "").replace("^", "")
    return f"[[{clean}]]"
