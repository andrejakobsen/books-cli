"""Tests for the `books covers` capability (booktools.covers)."""

from pathlib import Path

from booktools import covers


def test_dataclasses_exist():
    mb = covers.MissingBook(
        note_path=Path("/x/Books/A.md"),
        title="A Title",
        authors=["An Author"],
        isbn="123",
        amazon="B00XYZ",
    )
    assert mb.title == "A Title"
    assert mb.authors == ["An Author"]

    c = covers.Candidate(
        source="google", label="A Title — An Author",
        image_url="https://x/y.jpg", fmt=None,
    )
    assert c.source == "google"
    assert c.fmt is None


def _write_note(vault: Path, name: str, body: str) -> Path:
    books = vault / "Books"
    books.mkdir(parents=True, exist_ok=True)
    p = books / name
    p.write_text(body, encoding="utf-8")
    return p


def test_find_missing_selects_blank_cover_book_notes(tmp_path):
    # blank cover -> included
    _write_note(tmp_path, "A.md",
        '---\ntype: book\ntitle: "A"\nauthors: ["[[Ann Author]]"]\n'
        'isbn: "111"\namazon: "B001"\ncover:\n---\nbody\n')
    # non-empty cover -> excluded
    _write_note(tmp_path, "B.md",
        '---\ntype: book\ntitle: "B"\ncover: "[[Exports/x/cover.jpg]]"\n---\n')
    # absent cover key -> included
    _write_note(tmp_path, "C.md",
        '---\ntype: book\ntitle: "C"\nauthors: ["[[Cee]]"]\n---\n')
    # not a book -> excluded
    _write_note(tmp_path, "D.md", '---\ntype: author\ncover:\n---\n')

    missing = covers.find_missing(tmp_path)
    titles = sorted(m.title for m in missing)
    assert titles == ["A", "C"]

    a = next(m for m in missing if m.title == "A")
    assert a.authors == ["Ann Author"]
    assert a.isbn == "111"
    assert a.amazon == "B001"


def test_find_missing_no_books_dir_returns_empty(tmp_path):
    assert covers.find_missing(tmp_path) == []


GOOGLE_VOLUME = {
    "items": [
        {
            "volumeInfo": {
                "title": "The Deluge",
                "authors": ["Adam Tooze"],
                "imageLinks": {
                    "smallThumbnail": "http://books.google.com/x?zoom=5&edge=curl",
                    "thumbnail": "http://books.google.com/x?zoom=1&edge=curl",
                    "large": "http://books.google.com/x?zoom=3",
                },
            }
        }
    ]
}


def test_google_books_prefers_largest_and_upgrades_url():
    book = covers.MissingBook(
        note_path=None, title="The Deluge", authors=["Adam Tooze"],
        isbn=None, amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return GOOGLE_VOLUME

    cands = covers.google_books_candidates(book, fake_fetch)
    assert len(cands) == 1
    c = cands[0]
    assert c.source == "google"
    assert c.fmt is None
    # 'large' beats the thumbnails
    assert c.image_url.startswith("https://")   # http -> https
    assert "zoom=3" in c.image_url
    # title/author query when no ISBN
    assert "intitle" in captured["url"]
    assert "inauthor" in captured["url"]


def test_google_books_uses_isbn_query_when_present():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn="9780141032016", amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"items": []}

    covers.google_books_candidates(book, fake_fetch)
    assert "isbn:9780141032016" in captured["url"]


def test_google_books_no_images_returns_empty():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn=None, amazon=None)
    cands = covers.google_books_candidates(
        book, lambda url: {"items": [{"volumeInfo": {"title": "X"}}]})
    assert cands == []
