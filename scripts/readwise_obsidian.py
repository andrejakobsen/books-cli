#!/usr/bin/env python3
"""Standalone shim: `python readwise_obsidian.py -c readwise-data.csv -o Obsidian`.

The real implementation lives in ``booktools.readwise_obsidian``. This keeps the
script runnable on its own while there is a single source of truth. For the full
CLI with all capabilities, use ``books`` (see pyproject.toml).
"""

from booktools.readwise_obsidian import main

if __name__ == "__main__":
    main()
