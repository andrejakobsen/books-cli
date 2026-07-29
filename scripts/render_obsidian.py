#!/usr/bin/env python3
"""Standalone shim: `python render_obsidian.py [-o VAULT]`.

The real implementation lives in ``books.render_obsidian``. This keeps the
script runnable on its own while there is a single source of truth. For the full
CLI with all capabilities, use ``books`` (see pyproject.toml).
"""

from books.render_obsidian import main

if __name__ == "__main__":
    main()
