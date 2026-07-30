"""Tests for the Audible clips importer."""

import json
from pathlib import Path

from typer.testing import CliRunner

from books.cli import app
from books.commands.audible import client as ac
from books.commands.audible import command as ao
from books.commands.audible import models
from books.core import store

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures"


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
    assert ao.format_timestamp(-5) == "0:00:00"  # clamps negatives


def test_chapter_for_finds_containing_chapter():
    chapters = [
        models.Chapter(index=1, title="Intro", start_ms=0, end_ms=60_000),
        models.Chapter(index=2, title="Rise", start_ms=60_000, end_ms=120_000),
    ]
    assert ao.chapter_for(0, chapters).title == "Intro"
    assert ao.chapter_for(59_999, chapters).title == "Intro"
    assert ao.chapter_for(60_000, chapters).title == "Rise"
    assert ao.chapter_for(999_999, chapters) is None
    assert ao.chapter_for(0, []) is None


def _chapters():
    return [models.Chapter(index=2, title="The Rise", start_ms=60_000, end_ms=600_000)]


def test_annotation_to_record_maps_clip_with_chapter():
    ann = models.Annotation(
        id="a1",
        start_ms=120_000,
        end_ms=150_000,
        title="Clip title @lenin",
        note="Key idea #power @stalin",
        date="2026-07-01",
    )
    rec = ao.annotation_to_record(ann, "This is the clip text.", _chapters())
    assert rec["text"] == "This is the clip text."
    assert rec["start_ms"] == 120_000
    assert rec["end_ms"] == 150_000
    assert rec["title"] == "Clip title @lenin"
    assert rec["note"] == "Key idea #power @stalin"
    assert rec["chapter"] == "The Rise"
    assert rec["chapter_index"] == 2


def test_record_to_highlight_renders_bare_timestamp_and_markers():
    rec = {
        "text": "This is the clip text.",
        "start_ms": 120_000,
        "end_ms": 150_000,
        "note": "Key idea #power @stalin",
        "date": "2026-07-01",
        "chapter": "The Rise",
        "chapter_index": 2,
    }
    h = ao.record_to_highlight(rec)
    assert h.text == "This is the clip text."
    assert h.note == "Key idea"  # markers stripped from note
    assert h.tags == ["power"]
    assert h.links == ["Stalin"]
    assert h.chapter_index == 2
    assert h.chapter_title == "The Rise"
    assert h.page == "0:02:00"  # 120_000 ms = 2 minutes
    assert h.location_label == ""  # bare timestamp
    assert h.block == "000000120000"  # zero-padded ms for exact ordering


def test_record_to_highlight_falls_back_to_note_when_no_text():
    rec = {
        "text": "",
        "start_ms": 0,
        "end_ms": None,
        "note": "Just my note",
        "date": None,
        "chapter": None,
        "chapter_index": None,
    }
    h = ao.record_to_highlight(rec)
    assert h.text == "Just my note"  # note used as body
    assert h.note is None  # not duplicated


def test_record_to_highlight_merges_title_and_note_with_pooled_markers():
    # Both the clip's title and note may carry #tag/@link markers at the end;
    # they are stripped from both and pooled, and the two cleaned texts merge
    # into the note as `title\nbody` (title first).
    rec = {
        "text": "This is the clip text.",
        "start_ms": 120_000,
        "end_ms": 150_000,
        "title": "Purge begins @stalin",
        "note": "Key idea #power @trotsky",
        "date": "2026-07-01",
        "chapter": "The Rise",
        "chapter_index": 2,
    }
    h = ao.record_to_highlight(rec)
    assert h.text == "This is the clip text."  # transcription stays the body
    assert h.note == "Purge begins\nKey idea"  # title first, then note body
    assert h.tags == ["power"]
    assert h.links == ["Stalin", "Trotsky"]  # pooled, title's link first


