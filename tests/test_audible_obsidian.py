"""Tests for the Audible clips importer."""

from pathlib import Path

from typer.testing import CliRunner

from books import audible_obsidian as ao
from books.cli import app

runner = CliRunner()


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
                        note="Key idea #power @stalin", date="2026-07-01")
    rec = ao.annotation_to_record(ann, "This is the clip text.", _chapters())
    assert rec["text"] == "This is the clip text."
    assert rec["start_ms"] == 120_000
    assert rec["end_ms"] == 150_000
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


def _seed_note(out, stem, frontmatter):
    books = out / "Books"
    books.mkdir(parents=True, exist_ok=True)
    note = books / f"{stem}.md"
    note.write_text(frontmatter, encoding="utf-8")
    return note


def test_render_note_writes_frontmatter_and_marked_section(tmp_path):
    out = tmp_path / "V"
    note = _seed_note(
        out, "Stalin - Stephen Kotkin",
        '---\ntype: book\ntitle: "Stalin"\n'
        'authors: ["[[Stephen Kotkin]]"]\namazon:\nsource:\n'
        'highlighted: false\ncover:\n---\n\nMy body.\n')
    book = ao.LibraryBook(asin="B0ASIN", title="Stalin",
                          authors=["Stephen Kotkin"])
    clips = {
        "a1": {"text": "First clip.", "start_ms": 120_000, "end_ms": 150_000,
               "note": None, "date": None, "chapter": "The Rise",
               "chapter_index": 2},
    }
    n = ao.render_note(note, book, clips)
    assert n == 1
    text = note.read_text(encoding="utf-8")
    assert "My body." in text                       # body preserved
    assert 'amazon: "B0ASIN"' in text               # ASIN backfilled (quoted)
    assert "source: audible" in text
    assert "highlighted: true" in text
    assert "## Highlights" in text
    assert "%% books:highlights:start %%" in text
    assert "### The Rise" in text                   # chapter grouping header
    assert "Audible ch. 2 · 0:02:00" in text        # chapter_label + bare timestamp (120_000 ms)
    assert "First clip." in text


def test_render_note_skips_empty_text_highlights(tmp_path):
    out = tmp_path / "V"
    note = _seed_note(out, "Stalin - Stephen Kotkin",
                      '---\ntype: book\ntitle: "Stalin"\n---\n')
    book = ao.LibraryBook(asin="B0ASIN", title="Stalin")
    clips = {"a1": {"text": "", "start_ms": 0, "end_ms": None, "note": None,
                    "date": None, "chapter": None, "chapter_index": None}}
    assert ao.render_note(note, book, clips) == 0
