"""Kindle My Clippings.txt importer package.

Re-exports the public API so call sites use ``from books.commands.kindle import X``.
"""

from __future__ import annotations

from books.commands.kindle.command import (
    convert,
    default_clippings_path,
    kindle_import,
    register,
    run_import,
)

__all__ = [
    "convert",
    "default_clippings_path",
    "kindle_import",
    "register",
    "run_import",
]
