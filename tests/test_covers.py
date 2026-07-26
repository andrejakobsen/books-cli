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


# iTunes Search API shape: results[] with artworkUrl100 (size token = last
# path segment; ISBN, when present, is the second-to-last segment's stem).
ITUNES_RESULTS = {
    "results": [
        {
            "trackName": "The Deluge",
            "artistName": "Adam Tooze",
            "artworkUrl100": (
                "https://is1-ssl.mzstatic.com/image/thumb/Pub3/v4/57/c1/ac/"
                "abc/9780241006115.jpg/100x100bb.jpg"
            ),
        }
    ]
}

# artwork with an opaque (non-ISBN) filename stem -> no ISBN to backfill
ITUNES_RESULTS_NO_ISBN = {
    "results": [
        {
            "collectionName": "The Anatomy of Fascism",
            "artistName": "Robert O. Paxton",
            "artworkUrl100": (
                "https://is1-ssl.mzstatic.com/image/thumb/Publication/52/22/e8/"
                "mzi.mwffatop.jpg/100x100bb.jpg"
            ),
        }
    ]
}


def test_itunes_artwork_upgrades_size_token():
    art = ("https://is1-ssl.mzstatic.com/image/thumb/Pub3/v4/57/c1/ac/"
           "abc/9780241006115.jpg/100x100bb.jpg")
    big = covers._itunes_artwork(art)
    assert big.endswith("/9780241006115.jpg/1400x1400bb.jpg")
    assert "100x100bb" not in big


def test_itunes_isbn_reads_second_to_last_segment():
    art = ("https://is1-ssl.mzstatic.com/image/thumb/Pub3/v4/57/c1/ac/"
           "abc/9780241006115.jpg/100x100bb.jpg")
    assert covers._itunes_isbn(art) == "9780241006115"


def test_itunes_isbn_none_for_opaque_stem():
    art = ("https://is1-ssl.mzstatic.com/image/thumb/Publication/52/22/e8/"
           "mzi.mwffatop.jpg/100x100bb.jpg")
    assert covers._itunes_isbn(art) is None


def test_itunes_isbn_reads_isbn10_with_x_check_digit():
    art = ("https://is1-ssl.mzstatic.com/image/thumb/Pub3/v4/57/c1/ac/"
           "abc/184737453X.jpg/100x100bb.jpg")
    assert covers._itunes_isbn(art) == "184737453X"


def test_itunes_isbn_reads_isbn10_all_digits():
    art = ("https://is1-ssl.mzstatic.com/image/thumb/Pub3/v4/57/c1/ac/"
           "abc/0241006112.jpg/100x100bb.jpg")
    assert covers._itunes_isbn(art) == "0241006112"


def test_itunes_isbn_none_for_short_url():
    assert covers._itunes_isbn("9780241006115.jpg") is None


def test_normalize_author_collapses_whitespace():
    assert covers.normalize_author("James   Barr") == "James Barr"
    assert covers.normalize_author("  Andrew  Roberts ") == "Andrew Roberts"


def test_normalize_author_strips_translator_and_coauthor_tails():
    # translator merged into the author string
    assert covers.normalize_author("Plato and Benjamin Jowett") == "Plato"
    assert covers.normalize_author("Homer, translated by Emily Wilson") == "Homer"
    assert covers.normalize_author("Tolstoy with Louise Maude") == "Tolstoy"


def test_normalize_author_leaves_simple_names():
    assert covers.normalize_author("Adam Tooze") == "Adam Tooze"
    assert covers.normalize_author("") == ""


def test_google_query_uses_normalized_author():
    book = covers.MissingBook(
        note_path=None, title="The  Republic", authors=["Plato and Benjamin Jowett"],
        isbn=None, amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"items": []}

    covers.google_books_candidates(book, fake_fetch)
    # translator tail dropped, whitespace collapsed
    assert "Benjamin" not in captured["url"]
    assert "inauthor:Plato" in captured["url"]
    assert "The%20Republic" in captured["url"] or "The+Republic" in captured["url"]


