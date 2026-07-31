"""Tests for the config-export preview helpers (pure, no TUI)."""

from books.commands import config_preview as P
from books.core import config


def test_sample_highlights_exercises_features():
    hls = P.sample_highlights()
    assert len(hls) >= 2
    assert any(h.note for h in hls)
    assert any(h.tags for h in hls)
    assert any(h.links for h in hls)
    assert any(h.chapter_title for h in hls)
    assert any(h.date for h in hls)


def test_template_label_strips_suffix(tmp_path):
    assert P.template_label(tmp_path / "callout.md.jinja") == "callout"


def test_list_obsidian_templates_scaffolds_examples(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "templates_dir", lambda: tmp_path / "templates")
    templates = P.list_obsidian_templates()
    labels = {P.template_label(p) for p in templates}
    assert {"callout", "blockquote", "plain", "minimal"} <= labels


def test_list_obsidian_templates_includes_custom(monkeypatch, tmp_path):
    tdir = tmp_path / "templates" / "obsidian"
    tdir.mkdir(parents=True)
    (tdir / "custom.md.jinja").write_text("{{ h.text }} ^{{ h.anchor }}")
    monkeypatch.setattr(config, "templates_dir", lambda: tmp_path / "templates")
    labels = {P.template_label(p) for p in P.list_obsidian_templates()}
    assert "custom" in labels


def test_render_preview_produces_markdown(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "templates_dir", lambda: tmp_path / "templates")
    templates = P.list_obsidian_templates()
    callout = next(p for p in templates if P.template_label(p) == "callout")
    out = P.render_preview(callout)
    assert out.strip()
    assert "^" in out  # every template emits a block anchor
    assert "[!quote]" in out  # the callout template's marker
