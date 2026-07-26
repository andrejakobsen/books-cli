"""books package."""

from __future__ import annotations

from pathlib import Path


def resolve_path(path: Path, base: Path) -> Path:
    """Resolve *path* against *base* unless it is already absolute or uses ``~``.

    - Absolute paths (e.g. ``/foo/bar``) are returned unchanged.
    - ``~``-prefixed paths are expanded to the user's home.
    - Bare names / relative paths (e.g. ``Obsidian``, ``sub/dir``) are joined
      onto *base* (typically the cwd or the home directory).
    """
    expanded = Path(path).expanduser()
    if expanded.is_absolute():
        return expanded
    return base / expanded
