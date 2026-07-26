"""Tests for booktools.config (config file + vault resolution)."""

from pathlib import Path

from booktools import config


def test_load_config_creates_default_file_when_absent(tmp_path):
    cfg_file = tmp_path / "booktools" / "config.toml"
    cfg = config.load_config(cfg_file)
    assert cfg.obsidian_path == config.DEFAULT_OBSIDIAN_PATH
    assert cfg.vault == config.DEFAULT_VAULT
    assert cfg_file.is_file()
    text = cfg_file.read_text()
    assert 'obsidian_path = "~/Library/Mobile Documents/com~apple~CloudDocs/Obsidian"' in text
    assert 'vault = "History"' in text


def test_load_config_reads_existing_values(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('obsidian_path = "~/Vaults"\nvault = "Reading"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.obsidian_path == "~/Vaults"
    assert cfg.vault == "Reading"


def test_load_config_falls_back_per_key_on_partial_file(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('vault = "Reading"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.obsidian_path == config.DEFAULT_OBSIDIAN_PATH
    assert cfg.vault == "Reading"


def test_load_config_falls_back_on_malformed_toml(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("this is not valid toml = = =\n")
    cfg = config.load_config(cfg_file)
    assert cfg.obsidian_path == config.DEFAULT_OBSIDIAN_PATH
    assert cfg.vault == config.DEFAULT_VAULT


def test_load_config_falls_back_on_non_string_value(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('obsidian_path = 5\nvault = "History"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.obsidian_path == config.DEFAULT_OBSIDIAN_PATH
    assert cfg.vault == "History"


def test_load_config_falls_back_when_file_unwritable(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("")  # a FILE where a dir is expected -> mkdir raises
    cfg_file = blocker / "config.toml"
    cfg = config.load_config(cfg_file)
    assert cfg.obsidian_path == config.DEFAULT_OBSIDIAN_PATH
    assert cfg.vault == config.DEFAULT_VAULT


def test_config_path_respects_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config.config_path() == tmp_path / "xdg" / "booktools" / "config.toml"


def test_config_path_defaults_to_dot_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert config.config_path() == tmp_path / ".config" / "booktools" / "config.toml"


def test_default_vault_joins_and_expands(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('obsidian_path = "~/Obs"\nvault = "History"\n')
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/me")))
    assert config.default_vault(cfg_file) == Path("/home/me/Obs/History")


def test_resolve_vault_prefers_explicit_output(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
    assert config.resolve_vault(Path("SomeVault")) == tmp_path / "SomeVault"


def test_resolve_vault_uses_config_when_output_none(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('obsidian_path = "/data/Obs"\nvault = "History"\n')
    monkeypatch.setattr(config, "config_path", lambda: cfg_file)
    assert config.resolve_vault(None) == Path("/data/Obs/History")


def test_load_config_reads_imports_key(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        'obsidian_path = "~/Obs"\nvault = "History"\nimports = "Sources"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.imports == "Sources"


def test_load_config_defaults_imports_when_absent(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('vault = "History"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.imports == config.DEFAULT_IMPORTS


def test_load_config_defaults_imports_on_non_string(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('imports = 5\nvault = "History"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.imports == config.DEFAULT_IMPORTS


def test_default_file_includes_imports(tmp_path):
    cfg_file = tmp_path / "booktools" / "config.toml"
    config.load_config(cfg_file)
    assert 'imports = ".imports"' in cfg_file.read_text()


def test_importer_writes_to_configured_vault_without_output(monkeypatch, tmp_path):
    """An importer invoked without --output writes into the configured vault.

    Drives the readwise command end-to-end with no --output, proving it relies
    on config.resolve_vault(None) to locate the vault.
    """
    import typer
    from typer.testing import CliRunner

    from booktools import readwise_obsidian as rw

    vault = tmp_path / "ConfiguredVault"
    monkeypatch.setattr(config, "default_vault", lambda path=None: vault)

    csv = tmp_path / "readwise.csv"
    csv.write_text(
        "Highlight,Book Title,Book Author,Amazon Book ID,Note,Color,Tags,"
        "Location Type,Location,Highlighted at,Document tags\n"
        '"A passage.","Stalin: Volume I (Stalin #1)",Stephen Kotkin,B00INIXPYE,'
        ',,,page,3,2026-07-17 14:00:25+00:00,\n',
        encoding="utf-8")

    app = typer.Typer()
    rw.register(app)
    result = CliRunner().invoke(app, ["--csv", str(csv)])

    assert result.exit_code == 0, result.output
    assert (vault / "Books" / "Stalin - Stephen Kotkin.md").exists()
