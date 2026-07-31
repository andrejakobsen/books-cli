"""`books` CLI hub.

Each capability lives in its own module and exposes a ``register(app)`` function
that attaches its command(s) to the shared Typer app. To add a new capability:

    1. Create ``books/commands/<feature>.py`` with a ``register(app)`` function.
    2. Add the module to ``CAPABILITIES`` below.

That's it — the command shows up under ``books --help``.
"""

from __future__ import annotations

import typer

from books.commands import (
    config_cmd,
    export,
    import_cmd,
    reset,
)

# Modules that expose a register(app) function. Add new capabilities here.
CAPABILITIES = (
    config_cmd,
    export,
    import_cmd,
    reset,
)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=True,
    help="Tools for books & reading data: import sources into a store, export notes.",
)

for _module in CAPABILITIES:
    _module.register(app)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
