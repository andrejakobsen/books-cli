#!/usr/bin/env python3
"""Standalone shim: `python covers.py [-o VAULT] [--interactive] [--dry-run]`.

The real implementation lives in ``booktools.covers``. This keeps the script
runnable on its own while there is a single source of truth. For the full CLI
with all capabilities, use ``books`` (see pyproject.toml).
"""

from booktools.covers import main

if __name__ == "__main__":
    main()
