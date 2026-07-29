"""User configuration for the ``books`` CLI.

Reads ``~/.config/books/config.toml`` (respecting ``$XDG_CONFIG_HOME``),
auto-creating it with commented defaults on first run. Supplies the default
Obsidian vault directory so most commands need no ``--output``.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from books.core.paths import resolve_path

DEFAULT_OBSIDIAN_PATH = "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian"
DEFAULT_VAULT = "History"
DEFAULT_IMPORTS = "Data/Imports"

_DEFAULT_FILE = (
    "# books configuration\n"
    f'obsidian_path = "{DEFAULT_OBSIDIAN_PATH}"\n'
    f'vault = "{DEFAULT_VAULT}"\n'
    "# Folder (inside the vault) holding raw import sources.\n"
    f'imports = "{DEFAULT_IMPORTS}"\n'
)


@dataclass
class Config:
    """Resolved config values (built-in defaults when unset)."""

    obsidian_path: str = DEFAULT_OBSIDIAN_PATH
    vault: str = DEFAULT_VAULT
    imports: str = DEFAULT_IMPORTS


def config_path() -> Path:
    """Location of the config file, honouring ``$XDG_CONFIG_HOME``."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "books" / "config.toml"


def load_config(path: Path | None = None) -> Config:
    """Load config from *path* (default: ``config_path()``).

    Auto-creates the file with defaults when absent. Malformed TOML or missing
    keys fall back to the built-in default per key, so a bad config never crashes.
    """
    path = path or config_path()
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_DEFAULT_FILE)
        except OSError:
            pass
        return Config()
    try:
        data = tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, OSError):
        return Config()
    obsidian_path = data.get("obsidian_path")
    vault = data.get("vault")
    if not isinstance(obsidian_path, str) or not obsidian_path:
        obsidian_path = DEFAULT_OBSIDIAN_PATH
    if not isinstance(vault, str) or not vault:
        vault = DEFAULT_VAULT
    imports = data.get("imports")
    if not isinstance(imports, str) or not imports:
        imports = DEFAULT_IMPORTS
    return Config(obsidian_path=obsidian_path, vault=vault, imports=imports)


def _expand_user(raw: str) -> Path:
    """Expand a leading ``~`` against ``Path.home()`` (test-friendly)."""
    p = Path(raw)
    if raw == "~":
        return Path.home()
    if raw.startswith("~/"):
        return Path.home() / raw[2:]
    return p


def default_vault(path: Path | None = None) -> Path:
    """The configured vault directory: ``obsidian_path`` (expanded) / ``vault``."""
    cfg = load_config(path)
    return _expand_user(cfg.obsidian_path) / cfg.vault


def resolve_vault(output: Path | None) -> Path:
    """Resolve the vault to use for a command.

    Explicit ``--output`` (resolved against the cwd via ``resolve_path``) wins;
    otherwise fall back to the configured default vault.
    """
    if output is not None:
        return resolve_path(output, Path.cwd())
    return default_vault()


def resolve_imports(name: str, output: Path | None = None) -> Path:
    """Canonical import subfolder for a command: ``<vault>/<imports>/<name>``.

    The imports root resolves inside the vault selected by ``resolve_vault`` (so
    it travels with whichever vault ``--output``/config picks). An absolute
    ``imports`` config value is honored as-is; a relative one joins onto the vault.
    """
    vault = resolve_vault(output)
    cfg = load_config()
    root = resolve_path(Path(cfg.imports), vault)
    return root / name


def newest_csv(folder: Path) -> Path:
    """Return the most-recently-modified top-level ``*.csv`` in *folder*.

    Non-recursive. Raises ``FileNotFoundError`` (with *folder* in the message)
    when the folder is missing or contains no CSV files.
    """
    if not folder.is_dir():
        raise FileNotFoundError(f"no CSV found in {folder}")
    csvs = list(folder.glob("*.csv"))
    if not csvs:
        raise FileNotFoundError(f"no CSV found in {folder}")
    return max(csvs, key=lambda p: p.stat().st_mtime)


def resolve_csv_arg(csv: Path | None, name: str, output: Path | None = None) -> Path:
    """Resolve a ``--csv`` option (unset, a folder, or a file) to one CSV file.

    - ``None`` → newest CSV in ``<vault>/.imports/<name>``.
    - a directory → newest CSV in it.
    - a file → returned resolved against the cwd.

    Raises ``FileNotFoundError`` when no CSV is found (unset/folder cases). The
    caller is responsible for turning that into a user-facing error and for any
    final ``is_file`` check on an explicit path.
    """
    if csv is None:
        return newest_csv(resolve_imports(name, output))
    csv = resolve_path(csv, Path.cwd())
    if csv.is_dir():
        return newest_csv(csv)
    return csv