def test_record_to_highlight_title_only_becomes_note():
    rec = {
        "text": "The clip text.",
        "start_ms": 0,
        "end_ms": 10,
        "title": "A memorable moment #favorite",
        "note": None,
        "date": None,
        "chapter": None,
        "chapter_index": None,
    }
    h = ao.record_to_highlight(rec)
    assert h.text == "The clip text."
    assert h.note == "A memorable moment"  # title alone is the note
    assert h.tags == ["favorite"]


def test_record_to_highlight_merged_title_note_body_when_no_text():
    # No transcription: the merged title+note becomes the highlight body.
    rec = {
        "text": "",
        "start_ms": 0,
        "end_ms": None,
        "title": "The title",
        "note": "The note @person",
        "date": None,
        "chapter": None,
        "chapter_index": None,
    }
    h = ao.record_to_highlight(rec)
    assert h.text == "The title\nThe note"  # merged text used as body
    assert h.note is None  # not duplicated
    assert h.links == ["Person"]  # markers still pooled


def test_book_cache_roundtrip_and_missing(tmp_path):
    cache_dir = tmp_path / "sub" / "cache"
    assert ao.load_book_cache(cache_dir, "B01") == {}  # missing file -> {}
    data = {"title": "Stalin", "clips": {"a1": {"text": "hi"}}}
    ao.save_book_cache(cache_dir, "B01", data)
    assert ao.book_cache_path(cache_dir, "B01") == cache_dir / "B01.json"
    assert ao.load_book_cache(cache_dir, "B01") == data
    # each book is an independent file
    assert ao.load_book_cache(cache_dir, "B02") == {}


def test_load_book_cache_tolerates_corrupt_file(tmp_path):
    cache_dir = tmp_path / "cache"
    ao.save_book_cache(cache_dir, "B01", {"title": "x"})
    ao.book_cache_path(cache_dir, "B01").write_text("{not json", encoding="utf-8")
    assert ao.load_book_cache(cache_dir, "B01") == {}


def test_migrate_legacy_cache_splits_into_per_book_files(tmp_path):
    cache_dir = tmp_path / "Data" / "Imports" / "audible" / "cache"
    legacy = cache_dir.with_suffix(".json")  # .../audible/cache.json
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps(
            {
                "B01": {"title": "Stalin", "clips": {"a1": {"text": "hi"}}},
                "B02": {"title": "Peace", "clips": {"a2": {"text": "yo"}}},
            }
        ),
        encoding="utf-8",
    )
    ao.migrate_legacy_cache(cache_dir)
    assert not legacy.exists()  # legacy file removed after the split
    assert ao.load_book_cache(cache_dir, "B01")["clips"]["a1"]["text"] == "hi"
    assert ao.load_book_cache(cache_dir, "B02")["clips"]["a2"]["text"] == "yo"


def test_migrate_legacy_cache_never_overwrites_existing_and_is_noop_when_absent(tmp_path):
    cache_dir = tmp_path / "cache"
    # a per-book file already holds fresher data than the legacy blob
    ao.save_book_cache(cache_dir, "B01", {"title": "new", "clips": {"a1": {"text": "fresh"}}})
    legacy = cache_dir.with_suffix(".json")
    legacy.write_text(
        json.dumps({"B01": {"title": "old", "clips": {"a1": {"text": "stale"}}}}),
        encoding="utf-8",
    )
    ao.migrate_legacy_cache(cache_dir)
    assert ao.load_book_cache(cache_dir, "B01")["clips"]["a1"]["text"] == "fresh"
    assert not legacy.exists()
    # a second call with no legacy file is a harmless no-op
    ao.migrate_legacy_cache(cache_dir)


def test_uncached_returns_only_new_annotations():
    anns = [models.Annotation(id="a1", start_ms=0), models.Annotation(id="a2", start_ms=10)]
    clips = {"a1": {"text": "already"}}
    new = ao.uncached(anns, clips)
    assert [a.id for a in new] == ["a2"]


