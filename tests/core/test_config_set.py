"""Tests for config.set_highlights_template (comment-preserving TOML write)."""

from books.core import config


def test_set_creates_file_and_key_when_absent(tmp_path):
    cfg_file = tmp_path / "books" / "config.toml"
    config.set_highlights_template("~/t/callout.md.jinja", cfg_file)
    assert cfg_file.is_file()
    cfg = config.load_config(cfg_file)
    assert cfg.export.obsidian.highlights_template == "~/t/callout.md.jinja"


def test_set_preserves_existing_content_and_comments(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        "# my header comment\n"
        'obsidian_path = "~/Vaults"\n'
        'vault = "Reading"  # inline comment\n'
        "\n"
        "[export]\n"
        'timezone = "America/New_York"\n'
    )
    config.set_highlights_template("~/t/blockquote.md.jinja", cfg_file)
    text = cfg_file.read_text()
    assert "# my header comment" in text
    assert "# inline comment" in text
    assert 'timezone = "America/New_York"' in text
    cfg = config.load_config(cfg_file)
    assert cfg.vault == "Reading"
    assert cfg.export.timezone == "America/New_York"
    assert cfg.export.obsidian.highlights_template == "~/t/blockquote.md.jinja"


def test_set_overwrites_previous_value(tmp_path):
    cfg_file = tmp_path / "config.toml"
    config.set_highlights_template("~/t/a.md.jinja", cfg_file)
    config.set_highlights_template("~/t/b.md.jinja", cfg_file)
    cfg = config.load_config(cfg_file)
    assert cfg.export.obsidian.highlights_template == "~/t/b.md.jinja"
