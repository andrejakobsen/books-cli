"""The renderer seam: a common protocol every output target implements.

A renderer turns the merged CSV store (``Data/books.csv`` + per-book highlights)
into some concrete output. Obsidian is the only target today; future targets
(Notion, Evernote, …) implement the same :class:`Renderer` protocol and register
under their own name, and the ``render`` command dispatches to them by flag.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class Renderer(Protocol):
    """An output target: render the store under *vault* into notes/files.

    ``name`` is the stable identifier used to select the renderer (and matches
    the CLI flag, e.g. ``obsidian`` -> ``--obsidian``). ``render`` returns a
    stats dict describing what was produced.
    """

    name: str

    def render(
        self, vault: Path, *, refresh: bool = False, timezone: str = "Europe/Oslo"
    ) -> dict: ...
