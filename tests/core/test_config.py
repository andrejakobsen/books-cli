"""Tests for books.config (config file + vault resolution)."""

from pathlib import Path

from books.core import config


def test_load_config_creates_default_file_when_absent(tmp_path):
    cfg_file = tmp_path / "books" / "config.toml"
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
    assert config.config_path() == tmp_path / "xdg" / "books" / "config.toml"


def test_config_path_defaults_to_dot_config(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert config.config_path() == tmp_path / ".config" / "books" / "config.toml"


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
    cfg_file.write_text('obsidian_path = "~/Obs"\nvault = "History"\nimports = "Sources"\n')
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
    cfg_file = tmp_path / "books" / "config.toml"
    config.load_config(cfg_file)
    assert 'imports = "Data/Imports"' in cfg_file.read_text()


def test_resolve_imports_joins_onto_vault(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('obsidian_path = "/data/Obs"\nvault = "History"\nimports = ".imports"\n')
    monkeypatch.setattr(config, "config_path", lambda: cfg_file)
    assert config.resolve_imports("goodreads", None) == Path("/data/Obs/History/.imports/goodreads")


def test_resolve_imports_respects_output_override(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('imports = ".imports"\n')
    monkeypatch.setattr(config, "config_path", lambda: cfg_file)
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: Path("/work")))
    assert config.resolve_imports("kobo", Path("MyVault")) == Path("/work/MyVault/.imports/kobo")


def test_resolve_imports_honors_absolute_imports(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('obsidian_path = "/data/Obs"\nvault = "History"\nimports = "/srv/raw"\n')
    monkeypatch.setattr(config, "config_path", lambda: cfg_file)
    assert config.resolve_imports("calibre", None) == Path("/srv/raw/calibre")


def test_newest_csv_picks_most_recent(tmp_path):
    old = tmp_path / "old.csv"
    new = tmp_path / "new.csv"
    old.write_text("a")
    new.write_text("b")
    import os

    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))
    assert config.newest_csv(tmp_path) == new


def test_newest_csv_single_file(tmp_path):
    only = tmp_path / "export.csv"
    only.write_text("x")
    assert config.newest_csv(tmp_path) == only


def test_newest_csv_empty_folder_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        config.newest_csv(tmp_path)


