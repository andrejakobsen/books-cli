#!/usr/bin/env python3
"""Standalone shim: `python highlighted_obsidian.py -c export.csv -o Obsidian`.

The real implementation lives in ``books.highlighted_obsidian``. This keeps
the script runnable on its own while there is a single source of truth. For the
full CLI with all capabilities, use ``books`` (see pyproject.toml).
"""

from books.highlighted_obsidian import main

if __name__ == "__main__":
    main()
