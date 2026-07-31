"""Tests for the consolidated `import` command.

Step `run` functions are monkeypatched so no real Calibre/Kobo data is needed.
"""

from books.commands import import_cmd
from books.commands import import_cmd as imp
from books.core import config


def test_has_csv_true_when_csv_present(tmp_path):
    (tmp_path / "a.csv").write_text("x")
    assert imp._has_csv(tmp_path)


def test_has_csv_false_when_empty_or_missing(tmp_path):
    assert not imp._has_csv(tmp_path)
    assert not imp._has_csv(tmp_path / "nope")


# --- selection & merge injection -------------------------------------------


def _names(steps):
    return [s.name for s in steps]


def test_no_flags_runs_sync_set_with_one_merge():
    steps = imp.build_steps(set(imp.SYNC_SET))
    assert _names(steps) == [
        "calibre",
        "goodreads",
        "merge",
        "kobo",
        "highlighted",
        "readwise",
        "kindle",
    ]


def test_single_metadata_flag_gets_trailing_merge():
    assert _names(imp.build_steps({"calibre"})) == ["calibre", "merge"]


def test_single_highlight_flag_gets_leading_merge():
    assert _names(imp.build_steps({"kobo"})) == ["merge", "kobo"]


def test_enricher_gets_merge_before_and_after():
    assert _names(imp.build_steps({"audible"})) == ["merge", "audible", "merge"]
    assert _names(imp.build_steps({"covers"})) == ["merge", "covers", "merge"]


def test_selection_from_flags_uses_default_when_empty():
    default = {"calibre", "covers"}
    assert imp._selection_from_flags({"calibre": False}, default) == default
    assert imp._selection_from_flags({"calibre": True, "kobo": True}, default) == {
        "calibre",
        "kobo",
    }


# --- orchestration ----------------------------------------------------------


def _stub_runs(monkeypatch, order, *, failing=None):
    def make(name):
        def run(vault, cfg):
            order.append(name)
            if failing and name == failing:
                raise RuntimeError(f"{name} boom")
            return {}

        return run

    for name in ("calibre", "goodreads", "kobo", "highlighted", "readwise", "kindle", "merge"):
        monkeypatch.setattr(imp, f"_run_{name}", make(name))


def _detect_all(monkeypatch):
    for name in (
        "_detect_calibre",
        "_detect_goodreads",
        "_detect_kobo",
        "_detect_highlighted",
        "_detect_readwise",
        "_detect_kindle",
        "_detect_merge",
    ):
        monkeypatch.setattr(imp, name, lambda v, c: "src")


def test_runs_selected_in_dependency_order(tmp_path, monkeypatch):
    _detect_all(monkeypatch)
    order = []
    _stub_runs(monkeypatch, order)
    imp.run_import(tmp_path, selection=set(imp.SYNC_SET))
    assert order == [
        "calibre",
        "goodreads",
        "merge",
        "kobo",
        "highlighted",
        "readwise",
        "kindle",
    ]


def test_skips_steps_without_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(imp, "_detect_calibre", lambda v, c: None)
    monkeypatch.setattr(imp, "_detect_goodreads", lambda v, c: "src")
    monkeypatch.setattr(imp, "_detect_kobo", lambda v, c: None)
    monkeypatch.setattr(imp, "_detect_highlighted", lambda v, c: None)
    monkeypatch.setattr(imp, "_detect_readwise", lambda v, c: None)
    monkeypatch.setattr(imp, "_detect_merge", lambda v, c: "src")
    order = []
    _stub_runs(monkeypatch, order)
    results = imp.run_import(tmp_path, selection=set(imp.SYNC_SET))
    ran = [r.name for r in results if r.status == "ran"]
    assert ran == ["goodreads", "merge"]


def test_continue_on_error(tmp_path, monkeypatch):
    _detect_all(monkeypatch)
    order = []
    _stub_runs(monkeypatch, order, failing="goodreads")
    results = imp.run_import(tmp_path, selection=set(imp.SYNC_SET))
    statuses = {r.name: r.status for r in results}
    assert statuses["goodreads"] == "failed"
    assert statuses["kobo"] == "ran"  # later steps still run


def test_dry_run_does_not_execute(tmp_path, monkeypatch):
    _detect_all(monkeypatch)
    order = []
    _stub_runs(monkeypatch, order)
    results = imp.run_import(tmp_path, selection=set(imp.SYNC_SET), dry_run=True)
    assert order == []
    assert all(r.status == "planned" for r in results)


# --- kindle-specific wiring -------------------------------------------------


def test_detect_kindle_true_with_cache_only(tmp_path):
    from books.commands.kindle import cache
    from books.core.highlights import Highlight

    cdir = cache.cache_dir(tmp_path)
    cache.save_book(cdir, "T - A", "T", "A", [Highlight(text="x")])
    assert import_cmd._detect_kindle(tmp_path, config.Config()) == str(cdir)


def test_summ_kindle_reports_pending():
    assert "3 pending" in import_cmd._summ_kindle({"books": 1, "entries": 5, "pending": 3})
    assert "pending" not in import_cmd._summ_kindle({"books": 1, "entries": 5, "pending": 0})
