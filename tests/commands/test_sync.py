"""Tests for the master `sync` command (books.sync).

Covers detection predicates, run ordering, continue-on-error, and dry-run.
Step `run` functions are monkeypatched so no real Calibre/Kobo data is needed.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from books.cli import app
from books.commands import sync

runner = CliRunner()


def _make_csv(folder: Path, name: str = "export.csv") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_text("Highlight\nx\n", encoding="utf-8")
    return p


# --- Detection helpers ------------------------------------------------------

def test_has_csv_true_when_csv_present(tmp_path):
    _make_csv(tmp_path)
    assert sync._has_csv(tmp_path) is True


def test_has_csv_false_when_empty_or_missing(tmp_path):
    (tmp_path / "empty").mkdir()
    assert sync._has_csv(tmp_path / "empty") is False
    assert sync._has_csv(tmp_path / "nope") is False


def test_detect_calibre_follows_library(tmp_path, monkeypatch):
    lib = tmp_path / "Calibre Library"
    monkeypatch.setattr(sync, "_calibre_library", lambda: lib)
    assert sync._detect_calibre(tmp_path) is None
    lib.mkdir()
    assert sync._detect_calibre(tmp_path) is not None


def test_kobo_source_prefers_device(tmp_path, monkeypatch):
    device = tmp_path / "device.sqlite"
    device.write_text("db", encoding="utf-8")
    monkeypatch.setattr(sync.kobo, "KOBO_DEVICE_DB", device)
    assert sync._kobo_source(tmp_path) == "Kobo device"


def test_kobo_source_falls_back_to_imports_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(sync.kobo, "KOBO_DEVICE_DB",
                        tmp_path / "not-mounted.sqlite")
    folder = sync._imports_folder("kobo", tmp_path)
    folder.mkdir(parents=True)
    assert sync._kobo_source(tmp_path) is None
    (folder / "KoboReader.sqlite").write_text("db", encoding="utf-8")
    assert sync._kobo_source(tmp_path) is not None


# --- Orchestration ----------------------------------------------------------

def _seed_all_sources(vault: Path, monkeypatch):
    """Make every step's source detectable."""
    lib = vault / "Calibre Library"
    lib.mkdir(parents=True)
    monkeypatch.setattr(sync, "_calibre_library", lambda: lib)
    monkeypatch.setattr(sync.kobo, "KOBO_DEVICE_DB",
                        vault / "not-mounted.sqlite")
    for name in ("goodreads", "highlighted", "readwise"):
        _make_csv(sync._imports_folder(name, vault))
    kobo_folder = sync._imports_folder("kobo", vault)
    kobo_folder.mkdir(parents=True, exist_ok=True)
    (kobo_folder / "KoboReader.sqlite").write_text("db", encoding="utf-8")


def _stub_runs(monkeypatch, order, *, failing=None):
    """Replace each step's run fn with a recorder; optionally raise for one."""
    for name in ("calibre", "goodreads", "kobo", "highlighted", "readwise"):
        def make(n):
            def run(vault):
                order.append(n)
                if failing == n:
                    raise RuntimeError(f"boom in {n}")
                return {}
            return run
        monkeypatch.setattr(sync, f"_run_{name}", make(name))


def test_runs_in_dependency_order(tmp_path, monkeypatch):
    vault = tmp_path / "Vault"
    vault.mkdir()
    _seed_all_sources(vault, monkeypatch)
    order = []
    _stub_runs(monkeypatch, order)
    results = sync.run_sync(vault)
    assert order == ["calibre", "goodreads", "kobo", "highlighted", "readwise"]
    assert all(r.status == "ran" for r in results)


def test_skips_steps_without_sources(tmp_path, monkeypatch):
    vault = tmp_path / "Vault"
    vault.mkdir()
    # Only goodreads has a source.
    monkeypatch.setattr(sync, "_calibre_library", lambda: vault / "nolib")
    monkeypatch.setattr(sync.kobo, "KOBO_DEVICE_DB", vault / "nodev.sqlite")
    _make_csv(sync._imports_folder("goodreads", vault))
    order = []
    _stub_runs(monkeypatch, order)
    results = sync.run_sync(vault)
    assert order == ["goodreads"]
    by_name = {r.name: r.status for r in results}
    assert by_name["goodreads"] == "ran"
    assert by_name["readwise"] == "skipped"
    assert by_name["calibre"] == "skipped"