def test_book_highlight_rows_maps_clips_with_annotation_ids():
    clips = {
        "a1": {
            "text": "First clip.",
            "start_ms": 120_000,
            "end_ms": 150_000,
            "note": None,
            "date": None,
            "chapter": "The Rise",
            "chapter_index": 2,
        },
        "a2": {
            "text": "",
            "start_ms": 0,
            "end_ms": None,
            "note": None,
            "date": None,
            "chapter": None,
            "chapter_index": None,
        },  # empty -> dropped
    }
    rows = ao.book_highlight_rows(clips)
    assert [r.annotation_id for r in rows] == ["a1"]
    assert rows[0].source == "audible"
    assert rows[0].text == "First clip."
    assert rows[0].chapter_title == "The Rise"


def test_book_highlight_rows_prunes_stale_cache_ids():
    # A cache left over from before the twin-bookmark/duplicate-note fix still holds
    # transcriptions for ids that are no longer valid annotations. When the caller
    # passes the current annotation ids, only those are emitted (no stale dupes).
    clips = {
        "clip1": {"text": "Real clip.", "start_ms": 1000, "end_ms": 2000},
        "twin_bookmark": {"text": "Window before the mark.", "start_ms": 0, "end_ms": 1000},
        "dup_note": {"text": "A duplicated note.", "start_ms": 1000, "end_ms": 1000},
    }
    rows = ao.book_highlight_rows(clips, valid_ids={"clip1"})
    assert [r.annotation_id for r in rows] == ["clip1"]


class FakeClient:
    def __init__(self, library, annotations, chapters=None):
        self._library = library
        self._annotations = annotations  # {asin: [Annotation]}
        self._chapters = chapters or {}  # {asin: [Chapter]}
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
    _seed_catalog(
        out,
        [
            store.BookRow(
                book_id="Stalin - Stephen Kotkin",
                title="Stalin",
                authors=["Stephen Kotkin"],
                amazon="B0STALIN",
            )
        ],
    )
    book = models.LibraryBook(asin="B0STALIN", title="Stalin", authors=["Stephen Kotkin"])
    anns = {"B0STALIN": [models.Annotation(id="a1", start_ms=120_000, end_ms=150_000, note="Nice")]}
    return out, book, anns