def test_openlibrary_query_uses_normalized_author():
    book = covers.MissingBook(
        note_path=None, title="X", authors=["James   Barr"], isbn=None, amazon=None)
    captured = {}

    def fake_fetch(url):
        captured.setdefault("urls", []).append(url)
        return {"docs": []}

    covers.openlibrary_candidates(book, fake_fetch)
    search_url = next(u for u in captured["urls"] if "search.json" in u)
    assert "James+Barr" in search_url or "James%20Barr" in search_url
    assert "James++" not in search_url and "James%20%20" not in search_url


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


def test_google_books_captures_isbn13_from_identifiers():
    data = {"items": [{"volumeInfo": {
        "title": "The Deluge", "authors": ["Adam Tooze"],
        "industryIdentifiers": [
            {"type": "ISBN_10", "identifier": "0141032189"},
            {"type": "ISBN_13", "identifier": "9780141032184"},
        ],
        "imageLinks": {"thumbnail": "http://x/y?zoom=1"},
    }}]}
    book = covers.MissingBook(
        note_path=None, title="The Deluge", authors=["Adam Tooze"],
        isbn=None, amazon=None)
    cands = covers.google_books_candidates(book, lambda url: data)
    assert cands[0].isbn == "9780141032184"   # ISBN_13 preferred over ISBN_10


def test_apply_cover_backfills_isbn_when_learned(tmp_path):
    from booktools.obsidian import VaultIndex

    note = _write_note(tmp_path, "Deluge - Adam Tooze.md",
        '---\ntype: book\ntitle: "The Deluge"\n'
        'authors: ["[[Adam Tooze]]"]\nisbn:\ncover:\n---\n\nbody\n')
    book = covers.MissingBook(
        note_path=note, title="The Deluge", authors=["Adam Tooze"],
        isbn=None, amazon=None)
    index = VaultIndex(tmp_path)

    covers.apply_cover(index, book, _png(200, 300), isbn="9780141032184")

    text = note.read_text(encoding="utf-8")
    assert 'isbn: "9780141032184"' in text


def test_apply_cover_does_not_overwrite_existing_isbn(tmp_path):
    from booktools.obsidian import VaultIndex

    note = _write_note(tmp_path, "Deluge - Adam Tooze.md",
        '---\ntype: book\ntitle: "The Deluge"\n'
        'authors: ["[[Adam Tooze]]"]\nisbn: "111"\ncover:\n---\n')
    book = covers.MissingBook(
        note_path=note, title="The Deluge", authors=["Adam Tooze"],
        isbn="111", amazon=None)
    index = VaultIndex(tmp_path)

    covers.apply_cover(index, book, _png(200, 300), isbn="999")

    text = note.read_text(encoding="utf-8")
    assert 'isbn: "111"' in text
    assert "999" not in text


def test_google_books_uses_isbn_query_when_present():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn="9780141032016", amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"items": []}

    covers.google_books_candidates(book, fake_fetch)
    assert "isbn:9780141032016" in captured["url"]


def test_google_books_strips_edge_curl_when_only_thumbnail():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn=None, amazon=None)
    data = {"items": [{"volumeInfo": {"title": "X", "imageLinks": {
        "thumbnail": "http://books.google.com/x?zoom=1&edge=curl"}}}]}
    cands = covers.google_books_candidates(book, lambda url: data)
    assert cands and "edge=curl" not in cands[0].image_url
    assert cands[0].image_url.startswith("https://")


def test_google_books_no_images_returns_empty():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn=None, amazon=None)
    cands = covers.google_books_candidates(
        book, lambda url: {"items": [{"volumeInfo": {"title": "X"}}]})
    assert cands == []


# Open Library search.json shape (title/author path): yields a work key.
OL_SEARCH = {"docs": [{"key": "/works/OL1W", "cover_i": 999}]}