def test_continue_on_error(tmp_path, monkeypatch):
    vault = tmp_path / "Vault"
    vault.mkdir()
    _seed_all_sources(vault, monkeypatch)
    order = []
    _stub_runs(monkeypatch, order, failing="goodreads")
    results = sync.run_sync(vault)
    # Every detected step still attempted, despite goodreads failing.
    assert order == ["calibre", "goodreads", "kobo", "highlighted", "readwise"]
    by_name = {r.name: r for r in results}
    assert by_name["goodreads"].status == "failed"
    assert "boom" in by_name["goodreads"].error
    assert by_name["readwise"].status == "ran"


def test_dry_run_does_not_execute(tmp_path, monkeypatch):
    vault = tmp_path / "Vault"
    vault.mkdir()
    _seed_all_sources(vault, monkeypatch)
    order = []
    _stub_runs(monkeypatch, order)
    results = sync.run_sync(vault, dry_run=True)
    assert order == []  # nothing executed
    assert not (vault / "Books").exists()
    assert all(r.status == "planned" for r in results
               if r.name in {"calibre", "goodreads", "kobo",
                             "highlighted", "readwise"} and r.status != "skipped")


# --- Real (non-mocked) double run -------------------------------------------

def _seed_real_create_and_enrich(vault: Path, monkeypatch):
    """Seed real goodreads (creates) + highlighted (enriches) sources.

    calibre/kobo/readwise are left without a source so they skip; goodreads
    creates the Stalin note and highlighted enriches it — exercising the real
    create-then-enrich composition end to end.
    """
    monkeypatch.setattr(sync, "_calibre_library", lambda: vault / "nolib")
    monkeypatch.setattr(sync.kobo, "KOBO_DEVICE_DB", vault / "nodev.sqlite")

    gr_folder = sync._imports_folder("goodreads", vault)
    gr_folder.mkdir(parents=True, exist_ok=True)
    (gr_folder / "export.csv").write_text(
        "Book Id,Title,Author,ISBN,ISBN13,Exclusive Shelf\n"
        "3,Stalin,Stephen Kotkin,,9781594203794,currently-reading\n",
        encoding="utf-8")

    hi_folder = sync._imports_folder("highlighted", vault)
    hi_folder.mkdir(parents=True, exist_ok=True)
    (hi_folder / "Highlights for Stalin.csv").write_text(
        "Highlight,Title,Author,ISBN,Collections,Reading Status,"
        "Book Added Date,Location,Tags,Note,Date,Favorite\n"
        '"Fear is the mind-killer",Stalin,Stephen Kotkin,9781594203794,,Reading,'
        '2026-07-24,4,Stalin,That is true,2026-07-24 10:37:51,N\n',
        encoding="utf-8")


def test_sync_real_run_idempotent(tmp_path, monkeypatch):
    vault = tmp_path / "Vault"
    vault.mkdir()
    _seed_real_create_and_enrich(vault, monkeypatch)

    results = sync.run_sync(vault)
    status = {r.name: r.status for r in results}
    assert status["goodreads"] == "ran" and status["highlighted"] == "ran"

    note = vault / "Books" / "Stalin - Stephen Kotkin.md"
    assert note.exists()
    text = note.read_text()
    assert 'goodreads: "https://www.goodreads.com/book/show/3"' in text  # created
    assert "## Highlights" in text                                        # enriched

    before = {p: p.read_text() for p in vault.rglob("*.md")}
    sync.run_sync(vault)  # second full run must change nothing
    after = {p: p.read_text() for p in vault.rglob("*.md")}
    assert before == after


# --- CLI wiring -------------------------------------------------------------

def test_sync_registered():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "sync" in result.output


def test_sync_help():
    result = runner.invoke(app, ["sync", "--help"])
    assert result.exit_code == 0