def test_build_candidates_tags_match_clip_count_and_cache(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    new_book = models.LibraryBook(asin="B0NEW", title="Audio Only", authors=["A. Narrator"])
    library = [book, new_book]
    annotations = {**anns, "B0NEW": [models.Annotation(id="n1", start_ms=0, end_ms=10)]}
    client = FakeClient(library, annotations)
    cache_dir = out / "Data" / "Imports" / "audible" / "cache"
    # Pre-seed a cache file for the matched book so `cached` flips to True.
    ao.save_book_cache(cache_dir, "B0STALIN", {"title": "Stalin", "clips": {}})

    cands = ao.build_candidates(client, store.Catalog(out), cache_dir)

    by_asin = {c.book.asin: c for c in cands}
    assert by_asin["B0STALIN"].book_id == "Stalin - Stephen Kotkin"
    assert by_asin["B0STALIN"].clip_count == 1 and by_asin["B0STALIN"].cached is True
    assert by_asin["B0NEW"].book_id is None  # audiobook-only, no catalog match
    assert by_asin["B0NEW"].cached is False


def test_build_candidates_honors_asin_filter(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    other = models.LibraryBook(asin="B0OTHER", title="Other", authors=["X"])
    client = FakeClient([book, other], {**anns, "B0OTHER": []})
    cands = ao.build_candidates(client, store.Catalog(out), out / "cache", asin="B0STALIN")
    assert [c.book.asin for c in cands] == ["B0STALIN"]


def test_run_writes_highlights_and_audible_layer(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    client = FakeClient([book], anns)
    cache_dir = out / "Data" / "Imports" / "audible" / "cache"
    down, cut = FakeDownloader(), FakeCutter()
    stats = ao.run(
        out,
        client=client,
        downloader=down,
        cutter=cut,
        transcriber=_fake_transcriber,
        cache_dir=cache_dir,
        clip_window=30,
    )
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


def test_run_unmatched_writes_layer_and_caches_no_highlights(tmp_path):
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(out, [])  # empty catalog -> the book is audiobook-only ("new")
    book = models.LibraryBook(asin="B0NEW", title="Audio Only", authors=["Narrator"])
    anns = {"B0NEW": [models.Annotation(id="a1", start_ms=0, end_ms=10_000, note="Hi")]}
    down = FakeDownloader()
    cache_dir = out / "Data" / "Imports" / "audible" / "cache"
    stats = ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=down,
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_dir=cache_dir,
        clip_window=30,
    )
    # Audiobook-only book IS transcribed + cached now, and staged via a layer row...
    assert stats["new"] == 1 and stats["books"] == 0
    assert down.calls == ["B0NEW"]
    assert ao.load_book_cache(cache_dir, "B0NEW")["clips"]  # transcription cached
    layer = store.read_layer(out, "audible")
    assert [r.amazon for r in layer] == ["B0NEW"] and layer[0].format == "audiobook"
    # ...but no highlights are written this run (no book_id exists yet).
    assert store.read_highlights(out, "Audio Only - Narrator") == []


def test_run_processes_only_selected_candidates(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    other = models.LibraryBook(asin="B0OTHER", title="Other", authors=["X"])
    library = [book, other]
    annotations = {**anns, "B0OTHER": [models.Annotation(id="o1", start_ms=0, end_ms=5)]}
    client = FakeClient(library, annotations)
    cache_dir = out / "Data" / "Imports" / "audible" / "cache"
    # Select ONLY the matched Stalin book; Other must be untouched.
    selected = [
        c
        for c in ao.build_candidates(client, store.Catalog(out), cache_dir)
        if c.book.asin == "B0STALIN"
    ]
    down = FakeDownloader()
    stats = ao.run(
        out,
        selected=selected,
        client=client,
        downloader=down,
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_dir=cache_dir,
        clip_window=30,
    )
    assert stats["books"] == 1 and stats["new"] == 0
    assert down.calls == ["B0STALIN"]  # Other never downloaded
    assert ao.load_book_cache(cache_dir, "B0OTHER") == {}  # Other never cached


def test_run_no_highlights_writes_nothing(tmp_path):
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(
        out,
        [
            store.BookRow(
                book_id="Stalin - Stephen Kotkin",
                title="Stalin",
                authors=["Stephen Kotkin"],
                amazon="B0STALIN",
            )
        ],
    )
    book = models.LibraryBook(asin="B0STALIN", title="Stalin", authors=["Stephen Kotkin"])
    anns = {"B0STALIN": [models.Annotation(id="a1", start_ms=0, end_ms=10, note=None)]}
    stats = ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=FakeDownloader(),
        cutter=FakeCutter(),
        transcriber=lambda path: "",
        cache_dir=out / "cache",
        clip_window=30,
    )
    assert stats["books"] == 0 and stats["entries"] == 0
    assert store.read_highlights(out, "Stalin - Stephen Kotkin") == []
    assert store.read_layer(out, "audible") == []


def test_run_replaces_only_audible_highlights(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    store.write_highlights(
        out, "Stalin - Stephen Kotkin", "kobo", [store.HighlightRow(source="kobo", text="kept")]
    )
    ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=FakeDownloader(),
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_dir=out / "cache",
        clip_window=30,
    )
    hl = store.read_highlights(out, "Stalin - Stephen Kotkin")
    sources = sorted(r.source for r in hl)
    assert sources == ["audible", "kobo"]


def test_run_idempotent_uses_cache_no_redownload(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    cache_dir = out / "Data" / "Imports" / "audible" / "cache"
    down1 = FakeDownloader()
    ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=down1,
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_dir=cache_dir,
        clip_window=30,
    )
    before = store.read_highlights(out, "Stalin - Stephen Kotkin")
    down2 = FakeDownloader()
    ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=down2,
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_dir=cache_dir,
        clip_window=30,
    )
    after = store.read_highlights(out, "Stalin - Stephen Kotkin")
    assert down2.calls == []
    assert [r.to_csv_dict() for r in before] == [r.to_csv_dict() for r in after]


def test_run_point_bookmark_uses_window_before_mark(tmp_path):
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(
        out,
        [
            store.BookRow(
                book_id="Stalin - Stephen Kotkin",
                title="Stalin",
                authors=["Stephen Kotkin"],
                amazon="B0STALIN",
            )
        ],
    )
    book = models.LibraryBook(asin="B0STALIN", title="Stalin", authors=["Stephen Kotkin"])
    anns = {"B0STALIN": [models.Annotation(id="a1", start_ms=90_000, end_ms=None)]}
    cut = FakeCutter()
    ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=FakeDownloader(),
        cutter=cut,
        transcriber=_fake_transcriber,
        cache_dir=out / "cache",
        clip_window=30,
    )
    # point bookmark: window ends at the mark, starts clip_window seconds earlier
    assert cut.calls == [("B0STALIN.aaxc", 60_000, 90_000)]