# Open Library works/<id>/editions.json shape: per-edition format + covers.
OL_EDITIONS = {
    "entries": [
        {"physical_format": "Hardcover", "covers": [111]},
        {"physical_format": "Paperback", "covers": [222]},
    ]
}


def test_openlibrary_title_author_paperback_first():
    book = covers.MissingBook(
        note_path=None, title="Napoleon", authors=["Andrew Roberts"],
        isbn=None, amazon=None)
    captured = {}

    def fake_fetch(url):
        captured.setdefault("urls", []).append(url)
        if "editions.json" in url:
            return OL_EDITIONS
        return OL_SEARCH

    cands = covers.openlibrary_candidates(book, fake_fetch)
    assert cands, "expected at least one candidate"
    assert all(c.source == "openlibrary" for c in cands)
    # paperback edition ranked ahead of hardcover
    fmts = [c.fmt for c in cands]
    assert fmts.index("paperback") < fmts.index("hardcover")
    # paperback candidate points at its own cover id
    pb = next(c for c in cands if c.fmt == "paperback")
    assert "222-L.jpg" in pb.image_url
    urls = captured["urls"]
    search_url = next(u for u in urls if "search.json" in u)
    assert "title=Napoleon" in search_url
    assert "author=Andrew+Roberts" in search_url or "author=Andrew%20Roberts" in search_url
    assert any("/works/OL1W/editions.json" in u for u in urls)


def test_openlibrary_falls_back_to_search_cover_when_no_editions():
    book = covers.MissingBook(
        note_path=None, title="Napoleon", authors=["Andrew Roberts"],
        isbn=None, amazon=None)

    def fake_fetch(url):
        if "editions.json" in url:
            return {"entries": []}
        return OL_SEARCH

    cands = covers.openlibrary_candidates(book, fake_fetch)
    assert len(cands) == 1
    assert cands[0].fmt is None
    assert "999-L.jpg" in cands[0].image_url


def test_openlibrary_isbn_path_builds_isbn_cover_url():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn="9780141032016", amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"physical_format": "Paperback"}

    cands = covers.openlibrary_candidates(book, fake_fetch)
    assert "/isbn/9780141032016.json" in captured["url"]
    assert cands and "isbn/9780141032016-L.jpg" in cands[0].image_url
    assert cands[0].fmt == "paperback"


def test_openlibrary_no_cover_returns_empty():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn=None, amazon=None)
    cands = covers.openlibrary_candidates(book, lambda url: {"docs": []})
    assert cands == []


def test_amazon_candidate_from_asin():
    book = covers.MissingBook(
        note_path=None, title="X", authors=["Y"], isbn=None, amazon="B00ABCDEFG")
    cands = covers.amazon_candidates(book)
    assert len(cands) == 1
    assert cands[0].source == "amazon"
    assert "B00ABCDEFG" in cands[0].image_url


def test_amazon_no_asin_returns_empty():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn=None, amazon=None)
    assert covers.amazon_candidates(book) == []


def _http_error(code):
    from urllib.error import HTTPError
    return HTTPError("http://x", code, "err", {}, None)


def test_fetch_with_retry_retries_on_429_then_succeeds():
    calls = {"n": 0}
    slept = []

    def do():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(429)
        return {"ok": True}

    out = covers.fetch_with_retry(do, retries=3, backoff=0.1, sleep=slept.append)
    assert out == {"ok": True}
    assert calls["n"] == 3
    assert len(slept) == 2   # two backoff sleeps before the successful third call


def test_fetch_with_retry_does_not_retry_on_404():
    calls = {"n": 0}

    def do():
        calls["n"] += 1
        raise _http_error(404)

    import pytest
    with pytest.raises(Exception):
        covers.fetch_with_retry(do, retries=3, backoff=0.1, sleep=lambda s: None)
    assert calls["n"] == 1   # 404 is not retryable


