"""Output renderers. Each subpackage turns the store into one output format.

Renderers register here by name so the ``render`` command can dispatch to one by
flag (``--obsidian`` today; ``--notion``/``--evernote`` slot in beside it later).
"""

from __future__ import annotations

from books.renderers.base import Renderer
from books.renderers.obsidian.note import ObsidianRenderer

# The renderer registry: name -> constructor. Adding a target is a one-line entry
# here plus its flag on the ``render`` command.
_RENDERERS: dict[str, type] = {
    ObsidianRenderer.name: ObsidianRenderer,
}


def renderer_names() -> tuple[str, ...]:
    """The registered renderer names, in registration order."""
    return tuple(_RENDERERS)


def get_renderer(name: str) -> Renderer:
    """Return a fresh instance of the renderer registered under *name*.

    Raises ``KeyError`` for an unknown name (the caller turns this into a clean
    CLI error).
    """
    return _RENDERERS[name]()


__all__ = ["Renderer", "get_renderer", "renderer_names"]