def test_run_text_only_note_is_not_transcribed(tmp_path):
    # A standalone note (end == start, no audio range) must NOT be cut/transcribed;
    # its text is the highlight body directly.
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(
        out,
        [
            store.BookRow(
                book_id="Stalin - Stephen Kotkin",
                title="Stalin",
                authors=["Stephen Kotkin"],
                amazon="B0STALIN",
            )
        ],
    )
    book = models.LibraryBook(asin="B0STALIN", title="Stalin", authors=["Stephen Kotkin"])
    anns = {
        "B0STALIN": [
            models.Annotation(id="n1", start_ms=90_000, end_ms=90_000, note="A pure thought")
        ]
    }
    cut = FakeCutter()
    ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=FakeDownloader(),
        cutter=cut,
        transcriber=_fake_transcriber,
        cache_dir=out / "cache",
        clip_window=30,
    )
    assert cut.calls == []  # never cut a zero-length range
    hl = store.read_highlights(out, "Stalin - Stephen Kotkin")
    assert [r.text for r in hl] == ["A pure thought"]


def test_run_prunes_stale_cache_from_before_the_fix(tmp_path):
    # Regression: a cache.json written before the dedup fix holds transcriptions for
    # twin bookmarks / duplicate notes. A fresh run (whose annotations no longer
    # include those ids) must not resurface them as duplicate highlights.
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(
        out,
        [
            store.BookRow(
                book_id="Stalin - Stephen Kotkin",
                title="Stalin",
                authors=["Stephen Kotkin"],
                amazon="B0STALIN",
            )
        ],
    )
    cache_dir = out / "Data" / "Imports" / "audible" / "cache"
    ao.save_book_cache(
        cache_dir,
        "B0STALIN",
        {
            "title": "Stalin",
            "clips": {
                "clip1": {"text": "Real clip.", "start_ms": 1000, "end_ms": 2000},
                "twin_bm": {"text": "stale window", "start_ms": 0, "end_ms": 1000},
                "dup_note": {"text": "stale note", "start_ms": 1000, "end_ms": 1000},
            },
        },
    )
    book = models.LibraryBook(asin="B0STALIN", title="Stalin", authors=["Stephen Kotkin"])
    # The deduped client only returns the real clip now.
    anns = {"B0STALIN": [models.Annotation(id="clip1", start_ms=1000, end_ms=2000)]}
    down = FakeDownloader()
    ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=down,
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_dir=cache_dir,
        clip_window=30,
    )
    assert down.calls == []  # clip1 already cached, nothing new to download
    hl = store.read_highlights(out, "Stalin - Stephen Kotkin")
    assert [r.annotation_id for r in hl] == ["clip1"]  # stale ids not resurfaced