def test_fetch_with_retry_exhausts_and_raises():
    from urllib.error import HTTPError
    calls = {"n": 0}

    def do():
        calls["n"] += 1
        raise _http_error(503)

    import pytest
    with pytest.raises(HTTPError):
        covers.fetch_with_retry(do, retries=2, backoff=0.1, sleep=lambda s: None)
    assert calls["n"] == 2   # tried exactly `retries` times


def test_gather_with_errors_reports_failing_source():
    book = covers.MissingBook(
        note_path=None, title="X", authors=["Y"], isbn=None, amazon="B00ABCDEFG")

    def fetch_json(url):
        if "googleapis" in url:
            raise _http_error(429)      # google source fails entirely
        return {"docs": []}             # openlibrary finds nothing (not an error)

    cands, errored = covers.gather_with_errors(book, fetch_json)
    assert "google" in errored
    assert "openlibrary" not in errored
    # amazon still contributes despite google failing
    assert any(c.source == "amazon" for c in cands)


def test_run_counts_errored_sources(tmp_path):
    _write_note(tmp_path, "X - Y.md",
        '---\ntype: book\ntitle: "X"\nauthors: ["[[Y]]"]\namazon: "B00ABCDEFG"\ncover:\n---\n')

    def fetch_json(url):
        if "googleapis" in url:
            raise _http_error(429)
        return {"docs": []}

    stats = covers.run(
        tmp_path, interactive=False, dry_run=True, limit=None,
        fetch_json=fetch_json,
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"), prompt=None)

    assert stats["errored"]["google"] == 1
    assert stats["fetched"] == 1   # amazon still succeeded


def test_gather_candidates_source_order():
    book = covers.MissingBook(
        note_path=None, title="Napoleon", authors=["Andrew Roberts"],
        isbn=None, amazon="B00ABCDEFG")

    def fake_fetch(url):
        if "googleapis" in url:
            return GOOGLE_VOLUME
        if "editions.json" in url:
            return OL_EDITIONS
        return OL_SEARCH

    cands = covers.gather_candidates(book, fake_fetch)
    sources = [c.source for c in cands]
    assert sources[0] == "google"
    assert "openlibrary" in sources
    assert sources[-1] == "amazon"
    # google before every openlibrary before amazon
    assert sources.index("google") < sources.index("openlibrary") < sources.index("amazon")


def _png(width: int, height: int) -> bytes:
    """A byte string with a valid PNG signature + IHDR width/height."""
    return (b"\x89PNG\r\n\x1a\n"
            + b"\x00\x00\x00\rIHDR"
            + width.to_bytes(4, "big") + height.to_bytes(4, "big")
            + b"\x08\x06\x00\x00\x00" + b"x" * 2000)


def _gif(width: int, height: int) -> bytes:
    return b"GIF89a" + width.to_bytes(2, "little") + height.to_bytes(2, "little") + b"x" * 2000


def test_image_dimensions_png_gif_and_unknown():
    assert covers.image_dimensions(_png(200, 300)) == (200, 300)
    assert covers.image_dimensions(_gif(120, 160)) == (120, 160)
    assert covers.image_dimensions(b"x" * 5000) is None   # not a recognizable image


def test_is_valid_image():
    assert covers.is_valid_image(b"x" * 5000, "image/jpeg") is True
    assert covers.is_valid_image(b"x" * 5000, "text/html") is False   # wrong type
    assert covers.is_valid_image(b"x" * 10, "image/gif") is False      # too small
    assert covers.is_valid_image(b"x" * 5000, None) is False           # unknown type


def test_is_valid_image_rejects_tiny_dimensions():
    # a real but tiny placeholder image is rejected even though it is large enough in bytes
    assert covers.is_valid_image(_png(1, 1), "image/png") is False
    # a properly sized image passes
    assert covers.is_valid_image(_png(200, 300), "image/png") is True
    # a big-enough GIF passes; a 10x10 one does not
    assert covers.is_valid_image(_gif(300, 400), "image/gif") is True
    assert covers.is_valid_image(_gif(10, 10), "image/gif") is False


def _cand(source):
    return covers.Candidate(source=source, label="L", image_url=f"http://{source}", fmt=None)


def test_pick_cover_auto_first_valid():
    cands = [_cand("google"), _cand("openlibrary")]

    def fetch_bytes(url):
        if url.endswith("google"):
            return (b"x" * 5, "image/jpeg")       # too small -> invalid
        return (b"x" * 5000, "image/jpeg")        # valid

    picked = covers.pick_cover(cands, fetch_bytes, interactive=False, prompt=None)
    assert picked is not None
    cand, data = picked
    assert cand.source == "openlibrary"
    assert data == b"x" * 5000


def test_pick_cover_auto_none_when_all_invalid():
    cands = [_cand("google")]
    picked = covers.pick_cover(
        cands, lambda url: (b"", "text/html"), interactive=False, prompt=None)
    assert picked is None


def test_pick_cover_interactive_next_then_accept():
    cands = [_cand("google"), _cand("openlibrary")]
    answers = iter(["next", "accept"])

    def fetch_bytes(url):
        return (b"x" * 5000, "image/jpeg")

    picked = covers.pick_cover(
        cands, fetch_bytes, interactive=True, prompt=lambda c: next(answers))
    assert picked[0].source == "openlibrary"


def test_pick_cover_interactive_quit_raises():
    cands = [_cand("google")]
    import pytest
    with pytest.raises(covers.QuitRequested):
        covers.pick_cover(
            cands, lambda url: (b"x" * 5000, "image/jpeg"),
            interactive=True, prompt=lambda c: "quit")


def test_apply_cover_writes_file_and_frontmatter(tmp_path):
    from booktools.obsidian import VaultIndex

    note = _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n\nbody\n')
    book = covers.MissingBook(
        note_path=note, title="Napoleon", authors=["Andrew Roberts"],
        isbn=None, amazon=None)
    index = VaultIndex(tmp_path)

    covers.apply_cover(index, book, b"\xff\xd8\xffJPEGDATA" + b"x" * 2000)

    # cover written flat under Covers/, keyed to the note stem
    cover_file = tmp_path / "Covers" / "Napoleon - Andrew Roberts.jpg"
    assert cover_file.is_file()

    text = note.read_text(encoding="utf-8")
    # frontmatter cover filled with a wikilink (no width)
    assert 'cover: "[[Covers/Napoleon - Andrew Roberts.jpg]]"' in text
    # body embed added (with display width); original body preserved
    assert "![[Covers/Napoleon - Andrew Roberts.jpg|150]]" in text
    assert "body" in text


def test_apply_cover_idempotent(tmp_path):
    from booktools.obsidian import VaultIndex

    note = _write_note(tmp_path, "N - A.md",
        '---\ntype: book\ntitle: "N"\nauthors: ["[[A]]"]\ncover:\n---\n')
    book = covers.MissingBook(
        note_path=note, title="N", authors=["A"], isbn=None, amazon=None)
    index = VaultIndex(tmp_path)

    covers.apply_cover(index, book, b"x" * 2000)
    first = note.read_text(encoding="utf-8")
    covers.apply_cover(index, book, b"x" * 2000)
    second = note.read_text(encoding="utf-8")
    assert first == second   # cover already set -> no duplicate embed/frontmatter
    assert second.count("![[Covers/N - A.jpg|150]]") == 1


def test_terminal_prompt_maps_keys(monkeypatch):
    answers = iter(["y", "n", "s", "q", "?"])
    monkeypatch.setattr("builtins.input", lambda *a: next(answers))
    cand = _cand("google")
    assert covers._terminal_prompt(cand) == "accept"
    assert covers._terminal_prompt(cand) == "next"
    assert covers._terminal_prompt(cand) == "skip"
    assert covers._terminal_prompt(cand) == "quit"
    # unrecognized input defaults to "next" (safe, non-destructive)
    assert covers._terminal_prompt(cand) == "next"


def test_run_fetches_and_applies(tmp_path):
    _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')
    # a note that already has a cover -> untouched, not counted
    _write_note(tmp_path, "Done.md",
        '---\ntype: book\ntitle: "Done"\ncover: "[[x/cover.jpg]]"\n---\n')

    def fetch_json(url):
        return GOOGLE_VOLUME if "googleapis" in url else {"docs": []}

    def fetch_bytes(url):
        return (b"x" * 3000, "image/jpeg")

    stats = covers.run(
        tmp_path, interactive=False, dry_run=False, limit=None,
        fetch_json=fetch_json, fetch_bytes=fetch_bytes, prompt=None)

    assert stats["missing"] == 1
    assert stats["fetched"] == 1
    assert stats["by_source"]["google"] == 1
    cover_file = tmp_path / "Covers" / "Napoleon - Andrew Roberts.jpg"
    assert cover_file.is_file()


def test_run_backfills_isbn_from_chosen_candidate(tmp_path):
    note = _write_note(tmp_path, "Deluge - Adam Tooze.md",
        '---\ntype: book\ntitle: "The Deluge"\n'
        'authors: ["[[Adam Tooze]]"]\nisbn:\ncover:\n---\n')

    volume = {"items": [{"volumeInfo": {
        "title": "The Deluge", "authors": ["Adam Tooze"],
        "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9780141032184"}],
        "imageLinks": {"thumbnail": "http://x/y?zoom=1"},
    }}]}

    covers.run(
        tmp_path, interactive=False, dry_run=False, limit=None,
        fetch_json=lambda url: volume if "googleapis" in url else {"docs": []},
        fetch_bytes=lambda url: (_png(200, 300), "image/jpeg"), prompt=None)

    text = note.read_text(encoding="utf-8")
    assert 'isbn: "9780141032184"' in text


