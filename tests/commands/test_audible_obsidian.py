"""Tests for the Audible clips importer."""

from pathlib import Path

from typer.testing import CliRunner

from books.cli import app
from books.commands.audible import command as ao
from books.commands.audible import models
from books.core import store

runner = CliRunner()


def _seed_catalog(vault, rows):
    store.write_books_csv(vault, rows)


def test_command_is_registered():
    result = runner.invoke(app, ["audible", "--help"])
    assert result.exit_code == 0, result.output
    assert "audible" in result.output.lower()


def test_format_timestamp_always_has_hours():
    assert ao.format_timestamp(0) == "0:00:00"
    assert ao.format_timestamp(754_000) == "0:12:34"
    assert ao.format_timestamp(3_600_000) == "1:00:00"
    assert ao.format_timestamp(12_305_000) == "3:25:05"
    assert ao.format_timestamp(-5) == "0:00:00"   # clamps negatives


def test_chapter_for_finds_containing_chapter():
    chapters = [
        ao.Chapter(index=1, title="Intro", start_ms=0, end_ms=60_000),
        ao.Chapter(index=2, title="Rise", start_ms=60_000, end_ms=120_000),
    ]
    assert ao.chapter_for(0, chapters).title == "Intro"
    assert ao.chapter_for(59_999, chapters).title == "Intro"
    assert ao.chapter_for(60_000, chapters).title == "Rise"
    assert ao.chapter_for(999_999, chapters) is None
    assert ao.chapter_for(0, []) is None


def _chapters():
    return [ao.Chapter(index=2, title="The Rise", start_ms=60_000, end_ms=600_000)]


def test_annotation_to_record_maps_clip_with_chapter():
    ann = ao.Annotation(id="a1", start_ms=120_000, end_ms=150_000,
                        title="Clip title @lenin", note="Key idea #power @stalin",
                        date="2026-07-01")
    rec = ao.annotation_to_record(ann, "This is the clip text.", _chapters())
    assert rec["text"] == "This is the clip text."
    assert rec["start_ms"] == 120_000
    assert rec["end_ms"] == 150_000
    assert rec["title"] == "Clip title @lenin"
    assert rec["note"] == "Key idea #power @stalin"
    assert rec["chapter"] == "The Rise"
    assert rec["chapter_index"] == 2


def test_record_to_highlight_renders_bare_timestamp_and_markers():
    rec = {"text": "This is the clip text.", "start_ms": 120_000,
           "end_ms": 150_000, "note": "Key idea #power @stalin",
           "date": "2026-07-01", "chapter": "The Rise", "chapter_index": 2}
    h = ao.record_to_highlight(rec)
    assert h.text == "This is the clip text."
    assert h.note == "Key idea"           # markers stripped from note
    assert h.tags == ["power"]
    assert h.links == ["Stalin"]
    assert h.chapter_index == 2
    assert h.chapter_title == "The Rise"
    assert h.page == "0:02:00"            # 120_000 ms = 2 minutes
    assert h.location_label == ""         # bare timestamp
    assert h.block == "000000120000"      # zero-padded ms for exact ordering


def test_record_to_highlight_falls_back_to_note_when_no_text():
    rec = {"text": "", "start_ms": 0, "end_ms": None,
           "note": "Just my note", "date": None,
           "chapter": None, "chapter_index": None}
    h = ao.record_to_highlight(rec)
    assert h.text == "Just my note"       # note used as body
    assert h.note is None                 # not duplicated


def test_record_to_highlight_merges_title_and_note_with_pooled_markers():
    # Both the clip's title and note may carry #tag/@link markers at the end;
    # they are stripped from both and pooled, and the two cleaned texts merge
    # into the note as `title\nbody` (title first).
    rec = {"text": "This is the clip text.", "start_ms": 120_000,
           "end_ms": 150_000, "title": "Purge begins @stalin",
           "note": "Key idea #power @trotsky",
           "date": "2026-07-01", "chapter": "The Rise", "chapter_index": 2}
    h = ao.record_to_highlight(rec)
    assert h.text == "This is the clip text."     # transcription stays the body
    assert h.note == "Purge begins\nKey idea"     # title first, then note body
    assert h.tags == ["power"]
    assert h.links == ["Stalin", "Trotsky"]       # pooled, title's link first


def test_record_to_highlight_title_only_becomes_note():
    rec = {"text": "The clip text.", "start_ms": 0, "end_ms": 10,
           "title": "A memorable moment #favorite", "note": None,
           "date": None, "chapter": None, "chapter_index": None}
    h = ao.record_to_highlight(rec)
    assert h.text == "The clip text."
    assert h.note == "A memorable moment"         # title alone is the note
    assert h.tags == ["favorite"]


