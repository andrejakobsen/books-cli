"""User configuration for the ``books`` CLI.

Reads ``~/.config/booktools/config.toml`` (respecting ``$XDG_CONFIG_HOME``),
auto-creating it with commented defaults on first run. Supplies the default
Obsidian vault directory so most commands need no ``--output``.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from booktools import resolve_path

DEFAULT_OBSIDIAN_PATH = "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian"
DEFAULT_VAULT = "History"
DEFAULT_IMPORTS = ".imports"

_DEFAULT_FILE = (
    "# booktools configuration\n"
    f'obsidian_path = "{DEFAULT_OBSIDIAN_PATH}"\n'
    f'vault = "{DEFAULT_VAULT}"\n'
    "# Folder (inside the vault) holding raw import sources, hidden from Obsidian.\n"
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
    return root / "booktools" / "config.toml"


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