def test_run_dry_run_writes_nothing(tmp_path):
    _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')

    stats = covers.run(
        tmp_path, interactive=False, dry_run=True, limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"), prompt=None)

    assert stats["fetched"] == 1   # would-fetch is still counted
    assert not (tmp_path / "Covers").exists()


def test_run_limit_caps_processing(tmp_path):
    for i in range(3):
        _write_note(tmp_path, f"B{i} - A.md",
            f'---\ntype: book\ntitle: "B{i}"\nauthors: ["[[A]]"]\ncover:\n---\n')

    stats = covers.run(
        tmp_path, interactive=False, dry_run=True, limit=2,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"), prompt=None)
    assert stats["processed"] == 2


def test_run_quit_stops_early(tmp_path):
    for i in range(3):
        _write_note(tmp_path, f"B{i} - A.md",
            f'---\ntype: book\ntitle: "B{i}"\nauthors: ["[[A]]"]\ncover:\n---\n')

    stats = covers.run(
        tmp_path, interactive=True, dry_run=False, limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"),
        prompt=lambda c: "quit")
    assert stats["fetched"] == 0


def test_note_to_missing_eligible_and_ineligible(tmp_path):
    note = _write_note(tmp_path, "A - Ann.md",
        '---\ntype: book\ntitle: "A"\nauthors: ["[[Ann]]"]\ncover:\n---\n')
    mb = covers.note_to_missing(note)
    assert mb is not None
    assert mb.title == "A" and mb.authors == ["Ann"]

    has_cover = _write_note(tmp_path, "B - Bee.md",
        '---\ntype: book\ntitle: "B"\ncover: "[[x/cover.jpg]]"\n---\n')
    assert covers.note_to_missing(has_cover) is None   # cover already set

    not_book = _write_note(tmp_path, "C.md", '---\ntype: author\ncover:\n---\n')
    assert covers.note_to_missing(not_book) is None    # wrong type


def test_run_single_book_only_processes_that_note(tmp_path):
    target = _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')
    # another missing-cover book that must NOT be touched
    _write_note(tmp_path, "Other - X.md",
        '---\ntype: book\ntitle: "Other"\nauthors: ["[[X]]"]\ncover:\n---\n')

    stats = covers.run(
        tmp_path, interactive=False, dry_run=False, limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"),
        prompt=None, book_path=target)

    assert stats["scanned"] == 1
    assert stats["missing"] == 1
    assert stats["fetched"] == 1
    assert (tmp_path / "Covers" / "Napoleon - Andrew Roberts.jpg").is_file()
    assert not (tmp_path / "Covers" / "Other - X.jpg").exists()


def test_run_single_book_ineligible_is_no_op(tmp_path):
    target = _write_note(tmp_path, "Done - Y.md",
        '---\ntype: book\ntitle: "Done"\ncover: "[[x/cover.jpg]]"\n---\n')
    stats = covers.run(
        tmp_path, interactive=False, dry_run=False, limit=None,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"),
        prompt=None, book_path=target)
    assert stats["missing"] == 0
    assert stats["fetched"] == 0


def test_run_single_book_ignores_limit(tmp_path):
    target = _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')
    stats = covers.run(
        tmp_path, interactive=False, dry_run=True, limit=0,
        fetch_json=lambda url: GOOGLE_VOLUME,
        fetch_bytes=lambda url: (b"x" * 3000, "image/jpeg"),
        prompt=None, book_path=target)
    assert stats["processed"] == 1


def test_cli_covers_dry_run(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from booktools.cli import app

    _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')

    # stub the network so the CLI test stays offline
    monkeypatch.setattr(covers, "default_fetch_json", lambda url: GOOGLE_VOLUME)
    monkeypatch.setattr(
        covers, "default_fetch_bytes", lambda url: (b"x" * 3000, "image/jpeg"))

    result = CliRunner().invoke(
        app, ["covers", "-o", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "missing" in result.output.lower()
    assert not (tmp_path / "Covers").exists()


def test_cli_covers_reports_errored_sources(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from booktools.cli import app

    _write_note(tmp_path, "X - Y.md",
        '---\ntype: book\ntitle: "X"\nauthors: ["[[Y]]"]\namazon: "B00ABCDEFG"\ncover:\n---\n')

    def fetch_json(url):
        if "googleapis" in url:
            raise _http_error(429)
        return {"docs": []}

    monkeypatch.setattr(covers, "default_fetch_json", fetch_json)
    monkeypatch.setattr(
        covers, "default_fetch_bytes", lambda url: (_png(200, 300), "image/jpeg"))

    result = CliRunner().invoke(app, ["covers", "-o", str(tmp_path), "--dry-run"])
    assert result.exit_code == 0, result.output
    # the summary distinguishes a source that errored from one that found nothing
    assert "google" in result.output.lower()
    assert "error" in result.output.lower()


def test_cli_covers_registered():
    from booktools.cli import app
    names = {c.name for c in app.registered_commands}
    assert "covers" in names


def test_cli_covers_single_book_interactive_by_default(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from booktools.cli import app

    note = _write_note(tmp_path, "Napoleon - Andrew Roberts.md",
        '---\ntype: book\ntitle: "Napoleon"\n'
        'authors: ["[[Andrew Roberts]]"]\ncover:\n---\n')
    # another missing-cover book that must NOT be touched
    _write_note(tmp_path, "Other - X.md",
        '---\ntype: book\ntitle: "Other"\nauthors: ["[[X]]"]\ncover:\n---\n')

    monkeypatch.setattr(covers, "default_fetch_json", lambda url: GOOGLE_VOLUME)
    monkeypatch.setattr(
        covers, "default_fetch_bytes", lambda url: (b"x" * 3000, "image/jpeg"))
    # single-book mode is interactive by default -> the prompt is used; accept it.
    monkeypatch.setattr(covers, "_terminal_prompt", lambda c: "accept")

    result = CliRunner().invoke(app, ["covers", "-b", str(note)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "Covers" / "Napoleon - Andrew Roberts.jpg").is_file()
    assert not (tmp_path / "Covers" / "Other - X.jpg").exists()


def test_cli_covers_single_book_rejects_note_outside_books(tmp_path):
    from typer.testing import CliRunner
    from booktools.cli import app

    stray = tmp_path / "stray.md"
    stray.write_text('---\ntype: book\ntitle: "S"\ncover:\n---\n', encoding="utf-8")
    result = CliRunner().invoke(app, ["covers", "-b", str(stray)])
    assert result.exit_code != 0


def test_apple_books_query_uses_title_and_author_not_isbn():
    book = covers.MissingBook(
        note_path=None, title="The  Deluge", authors=["Adam Tooze"],
        isbn="9781847374530", amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"results": []}

    covers.apple_books_candidates(book, fake_fetch)
    url = captured["url"]
    assert "Deluge" in url and "Adam" in url and "Tooze" in url
    assert "The%20%20Deluge" not in url   # collapsed, not doubled
    assert "isbn" not in url.lower()
    assert "9781847374530" not in url
    assert "entity=ebook" in url
    assert "country=gb" in url


def test_apple_books_builds_candidate_with_hires_url_and_isbn():
    book = covers.MissingBook(
        note_path=None, title="The Deluge", authors=["Adam Tooze"],
        isbn=None, amazon=None)
    cands = covers.apple_books_candidates(book, lambda url: ITUNES_RESULTS)
    assert len(cands) == 1
    c = cands[0]
    assert c.source == "apple"
    assert c.fmt is None
    assert c.label == "The Deluge — Adam Tooze"
    assert c.image_url.endswith("/9780241006115.jpg/1400x1400bb.jpg")
    assert c.isbn == "9780241006115"


def test_apple_books_uses_collection_name_and_no_isbn_for_opaque_art():
    book = covers.MissingBook(
        note_path=None, title="The Anatomy of Fascism",
        authors=["Robert O. Paxton"], isbn=None, amazon=None)
    cands = covers.apple_books_candidates(book, lambda url: ITUNES_RESULTS_NO_ISBN)
    assert len(cands) == 1
    assert cands[0].label == "The Anatomy of Fascism — Robert O. Paxton"
    assert cands[0].isbn is None
    assert "1400x1400bb" in cands[0].image_url


def test_apple_books_normalizes_author():
    book = covers.MissingBook(
        note_path=None, title="The Republic",
        authors=["Plato and Benjamin Jowett"], isbn=None, amazon=None)
    captured = {}

    def fake_fetch(url):
        captured["url"] = url
        return {"results": []}

    covers.apple_books_candidates(book, fake_fetch)
    assert "Plato" in captured["url"]
    assert "Benjamin" not in captured["url"]


def test_apple_books_no_results_returns_empty():
    book = covers.MissingBook(
        note_path=None, title="X", authors=[], isbn=None, amazon=None)
    assert covers.apple_books_candidates(book, lambda url: {"results": []}) == []


def test_apple_books_skips_results_without_artwork():
    book = covers.MissingBook(
        note_path=None, title="X", authors=["Y"], isbn=None, amazon=None)
    data = {"results": [{"trackName": "X", "artistName": "Y"}]}
    assert covers.apple_books_candidates(book, lambda url: data) == []


def test_gather_candidates_apple_first():
    book = covers.MissingBook(
        note_path=None, title="The Deluge", authors=["Adam Tooze"],
        isbn=None, amazon="B00ABCDEFG")

    def fake_fetch(url):
        if "itunes.apple.com" in url:
            return ITUNES_RESULTS
        if "googleapis" in url:
            return GOOGLE_VOLUME
        if "editions.json" in url:
            return OL_EDITIONS
        return OL_SEARCH

    cands = covers.gather_candidates(book, fake_fetch)
    sources = [c.source for c in cands]
    assert sources[0] == "apple"
    assert sources[-1] == "amazon"
    assert (sources.index("apple") < sources.index("google")
            < sources.index("openlibrary") < sources.index("amazon"))
