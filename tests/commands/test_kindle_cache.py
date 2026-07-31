"""Unit tests for the Kindle per-book highlights cache."""

from books.commands.kindle import cache
from books.core.highlights import Highlight


def test_highlight_dict_round_trip():
    h = Highlight(
        text="hello",
        note="a thought",
        page="472-473",
        location_label="loc.",
        date="2015-07-31T00:18:38",
        source="kindle",
        tags=["x"],
        links=["Y"],
    )
    restored = cache.highlight_from_dict(cache.highlight_to_dict(h))
    assert restored == h


def test_highlight_from_dict_ignores_unknown_keys():
    d = {"text": "hi", "bogus": 1}
    assert cache.highlight_from_dict(d) == Highlight(text="hi")


def test_save_and_load_round_trip(tmp_path):
    cdir = cache.cache_dir(tmp_path)
    stem = cache.book_stem("The Deluge", "Adam Tooze", set())
    cache.save_book(cdir, stem, "The Deluge", "Adam Tooze", [Highlight(text="a")])
    records = cache.load_all(cdir)
    assert len(records) == 1
    assert records[0]["title"] == "The Deluge"
    assert records[0]["author"] == "Adam Tooze"
    assert records[0]["highlights"] == [Highlight(text="a")]


def test_save_book_wholesale_overwrite(tmp_path):
    cdir = cache.cache_dir(tmp_path)
    stem = cache.book_stem("T", "A", set())
    cache.save_book(cdir, stem, "T", "A", [Highlight(text="old")])
    cache.save_book(cdir, stem, "T", "A", [Highlight(text="new")])
    records = cache.load_all(cdir)
    assert len(records) == 1
    assert records[0]["highlights"] == [Highlight(text="new")]


def test_book_stem_readable_and_collision_suffix():
    used = set()
    assert cache.book_stem("The Deluge", "Adam Tooze", used) == "The Deluge - Adam Tooze"
    # A second distinct book that sanitizes to the same stem gets a numeric suffix.
    assert cache.book_stem("The Deluge", "Adam Tooze", used) == "The Deluge - Adam Tooze (2)"


def test_load_all_missing_dir_is_empty(tmp_path):
    assert cache.load_all(tmp_path / "nope") == []


def test_load_all_skips_corrupt_file(tmp_path):
    cdir = cache.cache_dir(tmp_path)
    cdir.mkdir(parents=True)
    (cdir / "bad.json").write_text("{not json", encoding="utf-8")
    assert cache.load_all(cdir) == []