def test_run_real_sidecar_produces_one_highlight_per_annotation(tmp_path):
    # End-to-end against a real (trimmed) Audible sidecar: 5 clips + twin bookmarks
    # + duplicate note records must collapse to exactly 5 highlights, each carrying
    # its merged note with @links parsed out — no duplicates.
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(
        out,
        [
            store.BookRow(
                book_id="The Japanese Empire - Author",
                title="The Japanese Empire",
                authors=["Author"],
                amazon="B0GWFB1KLJ",
            )
        ],
    )
    payload = json.loads((FIXTURES / "audible_sidecar_sample.json").read_text(encoding="utf-8"))
    anns = ac.annotations_from_sidecar(payload)
    book = models.LibraryBook(asin="B0GWFB1KLJ", title="The Japanese Empire", authors=["Author"])
    ao.run(
        out,
        client=FakeClient([book], {"B0GWFB1KLJ": anns}),
        downloader=FakeDownloader(),
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_dir=out / "cache",
        clip_window=30,
    )
    hl = store.read_highlights(out, "The Japanese Empire - Author")
    assert len(hl) == 5  # one per clip, no twin/duplicate highlights
    assert len({r.annotation_id for r in hl}) == 5  # no duplicate ids

    by_id = {r.annotation_id: r for r in hl}
    # "@causality" title + "Interesting way..." note -> link pooled, note is the body.
    causality = by_id["a3O1Z3YFAN0SNA"]
    assert "Causality" in causality.links
    assert causality.note.startswith("Interesting way to look")
    assert causality.text == "transcribed text"  # the clip audio is still the quote
    # "@causality @geopolitics" title + a note -> both links pooled.
    two = by_id["a24KW62IU3IU7U"]
    assert two.links == ["Causality", "Geopolitics"]
    assert two.note.startswith("Great discussion")


def test_run_continues_when_one_book_fails(tmp_path):
    out = tmp_path / "V"
    out.mkdir(parents=True)
    _seed_catalog(
        out,
        [
            store.BookRow(
                book_id="Stalin - Stephen Kotkin",
                title="Stalin",
                authors=["Stephen Kotkin"],
                amazon="B0BAD",
            ),
            store.BookRow(
                book_id="Peace - Leo Tolstoy",
                title="Peace",
                authors=["Leo Tolstoy"],
                amazon="B0GOOD",
            ),
        ],
    )
    bad = models.LibraryBook(asin="B0BAD", title="Stalin", authors=["Stephen Kotkin"])
    good = models.LibraryBook(asin="B0GOOD", title="Peace", authors=["Leo Tolstoy"])
    anns = {
        "B0BAD": [models.Annotation(id="a1", start_ms=1000, end_ms=2000)],
        "B0GOOD": [models.Annotation(id="a2", start_ms=1000, end_ms=2000)],
    }

    class BoomDownloader(FakeDownloader):
        def download(self, asin, dest_dir):
            if asin == "B0BAD":
                raise RuntimeError("boom")
            return super().download(asin, dest_dir)

    stats = ao.run(
        out,
        client=FakeClient([bad, good], anns),
        downloader=BoomDownloader(),
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_dir=out / "cache",
        clip_window=30,
    )
    assert stats["failed"] == 1
    assert stats["books"] == 1 and stats["entries"] == 1
    assert store.read_highlights(out, "Peace - Leo Tolstoy")[0].text == "transcribed text"


