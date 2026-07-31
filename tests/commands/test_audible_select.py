"""Tests for the Audible interactive book selection helpers."""

from books.commands.audible import models, select


def _cand(title="Stalin", authors=("Stephen Kotkin",), asin="B0", book_id=None, n=1, cached=False):
    book = models.LibraryBook(asin=asin, title=title, authors=list(authors))
    anns = [models.Annotation(id=f"a{i}", start_ms=i * 1000) for i in range(n)]
    return models.Candidate(book=book, book_id=book_id, annotations=anns, cached=cached)


def test_candidate_label_matched_with_clips_and_cache():
    cand = _cand(book_id="Stalin - Stephen Kotkin", n=2, cached=True)
    label = select.candidate_label(cand)
    assert "Stalin — Stephen Kotkin" in label
    assert "in library" in label
    assert "2 clip" in label
    assert label.endswith("(cached)")


def test_candidate_label_new_book():
    label = select.candidate_label(_cand(title="Audio Only", authors=(), book_id=None, n=1))
    assert "Audio Only — ?" in label  # no authors -> "?"
    assert "new" in label
    assert "1 clip" in label
    assert "(cached)" not in label


def test_should_precheck_only_matched_with_clips():
    assert select.should_precheck(_cand(book_id="X", n=1)) is True
    assert select.should_precheck(_cand(book_id="X", n=0)) is False  # zero clips
    assert select.should_precheck(_cand(book_id=None, n=5)) is False  # new book
    assert select.should_precheck(_cand(book_id=None, n=0)) is False
