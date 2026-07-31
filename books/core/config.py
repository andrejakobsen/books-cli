"""User configuration for the ``books`` CLI.

Reads ``~/.config/books/config.toml`` (respecting ``$XDG_CONFIG_HOME``),
auto-creating it with commented defaults on first run. Supplies the default
Obsidian vault directory so most commands need no ``--output``.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from books.core.paths import resolve_path

DEFAULT_OBSIDIAN_PATH = "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian"
DEFAULT_VAULT = "History"
DEFAULT_IMPORTS = "Data/Imports"

DEFAULT_CALIBRE_LIBRARY = "~/Calibre Library"
DEFAULT_TIMEZONE = "Europe/Oslo"
_TRANSCRIBERS = ("local", "openai", "google")
_SELECT_MODES = ("interactive", "all")
# Every importer name (validates [import].default). Kept in sync with import_cmd.
VALID_IMPORTERS = (
    "calibre",
    "goodreads",
    "kobo",
    "highlighted",
    "readwise",
    "audible",
    "covers",
    "kindle",
)
# The importers that run when `books import` gets no flags (out-of-the-box default).
DEFAULT_IMPORTERS = ("calibre", "goodreads", "kobo", "highlighted", "readwise", "kindle")

_DEFAULT_FILE = (
    "# books configuration\n"
    f'obsidian_path = "{DEFAULT_OBSIDIAN_PATH}"\n'
    f'vault = "{DEFAULT_VAULT}"\n'
    "# Folder (inside the vault) holding raw import sources.\n"
    f'imports = "{DEFAULT_IMPORTS}"\n'
    "\n"
    "# Importers run by `books import` when given no flags (add covers/audible to include them).\n"
    "# [import]\n"
    f"# default = {list(DEFAULT_IMPORTERS)!r}\n"
    "\n"
    "# Per-importer settings (uncomment to override the defaults shown).\n"
    "# [calibre]\n"
    f'# library = "{DEFAULT_CALIBRE_LIBRARY}"\n'
    "# [kobo]\n"
    '# db = "/path/to/KoboReader.sqlite"  # default: mounted device / imports folder\n'
    "# [audible]\n"
    '# transcriber = "local"   # local | openai | google\n'
    '# select = "interactive"  # interactive | all\n'
    "# [covers]\n"
    "# interactive = false\n"
    "# limit = 0                # 0 = no limit\n"
    "# [kindle]\n"
    '# clippings = "/path/to/My Clippings.txt"  # default: mounted Kindle / imports folder\n'
    "# [export]\n"
    f'# timezone = "{DEFAULT_TIMEZONE}"  # IANA zone for highlight date/time rendering\n'
)

# A fully-uncommented copy used only by tests to assert the sections parse.
_DEFAULT_FILE_PARSEABLE = (
    f'obsidian_path = "{DEFAULT_OBSIDIAN_PATH}"\n'
    f'vault = "{DEFAULT_VAULT}"\n'
    f'imports = "{DEFAULT_IMPORTS}"\n'
    "[import]\n"
    f"default = {list(DEFAULT_IMPORTERS)!r}\n"
    "[calibre]\n"
    f'library = "{DEFAULT_CALIBRE_LIBRARY}"\n'
    "[kobo]\n"
    'db = ""\n'
    "[audible]\n"
    'transcriber = "local"\n'
    'select = "interactive"\n'
    "[covers]\n"
    "interactive = false\n"
    "limit = 0\n"
    "[kindle]\n"
    'clippings = ""\n'
    "[export]\n"
    f'timezone = "{DEFAULT_TIMEZONE}"\n'
)


@dataclass
class ImportConfig:
    default: tuple[str, ...] = DEFAULT_IMPORTERS  # importers run when no flags given


@dataclass
class CalibreConfig:
    library: str = DEFAULT_CALIBRE_LIBRARY


@dataclass
class KoboConfig:
    db: str = ""  # empty = auto-detect (mounted device / canonical folder)


@dataclass
class AudibleConfig:
    transcriber: str = "local"  # local | openai | google
    select: str = "interactive"  # interactive | all


@dataclass
class CoversConfig:
    interactive: bool = False
    limit: int = 0  # 0 = no limit


@dataclass
class KindleConfig:
    clippings: str = ""  # empty = auto-detect (mounted device / canonical folder)


@dataclass
class ObsidianExportConfig:
    highlights_template: str = ""  # path to a custom callout template; "" = default


@dataclass
class ExportConfig:
    timezone: str = DEFAULT_TIMEZONE
    obsidian: ObsidianExportConfig = field(default_factory=ObsidianExportConfig)


@dataclass
class Config:
    """Resolved config values (built-in defaults when unset)."""

    obsidian_path: str = DEFAULT_OBSIDIAN_PATH
    vault: str = DEFAULT_VAULT
    imports: str = DEFAULT_IMPORTS
    import_: ImportConfig = field(default_factory=ImportConfig)
    calibre: CalibreConfig = field(default_factory=CalibreConfig)
    kobo: KoboConfig = field(default_factory=KoboConfig)
    audible: AudibleConfig = field(default_factory=AudibleConfig)
    covers: CoversConfig = field(default_factory=CoversConfig)
    kindle: KindleConfig = field(default_factory=KindleConfig)
    export: ExportConfig = field(default_factory=ExportConfig)


def config_path() -> Path:
    """Location of the config file, honouring ``$XDG_CONFIG_HOME``."""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "books" / "config.toml"


def templates_dir() -> Path:
    """Directory holding user-editable export templates (sibling of config.toml)."""
    return config_path().parent / "templates"


def _table(data: dict, name: str) -> dict:
    """Return the ``[name]`` sub-table, or ``{}`` when absent/not a table."""
    t = data.get(name)
    return t if isinstance(t, dict) else {}


def _str_or(t: dict, key: str, default: str) -> str:
    v = t.get(key)
    return v if isinstance(v, str) else default


def _nonempty_str_or(t: dict, key: str, default: str) -> str:
    v = t.get(key)
    return v if isinstance(v, str) and v else default


def _bool_or(t: dict, key: str, default: bool) -> bool:
    v = t.get(key)
    return v if isinstance(v, bool) else default


def _int_or(t: dict, key: str, default: int) -> int:
    v = t.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else default


def _choice_or(t: dict, key: str, choices: tuple[str, ...], default: str) -> str:
    v = t.get(key)
    return v if isinstance(v, str) and v in choices else default


def _importer_list_or(t: dict, key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Parse a list of importer names, dropping unknowns; fall back when empty."""
    v = t.get(key)
    if not isinstance(v, list):
        return default
    names = tuple(x for x in v if isinstance(x, str) and x in VALID_IMPORTERS)
    return names or default


