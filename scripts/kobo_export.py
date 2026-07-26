#!/usr/bin/env python3
"""Standalone shim: `python kobo_export.py [DB] [-i ...] [-o ...]`.

The real implementation lives in ``booktools.kobo_export``. This keeps the script
runnable on its own while there is a single source of truth. For the full CLI
with all capabilities, use ``books`` (see pyproject.toml).
"""

from booktools.kobo_export import main

if __name__ == "__main__":
    main()