def test_run_dry_run_writes_nothing(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    down = FakeDownloader()
    stats = ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=down,
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_dir=out / "cache",
        clip_window=30,
        dry_run=True,
    )
    assert down.calls == []
    assert store.read_highlights(out, "Stalin - Stephen Kotkin") == []
    assert store.read_layer(out, "audible") == []
    assert not (out / "cache").exists()
    assert stats["books"] == 0


def test_dry_run_reads_legacy_cache_without_migrating(tmp_path):
    # A not-yet-migrated monolithic cache.json must still count as cached during a
    # dry run (so nothing is re-estimated), and the dry run must not touch disk.
    out, book, anns = _catalog_and_library(tmp_path)
    cache_dir = out / "Data" / "Imports" / "audible" / "cache"
    legacy = cache_dir.with_suffix(".json")
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps({"B0STALIN": {"title": "Stalin", "clips": {"a1": {"text": "hi"}}}}),
        encoding="utf-8",
    )
    stats = ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=FakeDownloader(),
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_dir=cache_dir,
        clip_window=30,
        dry_run=True,
    )
    assert stats["est_seconds"] == 0.0  # a1 already cached -> nothing new to transcribe
    assert legacy.exists()  # dry run never migrates
    assert not any(cache_dir.glob("*.json"))  # nor writes per-book files


def test_dry_run_lists_matched_and_new_without_cost_for_local(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    new_book = models.LibraryBook(asin="B0NEW", title="Audio Only", authors=["Narrator"])
    client = FakeClient(
        [book, new_book],
        {**anns, "B0NEW": [models.Annotation(id="n1", start_ms=0, end_ms=60_000)]},
    )
    lines = []
    stats = ao.run(
        out,
        client=client,
        downloader=None,
        cutter=None,
        transcriber=None,
        cache_dir=out / "cache",
        clip_window=30,
        dry_run=True,
        show_cost=False,
        echo=lines.append,
    )
    text = "\n".join(lines)
    assert "Stalin" in text and "Audio Only" in text
    assert "new" in text.lower()  # the audiobook-only book is flagged
    assert "$" not in text  # local backend -> no cost shown
    assert stats["new"] == 1 and stats["matched"] == 1


def test_dry_run_shows_cost_for_openai(tmp_path):
    out, book, anns = _catalog_and_library(tmp_path)
    lines = []
    ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=None,
        cutter=None,
        transcriber=None,
        cache_dir=out / "cache",
        clip_window=30,
        dry_run=True,
        show_cost=True,
        echo=lines.append,
    )
    assert "$" in "\n".join(lines)  # openai backend -> cost shown


def test_cli_enriches_book_end_to_end(monkeypatch, tmp_path):
    from books.core import config, store

    out, book, anns = _catalog_and_library(tmp_path)
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: out)
    monkeypatch.setattr(
        config, "resolve_imports", lambda name, output=None: out / "Data" / "Imports" / name
    )
    monkeypatch.setattr(ao, "_build_client", lambda quality="normal": FakeClient([book], anns))
    monkeypatch.setattr(ao, "_build_transcriber", lambda kind, model: _fake_transcriber)
    monkeypatch.setattr(ao, "_build_cutter", lambda: FakeCutter())
    monkeypatch.setattr(ao, "_build_downloader", lambda client: FakeDownloader())

    result = runner.invoke(app, ["audible", "--all"])
    assert result.exit_code == 0, result.output
    hl = store.read_highlights(out, "Stalin - Stephen Kotkin")
    assert hl and hl[0].text == "transcribed text"
    assert "1 book" in result.output


def test_cli_off_tty_without_all_errors(tmp_path, monkeypatch):
    out, book, anns = _catalog_and_library(tmp_path)
    monkeypatch.setattr(ao, "_build_client", lambda quality="normal": FakeClient([book], anns))
    # CliRunner is not a tty; no --all/--asin -> clean error, nothing built.
    result = runner.invoke(app, ["audible", "-o", str(out)])
    assert result.exit_code != 0
    assert "--all" in result.output or "--asin" in result.output