def _parse_sections(data: dict) -> dict:
    """Build the importer sub-configs from parsed TOML *data*."""
    imp = _table(data, "import")
    cal = _table(data, "calibre")
    kob = _table(data, "kobo")
    aud = _table(data, "audible")
    cov = _table(data, "covers")
    kin = _table(data, "kindle")
    exp = _table(data, "export")
    return {
        "import_": ImportConfig(default=_importer_list_or(imp, "default", DEFAULT_IMPORTERS)),
        "calibre": CalibreConfig(library=_nonempty_str_or(cal, "library", DEFAULT_CALIBRE_LIBRARY)),
        "kobo": KoboConfig(db=_str_or(kob, "db", "")),
        "audible": AudibleConfig(
            transcriber=_choice_or(aud, "transcriber", _TRANSCRIBERS, "local"),
            select=_choice_or(aud, "select", _SELECT_MODES, "interactive"),
        ),
        "covers": CoversConfig(
            interactive=_bool_or(cov, "interactive", False),
            limit=_int_or(cov, "limit", 0),
        ),
        "kindle": KindleConfig(clippings=_str_or(kin, "clippings", "")),
        "export": ExportConfig(
            timezone=_nonempty_str_or(exp, "timezone", DEFAULT_TIMEZONE),
            obsidian=ObsidianExportConfig(
                highlights_template=_str_or(_table(exp, "obsidian"), "highlights_template", ""),
            ),
        ),
    }


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
    return Config(
        obsidian_path=obsidian_path,
        vault=vault,
        imports=imports,
        **_parse_sections(data),
    )


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