def test_record_to_highlight_merged_title_note_body_when_no_text():
    # No transcription: the merged title+note becomes the highlight body.
    rec = {"text": "", "start_ms": 0, "end_ms": None,
           "title": "The title", "note": "The note @person",
           "date": None, "chapter": None, "chapter_index": None}
    h = ao.record_to_highlight(rec)
    assert h.text == "The title\nThe note"        # merged text used as body
    assert h.note is None                         # not duplicated
    assert h.links == ["Person"]                  # markers still pooled


def test_cache_roundtrip_and_missing(tmp_path):
    path = tmp_path / "sub" / "cache.json"
    assert ao.load_cache(path) == {}          # missing file -> {}
    data = {"B01": {"title": "Stalin", "clips": {"a1": {"text": "hi"}}}}
    ao.save_cache(path, data)
    assert ao.load_cache(path) == data


def test_load_cache_tolerates_corrupt_file(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("{not json", encoding="utf-8")
    assert ao.load_cache(path) == {}


def test_uncached_returns_only_new_annotations():
    anns = [ao.Annotation(id="a1", start_ms=0),
            ao.Annotation(id="a2", start_ms=10)]
    clips = {"a1": {"text": "already"}}
    new = ao.uncached(anns, clips)
    assert [a.id for a in new] == ["a2"]


def test_book_highlight_rows_maps_clips_with_annotation_ids():
    clips = {
        "a1": {"text": "First clip.", "start_ms": 120_000, "end_ms": 150_000,
               "note": None, "date": None, "chapter": "The Rise", "chapter_index": 2},
        "a2": {"text": "", "start_ms": 0, "end_ms": None, "note": None,
               "date": None, "chapter": None, "chapter_index": None},  # empty -> dropped
    }
    rows = ao.book_highlight_rows(clips)
    assert [r.annotation_id for r in rows] == ["a1"]
    assert rows[0].source == "audible"
    assert rows[0].text == "First clip."
    assert rows[0].chapter_title == "The Rise"


class FakeClient:
    def __init__(self, library, annotations, chapters=None):
        self._library = library
        self._annotations = annotations          # {asin: [Annotation]}
        self._chapters = chapters or {}          # {asin: [Chapter]}
        self.annotation_calls = []

    def library(self):
        return list(self._library)

    def annotations(self, asin):
        self.annotation_calls.append(asin)
        return list(self._annotations.get(asin, []))

    def chapters(self, asin):
        return list(self._chapters.get(asin, []))


class FakeDownloader:
    def __init__(self):
        self.calls = []

    def download(self, asin, dest_dir):
        self.calls.append(asin)
        p = Path(dest_dir) / f"{asin}.aaxc"
        p.write_bytes(b"fake-audio")
        return models.DownloadedAudio(path=p, key=None, iv=None)


class FakeCutter:
    def __init__(self):
        self.calls = []

    def cut(self, audio, start_ms, end_ms, dest):
        self.calls.append((audio.path.name, start_ms, end_ms))
        Path(dest).write_bytes(b"clip")
        return Path(dest)


def _fake_transcriber(path):
    return "transcribed text"


def _catalog_and_library(tmp_path):
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(out, [store.BookRow(
        book_id="Stalin - Stephen Kotkin", title="Stalin",
        authors=["Stephen Kotkin"], amazon="B0STALIN")])
    book = ao.LibraryBook(asin="B0STALIN", title="Stalin",
                          authors=["Stephen Kotkin"])
    anns = {"B0STALIN": [ao.Annotation(id="a1", start_ms=120_000,
                                       end_ms=150_000, note="Nice")]}
    return out, book, anns


def test_run_writes_highlights_and_audible_layer(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    client = FakeClient([book], anns)
    cache_path = out / "Data" / "Imports" / "audible" / "cache.json"
    down, cut = FakeDownloader(), FakeCutter()
    stats = ao.run(out, client=client, downloader=down, cutter=cut,
                   transcriber=_fake_transcriber, cache_path=cache_path,
                   clip_window=30)
    assert stats["books"] == 1 and stats["entries"] == 1
    assert stats["downloaded"] == 1 and stats["transcribed"] == 1
    hl = store.read_highlights(out, "Stalin - Stephen Kotkin")
    assert [r.source for r in hl] == ["audible"]
    assert hl[0].text == "transcribed text"
    assert hl[0].annotation_id == "a1"
    layer = store.read_layer(out, "audible")
    assert len(layer) == 1
    assert layer[0].amazon == "B0STALIN"
    assert layer[0].format == "audiobook"


def test_run_skips_unmatched_without_download(tmp_path):
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(out, [])                     # empty catalog -> no match
    book = ao.LibraryBook(asin="B0X", title="Unknown", authors=["Nobody"])
    client = FakeClient([book], {"B0X": [ao.Annotation(id="a1", start_ms=0, end_ms=10)]})
    down = FakeDownloader()
    stats = ao.run(out, client=client, downloader=down, cutter=FakeCutter(),
                   transcriber=_fake_transcriber,
                   cache_path=out / "c.json", clip_window=30)
    assert stats["skipped"] == 1 and stats["books"] == 0
    assert down.calls == []
    assert store.read_layer(out, "audible") == []


def test_run_no_highlights_writes_nothing(tmp_path):
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(out, [store.BookRow(
        book_id="Stalin - Stephen Kotkin", title="Stalin",
        authors=["Stephen Kotkin"], amazon="B0STALIN")])
    book = ao.LibraryBook(asin="B0STALIN", title="Stalin", authors=["Stephen Kotkin"])
    anns = {"B0STALIN": [ao.Annotation(id="a1", start_ms=0, end_ms=10, note=None)]}
    stats = ao.run(out, client=FakeClient([book], anns),
                   downloader=FakeDownloader(), cutter=FakeCutter(),
                   transcriber=lambda path: "", cache_path=out / "c.json",
                   clip_window=30)
    assert stats["books"] == 0 and stats["entries"] == 0
    assert store.read_highlights(out, "Stalin - Stephen Kotkin") == []
    assert store.read_layer(out, "audible") == []


def test_run_replaces_only_audible_highlights(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    store.write_highlights(out, "Stalin - Stephen Kotkin", "kobo",
                           [store.HighlightRow(source="kobo", text="kept")])
    ao.run(out, client=FakeClient([book], anns), downloader=FakeDownloader(),
           cutter=FakeCutter(), transcriber=_fake_transcriber,
           cache_path=out / "c.json", clip_window=30)
    hl = store.read_highlights(out, "Stalin - Stephen Kotkin")
    sources = sorted(r.source for r in hl)
    assert sources == ["audible", "kobo"]


def test_run_idempotent_uses_cache_no_redownload(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    cache_path = out / "Data" / "Imports" / "audible" / "cache.json"
    down1 = FakeDownloader()
    ao.run(out, client=FakeClient([book], anns), downloader=down1,
           cutter=FakeCutter(), transcriber=_fake_transcriber,
           cache_path=cache_path, clip_window=30)
    before = store.read_highlights(out, "Stalin - Stephen Kotkin")
    down2 = FakeDownloader()
    ao.run(out, client=FakeClient([book], anns), downloader=down2,
           cutter=FakeCutter(), transcriber=_fake_transcriber,
           cache_path=cache_path, clip_window=30)
    after = store.read_highlights(out, "Stalin - Stephen Kotkin")
    assert down2.calls == []
    assert [r.to_csv_dict() for r in before] == [r.to_csv_dict() for r in after]


def test_run_point_bookmark_uses_window_before_mark(tmp_path):
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(out, [store.BookRow(
        book_id="Stalin - Stephen Kotkin", title="Stalin",
        authors=["Stephen Kotkin"], amazon="B0STALIN")])
    book = ao.LibraryBook(asin="B0STALIN", title="Stalin",
                          authors=["Stephen Kotkin"])
    anns = {"B0STALIN": [ao.Annotation(id="a1", start_ms=90_000, end_ms=None)]}
    cut = FakeCutter()
    ao.run(out, client=FakeClient([book], anns), downloader=FakeDownloader(),
           cutter=cut, transcriber=_fake_transcriber,
           cache_path=out / "c.json", clip_window=30)
    # point bookmark: window ends at the mark, starts clip_window seconds earlier
    assert cut.calls == [("B0STALIN.aaxc", 60_000, 90_000)]


def test_run_continues_when_one_book_fails(tmp_path):
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(out, [
        store.BookRow(book_id="Stalin - Stephen Kotkin", title="Stalin",
                      authors=["Stephen Kotkin"], amazon="B0BAD"),
        store.BookRow(book_id="Peace - Leo Tolstoy", title="Peace",
                      authors=["Leo Tolstoy"], amazon="B0GOOD"),
    ])
    bad = ao.LibraryBook(asin="B0BAD", title="Stalin", authors=["Stephen Kotkin"])
    good = ao.LibraryBook(asin="B0GOOD", title="Peace", authors=["Leo Tolstoy"])
    anns = {
        "B0BAD": [ao.Annotation(id="a1", start_ms=1000, end_ms=2000)],
        "B0GOOD": [ao.Annotation(id="a2", start_ms=1000, end_ms=2000)],
    }

    class BoomDownloader(FakeDownloader):
        def download(self, asin, dest_dir):
            if asin == "B0BAD":
                raise RuntimeError("boom")
            return super().download(asin, dest_dir)

    stats = ao.run(out, client=FakeClient([bad, good], anns),
                   downloader=BoomDownloader(), cutter=FakeCutter(),
                   transcriber=_fake_transcriber, cache_path=out / "c.json",
                   clip_window=30)
    assert stats["failed"] == 1
    assert stats["books"] == 1 and stats["entries"] == 1
    assert store.read_highlights(out, "Peace - Leo Tolstoy")[0].text == "transcribed text"


def test_run_dry_run_writes_nothing(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    down = FakeDownloader()
    stats = ao.run(out, client=FakeClient([book], anns), downloader=down,
                   cutter=FakeCutter(), transcriber=_fake_transcriber,
                   cache_path=out / "c.json", clip_window=30, dry_run=True)
    assert down.calls == []
    assert store.read_highlights(out, "Stalin - Stephen Kotkin") == []
    assert store.read_layer(out, "audible") == []
    assert not (out / "c.json").exists()
    assert stats["books"] == 0


def test_cli_enriches_book_end_to_end(monkeypatch, tmp_path):
    from books.core import config, store
    out, book, anns = _catalog_and_library(tmp_path)
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: out)
    monkeypatch.setattr(
        config, "resolve_imports",
        lambda name, output=None: out / "Data" / "Imports" / name)
    monkeypatch.setattr(ao, "_build_client",
                        lambda quality="normal": FakeClient([book], anns))
    monkeypatch.setattr(ao, "_build_transcriber",
                        lambda kind, model: _fake_transcriber)
    monkeypatch.setattr(ao, "_build_cutter", lambda: FakeCutter())
    monkeypatch.setattr(ao, "_build_downloader", lambda client: FakeDownloader())

    result = runner.invoke(app, ["audible"])
    assert result.exit_code == 0, result.output
    hl = store.read_highlights(out, "Stalin - Stephen Kotkin")
    assert hl and hl[0].text == "transcribed text"
    assert "1 book" in result.output


def test_cli_dry_run_builds_no_heavy_adapters(monkeypatch, tmp_path):
    from books.core import config
    out, book, anns = _catalog_and_library(tmp_path)
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: out)
    monkeypatch.setattr(
        config, "resolve_imports",
        lambda name, output=None: out / "Data" / "Imports" / name)
    monkeypatch.setattr(ao, "_build_client",
                        lambda quality="normal": FakeClient([book], anns))

    def _boom(*a, **k):
        raise AssertionError("heavy adapter built during dry-run")

    monkeypatch.setattr(ao, "_build_transcriber", _boom)
    monkeypatch.setattr(ao, "_build_cutter", _boom)
    monkeypatch.setattr(ao, "_build_downloader", _boom)

    result = runner.invoke(app, ["audible", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "[dry-run]" in result.output


def test_run_asin_preserves_other_audible_layer_rows(tmp_path):
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(out, [
        store.BookRow(book_id="Stalin - Stephen Kotkin", title="Stalin",
                      authors=["Stephen Kotkin"], amazon="B0STALIN"),
        store.BookRow(book_id="Peace - Leo Tolstoy", title="Peace",
                      authors=["Leo Tolstoy"], amazon="B0PEACE"),
    ])
    # a prior audible run already recorded a layer row for another book
    store.write_layer(out, "audible", [store.BookRow(
        title="Peace", authors=["Leo Tolstoy"], amazon="B0PEACE",
        format="audiobook")])

    book = ao.LibraryBook(asin="B0STALIN", title="Stalin",
                          authors=["Stephen Kotkin"])
    anns = {"B0STALIN": [ao.Annotation(id="a1", start_ms=120_000, end_ms=150_000)]}
    ao.run(out, client=FakeClient([book], anns), downloader=FakeDownloader(),
           cutter=FakeCutter(), transcriber=_fake_transcriber,
           cache_path=out / "c.json", clip_window=30, asin="B0STALIN")

    asins = sorted(r.amazon for r in store.read_layer(out, "audible"))
    assert asins == ["B0PEACE", "B0STALIN"]     # prior row preserved + new one added
