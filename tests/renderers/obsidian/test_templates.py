"""Tests for the Obsidian highlight template env, resolution, and scaffold."""

import jinja2

from books.core.highlights import Highlight
from books.renderers.obsidian import render_highlights
from books.renderers.obsidian import templates as T


def test_quote_filter_prefixes_lines_and_blank():
    assert T._quote_filter("a\n\nb") == "> a\n>\n> b"
    assert T._quote_filter("x", ">>") == ">> x"


def test_tag_filter():
    assert T._tag_filter("history") == "#history"


def test_custom_template_changes_callout_shape():
    tmpl = jinja2.Template("PLAIN: {{ h.text }} ^{{ h.anchor }}")
    out = render_highlights([Highlight(text="hi", page="4")], template=tmpl)
    assert "PLAIN: hi ^p4" in out
    assert "> [!quote]" not in out


def test_custom_template_still_groups_by_source():
    tmpl = jinja2.Template("- {{ h.text }}")
    out = render_highlights(
        [
            Highlight(text="k", progress=0.1, source="kobo"),
            Highlight(text="r", progress=0.2, source="readwise"),
        ],
        template=tmpl,
    )
    # Python still owns the source headers regardless of the template
    assert "### Kobo" in out and "### Readwise" in out


def test_resolve_template_falls_back_to_packaged_when_config_absent(monkeypatch, tmp_path):
    # point templates_dir at an empty tmp dir -> no .config default -> packaged backup
    monkeypatch.setattr(T.config, "templates_dir", lambda: tmp_path)
    tmpl = T.resolve_template(None)
    out = tmpl.render(
        h={
            "text": "x",
            "note": "",
            "tags": [],
            "links": [],
            "label": "",
            "date": "",
            "time": "",
            "anchor": "a1",
        }
    )
    assert "> [!quote]+" in out
    assert "> x" in out
    assert "^a1" in out


def test_resolve_template_bad_explicit_path_warns_and_falls_back(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(T.config, "templates_dir", lambda: tmp_path)
    tmpl = T.resolve_template(str(tmp_path / "does-not-exist.jinja"))
    # falls back to packaged default (still compiles + renders a callout)
    out = tmpl.render(
        h={
            "text": "x",
            "note": "",
            "tags": [],
            "links": [],
            "label": "",
            "date": "",
            "time": "",
            "anchor": "a1",
        }
    )
    assert "> [!quote]+" in out


def test_resolve_template_invalid_syntax_warns_and_falls_back(monkeypatch, tmp_path):
    bad = tmp_path / "bad.jinja"
    bad.write_text("{% if %}broken")  # invalid Jinja
    monkeypatch.setattr(T.config, "templates_dir", lambda: tmp_path)
    tmpl = T.resolve_template(str(bad))
    out = tmpl.render(
        h={
            "text": "x",
            "note": "",
            "tags": [],
            "links": [],
            "label": "",
            "date": "",
            "time": "",
            "anchor": "a1",
        }
    )
    assert "> [!quote]+" in out


def test_resolve_template_uses_config_default_when_present(monkeypatch, tmp_path):
    obs = tmp_path / "obsidian"
    obs.mkdir()
    (obs / "callout.md.jinja").write_text("CFG:{{ h.text }}")
    monkeypatch.setattr(T.config, "templates_dir", lambda: tmp_path)
    tmpl = T.resolve_template(None)
    assert tmpl.render(h={"text": "hi"}) == "CFG:hi"