def test_cli_all_flag_runs_without_picker(tmp_path, monkeypatch):
    out, book, anns = _catalog_and_library(tmp_path)
    monkeypatch.setattr(ao, "_build_client", lambda quality="normal": FakeClient([book], anns))
    monkeypatch.setattr(ao, "_build_transcriber", lambda kind, model: _fake_transcriber)
    monkeypatch.setattr(ao, "_build_cutter", lambda: FakeCutter())
    monkeypatch.setattr(ao, "_build_downloader", lambda client: FakeDownloader())
    result = runner.invoke(app, ["audible", "-o", str(out), "--all"])
    assert result.exit_code == 0, result.output
    assert store.read_highlights(out, "Stalin - Stephen Kotkin")  # highlights written


def test_cli_dry_run_builds_no_heavy_adapters(monkeypatch, tmp_path):
    from books.core import config

    out, book, anns = _catalog_and_library(tmp_path)
    monkeypatch.setattr(config, "resolve_vault", lambda output=None: out)
    monkeypatch.setattr(
        config, "resolve_imports", lambda name, output=None: out / "Data" / "Imports" / name
    )
    monkeypatch.setattr(ao, "_build_client", lambda quality="normal": FakeClient([book], anns))

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
    _seed_catalog(
        out,
        [
            store.BookRow(
                book_id="Stalin - Stephen Kotkin",
                title="Stalin",
                authors=["Stephen Kotkin"],
                amazon="B0STALIN",
            ),
            store.BookRow(
                book_id="Peace - Leo Tolstoy",
                title="Peace",
                authors=["Leo Tolstoy"],
                amazon="B0PEACE",
            ),
        ],
    )
    # a prior audible run already recorded a layer row for another book
    store.write_layer(
        out,
        "audible",
        [
            store.BookRow(
                title="Peace", authors=["Leo Tolstoy"], amazon="B0PEACE", format="audiobook"
            )
        ],
    )

    book = models.LibraryBook(asin="B0STALIN", title="Stalin", authors=["Stephen Kotkin"])
    anns = {"B0STALIN": [models.Annotation(id="a1", start_ms=120_000, end_ms=150_000)]}
    ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=FakeDownloader(),
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_dir=out / "cache",
        clip_window=30,
        asin="B0STALIN",
    )

    asins = sorted(r.amazon for r in store.read_layer(out, "audible"))
    assert asins == ["B0PEACE", "B0STALIN"]  # prior row preserved + new one added


class RecordingStep:
    def __init__(self):
        self.statuses = []
        self.books = []  # (description, total) per book
        self.describes = []  # per-book bar label changes
        self.advances = 0

    def status(self, text):
        self.statuses.append(text)

    def book(self, description, total=None):
        self.books.append((description, total))

    def describe(self, text):
        self.describes.append(text)

    def advance(self, n=1):
        self.advances += n


def test_run_reports_per_clip_progress(monkeypatch, tmp_path):
    from contextlib import contextmanager

    out, book, anns = _catalog_and_library(tmp_path)
    rec = RecordingStep()

    @contextmanager
    def fake_nested(status):
        rec.statuses.append(status)
        yield rec

    monkeypatch.setattr(ao.ui, "nested_progress", fake_nested)

    ao.run(
        out,
        client=FakeClient([book], anns),
        downloader=FakeDownloader(),
        cutter=FakeCutter(),
        transcriber=_fake_transcriber,
        cache_dir=out / "cache",
        clip_window=30,
    )

    # Overall status line tracks the book count (1/1 books here).
    assert any("1/1 books" in s for s in rec.statuses)
    # The per-book bar is sized to the book's one clip and advanced once.
    assert (1 in (total for _, total in rec.books)) and rec.advances == 1
    # Download/transcribe phases show on the per-book bar label, not the status.
    assert any("downloading" in d for d in rec.describes)
    assert any("transcribing" in d for d in rec.describes)
