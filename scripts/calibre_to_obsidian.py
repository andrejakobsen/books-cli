#!/usr/bin/env python3
"""Standalone shim: `python calibre_to_obsidian.py [--library ...] [--output ...]`.

The real implementation lives in ``books.calibre_obsidian``. This keeps the
script runnable on its own while there is a single source of truth. For the full
CLI with all capabilities, use ``books`` (see pyproject.toml).
"""

from books.calibre_obsidian import main

if __name__ == "__main__":
    main()