def test_newest_csv_missing_folder_raises(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        config.newest_csv(tmp_path / "nope")


def test_resolve_csv_arg_none_uses_imports_newest(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(f'obsidian_path = "{tmp_path}"\nvault = "V"\nimports = ".imports"\n')
    monkeypatch.setattr(config, "config_path", lambda: cfg_file)
    folder = tmp_path / "V" / ".imports" / "readwise"
    folder.mkdir(parents=True)
    (folder / "a.csv").write_text("x")
    assert config.resolve_csv_arg(None, "readwise", None) == folder / "a.csv"


def test_resolve_csv_arg_file_returned_resolved(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: tmp_path))
    f = tmp_path / "export.csv"
    f.write_text("x")
    assert config.resolve_csv_arg(Path("export.csv"), "goodreads", None) == f


def test_resolve_csv_arg_folder_picks_newest(tmp_path, monkeypatch):
    import os

    folder = tmp_path / "exports"
    folder.mkdir()
    (folder / "old.csv").write_text("a")
    (folder / "new.csv").write_text("b")
    os.utime(folder / "old.csv", (1000, 1000))
    os.utime(folder / "new.csv", (2000, 2000))
    assert config.resolve_csv_arg(folder, "goodreads", None) == folder / "new.csv"


def test_resolve_csv_arg_missing_raises(tmp_path, monkeypatch):
    import pytest

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(f'obsidian_path = "{tmp_path}"\nvault = "V"\nimports = ".imports"\n')
    monkeypatch.setattr(config, "config_path", lambda: cfg_file)
    with pytest.raises(FileNotFoundError):
        config.resolve_csv_arg(None, "readwise", None)


def test_importer_writes_to_configured_vault_without_output(monkeypatch, tmp_path):
    """An importer invoked without --output writes into the configured vault.

    Drives the readwise command end-to-end with no --output, proving it relies
    on config.resolve_vault(None) to locate the vault.
    """
    import typer
    from typer.testing import CliRunner

    from books.commands import readwise as rw

    vault = tmp_path / "ConfiguredVault"
    monkeypatch.setattr(config, "default_vault", lambda path=None: vault)

    csv = tmp_path / "readwise.csv"
    csv.write_text(
        "Highlight,Book Title,Book Author,Amazon Book ID,Note,Color,Tags,"
        "Location Type,Location,Highlighted at,Document tags\n"
        '"A passage.","Stalin: Volume I (Stalin #1)",Stephen Kotkin,B00INIXPYE,'
        ",,,page,3,2026-07-17 14:00:25+00:00,\n",
        encoding="utf-8",
    )

    # The highlight importer only enriches, so pre-create the note (as
    # calibre/goodreads would) inside the configured vault.
    books = vault / "Books"
    books.mkdir(parents=True)
    (books / "Stalin - Stephen Kotkin.md").write_text(
        '---\ntype: book\ntitle: "Stalin"\n'
        'authors: ["[[Stephen Kotkin]]"]\namazon: "B00INIXPYE"\n---\n\n',
        encoding="utf-8",
    )

    app = typer.Typer()
    rw.register(app)
    result = CliRunner().invoke(app, ["--csv", str(csv)])

    assert result.exit_code == 0, result.output
    assert (vault / "Books" / "Stalin - Stephen Kotkin.md").exists()


def _write(tmp_path, text):
    p = tmp_path / "config.toml"
    p.write_text(text)
    return p


def test_config_defaults_when_sections_absent(tmp_path):
    cfg = config.load_config(_write(tmp_path, 'vault = "V"\n'))
    assert cfg.calibre.library == config.DEFAULT_CALIBRE_LIBRARY
    assert cfg.kobo.db == ""
    assert cfg.audible.transcriber == "local"
    assert cfg.audible.select == "interactive"
    assert cfg.covers.interactive is False
    assert cfg.covers.limit == 0


def test_config_reads_importer_sections(tmp_path):
    text = (
        'vault = "V"\n'
        '[calibre]\nlibrary = "~/Books"\n'
        '[kobo]\ndb = "/tmp/K.sqlite"\n'
        '[audible]\ntranscriber = "openai"\nselect = "all"\n'
        "[covers]\ninteractive = true\nlimit = 5\n"
    )
    cfg = config.load_config(_write(tmp_path, text))
    assert cfg.calibre.library == "~/Books"
    assert cfg.kobo.db == "/tmp/K.sqlite"
    assert cfg.audible.transcriber == "openai"
    assert cfg.audible.select == "all"
    assert cfg.covers.interactive is True
    assert cfg.covers.limit == 5


def test_config_default_importers_default_is_sync_set(tmp_path):
    cfg = config.load_config(_write(tmp_path, 'vault = "V"\n'))
    assert cfg.import_.default == config.DEFAULT_IMPORTERS


def test_config_reads_default_importers(tmp_path):
    text = 'vault = "V"\n[import]\ndefault = ["calibre", "covers", "audible"]\n'
    cfg = config.load_config(_write(tmp_path, text))
    assert cfg.import_.default == ("calibre", "covers", "audible")


def test_config_default_importers_drops_unknown_and_falls_back(tmp_path):
    # Unknown names are dropped; a list with none valid falls back to the sync-set.
    text = 'vault = "V"\n[import]\ndefault = ["calibre", "bogus"]\n'
    cfg = config.load_config(_write(tmp_path, text))
    assert cfg.import_.default == ("calibre",)

    text2 = 'vault = "V"\n[import]\ndefault = ["nope", 3]\n'
    cfg2 = config.load_config(_write(tmp_path, text2))
    assert cfg2.import_.default == config.DEFAULT_IMPORTERS

    text3 = 'vault = "V"\n[import]\ndefault = "calibre"\n'  # wrong type
    cfg3 = config.load_config(_write(tmp_path, text3))
    assert cfg3.import_.default == config.DEFAULT_IMPORTERS


def test_config_rejects_bad_values_per_key(tmp_path):
    text = (
        'vault = "V"\n'
        '[audible]\ntranscriber = "bogus"\nselect = 3\n'
        '[covers]\ninteractive = "yes"\nlimit = "lots"\n'
    )
    cfg = config.load_config(_write(tmp_path, text))
    assert cfg.audible.transcriber == "local"  # invalid choice → default
    assert cfg.audible.select == "interactive"  # wrong type → default
    assert cfg.covers.interactive is False  # wrong type → default
    assert cfg.covers.limit == 0  # wrong type → default


def test_config_malformed_toml_falls_back(tmp_path):
    cfg = config.load_config(_write(tmp_path, "this = = not toml"))
    assert cfg.calibre.library == config.DEFAULT_CALIBRE_LIBRARY
    assert cfg.audible.transcriber == "local"


def test_default_file_parses_and_has_sections():
    import tomllib

    data = tomllib.loads(config._DEFAULT_FILE_PARSEABLE)
    assert "calibre" in data and "audible" in data and "covers" in data and "kindle" in data
    assert data["import"]["default"] == list(config.DEFAULT_IMPORTERS)


def test_kindle_config_parsed(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        'obsidian_path = "/tmp/o"\nvault = "V"\n[kindle]\nclippings = "/tmp/My Clippings.txt"\n'
    )
    cfg = config.load_config(cfg_file)
    assert cfg.kindle.clippings == "/tmp/My Clippings.txt"


def test_kindle_config_defaults_empty(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('vault = "V"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.kindle.clippings == ""


def test_load_config_reads_export_timezone(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[export]\ntimezone = "America/New_York"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.export.timezone == "America/New_York"


def test_load_config_defaults_export_timezone_when_absent(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('vault = "History"\n')
    cfg = config.load_config(cfg_file)
    assert cfg.export.timezone == "Europe/Oslo"


def test_load_config_defaults_export_timezone_on_non_string(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[export]\ntimezone = 5\n")
    cfg = config.load_config(cfg_file)
    assert cfg.export.timezone == "Europe/Oslo"
