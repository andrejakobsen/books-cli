#!/usr/bin/env python3
"""Standalone shim: `python sync.py [--output ...] [--dry-run]`.

The real implementation lives in ``books.sync``. This keeps the script
runnable on its own while there is a single source of truth. For the full CLI
with all capabilities, use ``books`` (see pyproject.toml).
"""

from books.sync import main

if __name__ == "__main__":
    main()
